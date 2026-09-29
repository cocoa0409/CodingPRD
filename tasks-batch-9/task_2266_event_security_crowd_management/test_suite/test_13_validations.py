"""The refusals, each taken to the boundary and then across it.

Every case here pairs a rejection with the smallest possible repair, so the
assertions pin both the error vocabulary and the fact that the boundary instant,
the exact cent and the exactly-equal headcount are all on the accepting side.
Where two rules could fire at once, the more specific one is shown winning.
"""

from test_helpers import (
    AUDITOR_HEADERS,
    COMMANDER_HEADERS,
    COORDINATOR_HEADERS,
    DIRECTOR_HEADERS,
    NON_EXISTENT_UUID,
    ApiClient,
    ApiErrorId,
    AssignmentStatus,
    DensityLevel,
    DutyStatus,
    EventStatus,
    GatePosture,
    IncidentCategory,
    IncidentStatus,
    IngressStatus,
    LaneStatus,
    LaneType,
    PayBasis,
    PlanStatus,
    PostStatus,
    PostType,
    ReadinessPosture,
    ReviewStatus,
    Severity,
    SubcontractorStatus,
    ZoneType,
    action,
    after_action_review_payload,
    assert_assignment_cost,
    assert_assignment_state,
    assert_coverage,
    assert_error_envelope_meta,
    assert_ledger,
    assert_post_fill,
    assert_three_decimals,
    brief,
    build_briefed_event_world,
    build_clock_world,
    build_event_world,
    build_plan_with_perimeter_post_world,
    build_plan_world,
    build_published_plan_with_posts_world,
    build_review_world,
    build_six_post_partial_checkin_world,
    build_six_post_pre_doors_world,
    check_in,
    confirm,
    create_assignment,
    create_verified_guard,
    density_reading_payload,
    guard_payload,
    incident_payload,
    post_payload,
    read_event_version,
    read_post_version,
    screening_lane_payload,
    set_clock,
    staffing_plan_payload,
    subcontractor_payload,
    validate_error,
    validate_paginated,
    validate_success,
    venue_payload,
    zone_payload,
)

POST_WINDOW_START = "2026-09-12T15:00:00Z"
POST_WINDOW_END = "2026-09-12T22:30:00Z"
PRE_DOORS_INSTANT = "2026-09-12T16:30:00Z"


def test_a_shift_may_touch_the_post_window_edges_but_not_cross_them():
    """Containment is inclusive at both ends and nowhere else.

    One minute early and one minute late are both refused; the shift that exactly
    coincides with the post window is accepted, as is the strictly interior one,
    and each is priced on its own length. Neither accepted row commits anything,
    so the post is still open and unfilled.

    PRD: "**Shift containment** — the assignment's `window_start` is at or after the post's `window_start` and its `window_end` is at or before the post's `window_end`, else `ERR_ASSIGNMENT_WINDOW_OUTSIDE_POST` (422)."
    Design: Corner/validations/assignment_window_outside_post_window_is_rejected
    """
    api = ApiClient()
    world = build_plan_with_perimeter_post_world(api)
    first_guard = create_verified_guard(api, "GC-7001")
    second_guard = create_verified_guard(api, "GC-7002", full_name="Gale Two")

    validate_error(
        api.create_post_assignment(
            {
                "post_id": world.p1_id,
                "guard_id": first_guard,
                "window_start": "2026-09-12T14:59:00Z",
                "window_end": POST_WINDOW_END,
            },
            COORDINATOR_HEADERS,
        ),
        ApiErrorId.ASSIGNMENT_WINDOW_OUTSIDE_POST,
    )
    validate_error(
        api.create_post_assignment(
            {
                "post_id": world.p1_id,
                "guard_id": first_guard,
                "window_start": POST_WINDOW_START,
                "window_end": "2026-09-12T22:31:00Z",
            },
            COORDINATOR_HEADERS,
        ),
        ApiErrorId.ASSIGNMENT_WINDOW_OUTSIDE_POST,
    )

    coincident = validate_success(
        api.create_post_assignment(
            {
                "post_id": world.p1_id,
                "guard_id": first_guard,
                "window_start": POST_WINDOW_START,
                "window_end": POST_WINDOW_END,
            },
            COORDINATOR_HEADERS,
        ),
        expected_status=201,
    )
    assert_assignment_cost(coincident, 7.50, 16500, PayBasis.EMPLOYEE_STRAIGHT)

    interior = validate_success(
        api.create_post_assignment(
            {
                "post_id": world.p1_id,
                "guard_id": second_guard,
                "window_start": "2026-09-12T15:30:00Z",
                "window_end": "2026-09-12T22:00:00Z",
            },
            COORDINATOR_HEADERS,
        ),
        expected_status=201,
    )
    assert_assignment_cost(interior, 6.50, 14300, PayBasis.EMPLOYEE_STRAIGHT)

    assert_post_fill(
        validate_success(api.get_post(world.p1_id, COORDINATOR_HEADERS)), 0, PostStatus.OPEN
    )
    _, meta = validate_paginated(
        api.list_post_assignments(COORDINATOR_HEADERS, params={"post_id": world.p1_id})
    )
    assert meta["total_count"] == 2


def test_a_confirmation_that_clears_every_rule_runs_all_three_hops():
    """The happy path, so the refusals around it are not vacuous.

    A verified level-three guard on a supervisor post is confirmed, the post
    fills, and the plan's coverage, ledger and headroom all move in the same
    request while the duty dimension stays untouched at PENDING_BRIEF. One filled
    slot out of five is nowhere near ready, so the plan stays blocked — and the
    event is still RISK_ASSESSED, so the pre-plan variant of the posture ladder
    skips the plan clause entirely and the gate stays open.

    PRD: "A successful confirmation sets `assignment_status` to `CONFIRMED` and then runs three hops upward."
    Design: Corner/validations/confirm_succeeds_when_every_precondition_holds
    """
    api = ApiClient()
    world = build_published_plan_with_posts_world(
        api,
        [
            {
                "code": "S1",
                "post_type": PostType.SUPERVISOR,
                "required_guard_count": 1,
                "min_credential_level": 3,
            },
            {"code": "P1", "post_type": PostType.PERIMETER, "required_guard_count": 4},
        ],
    )
    guard_id = create_verified_guard(
        api, "GC-7301", credential_level=3, full_name="Sam Sentinel"
    )
    row = create_assignment(api, world.s1_id, guard_id)

    confirmed = confirm(api, row)
    assert_assignment_state(confirmed, AssignmentStatus.CONFIRMED, DutyStatus.PENDING_BRIEF)
    assert_assignment_cost(confirmed, 7.50, 16500, PayBasis.EMPLOYEE_STRAIGHT)

    assert_post_fill(
        validate_success(api.get_post(world.s1_id, COORDINATOR_HEADERS)), 1, PostStatus.FILLED
    )

    summary = validate_success(api.get_coverage_summary(world.plan_id, COORDINATOR_HEADERS))
    assert_coverage(summary, 5, 1, 0.20, ReadinessPosture.BLOCKED)
    assert summary["supervisor_coverage_ok"] is True
    assert summary["understaffed_post_count"] == 0
    assert_ledger(summary, 16500, 7.50, budget_remaining_cents=483500)

    plan = validate_success(api.get_staffing_plan(world.plan_id, COORDINATOR_HEADERS))
    assert plan["status"] == PlanStatus.PUBLISHED
    event = validate_success(api.get_event(world.event_id, DIRECTOR_HEADERS))
    assert event["status"] == EventStatus.RISK_ASSESSED
    assert event["gate_posture"] == GatePosture.OPEN


def test_the_supervisor_floor_is_a_separate_rule_from_the_posts_declared_minimum():
    """A level-two guard fails two different rules on two different posts.

    On the perimeter post it is the post's own declared minimum of three that
    rejects the guard. On the supervisor post the declared minimum is only one and
    is satisfied, so the earlier rule passes and the supervisor-specific floor of
    three is what refuses — a different error id for the same guard. The
    level-three guard is confirmed and only that one row moves the ledger.

    PRD: "**Supervisor qualification** — a `SUPERVISOR` post requires a guard whose `credential_level` is at least 3, else `ERR_SUPERVISOR_NOT_QUALIFIED` (422). Guards the `CONFIRM` action."
    Design: Corner/validations/credential_level_below_post_minimum_and_supervisor_not_qualified
    """
    api = ApiClient()
    world = build_published_plan_with_posts_world(
        api,
        [
            {
                "code": "S1",
                "post_type": PostType.SUPERVISOR,
                "required_guard_count": 1,
                "min_credential_level": 1,
            },
            {
                "code": "PX",
                "post_type": PostType.PERIMETER,
                "required_guard_count": 4,
                "min_credential_level": 3,
            },
        ],
    )
    under_qualified = create_verified_guard(
        api, "GC-7201", credential_level=2, full_name="Gale Two"
    )
    qualified = create_verified_guard(
        api, "GC-7202", credential_level=3, full_name="Sam Sentinel"
    )
    on_perimeter = create_assignment(api, world.px_id, under_qualified)
    unqualified_on_supervisor = create_assignment(api, world.s1_id, under_qualified)
    qualified_on_supervisor = create_assignment(api, world.s1_id, qualified)

    validate_error(
        api.post_assignment_duty_event(on_perimeter, action("CONFIRM"), COORDINATOR_HEADERS),
        ApiErrorId.CREDENTIAL_LEVEL_INSUFFICIENT,
    )
    validate_error(
        api.post_assignment_duty_event(
            unqualified_on_supervisor, action("CONFIRM"), COORDINATOR_HEADERS
        ),
        ApiErrorId.SUPERVISOR_NOT_QUALIFIED,
    )
    accepted = confirm(api, qualified_on_supervisor)
    assert accepted["assignment_status"] == AssignmentStatus.CONFIRMED

    for rejected in (on_perimeter, unqualified_on_supervisor):
        row = validate_success(api.get_post_assignment(rejected, COORDINATOR_HEADERS))
        assert row["assignment_status"] == AssignmentStatus.TENTATIVE

    assert_post_fill(
        validate_success(api.get_post(world.s1_id, COORDINATOR_HEADERS)), 1, PostStatus.FILLED
    )
    assert_post_fill(
        validate_success(api.get_post(world.px_id, COORDINATOR_HEADERS)), 0, PostStatus.OPEN
    )
    plan = validate_success(api.get_staffing_plan(world.plan_id, COORDINATOR_HEADERS))
    assert_ledger(plan, 16500, 7.50)


def test_an_observation_is_admissible_two_hours_either_side_of_the_night():
    """The reading window is an interval on `observed_at`, nothing else.

    One minute before the opening bound and one minute after the closing bound are
    both refused, while both bound instants themselves are accepted — and they are
    accepted while the event is still in PLANNING and the clock has not moved,
    because this rule reads neither the event state nor the clock. Only the two
    accepted rows exist.

    PRD: "**Observation window** — a density reading's `observed_at` falls no earlier than two hours before the event's `doors_open_at` and no later than two hours after its `event_end_at`, else `ERR_READING_TIMESTAMP_OUT_OF_RANGE` (422)."
    Design: Corner/validations/density_reading_outside_window_returns_reading_timestamp_out_of_range
    """
    api = ApiClient()
    world = build_event_world(api)

    validate_error(
        api.create_density_reading(
            world.event_id,
            density_reading_payload(world.zf_id, "2026-09-12T14:59:00Z", 100),
            DIRECTOR_HEADERS,
        ),
        ApiErrorId.READING_TIMESTAMP_OUT_OF_RANGE,
    )
    early_bound = validate_success(
        api.create_density_reading(
            world.event_id,
            density_reading_payload(world.zf_id, "2026-09-12T15:00:00Z", 100),
            DIRECTOR_HEADERS,
        ),
        expected_status=201,
    )
    validate_error(
        api.create_density_reading(
            world.event_id,
            density_reading_payload(world.zf_id, "2026-09-13T00:31:00Z", 100),
            DIRECTOR_HEADERS,
        ),
        ApiErrorId.READING_TIMESTAMP_OUT_OF_RANGE,
    )
    late_bound = validate_success(
        api.create_density_reading(
            world.event_id,
            density_reading_payload(world.zf_id, "2026-09-13T00:30:00Z", 100),
            DIRECTOR_HEADERS,
        ),
        expected_status=201,
    )

    for reading in (early_bound, late_bound):
        assert_three_decimals(reading["density_persons_per_sqm"], 0.500, "density")
        assert_three_decimals(reading["occupancy_ratio"], 0.333, "occupancy_ratio")
        assert reading["effective_level"] == DensityLevel.GREEN

    _, meta = validate_paginated(
        api.list_density_readings(DIRECTOR_HEADERS, params={"event_id": world.event_id})
    )
    assert meta["total_count"] == 2

    event = validate_success(api.get_event(world.event_id, DIRECTOR_HEADERS))
    assert event["status"] == EventStatus.PLANNING


def _ready_to_open_world(api: ApiClient, open_lanes=("lane1", "lane2"), check_in_exit=True):
    """Six-slot briefed chain, optionally with the exit staffed and lanes open."""
    world = build_six_post_partial_checkin_world(api)
    if check_in_exit:
        check_in(api, world.a_e1, world.gs_id)
    for lane_key in open_lanes:
        validate_success(
            api.screening_lane_status(
                getattr(world, "%s_id" % lane_key), action("OPEN"), COORDINATOR_HEADERS
            )
        )
    return world


def test_the_doors_may_not_open_more_than_an_hour_before_they_are_scheduled():
    """One minute outside the lead window is refused; the boundary itself is not.

    Everything else about the night is ready — the exit is staffed and both lanes
    are running — so the only thing standing between the event and DOORS_OPEN is
    the clock. At exactly one hour before the scheduled opening the comparison
    passes and the doors open with the ingress flowing normally.

    PRD: "**Doors-open lead time** — the logical clock is at or after one hour before the event's `doors_open_at`, else `ERR_DOORS_OPEN_TOO_EARLY` (409). Guards the `DOORS_OPEN` action."
    Design: Corner/validations/doors_open_before_lead_window_returns_doors_open_too_early
    """
    api = ApiClient()
    world = _ready_to_open_world(api)
    set_clock(api, "2026-09-12T15:59:00Z")

    validate_error(
        api.event_lifecycle(world.event_id, action("DOORS_OPEN"), DIRECTOR_HEADERS),
        ApiErrorId.DOORS_OPEN_TOO_EARLY,
    )
    still_briefed = validate_success(api.get_event(world.event_id, DIRECTOR_HEADERS))
    assert still_briefed["status"] == EventStatus.BRIEFED

    set_clock(api, "2026-09-12T16:00:00Z")
    opened = validate_success(
        api.event_lifecycle(world.event_id, action("DOORS_OPEN"), DIRECTOR_HEADERS)
    )
    assert opened["status"] == EventStatus.DOORS_OPEN
    assert opened["ingress_status"] == IngressStatus.NORMAL
    assert opened["gate_posture"] == GatePosture.OPEN


def test_the_doors_stay_shut_until_as_many_lanes_are_open_as_the_assessment_demands():
    """One open lane is not two, and the pinned assessment is what says so.

    The running lane is throughputting correctly and the exit is staffed, so the
    only failing term is the count of open lanes. Opening the second lane brings
    it up to the pinned requirement and the same request that failed now succeeds.

    PRD: "**Screening capacity** — the number of the event's lanes whose `status` is `OPEN` is at least the assessment's `required_screening_lanes`, else `ERR_SCREENING_CAPACITY_INSUFFICIENT` (409). Guards the `DOORS_OPEN` action."
    Design: Corner/validations/doors_open_with_too_few_open_lanes_returns_screening_capacity_insufficient
    """
    api = ApiClient()
    world = _ready_to_open_world(api, open_lanes=("lane1",))

    validate_error(
        api.event_lifecycle(world.event_id, action("DOORS_OPEN"), DIRECTOR_HEADERS),
        ApiErrorId.SCREENING_CAPACITY_INSUFFICIENT,
    )
    assert (
        validate_success(api.get_event(world.event_id, DIRECTOR_HEADERS))["status"]
        == EventStatus.BRIEFED
    )

    running = validate_success(api.get_screening_lane(world.lane1_id, COORDINATOR_HEADERS))
    assert running["status"] == LaneStatus.OPEN
    assert running["effective_throughput_pph"] == 175
    idle = validate_success(api.get_screening_lane(world.lane2_id, COORDINATOR_HEADERS))
    assert idle["status"] == LaneStatus.PLANNED
    assert idle["effective_throughput_pph"] == 0

    second = validate_success(
        api.screening_lane_status(world.lane2_id, action("OPEN"), COORDINATOR_HEADERS)
    )
    assert second["effective_throughput_pph"] == 409

    opened = validate_success(
        api.event_lifecycle(world.event_id, action("DOORS_OPEN"), DIRECTOR_HEADERS)
    )
    assert opened["status"] == EventStatus.DOORS_OPEN


def test_a_rostered_emergency_exit_is_not_a_staffed_one():
    """The exit rule reads bodies on post, not names on the roster.

    The exit post is FILLED on paper and stays FILLED through the refusal — which
    is precisely the distinction the rule draws. Once its guard actually checks in,
    the doors open.

    PRD: "Every post on the current plan whose `post_type` is `EMERGENCY_EXIT` must have a `filled_guard_count` of at least its `required_guard_count` **and** at least that many assignments actually standing there with `duty_status` equal to `ON_POST`, else `ERR_EXIT_POSTS_UNSTAFFED` — a roster on paper is not an exit covered."
    Design: Corner/validations/doors_open_with_unstaffed_emergency_exit_returns_exit_posts_unstaffed
    """
    api = ApiClient()
    world = _ready_to_open_world(api, check_in_exit=False)

    validate_error(
        api.event_lifecycle(world.event_id, action("DOORS_OPEN"), DIRECTOR_HEADERS),
        ApiErrorId.EXIT_POSTS_UNSTAFFED,
    )
    assert (
        validate_success(api.get_event(world.event_id, DIRECTOR_HEADERS))["status"]
        == EventStatus.BRIEFED
    )
    assert_post_fill(
        validate_success(api.get_post(world.e1_id, COORDINATOR_HEADERS)), 1, PostStatus.FILLED
    )

    check_in(api, world.a_e1, world.gs_id)
    opened = validate_success(
        api.event_lifecycle(world.event_id, action("DOORS_OPEN"), DIRECTOR_HEADERS)
    )
    assert opened["status"] == EventStatus.DOORS_OPEN

    exit_row = validate_success(api.get_post_assignment(world.a_e1, COORDINATOR_HEADERS))
    assert exit_row["duty_status"] == DutyStatus.ON_POST
    assert exit_row["check_in_at"] == PRE_DOORS_INSTANT


def test_a_licence_number_is_unique_across_guards_and_vendors_alike():
    """One namespace, two entity types, four refusals.

    A guard cannot take another guard's licence, nor a vendor's, and a vendor
    cannot take a vendor's nor a guard's. A genuinely fresh number is registered
    normally, and the guard listing shows that none of the four rejected requests
    left a row behind.

    PRD: "**Licence uniqueness** — a `license_number` is globally unique across every guard and every vendor, else `ERR_DUPLICATE_LICENSE_NUMBER` (409). Guards `POST /event-security/guards` and `POST /event-security/subcontractors`."
    Design: Corner/validations/duplicate_license_number_is_rejected_across_guards_and_subcontractors
    """
    api = ApiClient()
    build_clock_world(api)
    validate_success(
        api.create_guard(guard_payload("GC-4001"), COORDINATOR_HEADERS), expected_status=201
    )
    validate_success(
        api.create_subcontractor(subcontractor_payload(), AUDITOR_HEADERS), expected_status=201
    )

    validate_error(
        api.create_guard(
            guard_payload("GC-4001", full_name="Gale Two"), COORDINATOR_HEADERS
        ),
        ApiErrorId.DUPLICATE_LICENSE_NUMBER,
    )
    validate_error(
        api.create_guard(
            guard_payload("SC-3001", full_name="Gale Three"), COORDINATOR_HEADERS
        ),
        ApiErrorId.DUPLICATE_LICENSE_NUMBER,
    )
    validate_error(
        api.create_subcontractor(
            subcontractor_payload(company_name="Meridian Guarding", license_number="SC-3001"),
            AUDITOR_HEADERS,
        ),
        ApiErrorId.DUPLICATE_LICENSE_NUMBER,
    )
    validate_error(
        api.create_subcontractor(
            subcontractor_payload(company_name="Meridian Guarding", license_number="GC-4001"),
            AUDITOR_HEADERS,
        ),
        ApiErrorId.DUPLICATE_LICENSE_NUMBER,
    )

    fresh = validate_success(
        api.create_subcontractor(
            subcontractor_payload(company_name="Meridian Guarding", license_number="SC-3002"),
            AUDITOR_HEADERS,
        ),
        expected_status=201,
    )
    assert fresh["status"] == SubcontractorStatus.PENDING
    assert fresh["verified_guard_count"] == 0

    _, meta = validate_paginated(api.list_guards(COORDINATOR_HEADERS))
    assert meta["total_count"] == 1


def _triaged_incident(api: ApiClient, world, severity=Severity.MODERATE, category=None):
    """Report and triage one incident on a briefed six-slot chain."""
    incident = validate_success(
        api.create_incident(
            world.event_id,
            incident_payload(
                world.zi_id,
                category or IncidentCategory.PROHIBITED_ITEM,
                severity,
                description="wand alarm at the concourse line",
            ),
            COMMANDER_HEADERS,
        ),
        expected_status=201,
    )
    return validate_success(
        api.incident_action(incident["id"], action("TRIAGE"), COMMANDER_HEADERS)
    )["id"]


def test_an_ejection_needs_a_supervisor_actually_standing_a_post():
    """A confirmed supervisor on the roster is not a supervisor on duty.

    With nobody checked in, the ejection is refused and the incident keeps both
    its status and its null patron reference. The moment the supervisor checks in
    the same request succeeds, and the ejection branch leaves the door flow, the
    gate and every lane exactly where they were.

    PRD: "**Supervisor on duty** — an ejection or a law-enforcement handoff requires at least one assignment on the event's current plan whose post has `post_type` `SUPERVISOR`, whose `assignment_status` is `CONFIRMED` and whose `duty_status` is `ON_POST`, else `ERR_NO_SUPERVISOR_ON_DUTY` (409)."
    Design: Corner/validations/eject_without_on_post_supervisor_returns_no_supervisor_on_duty
    """
    api = ApiClient()
    world = build_six_post_pre_doors_world(api)
    incident_id = _triaged_incident(api, world)

    validate_error(
        api.incident_action(
            incident_id, action("EJECT", ejection_patron_ref="PT-8890"), COMMANDER_HEADERS
        ),
        ApiErrorId.NO_SUPERVISOR_ON_DUTY,
    )
    pending = validate_success(api.get_incident(incident_id, COMMANDER_HEADERS))
    assert pending["status"] == IncidentStatus.TRIAGED
    assert pending["ejection_patron_ref"] is None

    check_in(api, world.a_s1, world.gs_id)
    ejecting = validate_success(
        api.incident_action(
            incident_id, action("EJECT", ejection_patron_ref="PT-8890"), COMMANDER_HEADERS
        )
    )
    assert ejecting["status"] == IncidentStatus.EJECTION_IN_PROGRESS
    assert ejecting["ejection_patron_ref"] == "PT-8890"

    event = validate_success(api.get_event(world.event_id, DIRECTOR_HEADERS))
    assert event["ingress_status"] == IngressStatus.NORMAL
    assert event["gate_posture"] == GatePosture.OPEN
    for lane_id in (world.lane1_id, world.lane2_id):
        lane = validate_success(api.get_screening_lane(lane_id, COORDINATOR_HEADERS))
        assert lane["status"] == LaneStatus.PLANNED


def test_an_escalation_must_move_strictly_up_the_severity_ordering():
    """Sideways and downwards are both refused; only upwards is an escalation.

    Re-declaring the same severity is not idempotent — it is rejected — and so is
    a downgrade. The genuine escalation is accepted and rewrites `severity` while
    leaving the reported severity as the historical record. SEVERE is not CRITICAL,
    so the gate is untouched throughout.

    PRD: "**Escalation direction** — an escalation requires the requested `severity` to sit strictly higher in the ordering `MINOR`, `MODERATE`, `SEVERE`, `CRITICAL` than the incident's current `severity`, else `ERR_SEVERITY_NOT_ESCALATING` (422)."
    Design: Corner/validations/escalate_to_equal_severity_returns_severity_not_escalating
    """
    api = ApiClient()
    world = build_six_post_pre_doors_world(api)
    incident_id = _triaged_incident(api, world, severity=Severity.MODERATE)

    for refused in (Severity.MODERATE, Severity.MINOR):
        validate_error(
            api.incident_action(
                incident_id, action("ESCALATE", severity=refused), COMMANDER_HEADERS
            ),
            ApiErrorId.SEVERITY_NOT_ESCALATING,
        )
    unchanged = validate_success(api.get_incident(incident_id, COMMANDER_HEADERS))
    assert unchanged["severity"] == Severity.MODERATE
    assert unchanged["severity_at_report"] == Severity.MODERATE

    escalated = validate_success(
        api.incident_action(
            incident_id, action("ESCALATE", severity=Severity.SEVERE), COMMANDER_HEADERS
        )
    )
    assert escalated["severity"] == Severity.SEVERE
    assert escalated["severity_at_report"] == Severity.MODERATE
    assert escalated["status"] == IncidentStatus.TRIAGED

    event = validate_success(api.get_event(world.event_id, DIRECTOR_HEADERS))
    assert event["open_critical_incident_count"] == 0
    assert event["gate_posture"] == GatePosture.OPEN


def test_briefing_the_event_requires_the_plan_to_be_ready_not_merely_at_risk():
    """At-risk is not ready, and the error says so specifically.

    Every confirmed guard has already been briefed, so the generic state error is
    not what fires: the named readiness rule is. Trimming the understaffed post's
    requirement to the headcount that actually turned up flips the posture to
    READY without moving a single guard or a single cent, and the briefing then
    goes through.

    PRD: "**Readiness for briefing** — a briefing requires the event's current plan to have `readiness_posture` equal to `READY`, else `ERR_PLAN_NOT_READY` (409). Guards `POST /event-security/security-events/{id}/lifecycle` for the `BRIEF` action."
    Design: Corner/validations/event_brief_with_at_risk_plan_returns_plan_not_ready
    """
    api = ApiClient()
    world = build_published_plan_with_posts_world(
        api,
        [
            {
                "code": "S1",
                "post_type": PostType.SUPERVISOR,
                "required_guard_count": 1,
                "min_credential_level": 3,
            },
            {"code": "P1", "post_type": PostType.PERIMETER, "required_guard_count": 9},
        ],
    )
    supervisor_guard = create_verified_guard(
        api, "GC-6000", credential_level=3, full_name="Sam Sentinel"
    )
    rows = [create_assignment(api, world.s1_id, supervisor_guard)]
    for index in range(8):
        guard_id = create_verified_guard(
            api, "GC-600%d" % (index + 1), full_name="Gale %d" % (index + 1)
        )
        rows.append(create_assignment(api, world.p1_id, guard_id))
    for row in rows:
        confirm(api, row)
    validate_success(
        api.staffing_plan_lifecycle(world.plan_id, action("ACTIVATE"), DIRECTOR_HEADERS)
    )
    for row in rows:
        brief(api, row, supervisor_guard)

    validate_error(
        api.event_lifecycle(world.event_id, action("BRIEF"), DIRECTOR_HEADERS),
        ApiErrorId.PLAN_NOT_READY,
    )
    assert (
        validate_success(api.get_event(world.event_id, DIRECTOR_HEADERS))["status"]
        == EventStatus.STAFFED
    )

    validate_success(
        api.update_post(
            world.p1_id,
            {
                "expected_post_version": read_post_version(api, world.p1_id),
                "required_guard_count": 8,
            },
            COORDINATOR_HEADERS,
        )
    )
    summary = validate_success(api.get_coverage_summary(world.plan_id, COORDINATOR_HEADERS))
    assert_coverage(summary, 9, 9, 1.00, ReadinessPosture.READY)
    assert summary["understaffed_post_count"] == 0
    assert summary["supervisor_coverage_ok"] is True
    assert_ledger(summary, 148500, 67.50)
    assert_post_fill(
        validate_success(api.get_post(world.p1_id, COORDINATOR_HEADERS)), 8, PostStatus.FILLED
    )

    briefed = validate_success(
        api.event_lifecycle(world.event_id, action("BRIEF"), DIRECTOR_HEADERS)
    )
    assert briefed["status"] == EventStatus.BRIEFED


def test_a_lane_cannot_open_with_nobody_standing_at_it():
    """Briefed operators do not count; checked-in ones do.

    The lane is refused while both its operators are still at the briefing, and
    the refusal leaves the lane untouched down to its version. One check-in is
    enough to open it, at half rate because the lane is crewed one of two — and
    the operator who stayed briefed still contributes nothing.

    PRD: "**Lane staffing** — opening a lane requires its `assigned_operator_count` to be at least 1, else `ERR_LANE_UNSTAFFED` (409). Guards `POST /event-security/screening-lanes/{id}/status` for the `OPEN` action."
    Design: Corner/validations/lane_open_without_on_post_operator_returns_lane_unstaffed
    """
    api = ApiClient()
    world = build_briefed_event_world(api)

    validate_error(
        api.screening_lane_status(world.lane1_id, action("OPEN"), COORDINATOR_HEADERS),
        ApiErrorId.LANE_UNSTAFFED,
    )
    idle = validate_success(api.get_screening_lane(world.lane1_id, COORDINATOR_HEADERS))
    assert idle["status"] == LaneStatus.PLANNED
    assert idle["assigned_operator_count"] == 0
    assert idle["effective_throughput_pph"] == 0
    assert idle["version"] == 1

    check_in(api, world.a_i1, world.gs_id)
    opened = validate_success(
        api.screening_lane_status(world.lane1_id, action("OPEN"), COORDINATOR_HEADERS)
    )
    assert opened["status"] == LaneStatus.OPEN
    assert opened["assigned_operator_count"] == 1
    assert opened["effective_throughput_pph"] == 87

    still_briefed = validate_success(api.get_post_assignment(world.a_i2, COORDINATOR_HEADERS))
    assert still_briefed["duty_status"] == DutyStatus.BRIEFED


def test_every_request_needs_its_identity_headers_before_anything_else_is_looked_at():
    """Authentication precedes even the question of whether the row exists.

    An existing row, a non-existent row and a create attempt all fail the same
    way with no headers — notably the unknown plan is a 401 and not a 404, because
    the header check is the first rank of the ladder. Each refusal still carries
    the standard envelope.

    PRD: "**Header presence** — `X-User-ID` and `X-User-Role` are present and non-empty, else `ERR_UNAUTHENTICATED` (401). Applies to every endpoint."
    Design: Corner/validations/missing_auth_headers_return_unauthenticated
    """
    api = ApiClient()
    world = build_event_world(api)

    existing = api.get_event(world.event_id, {})
    validate_error(existing, ApiErrorId.UNAUTHENTICATED)
    assert_error_envelope_meta(existing)

    unknown = api.get_staffing_plan(NON_EXISTENT_UUID, {})
    validate_error(unknown, ApiErrorId.UNAUTHENTICATED)
    assert_error_envelope_meta(unknown)

    creating = api.create_venue(venue_payload(name="Quiet Hall", gross_capacity=2000), {})
    validate_error(creating, ApiErrorId.UNAUTHENTICATED)
    assert_error_envelope_meta(creating)


def test_publishing_needs_as_many_declared_slots_as_the_assessment_asked_for():
    """Four declared slots against an assessed five, then the exact repair.

    The plan is refused while it is one slot short, and stays in DRAFT with no
    version pin. Raising the post's requirement by one makes the comparison an
    equality, which is accepted — and publishing does not require anybody to be
    rostered into those slots yet.

    PRD: "**Assessed floor on headcount** — a publish requires the plan's `required_total_staff` to be at least the assessment's `required_total_staff`, else `ERR_STAFFING_BELOW_ASSESSED_REQUIREMENT` (422). Guards the `PUBLISH` action."
    Design: Corner/validations/publish_below_assessed_requirement_returns_staffing_below_assessed_requirement
    """
    api = ApiClient()
    world = build_plan_world(api)
    post = validate_success(
        api.create_post(
            world.plan_id,
            post_payload(world.zf_id, "P1", PostType.PERIMETER, required_guard_count=4),
            COORDINATOR_HEADERS,
        ),
        expected_status=201,
    )

    validate_error(
        api.staffing_plan_lifecycle(world.plan_id, action("PUBLISH"), COORDINATOR_HEADERS),
        ApiErrorId.STAFFING_BELOW_ASSESSED_REQUIREMENT,
    )
    short = validate_success(api.get_staffing_plan(world.plan_id, COORDINATOR_HEADERS))
    assert short["status"] == PlanStatus.DRAFT
    assert short["required_total_staff"] == 4
    assert short["pinned_risk_assessment_version"] is None

    validate_success(
        api.update_post(
            post["id"],
            {
                "expected_post_version": read_post_version(api, post["id"]),
                "required_guard_count": 5,
            },
            COORDINATOR_HEADERS,
        )
    )
    published = validate_success(
        api.staffing_plan_lifecycle(world.plan_id, action("PUBLISH"), COORDINATOR_HEADERS)
    )
    assert published["status"] == PlanStatus.PUBLISHED
    assert published["required_total_staff"] == 5
    assert published["pinned_risk_assessment_version"] == 3
    assert_coverage(published, 5, 0, 0.00, ReadinessPosture.BLOCKED)


def test_a_budget_one_cent_under_the_assessed_floor_cannot_be_published():
    """The floor is a `>=` comparison, checked against a plan that cannot be edited up.

    A budget is fixed at creation, so the only repair is a replacement plan — which
    supersedes the under-funded one and closes its post on the way. The
    replacement, funded at exactly the floor, publishes.

    PRD: "**Budget floor** — a publish requires the plan's `budget_cents` to be at least the assessment's `minimum_staffing_cost_floor_cents`, else `ERR_PLAN_BUDGET_BELOW_FLOOR` (402). Guards the `PUBLISH` action."
    Design: Corner/validations/publish_with_budget_below_floor_returns_plan_budget_below_floor
    """
    api = ApiClient()
    world = build_plan_world(api, budget_cents=35999)
    first_post = validate_success(
        api.create_post(
            world.plan_id,
            post_payload(world.zf_id, "P1", PostType.PERIMETER, required_guard_count=5),
            COORDINATOR_HEADERS,
        ),
        expected_status=201,
    )

    validate_error(
        api.staffing_plan_lifecycle(world.plan_id, action("PUBLISH"), COORDINATOR_HEADERS),
        ApiErrorId.PLAN_BUDGET_BELOW_FLOOR,
    )
    under_funded = validate_success(api.get_staffing_plan(world.plan_id, COORDINATOR_HEADERS))
    assert under_funded["status"] == PlanStatus.DRAFT
    assert under_funded["pinned_risk_assessment_version"] is None

    replacement = validate_success(
        api.create_staffing_plan(
            world.event_id,
            staffing_plan_payload(
                world.ra_id, read_event_version(api, world.event_id), budget_cents=36000
            ),
            COORDINATOR_HEADERS,
        ),
        expected_status=201,
    )
    superseded = validate_success(api.get_staffing_plan(world.plan_id, COORDINATOR_HEADERS))
    assert superseded["status"] == PlanStatus.SUPERSEDED
    assert superseded["is_current"] is False
    assert (
        validate_success(api.get_post(first_post["id"], COORDINATOR_HEADERS))["status"]
        == PostStatus.CLOSED
    )

    validate_success(
        api.create_post(
            replacement["id"],
            post_payload(world.zf_id, "P1", PostType.PERIMETER, required_guard_count=5),
            COORDINATOR_HEADERS,
        ),
        expected_status=201,
    )
    published = validate_success(
        api.staffing_plan_lifecycle(replacement["id"], action("PUBLISH"), COORDINATOR_HEADERS)
    )
    assert published["status"] == PlanStatus.PUBLISHED
    assert published["pinned_risk_assessment_version"] == 3
    assert published["budget_remaining_cents"] == 36000
    assert_coverage(published, 5, 0, 0.00, ReadinessPosture.BLOCKED)


def test_nothing_can_be_written_through_a_superseded_plan():
    """Four writes on a retired plan, and the closed post is still not a 404.

    Declaring a post, re-profiling one, pencilling a shift in and publishing are
    all refused for the same reason, and the post-update refusal in particular
    proves the row is still there — merely closed. The replacement plan is the
    current one, and the retired plan's committed row was cancelled on the way out.

    PRD: "**Plan currency** — the owning staffing plan's `is_current` is true, else `ERR_PLAN_NOT_CURRENT` (409)."
    Design: Corner/validations/roster_write_on_superseded_plan_returns_plan_not_current
    """
    api = ApiClient()
    world = build_plan_with_perimeter_post_world(api)
    guard_id = create_verified_guard(api, "GC-7001")
    row = create_assignment(api, world.p1_id, guard_id)

    replacement = validate_success(
        api.create_staffing_plan(
            world.event_id,
            staffing_plan_payload(world.ra_id, read_event_version(api, world.event_id)),
            COORDINATOR_HEADERS,
        ),
        expected_status=201,
    )
    # Supersession closes the retired plan's posts, so the post's version has moved
    # (PRD 2.6). Pin the observed version afterwards, or rank 9 would pre-empt rank 11.
    post_version = read_post_version(api, world.p1_id)

    validate_error(
        api.create_post(
            world.plan_id,
            post_payload(world.zf_id, "P2", PostType.PERIMETER, required_guard_count=5),
            COORDINATOR_HEADERS,
        ),
        ApiErrorId.PLAN_NOT_CURRENT,
    )
    validate_error(
        api.update_post(
            world.p1_id,
            {"expected_post_version": post_version, "required_guard_count": 3},
            COORDINATOR_HEADERS,
        ),
        ApiErrorId.PLAN_NOT_CURRENT,
    )
    validate_error(
        api.create_post_assignment(
            {
                "post_id": world.p1_id,
                "guard_id": guard_id,
                "window_start": POST_WINDOW_START,
                "window_end": POST_WINDOW_END,
            },
            COORDINATOR_HEADERS,
        ),
        ApiErrorId.PLAN_NOT_CURRENT,
    )
    validate_error(
        api.staffing_plan_lifecycle(world.plan_id, action("PUBLISH"), COORDINATOR_HEADERS),
        ApiErrorId.PLAN_NOT_CURRENT,
    )

    retired = validate_success(api.get_staffing_plan(world.plan_id, COORDINATOR_HEADERS))
    assert retired["status"] == PlanStatus.SUPERSEDED
    assert retired["is_current"] is False

    closed_post = validate_success(api.get_post(world.p1_id, COORDINATOR_HEADERS))
    assert closed_post["status"] == PostStatus.CLOSED
    assert closed_post["required_guard_count"] == 5

    cancelled = validate_success(api.get_post_assignment(row, COORDINATOR_HEADERS))
    assert cancelled["assignment_status"] == AssignmentStatus.CANCELLED
    assert cancelled["cancellation_reason"] == "PLAN_SUPERSEDED"

    current = validate_success(api.get_staffing_plan(replacement["id"], COORDINATOR_HEADERS))
    assert current["is_current"] is True
    assert current["status"] == PlanStatus.DRAFT


def test_only_one_unfinalized_review_may_exist_per_event():
    """A draft incumbent blocks a rival, and so does a submitted one.

    Both competing creates are refused, and the incumbent's narrative, action
    count and author are untouched by the attempts. Only finalization would open
    the slot, which is why the submitted incumbent still blocks. The event carries
    exactly one review throughout.

    PRD: "**Single open review** — at most one after-action review per event may exist with a `status` other than `FINALIZED`, else `ERR_REVIEW_ALREADY_EXISTS` (409). Guards `POST /event-security/security-events/{id}/after-action-reviews`."
    Design: Corner/validations/second_after_action_review_returns_review_already_exists
    """
    api = ApiClient()
    world = build_review_world(api)
    incumbent = world.review

    validate_error(
        api.create_after_action_review(
            world.event_id,
            after_action_review_payload(narrative="a competing draft", corrective_action_count=1),
            DIRECTOR_HEADERS,
        ),
        ApiErrorId.REVIEW_ALREADY_EXISTS,
    )
    submitted = validate_success(
        api.after_action_review_decision(world.aar_id, action("SUBMIT"), COMMANDER_HEADERS)
    )
    assert submitted["status"] == ReviewStatus.SUBMITTED

    validate_error(
        api.create_after_action_review(
            world.event_id,
            after_action_review_payload(
                narrative="another competing draft", corrective_action_count=2
            ),
            DIRECTOR_HEADERS,
        ),
        ApiErrorId.REVIEW_ALREADY_EXISTS,
    )

    assert submitted["narrative"] == incumbent["narrative"]
    assert submitted["corrective_action_count"] == incumbent["corrective_action_count"]
    assert submitted["authored_by_user_id"] == "commander-1"

    _, meta = validate_paginated(
        api.list_event_after_action_reviews(world.event_id, DIRECTOR_HEADERS)
    )
    assert meta["total_count"] == 1


def test_a_supervisor_may_not_be_given_an_eleventh_guard_slot_to_watch():
    """Ten reporting slots is the bound, and the bound itself is legal.

    The eleventh slot is refused and no fourth post appears. Freeing one slot on
    an existing subordinate post makes room, and the same create then lands on
    exactly ten reporting slots. The plan's own headcount counts the supervisor's
    slot on top of those ten.

    PRD: "**Span of control** — the sum of `required_guard_count` over the posts reporting to a given `SUPERVISOR` post does not exceed 10, else `ERR_SPAN_OF_CONTROL_EXCEEDED` (422). Guards `POST /event-security/staffing-plans/{id}/posts` and `PATCH /event-security/posts/{id}`."
    Design: Corner/validations/span_of_control_exceeded_on_post_create
    """
    api = ApiClient()
    world = build_plan_world(api)
    supervisor = validate_success(
        api.create_post(
            world.plan_id,
            post_payload(world.zf_id, "S1", PostType.SUPERVISOR, required_guard_count=1),
            COORDINATOR_HEADERS,
        ),
        expected_status=201,
    )
    validate_success(
        api.create_post(
            world.plan_id,
            post_payload(
                world.zf_id,
                "P1",
                PostType.PERIMETER,
                required_guard_count=6,
                reports_to_post_id=supervisor["id"],
            ),
            COORDINATOR_HEADERS,
        ),
        expected_status=201,
    )
    second = validate_success(
        api.create_post(
            world.plan_id,
            post_payload(
                world.zf_id,
                "P2",
                PostType.FLOOR,
                required_guard_count=4,
                reports_to_post_id=supervisor["id"],
            ),
            COORDINATOR_HEADERS,
        ),
        expected_status=201,
    )

    eleventh = post_payload(
        world.zf_id,
        "P3",
        PostType.FLOOR,
        required_guard_count=1,
        reports_to_post_id=supervisor["id"],
    )
    validate_error(
        api.create_post(world.plan_id, eleventh, COORDINATOR_HEADERS),
        ApiErrorId.SPAN_OF_CONTROL_EXCEEDED,
    )
    _, meta = validate_paginated(
        api.list_posts(COORDINATOR_HEADERS, params={"staffing_plan_id": world.plan_id})
    )
    assert meta["total_count"] == 3

    validate_success(
        api.update_post(
            second["id"],
            {
                "expected_post_version": read_post_version(api, second["id"]),
                "required_guard_count": 3,
            },
            COORDINATOR_HEADERS,
        )
    )
    validate_success(
        api.create_post(world.plan_id, eleventh, COORDINATOR_HEADERS), expected_status=201
    )

    plan = validate_success(api.get_staffing_plan(world.plan_id, COORDINATOR_HEADERS))
    assert plan["required_total_staff"] == 11
    _, meta = validate_paginated(
        api.list_posts(COORDINATOR_HEADERS, params={"staffing_plan_id": world.plan_id})
    )
    assert meta["total_count"] == 4


def test_a_foreign_zone_and_a_non_supervisor_report_target_share_one_scoping_error():
    """Existence is not enough: the reference has to belong here.

    Another venue's zone is refused for a post, a lane and a density reading
    alike, and the same error covers a `reports_to_post_id` that names a real post
    which simply is not a supervisor. Every refusal is a 422 rather than a 404,
    because each referenced row does exist. Nothing was written on any of the four
    attempts.

    PRD: "**Referential scoping** — a referenced zone belongs to the event's venue, a referenced lane belongs to the same event, `reports_to_post_id` names a `SUPERVISOR` post in the same staffing plan, and `risk_assessment_id` belongs to the event named in the path. Any mismatch is `ERR_ZONE_VENUE_MISMATCH` (422)."
    Design: Corner/validations/zone_venue_mismatch_rejects_foreign_zone_and_non_supervisor_report_target
    """
    api = ApiClient()
    world = build_plan_with_perimeter_post_world(api)
    other_venue = validate_success(
        api.create_venue(
            venue_payload(name="Riverside Bowl", gross_capacity=20000, door_count=6),
            DIRECTOR_HEADERS,
        ),
        expected_status=201,
    )
    foreign_zone = validate_success(
        api.create_zone(
            other_venue["id"],
            zone_payload(zone_code="ZX", zone_type=ZoneType.SEATED, is_ingress_zone=True),
            DIRECTOR_HEADERS,
        ),
        expected_status=201,
    )

    validate_error(
        api.create_post(
            world.plan_id,
            post_payload(foreign_zone["id"], "PY", PostType.FLOOR),
            COORDINATOR_HEADERS,
        ),
        ApiErrorId.ZONE_VENUE_MISMATCH,
    )
    validate_error(
        api.create_post(
            world.plan_id,
            post_payload(world.zf_id, "PZ", PostType.FLOOR, reports_to_post_id=world.p1_id),
            COORDINATOR_HEADERS,
        ),
        ApiErrorId.ZONE_VENUE_MISMATCH,
    )
    validate_error(
        api.create_screening_lane(
            world.event_id,
            screening_lane_payload(foreign_zone["id"], lane_type=LaneType.BAG_CHECK),
            COORDINATOR_HEADERS,
        ),
        ApiErrorId.ZONE_VENUE_MISMATCH,
    )
    validate_error(
        api.create_density_reading(
            world.event_id,
            density_reading_payload(foreign_zone["id"], PRE_DOORS_INSTANT, 100),
            DIRECTOR_HEADERS,
        ),
        ApiErrorId.ZONE_VENUE_MISMATCH,
    )

    _, posts_meta = validate_paginated(
        api.list_posts(COORDINATOR_HEADERS, params={"staffing_plan_id": world.plan_id})
    )
    assert posts_meta["total_count"] == 1
    plan = validate_success(api.get_staffing_plan(world.plan_id, COORDINATOR_HEADERS))
    assert plan["required_total_staff"] == 5

    _, lanes_meta = validate_paginated(
        api.list_screening_lanes(COORDINATOR_HEADERS, params={"event_id": world.event_id})
    )
    assert lanes_meta["total_count"] == 0
    _, readings_meta = validate_paginated(
        api.list_density_readings(DIRECTOR_HEADERS, params={"event_id": world.event_id})
    )
    assert readings_meta["total_count"] == 0
