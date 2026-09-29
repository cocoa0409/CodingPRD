"""The derived numbers, checked where the arithmetic can go wrong.

Three-way minima with a truncated division, a pinned score order with two caps,
the downward-only supervisor pass, per-stream lane ceilings, the two-tier shift
cost with its separate roundings, the strict SLA comparison, the ladder
boundaries at exactly 0.90 and one place below, and the two ledgers that must not
contaminate each other.
"""

from test_helpers import (
    ANALYST_HEADERS,
    COMMANDER_HEADERS,
    COORDINATOR_HEADERS,
    DIRECTOR_HEADERS,
    ApiClient,
    AssessmentStatus,
    AssignmentStatus,
    AttendanceBasis,
    CrowdProfile,
    DensityLevel,
    DutyStatus,
    EventStatus,
    GatePosture,
    IncidentCategory,
    IncidentStatus,
    IngressStatus,
    LaneStatus,
    PayBasis,
    PlanStatus,
    PostStatus,
    PostType,
    ProtestLikelihood,
    ReadinessPosture,
    ReviewStatus,
    RiskTier,
    Severity,
    ThreatLevel,
    ZoneType,
    action,
    assert_assignment_cost,
    assert_assignment_state,
    assert_coverage,
    assert_coverage_summary_shape,
    assert_decimal,
    assert_four_decimals,
    assert_gate,
    assert_ledger,
    assert_money,
    assert_post_fill,
    build_briefed_event_world,
    build_doors_open_world,
    build_plan_with_perimeter_post_world,
    build_plan_world,
    build_published_plan_with_posts_world,
    build_review_world,
    build_venue_world,
    check_in,
    confirm,
    create_assignment,
    create_verified_guard,
    event_payload,
    incident_payload,
    make_post_supervisor_headers,
    post_payload,
    read_post_version,
    risk_assessment_payload,
    set_clock,
    validate_success,
    venue_payload,
    zone_payload,
)

POST_WINDOW_END = "2026-09-12T22:30:00Z"
EARLY_WINDOW_START = "2026-09-12T12:00:00Z"
RELIEF_INSTANT = "2026-09-12T20:00:00Z"


def test_the_binding_occupancy_ceiling_can_be_any_of_the_three_and_the_area_one_truncates():
    """Three zones, three different ceilings doing the binding.

    The concourse is squeezed by its floor space, the floor by its exits, and the
    seated bowl by floor space again — this time on a division with a fraction,
    which is dropped rather than rounded, so the answer is 1538 and not 1539.
    None of the three inputs is consumed: every zone still echoes its own.

    PRD: "The second is an area ceiling: the fire-code allowance is 0.65 square metres of usable floor per person, so the zone's `floor_area_sqm` divided by that allowance, rounded down to a whole person, gives the number the floor space can hold. The third is an egress ceiling: each exit unit can discharge 100 persons, so `exit_units` multiplied by 100 gives the number the exits can clear. `max_safe_occupancy` is the smallest of those three whole numbers."
    Design: Corner/calculations/zone_max_safe_occupancy_applies_declared_constants
    """
    api = ApiClient()
    world = build_venue_world(api)

    area_bound = validate_success(
        api.create_zone(
            world.venue_id,
            zone_payload(
                zone_code="ZA",
                zone_type=ZoneType.CONCOURSE,
                floor_area_sqm=65.0,
                posted_capacity=500,
                exit_units=5,
            ),
            DIRECTOR_HEADERS,
        ),
        expected_status=201,
    )
    assert area_bound["max_safe_occupancy"] == 100
    assert_decimal(area_bound["floor_area_sqm"], 65.00, "floor_area_sqm")
    assert area_bound["posted_capacity"] == 500
    assert area_bound["exit_units"] == 5
    assert area_bound["post_slot_capacity"] == 12
    assert area_bound["version"] == 1

    egress_bound = validate_success(
        api.create_zone(
            world.venue_id,
            zone_payload(
                zone_code="ZB",
                zone_type=ZoneType.FLOOR,
                floor_area_sqm=1000.0,
                posted_capacity=500,
                exit_units=2,
            ),
            DIRECTOR_HEADERS,
        ),
        expected_status=201,
    )
    assert egress_bound["max_safe_occupancy"] == 200
    assert egress_bound["exit_units"] == 2
    assert egress_bound["version"] == 1

    truncated = validate_success(
        api.create_zone(
            world.venue_id,
            zone_payload(
                zone_code="ZC",
                zone_type=ZoneType.SEATED,
                floor_area_sqm=1000.0,
                posted_capacity=5000,
                exit_units=20,
            ),
            DIRECTOR_HEADERS,
        ),
        expected_status=201,
    )
    assert truncated["max_safe_occupancy"] == 1538
    assert truncated["posted_capacity"] == 5000
    assert truncated["version"] == 1


def _submitted_assessment(api: ApiClient, venue_body, event_body, assessment_body):
    """Submit one assessment against a venue and event described inline."""
    venue = validate_success(api.create_venue(venue_body, DIRECTOR_HEADERS), expected_status=201)
    event = validate_success(
        api.create_event(event_payload(venue["id"], **event_body), DIRECTOR_HEADERS),
        expected_status=201,
    )
    draft = validate_success(
        api.create_risk_assessment(
            event["id"], risk_assessment_payload(**assessment_body), ANALYST_HEADERS
        ),
        expected_status=201,
    )
    return validate_success(
        api.risk_assessment_decision(draft["id"], action("SUBMIT"), ANALYST_HEADERS)
    )


def test_the_supervisor_pass_runs_downward_over_line_guards_only():
    """A small show needs one tier of supervision; a large one needs two.

    Sixteen line guards ask for two first-line supervisors, and two does not
    exceed the supervisor-to-supervisor span, so no second tier appears. Ninety-one
    line guards ask for ten, which does exceed it, so two more supervisors are
    added on top — never solved as a fixed point over the total headcount, which
    would give a larger answer. The cost floor and the per-stream lane ceilings
    ride on the same submissions.

    PRD: "The first-line supervisor count is `required_line_guards` divided by a span of control of 10, rounded up. A second line is added only when that first-line count exceeds a supervisor-to-supervisor span of 5: in that case the second-line count is the first-line count divided by 5, rounded up; otherwise it is zero. `required_supervisors` is the sum of the two lines, and the assessment's `required_total_staff` is `required_line_guards` plus `required_supervisors`."
    Design: Corner/calculations/assessment_approval_derives_supervisor_span_lane_and_cost_floor
    """
    api = ApiClient()
    set_clock(api, "2026-09-01T00:00:00Z")

    small = _submitted_assessment(
        api,
        venue_payload(name="Harbor Arena", gross_capacity=8000, door_count=3),
        {"expected_attendance": 5000},
        {
            "threat_level_input": ThreatLevel.GUARDED,
            "crowd_profile": CrowdProfile.GENERAL_ADMISSION,
            "ingress_door_count": 3,
            "layout_complexity_score": 2,
        },
    )
    assert small["status"] == AssessmentStatus.SUBMITTED
    assert_decimal(small["composite_threat_score"], 42.75, "composite_threat_score")
    assert small["risk_tier"] == RiskTier.T2
    assert small["required_perimeter_guards"] == 4
    assert small["required_ingress_guards"] == 4
    assert small["required_floor_guards"] == 5
    assert small["required_exit_guards"] == 3
    assert small["required_line_guards"] == 16
    assert small["required_supervisors"] == 2
    assert small["required_total_staff"] == 18
    assert_money(small["minimum_staffing_cost_floor_cents"], 129600)
    assert small["required_screening_lanes"] == 12
    assert small["attendance_basis"] == AttendanceBasis.EXPECTED
    assert small["score_basis_attendance"] == 5000

    large = _submitted_assessment(
        api,
        venue_payload(name="Riverside Bowl", gross_capacity=20000, door_count=6),
        {"expected_attendance": 15000, "alcohol_served": True, "vip_present": True},
        {
            "threat_level_input": ThreatLevel.ELEVATED,
            "protest_likelihood": ProtestLikelihood.POSSIBLE,
            "crowd_profile": CrowdProfile.MOSH_PIT,
            "ingress_door_count": 6,
            "layout_complexity_score": 4,
            "history_incident_rate": 2,
        },
    )
    assert large["status"] == AssessmentStatus.SUBMITTED
    assert_decimal(large["composite_threat_score"], 97.74, "composite_threat_score")
    assert large["risk_tier"] == RiskTier.T4
    assert large["required_perimeter_guards"] == 27
    assert large["required_ingress_guards"] == 23
    assert large["required_floor_guards"] == 32
    assert large["required_exit_guards"] == 9
    assert large["required_line_guards"] == 91
    assert large["required_supervisors"] == 12
    assert large["required_total_staff"] == 103
    assert_money(large["minimum_staffing_cost_floor_cents"], 741600)
    assert large["required_screening_lanes"] == 34
    assert large["attendance_basis"] == AttendanceBasis.EXPECTED
    assert large["score_basis_attendance"] == 15000


def test_a_triage_exactly_on_the_budget_is_not_a_breach():
    """Ten minutes flat against a ten-minute budget, and the strictness decides.

    The first incident lands exactly on its budget and passes, the second is one
    minute over its looser budget and fails, and the third is triaged twenty
    seconds after report, which is two decimal places of a minute rather than
    zero. None of the three is critical, so the gate never moves.

    PRD: "`sla_breached` is true when `response_minutes` is strictly greater than the budget for the incident's `severity_at_report` — 15 minutes for `MINOR`, 10 for `MODERATE`, 5 for `SEVERE` and 3 for `CRITICAL`."
    Design: Corner/calculations/incident_response_minutes_at_exact_sla_budget_is_not_a_breach
    """
    api = ApiClient()
    world = build_doors_open_world(api)

    on_budget = validate_success(
        api.create_incident(
            world.event_id,
            incident_payload(
                world.zf_id,
                IncidentCategory.MEDICAL,
                Severity.MODERATE,
                description="patron fainted at the pit rail",
            ),
            COMMANDER_HEADERS,
        ),
        expected_status=201,
    )
    set_clock(api, "2026-09-12T16:40:00Z")
    on_budget = validate_success(
        api.incident_action(on_budget["id"], action("TRIAGE"), COMMANDER_HEADERS)
    )
    assert on_budget["reported_at"] == "2026-09-12T16:30:00Z"
    assert on_budget["triaged_at"] == "2026-09-12T16:40:00Z"
    assert_decimal(on_budget["response_minutes"], 10.00, "response_minutes")
    assert on_budget["sla_breached"] is False
    assert on_budget["severity_at_report"] == Severity.MODERATE

    over_budget = validate_success(
        api.create_incident(
            world.event_id,
            incident_payload(
                world.zi_id,
                IncidentCategory.CROWD_SURGE,
                Severity.MINOR,
                description="brief push at door 1",
            ),
            COMMANDER_HEADERS,
        ),
        expected_status=201,
    )
    set_clock(api, "2026-09-12T16:56:00Z")
    over_budget = validate_success(
        api.incident_action(over_budget["id"], action("TRIAGE"), COMMANDER_HEADERS)
    )
    assert_decimal(over_budget["response_minutes"], 16.00, "response_minutes")
    assert over_budget["sla_breached"] is True
    assert over_budget["severity_at_report"] == Severity.MINOR

    sub_minute = validate_success(
        api.create_incident(
            world.event_id,
            incident_payload(
                world.zi_id,
                IncidentCategory.PROHIBITED_ITEM,
                Severity.SEVERE,
                description="wand alarm, secondary screen",
            ),
            COMMANDER_HEADERS,
        ),
        expected_status=201,
    )
    set_clock(api, "2026-09-12T16:56:20Z")
    sub_minute = validate_success(
        api.incident_action(sub_minute["id"], action("TRIAGE"), COMMANDER_HEADERS)
    )
    assert_decimal(sub_minute["response_minutes"], 0.33, "response_minutes")
    assert sub_minute["sla_breached"] is False
    assert sub_minute["severity_at_report"] == Severity.SEVERE

    for incident in (on_budget, over_budget, sub_minute):
        assert incident["status"] == IncidentStatus.TRIAGED

    event = validate_success(api.get_event(world.event_id, DIRECTOR_HEADERS))
    assert event["open_critical_incident_count"] == 0
    assert_gate(event, GatePosture.OPEN)


def test_escalating_after_a_slow_triage_neither_creates_nor_clears_a_breach():
    """The SLA verdict is frozen at triage against the severity as first reported.

    Twelve minutes was inside the minor budget, and re-badging the incident as
    critical does not retroactively measure it against the three-minute budget.
    What the escalation does move is the gate, which freezes on the open critical
    count — while leaving the door flow alone, since only the law-enforcement
    branch touches ingress.

    PRD: "The clock is keyed on `severity_at_report`, never on the possibly-escalated current `severity`, so escalating a minor incident to critical after a slow triage neither creates nor clears a breach."
    Design: Corner/calculations/sla_clock_keyed_on_severity_at_report_not_escalated_severity
    """
    api = ApiClient()
    world = build_doors_open_world(api)
    reported = validate_success(
        api.create_incident(
            world.event_id,
            incident_payload(
                world.zi_id,
                IncidentCategory.CROWD_SURGE,
                Severity.MINOR,
                description="shoving in the queue at door 1",
            ),
            COMMANDER_HEADERS,
        ),
        expected_status=201,
    )
    set_clock(api, "2026-09-12T16:42:00Z")
    triaged = validate_success(
        api.incident_action(reported["id"], action("TRIAGE"), COMMANDER_HEADERS)
    )
    assert_decimal(triaged["response_minutes"], 12.00, "response_minutes")
    assert triaged["sla_breached"] is False

    escalated = validate_success(
        api.incident_action(
            reported["id"], action("ESCALATE", severity=Severity.CRITICAL), COMMANDER_HEADERS
        )
    )
    assert escalated["severity"] == Severity.CRITICAL
    assert escalated["severity_at_report"] == Severity.MINOR
    assert_decimal(escalated["response_minutes"], 12.00, "response_minutes")
    assert escalated["sla_breached"] is False
    assert escalated["status"] == IncidentStatus.TRIAGED
    assert escalated["triaged_at"] == "2026-09-12T16:42:00Z"

    event = validate_success(api.get_event(world.event_id, COMMANDER_HEADERS))
    assert event["open_critical_incident_count"] == 1
    assert_gate(event, GatePosture.FROZEN, IngressStatus.NORMAL)


def test_the_review_metrics_drop_unfounded_reports_and_measure_the_committed_roster():
    """Five metrics computed at submission, each over a different filtered set.

    The unfounded report leaves the incident count entirely, while the roster
    denominator keeps the no-show row because it is still committed. The peak
    density is the higher of the two zones read that night, and the shortfall
    minutes count only the posts nobody ever actually stood — the briefed-but-absent
    guard and the no-show — at seven and a half hours each. Submission does not
    touch the event.

    PRD: "`total_incident_count` is the number of the event's incidents whose `status` is not `CLOSED_UNFOUNDED` — unfounded reports are excluded from the count entirely."
    Design: Corner/calculations/after_action_metrics_exclude_unfounded_incidents_and_tentative_rows
    """
    api = ApiClient()
    world = build_review_world(api)

    submitted = validate_success(
        api.after_action_review_decision(world.aar_id, action("SUBMIT"), COMMANDER_HEADERS)
    )
    assert submitted["status"] == ReviewStatus.SUBMITTED
    assert submitted["total_incident_count"] == 2
    assert submitted["sla_breach_count"] == 1
    assert submitted["peak_density_level"] == DensityLevel.RED
    assert_four_decimals(submitted["no_show_rate"], 0.1667, "no_show_rate")
    assert_decimal(submitted["coverage_shortfall_minutes"], 900.00, "coverage_shortfall_minutes")
    assert submitted["authored_by_user_id"] == "commander-1"
    assert submitted["finalized_by_user_id"] is None

    event = validate_success(api.get_event(world.event_id, DIRECTOR_HEADERS))
    assert event["status"] == EventStatus.CLOSED


def test_lane_throughput_tracks_the_bodies_actually_standing_at_the_lane():
    """A half-crewed lane runs at half rate, and the drag is never escaped.

    Before the lane opens the formula short-circuits to zero even though an
    operator has already checked in. Open with one of two operators gives half of
    195 with the ten percent secondary-screening drag on top; the second operator
    caps the staffing factor at one, leaving the drag alone to account for the
    twenty pph shortfall against the rating. A hold zeroes the throughput without
    sending anybody home.

    PRD: "`effective_throughput_pph` is `nominal_throughput_pph` multiplied by the staffing factor multiplied by the drag factor, rounded **down** to a whole patron per hour."
    Design: Corner/calculations/lane_effective_throughput_scales_by_staffing_factor_and_prohibited_item_drag
    """
    api = ApiClient()
    world = build_briefed_event_world(api)

    check_in(api, world.a_i1, world.gs_id)
    planned = validate_success(api.get_screening_lane(world.lane1_id, COORDINATOR_HEADERS))
    assert planned["status"] == LaneStatus.PLANNED
    assert planned["assigned_operator_count"] == 1
    assert planned["effective_throughput_pph"] == 0

    opened = validate_success(
        api.screening_lane_status(world.lane1_id, action("OPEN"), COORDINATOR_HEADERS)
    )
    assert opened["status"] == LaneStatus.OPEN
    assert opened["assigned_operator_count"] == 1
    assert opened["effective_throughput_pph"] == 87

    check_in(api, world.a_i2, world.gs_id)
    crewed = validate_success(api.get_screening_lane(world.lane1_id, COORDINATOR_HEADERS))
    assert crewed["assigned_operator_count"] == 2
    assert crewed["effective_throughput_pph"] == 175

    held = validate_success(
        api.screening_lane_status(world.lane1_id, action("HOLD"), COORDINATOR_HEADERS)
    )
    assert held["status"] == LaneStatus.HOLD
    assert held["effective_throughput_pph"] == 0
    assert held["assigned_operator_count"] == 2

    for assignment_id in (world.a_i1, world.a_i2):
        row = validate_success(api.get_post_assignment(assignment_id, COORDINATOR_HEADERS))
        assert row["duty_status"] == DutyStatus.ON_POST


def test_a_ten_and_a_half_hour_shift_is_priced_in_two_tiers_and_two_roundings():
    """Overtime is a separate rounded term, not a blended rate.

    Eight straight hours and two and a half overtime hours are each costed and
    rounded on their own before being added, and the noon start keeps the night
    differential out of it. The seven-and-a-half hour shift never reaches the
    threshold, so it is priced straight. Neither row moves money until it is
    confirmed, and then the plan sums the two already-rounded line values.

    PRD: "First, base pay is the guard's `base_hourly_rate_cents` times straight hours, rounded to a whole cent, **plus** the guard's `base_hourly_rate_cents` times an overtime multiplier of 1.5 times overtime hours, rounded to a whole cent separately — two roundings, then an addition."
    Design: Corner/calculations/assignment_cost_splits_straight_and_overtime_hours
    """
    api = ApiClient()
    world = build_plan_world(api)
    post = validate_success(
        api.create_post(
            world.plan_id,
            post_payload(
                world.zf_id,
                "P1",
                PostType.PERIMETER,
                required_guard_count=5,
                window_start=EARLY_WINDOW_START,
            ),
            COORDINATOR_HEADERS,
        ),
        expected_status=201,
    )
    validate_success(
        api.staffing_plan_lifecycle(world.plan_id, action("PUBLISH"), COORDINATOR_HEADERS)
    )
    long_guard = create_verified_guard(api, "GC-7001")
    short_guard = create_verified_guard(api, "GC-7002", full_name="Gale Two")

    long_row = create_assignment(
        api, post["id"], long_guard, window_start=EARLY_WINDOW_START, window_end=POST_WINDOW_END
    )
    short_row = create_assignment(api, post["id"], short_guard)

    overtime = validate_success(api.get_post_assignment(long_row, COORDINATOR_HEADERS))
    assert_assignment_cost(overtime, 10.50, 25850, PayBasis.EMPLOYEE_OT)
    assert overtime["night_differential_applies"] is False
    assert overtime["assignment_status"] == AssignmentStatus.TENTATIVE

    straight = validate_success(api.get_post_assignment(short_row, COORDINATOR_HEADERS))
    assert_assignment_cost(straight, 7.50, 16500, PayBasis.EMPLOYEE_STRAIGHT)
    assert straight["assignment_status"] == AssignmentStatus.TENTATIVE

    pencilled = validate_success(api.get_staffing_plan(world.plan_id, COORDINATOR_HEADERS))
    assert_ledger(pencilled, 0, 0.00)

    confirm(api, long_row)
    confirm(api, short_row)
    plan = validate_success(api.get_staffing_plan(world.plan_id, COORDINATOR_HEADERS))
    assert_ledger(plan, 42350, 18.00, budget_remaining_cents=457650)
    assert plan["committed_cost_cents"] + plan["budget_remaining_cents"] == 500000

    summary = validate_success(api.get_coverage_summary(world.plan_id, COORDINATOR_HEADERS))
    assert_coverage_summary_shape(summary)
    assert_coverage(summary, 5, 2, 0.40, ReadinessPosture.BLOCKED)


def test_relief_bills_the_delivered_hours_without_disturbing_the_commitment():
    """Two cost columns on one row, and the billed one is strictly additive.

    Three and a half hours were actually stood, so the billed pair is written from
    the check-in and relief instants while the scheduled pair keeps its full
    seven-and-a-half-hour figures. The plan's committed columns and budget
    headroom do not move, because a completed row is still committed; only
    `billed_cost_cents` grows. The post keeps its fill, so readiness is untouched.

    PRD: "Relief then cascades on the roster dimension: `assignment_status` moves `CONFIRMED → COMPLETED`, the row's `billed_cost_cents` is added to the plan's `billed_cost_cents`, and the plan's `committed_cost_cents` and `committed_guard_hours` are deliberately left untouched, since a `COMPLETED` row stays inside the committed ledger set."
    Design: Corner/calculations/relieve_writes_billed_variant_and_leaves_committed_ledger_untouched
    """
    api = ApiClient()
    world = build_briefed_event_world(api)
    check_in(api, world.a_s1, world.gs_id)
    check_in(api, world.a_f1, world.gs_id)
    set_clock(api, RELIEF_INSTANT)

    relieved = validate_success(
        api.post_assignment_duty_event(
            world.a_f1, action("RELIEVE"), make_post_supervisor_headers(world.gs_id)
        )
    )
    assert_assignment_state(relieved, AssignmentStatus.COMPLETED, DutyStatus.RELIEVED)
    assert relieved["relieved_at"] == RELIEF_INSTANT
    assert_decimal(relieved["billed_hours"], 3.50, "billed_hours")
    assert_money(relieved["billed_cost_cents"], 7700, "billed_cost_cents")
    assert_assignment_cost(relieved, 7.50, 16500, PayBasis.EMPLOYEE_STRAIGHT)

    plan = validate_success(api.get_staffing_plan(world.plan_id, COORDINATOR_HEADERS))
    assert_ledger(plan, 82500, 37.50, budget_remaining_cents=417500)
    assert_money(plan["billed_cost_cents"], 7700, "billed_cost_cents")

    post = validate_success(api.get_post(world.f1_id, COORDINATOR_HEADERS))
    assert_post_fill(post, 1, PostStatus.FILLED)

    summary = validate_success(api.get_coverage_summary(world.plan_id, COORDINATOR_HEADERS))
    assert_coverage(summary, 5, 5, 1.00, ReadinessPosture.READY)


def test_a_fully_staffed_plan_with_no_supervisor_post_is_only_at_risk():
    """Full coverage is not readiness while the supervision term is unmet.

    Five of five slots filled satisfies the coverage clause outright, but the
    approved assessment asks for one supervisor and the plan has no supervisor
    post at all, so the first ladder clause fails on that term alone and the
    second decides. Declaring the supervisor post and staffing it flips the
    boolean and the posture together.

    PRD: "A separate boolean, `supervisor_coverage_ok`, is true when the number of assignments on the plan's `SUPERVISOR` posts with `assignment_status` in `CONFIRMED` or `COMPLETED` and `duty_status` other than `NO_SHOW` is at least the assessment's `required_supervisors`."
    Design: Corner/calculations/plan_posture_is_at_risk_at_full_coverage_without_supervisor_cover
    """
    api = ApiClient()
    world = build_plan_with_perimeter_post_world(api)
    validate_success(
        api.staffing_plan_lifecycle(world.plan_id, action("PUBLISH"), COORDINATOR_HEADERS)
    )
    for index in range(5):
        guard_id = create_verified_guard(
            api, "GC-700%d" % (index + 1), full_name="Gale %d" % (index + 1)
        )
        confirm(api, create_assignment(api, world.p1_id, guard_id))

    unsupervised = validate_success(api.get_coverage_summary(world.plan_id, COORDINATOR_HEADERS))
    assert_coverage(unsupervised, 5, 5, 1.00, ReadinessPosture.AT_RISK)
    assert unsupervised["supervisor_coverage_ok"] is False
    assert unsupervised["understaffed_post_count"] == 0
    assert_ledger(unsupervised, 82500, 37.50, budget_remaining_cents=417500)

    supervisor_post = validate_success(
        api.create_post(
            world.plan_id,
            post_payload(
                world.zf_id,
                "S1",
                PostType.SUPERVISOR,
                required_guard_count=1,
                min_credential_level=3,
            ),
            COORDINATOR_HEADERS,
        ),
        expected_status=201,
    )
    supervisor_guard = create_verified_guard(
        api, "GC-7006", credential_level=3, full_name="Sam Sentinel"
    )
    confirm(api, create_assignment(api, supervisor_post["id"], supervisor_guard))

    supervised = validate_success(api.get_coverage_summary(world.plan_id, COORDINATOR_HEADERS))
    assert_coverage(supervised, 6, 6, 1.00, ReadinessPosture.READY)
    assert supervised["supervisor_coverage_ok"] is True
    assert_ledger(supervised, 99000, 45.00, budget_remaining_cents=401000)

    assert_post_fill(
        validate_success(api.get_post(supervisor_post["id"], COORDINATOR_HEADERS)),
        1,
        PostStatus.FILLED,
    )
    assert_post_fill(
        validate_success(api.get_post(world.p1_id, COORDINATOR_HEADERS)), 5, PostStatus.FILLED
    )


def test_nine_tenths_of_coverage_is_at_risk_and_the_place_below_it_is_blocked():
    """The two ladder boundaries, approached from both sides of one denominator.

    Nine of ten filled is exactly the at-risk floor: enough for clause two, short
    of clause one. Trimming the requirement to nine makes the same roster READY
    without touching the roster. Releasing one guard then leaves eight of nine,
    which rounds to 0.89 — a single hundredth below the floor, and therefore
    blocked — and releases exactly that guard's money and hours.

    PRD: "Otherwise, if `coverage_ratio` is at least 0.90, the posture is `AT_RISK`."
    Design: Corner/calculations/coverage_ratio_boundary_ninety_percent_is_at_risk_and_eighty_nine_is_blocked
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
    confirm(api, create_assignment(api, world.s1_id, supervisor_guard))
    perimeter_rows = []
    for index in range(8):
        guard_id = create_verified_guard(
            api, "GC-600%d" % (index + 1), full_name="Gale %d" % (index + 1)
        )
        row = create_assignment(api, world.p1_id, guard_id)
        confirm(api, row)
        perimeter_rows.append(row)

    at_risk = validate_success(api.get_coverage_summary(world.plan_id, COORDINATOR_HEADERS))
    assert_coverage(at_risk, 10, 9, 0.90, ReadinessPosture.AT_RISK)
    assert at_risk["supervisor_coverage_ok"] is True
    assert at_risk["understaffed_post_count"] == 0
    assert_ledger(at_risk, 148500, 67.50)

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
    ready = validate_success(api.get_coverage_summary(world.plan_id, COORDINATOR_HEADERS))
    assert_coverage(ready, 9, 9, 1.00, ReadinessPosture.READY)

    validate_success(
        api.post_assignment_duty_event(
            perimeter_rows[0],
            action("CANCEL", cancellation_reason="guard reassigned to another event"),
            COORDINATOR_HEADERS,
        )
    )
    blocked = validate_success(api.get_coverage_summary(world.plan_id, COORDINATOR_HEADERS))
    assert_coverage(blocked, 9, 8, 0.89, ReadinessPosture.BLOCKED)
    assert_ledger(blocked, 132000, 60.00)
    assert blocked["understaffed_post_count"] == 0

    post = validate_success(api.get_post(world.p1_id, COORDINATOR_HEADERS))
    assert_post_fill(post, 7, PostStatus.PARTIALLY_STAFFED)


def test_a_short_post_only_becomes_understaffed_once_the_plan_goes_live():
    """The same fill count reads differently either side of activation.

    One of four guards on a published plan is a partial fill; activating the plan
    makes the identical shortfall an understaffed post, because that clause is
    conditioned on the plan being live and outranks the partial one. The
    supervisor post is unaffected, since the fill clause is checked first. The
    activation drags the event to STAFFED and, with the plan blocked, restricts
    the gate.

    PRD: "Otherwise, if the plan's `status` is `ACTIVATED` or `LOCKED`, the post is `UNDERSTAFFED`."
    Design: Corner/calculations/post_status_ladder_marks_understaffed_only_after_activation
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
    supervisor_guard = create_verified_guard(
        api, "GC-7101", credential_level=3, full_name="Sam Sentinel"
    )
    confirm(api, create_assignment(api, world.s1_id, supervisor_guard))
    line_guard = create_verified_guard(api, "GC-7102", full_name="Gale One")
    confirm(api, create_assignment(api, world.p1_id, line_guard))

    assert_post_fill(
        validate_success(api.get_post(world.s1_id, COORDINATOR_HEADERS)), 1, PostStatus.FILLED
    )
    assert_post_fill(
        validate_success(api.get_post(world.p1_id, COORDINATOR_HEADERS)),
        1,
        PostStatus.PARTIALLY_STAFFED,
    )
    published = validate_success(api.get_coverage_summary(world.plan_id, COORDINATOR_HEADERS))
    assert_coverage(published, 5, 2, 0.40, ReadinessPosture.BLOCKED)
    assert published["understaffed_post_count"] == 0

    activated = validate_success(
        api.staffing_plan_lifecycle(world.plan_id, action("ACTIVATE"), DIRECTOR_HEADERS)
    )
    assert activated["status"] == PlanStatus.ACTIVATED

    assert_post_fill(
        validate_success(api.get_post(world.p1_id, COORDINATOR_HEADERS)),
        1,
        PostStatus.UNDERSTAFFED,
    )
    assert_post_fill(
        validate_success(api.get_post(world.s1_id, COORDINATOR_HEADERS)), 1, PostStatus.FILLED
    )

    live = validate_success(api.get_coverage_summary(world.plan_id, COORDINATOR_HEADERS))
    assert_coverage(live, 5, 2, 0.40, ReadinessPosture.BLOCKED)
    assert live["understaffed_post_count"] == 1
    assert live["supervisor_coverage_ok"] is True
    assert_ledger(live, 33000, 15.00)

    event = validate_success(api.get_event(world.event_id, DIRECTOR_HEADERS))
    assert event["status"] == EventStatus.STAFFED
    assert_gate(event, GatePosture.RESTRICTED)
