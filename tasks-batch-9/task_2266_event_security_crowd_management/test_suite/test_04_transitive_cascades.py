"""One request, four levels of the graph re-derived.

The canonical chain runs upward from a roster row: the post's fill, then the
plan's coverage and ledger, then the event's gate posture. Three triggers are
exercised here — a coordinator's cancellation, the clock-driven credential
expiry sweep, and a critical law-enforcement handoff that runs downward through
ingress into every open lane — and each is checked at every hop it touches.
"""

from test_helpers import (
    COMMANDER_HEADERS,
    COORDINATOR_HEADERS,
    DIRECTOR_HEADERS,
    ApiClient,
    ApiErrorId,
    AssignmentStatus,
    DutyStatus,
    EventStatus,
    GatePosture,
    IncidentCategory,
    IngressStatus,
    LaneStatus,
    PostStatus,
    ReadinessPosture,
    Severity,
    VerificationStatus,
    action,
    assert_assignment_state,
    assert_coverage,
    assert_gate,
    assert_ledger,
    assert_post_fill,
    build_canonical_five_post_activated_world,
    build_doors_open_world,
    cancel_action,
    incident_payload,
    set_clock,
    validate_error,
    validate_success,
)

EXPIRY_SWEEP_CLOCK = "2026-09-13T00:00:00Z"


def _cancelled_world(api: ApiClient):
    world = build_canonical_five_post_activated_world(api)
    world.cancelled = validate_success(
        api.post_assignment_duty_event(
            world.a_p1, cancel_action("guard withdrew"), COORDINATOR_HEADERS
        )
    )
    return world


def test_cancelling_a_confirmed_shift_walks_post_then_plan_then_event():
    """One cancellation drops a post to UNDERSTAFFED, the plan to BLOCKED, the gate to RESTRICTED.

    The row keeps its duty dimension at PENDING_BRIEF and records the reason it
    was pulled. Its post loses its only filled slot; the plan falls to four of
    five slots with one understaffed post; the event's gate follows the plan down.

    PRD: "Cancelling a `CONFIRMED` row runs the compensating cascade: hop one lowers the post's `filled_guard_count` by one and re-derives the post's `status`, which typically means `FILLED → UNDERSTAFFED` once the plan is `ACTIVATED` or `LOCKED`; hop two re-derives the plan's `coverage_ratio`, `understaffed_post_count` and `readiness_posture`, which typically means `READY → BLOCKED` once `coverage_ratio` falls below 0.90; hop three re-derives the event's `gate_posture`, which typically means `OPEN → RESTRICTED`."
    Design: Difficulty/transitive_cascade/cancel_confirmed_assignment_cascades_post_plan_event
    """
    api = ApiClient()
    world = _cancelled_world(api)

    assert_assignment_state(world.cancelled, AssignmentStatus.CANCELLED, DutyStatus.PENDING_BRIEF)
    assert world.cancelled["cancellation_reason"] == "guard withdrew"

    post = validate_success(api.get_post(world.p1_id, COORDINATOR_HEADERS))
    assert_post_fill(post, 0, PostStatus.UNDERSTAFFED)

    plan = validate_success(api.get_staffing_plan(world.plan_id, COORDINATOR_HEADERS))
    assert_coverage(plan, 5, 4, 0.80, ReadinessPosture.BLOCKED)
    assert plan["understaffed_post_count"] == 1

    event = validate_success(api.get_event(world.event_id, DIRECTOR_HEADERS))
    assert_gate(event, GatePosture.RESTRICTED)
    assert event["status"] == EventStatus.STAFFED


def test_cancellation_releases_exactly_one_shift_and_leaves_the_peers_alone():
    """16500 cents and 7.50 hours come back out of the ledger and nothing else moves.

    The four surviving posts stay FILLED and their rows stay CONFIRMED, so the
    committed columns fall from 82500 to 66000 cents and from 37.50 to 30.00
    hours with the budget still conserved to the cent.

    PRD: "The compensating ledger sync subtracts the row's `line_cost_cents` from `committed_cost_cents` and its `scheduled_hours` from `committed_guard_hours`, then recomputes `budget_remaining_cents`."
    Design: Difficulty/transitive_cascade/cancel_confirmed_assignment_cascades_post_plan_event
    """
    api = ApiClient()
    world = _cancelled_world(api)

    plan = validate_success(api.get_staffing_plan(world.plan_id, COORDINATOR_HEADERS))
    assert_ledger(plan, 66000, 30.00, budget_remaining_cents=434000)

    for post_id in (world.s1_id, world.i1_id, world.f1_id, world.e1_id):
        post = validate_success(api.get_post(post_id, COORDINATOR_HEADERS))
        assert_post_fill(post, 1, PostStatus.FILLED)

    for assignment_id in (world.a_i1, world.a_e1):
        row = validate_success(api.get_post_assignment(assignment_id, COORDINATOR_HEADERS))
        assert row["assignment_status"] == AssignmentStatus.CONFIRMED


def _swept_world(api: ApiClient):
    world = build_canonical_five_post_activated_world(
        api, exit_guard_credential_expires_on=EXPIRY_SWEEP_CLOCK
    )
    world.sweep = set_clock(api, EXPIRY_SWEEP_CLOCK)
    return world


def test_clock_advance_sweeps_the_lapsed_card_and_reports_what_it_touched():
    """Moving the clock onto the expiry instant strands one guard and one shift.

    The comparison is at-or-before, so a card expiring at exactly the new clock
    value lapses. The checkpoint response names the new instant and counts one
    expired guard and one voided assignment; the two guards whose cards run to
    year end are untouched.

    PRD: "The call reports how many guards expired and how many assignments were voided as a result."
    Design: Difficulty/transitive_cascade/clock_sweep_credential_expiry_cascades_four_hops
    """
    api = ApiClient()
    world = _swept_world(api)

    assert world.sweep["current_utc"] == EXPIRY_SWEEP_CLOCK
    assert world.sweep["expired_guard_count"] == 1
    assert world.sweep["voided_assignment_count"] == 1

    lapsed = validate_success(api.get_guard(world.g4_id, COORDINATOR_HEADERS))
    assert lapsed["verification_status"] == VerificationStatus.EXPIRED
    assert lapsed["verified_at"] is None

    for guard_id in (world.gs_id, world.g1_id):
        guard = validate_success(api.get_guard(guard_id, COORDINATOR_HEADERS))
        assert guard["verification_status"] == VerificationStatus.VERIFIED


def test_the_expiry_sweep_voids_the_shift_and_re_derives_post_plan_and_event():
    """A lapsed card the client never touched still walks all four hops of the graph.

    The exit shift becomes VOIDED with the system's own reason, the emergency
    exit post loses its cover, the plan falls to 0.80 coverage with 66000 cents
    and 30.00 hours committed, and the event's gate restricts.

    PRD: "A `CONFIRMED` row becomes `VOIDED` with the same reason and additionally runs the upward hops — post `filled_guard_count` and `status`, then plan coverage, understaffed count, readiness and ledger, then event `gate_posture` — with the compensating ledger sync subtracting `line_cost_cents` and `scheduled_hours` and recomputing `budget_remaining_cents`."
    Design: Difficulty/transitive_cascade/clock_sweep_credential_expiry_cascades_four_hops
    """
    api = ApiClient()
    world = _swept_world(api)

    voided = validate_success(api.get_post_assignment(world.a_e1, COORDINATOR_HEADERS))
    assert voided["assignment_status"] == AssignmentStatus.VOIDED
    assert voided["cancellation_reason"] == "CREDENTIAL_NOT_CURRENT"

    post = validate_success(api.get_post(world.e1_id, COORDINATOR_HEADERS))
    assert_post_fill(post, 0, PostStatus.UNDERSTAFFED)

    plan = validate_success(api.get_staffing_plan(world.plan_id, COORDINATOR_HEADERS))
    assert_coverage(plan, 5, 4, 0.80, ReadinessPosture.BLOCKED)
    assert_ledger(plan, 66000, 30.00, budget_remaining_cents=434000)

    event = validate_success(api.get_event(world.event_id, DIRECTOR_HEADERS))
    assert_gate(event, GatePosture.RESTRICTED)


def _frozen_world(api: ApiClient):
    world = build_doors_open_world(api)
    incident = validate_success(
        api.create_incident(
            world.event_id,
            incident_payload(
                world.zi_id,
                IncidentCategory.LAW_ENFORCEMENT,
                Severity.CRITICAL,
                description="weapon recovered at the express lane",
            ),
            COMMANDER_HEADERS,
        ),
        expected_status=201,
    )
    world.incident_id = incident["id"]
    validate_success(api.incident_action(world.incident_id, action("TRIAGE"), COMMANDER_HEADERS))
    world.handoff = validate_success(
        api.incident_action(
            world.incident_id,
            action("LE_HANDOFF", handoff_agency_ref="PD-1120"),
            COMMANDER_HEADERS,
        )
    )
    return world


def test_critical_handoff_zeroes_both_lane_throughputs_on_its_way_to_the_gate():
    """Two lanes running at 175 and 409 patrons an hour are stopped dead by one handoff.

    Each lane has its single operator on post, so the staffing factor is 1 and
    the 0.90 prohibited-item drag alone sets the rated figures. Holding the lanes
    forces both to zero, ingress to HOLD and the event's gate to FROZEN behind a
    single open critical incident.

    PRD: "Placing a lane on `HOLD` — by a coordinator or director, or as a system cascade — sets `status` to `HOLD` and forces `effective_throughput_pph` to 0."
    Design: Difficulty/transitive_cascade/critical_le_handoff_cascades_ingress_lanes_gate
    """
    api = ApiClient()
    world = build_doors_open_world(api)

    before1 = validate_success(api.get_screening_lane(world.lane1_id, COORDINATOR_HEADERS))
    before2 = validate_success(api.get_screening_lane(world.lane2_id, COORDINATOR_HEADERS))
    assert before1["effective_throughput_pph"] == 175
    assert before2["effective_throughput_pph"] == 409

    incident = validate_success(
        api.create_incident(
            world.event_id,
            incident_payload(
                world.zi_id,
                IncidentCategory.LAW_ENFORCEMENT,
                Severity.CRITICAL,
                description="weapon recovered at the express lane",
            ),
            COMMANDER_HEADERS,
        ),
        expected_status=201,
    )
    validate_success(api.incident_action(incident["id"], action("TRIAGE"), COMMANDER_HEADERS))
    validate_success(
        api.incident_action(
            incident["id"],
            action("LE_HANDOFF", handoff_agency_ref="PD-1120"),
            COMMANDER_HEADERS,
        )
    )

    after1 = validate_success(api.get_screening_lane(world.lane1_id, COORDINATOR_HEADERS))
    after2 = validate_success(api.get_screening_lane(world.lane2_id, COORDINATOR_HEADERS))
    assert after1["status"] == LaneStatus.HOLD
    assert after2["status"] == LaneStatus.HOLD
    assert after1["effective_throughput_pph"] == 0
    assert after2["effective_throughput_pph"] == 0

    event = validate_success(api.get_event(world.event_id, DIRECTOR_HEADERS))
    assert_gate(event, GatePosture.FROZEN, ingress_status=IngressStatus.HOLD)
    assert event["open_critical_incident_count"] == 1


def test_a_frozen_gate_then_refuses_the_roster_mutation_underneath_it():
    """With the gate frozen, cancelling a confirmed shift is refused outright.

    The interlock is the point of the cascade: the coordinator's cancellation is
    turned away, the row stays CONFIRMED and the plan's committed money stays at
    99000 cents.

    PRD: "It is the system's master interlock: while an event's `gate_posture` is `FROZEN`, the child mutations listed at rank 13 of §2.5 are refused with `ERR_EVENT_GATE_FROZEN`."
    Design: Difficulty/transitive_cascade/critical_le_handoff_cascades_ingress_lanes_gate
    """
    api = ApiClient()
    world = _frozen_world(api)

    response = api.post_assignment_duty_event(
        world.a_p1, cancel_action("roster churn"), COORDINATOR_HEADERS
    )
    validate_error(response, ApiErrorId.EVENT_GATE_FROZEN)

    row = validate_success(api.get_post_assignment(world.a_p1, COORDINATOR_HEADERS))
    assert row["assignment_status"] == AssignmentStatus.CONFIRMED

    plan = validate_success(api.get_staffing_plan(world.plan_id, COORDINATOR_HEADERS))
    assert plan["committed_cost_cents"] == 99000
