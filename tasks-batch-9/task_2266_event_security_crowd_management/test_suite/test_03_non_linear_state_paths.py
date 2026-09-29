"""State machines that loop, that move one dimension without the other, and that fork.

An assessment can travel DRAFT to SUBMITTED to REJECTED and back to DRAFT any
number of times, and the loop must reset the right fields without losing the
version trail. A roster row carries two independent dimensions, so a no-show
moves duty without releasing the contract. And a triaged incident forks into
handoff branches whose side effects differ materially from one another.
"""

from test_helpers import (
    ANALYST_HEADERS,
    COMMANDER_HEADERS,
    DIRECTOR_HEADERS,
    ApiClient,
    AssessmentStatus,
    AssignmentStatus,
    DutyStatus,
    EventStatus,
    GatePosture,
    IncidentCategory,
    IncidentStatus,
    IngressStatus,
    LaneStatus,
    PostStatus,
    ReadinessPosture,
    RiskTier,
    Severity,
    action,
    assert_assignment_state,
    assert_coverage,
    assert_decimal,
    assert_gate,
    assert_ledger,
    assert_post_fill,
    build_canonical_five_post_activated_world,
    build_doors_open_world,
    build_submitted_assessment_world,
    incident_payload,
    make_post_supervisor_headers,
    set_clock,
    validate_success,
)

NO_SHOW_CLOCK = "2026-09-12T15:20:00Z"
TRIAGE_CLOCK = "2026-09-12T16:42:00Z"


def _rejected_assessment(api: ApiClient):
    world = build_submitted_assessment_world(api)
    world.rejected = validate_success(
        api.risk_assessment_decision(
            world.ra_id,
            action("REJECT", rejection_reason="layout complexity understated for the pit rail"),
            DIRECTOR_HEADERS,
        )
    )
    return world


def test_revising_a_rejected_assessment_reopens_it_as_a_fresh_revision():
    """The revise hop clears the submitter and the rejection reason and counts a revision.

    Rejection stores the director's reason on the row; the analyst's revise then
    walks it back to DRAFT as revision 2 with both of those fields cleared, which
    is what makes the loop repeatable rather than a dead end.

    PRD: "A rejected assessment can be revised back to `DRAFT` by the analyst, which increases `revision_number` by one, clears `submitted_by_user_id` back to null, clears `rejection_reason` back to null, and increments `version`."
    Design: Difficulty/non_linear_state_machine/risk_assessment_reject_revise_resubmit_cycle
    """
    api = ApiClient()
    world = _rejected_assessment(api)

    assert world.rejected["status"] == AssessmentStatus.REJECTED
    assert world.rejected["rejection_reason"] == (
        "layout complexity understated for the pit rail"
    )

    revised = validate_success(
        api.risk_assessment_decision(world.ra_id, action("REVISE"), ANALYST_HEADERS)
    )
    assert revised["status"] == AssessmentStatus.DRAFT
    assert revised["revision_number"] == 2
    assert revised["submitted_by_user_id"] is None
    assert revised["rejection_reason"] is None


def test_resubmission_after_the_reject_loop_still_approves_and_cascades_the_event():
    """Six mutations later the assessment approves with its full derived block intact.

    Create, submit, reject, revise, submit and approve are six versions on the
    one row. The second submission re-stamps the analyst as submitter, approval
    stamps the director, and the event finally leaves PLANNING.

    PRD: "That revision loop — `DRAFT → SUBMITTED → REJECTED → DRAFT` — may repeat any number of times."
    Design: Difficulty/non_linear_state_machine/risk_assessment_reject_revise_resubmit_cycle
    """
    api = ApiClient()
    world = _rejected_assessment(api)
    validate_success(api.risk_assessment_decision(world.ra_id, action("REVISE"), ANALYST_HEADERS))

    resubmitted = validate_success(
        api.risk_assessment_decision(world.ra_id, action("SUBMIT"), ANALYST_HEADERS)
    )
    assert resubmitted["status"] == AssessmentStatus.SUBMITTED
    assert resubmitted["submitted_by_user_id"] == "analyst-1"
    assert resubmitted["version"] == 5

    approved = validate_success(
        api.risk_assessment_decision(world.ra_id, action("APPROVE"), DIRECTOR_HEADERS)
    )
    assert approved["status"] == AssessmentStatus.APPROVED
    assert approved["approved_by_user_id"] == "director-1"
    assert_decimal(approved["composite_threat_score"], 3.75, "composite_threat_score")
    assert approved["risk_tier"] == RiskTier.T1
    assert approved["required_total_staff"] == 5
    assert approved["version"] == 6

    event = validate_success(api.get_event(world.event_id, DIRECTOR_HEADERS))
    assert event["status"] == EventStatus.RISK_ASSESSED


def _no_show_world(api: ApiClient):
    world = build_canonical_five_post_activated_world(api)
    set_clock(api, NO_SHOW_CLOCK)
    world.no_show = validate_success(
        api.post_assignment_duty_event(
            world.a_p1, action("MARK_NO_SHOW"), make_post_supervisor_headers(world.gs_id)
        )
    )
    return world


def test_marking_a_no_show_moves_only_the_duty_dimension_of_the_row():
    """The guard fails to appear, yet the shift stays contractually confirmed.

    duty_status goes to NO_SHOW while assignment_status is deliberately left at
    CONFIRMED. Because a NO_SHOW row no longer counts toward fill, the perimeter
    post drops to zero filled slots and, on a live plan, to UNDERSTAFFED.

    PRD: "It sets `duty_status` to `NO_SHOW` while deliberately leaving `assignment_status` at `CONFIRMED` — the dimensions are independent, and the shift remains contractually committed."
    Design: Difficulty/non_linear_state_machine/assignment_no_show_moves_duty_dimension_only
    """
    api = ApiClient()
    world = _no_show_world(api)

    assert_assignment_state(world.no_show, AssignmentStatus.CONFIRMED, DutyStatus.NO_SHOW)

    post = validate_success(api.get_post(world.p1_id, DIRECTOR_HEADERS))
    assert_post_fill(post, 0, PostStatus.UNDERSTAFFED)


def test_a_no_show_costs_coverage_but_not_a_cent_of_the_committed_ledger():
    """Coverage falls to 0.80 and the gate restricts, while the firm still owes the shift.

    Four of five slots still count, so the plan is BLOCKED with one understaffed
    post and the event's gate drops to RESTRICTED. The committed columns are
    untouched at 82500 cents and 37.50 hours.

    PRD: "The plan's `committed_cost_cents` and `committed_guard_hours` are pointedly **not** reduced: the firm still owes for the shift it booked."
    Design: Difficulty/non_linear_state_machine/assignment_no_show_moves_duty_dimension_only
    """
    api = ApiClient()
    world = _no_show_world(api)

    plan = validate_success(api.get_staffing_plan(world.plan_id, DIRECTOR_HEADERS))
    assert_coverage(plan, 5, 4, 0.80, ReadinessPosture.BLOCKED)
    assert plan["understaffed_post_count"] == 1
    assert_ledger(plan, 82500, 37.50, budget_remaining_cents=417500)

    event = validate_success(api.get_event(world.event_id, DIRECTOR_HEADERS))
    assert_gate(event, GatePosture.RESTRICTED)
    assert event["status"] == EventStatus.STAFFED


def test_medical_handoff_branch_leaves_ingress_lanes_and_gate_alone():
    """A late-triaged medical case breaches its SLA and still touches nothing else.

    Reported at 16:30 and triaged at 16:42, the response is 12.00 minutes against
    a 10-minute MODERATE budget, so the breach flag is raised. The handoff then
    stores the receiving agency and stops there: ingress stays NORMAL, both lanes
    stay OPEN and the gate stays OPEN.

    PRD: "This branch changes nothing else: `ingress_status`, lane statuses and `gate_posture` are all left alone."
    Design: Difficulty/non_linear_state_machine/incident_medical_branch_vs_le_branch_divergent_side_effects
    """
    api = ApiClient()
    world = build_doors_open_world(api)

    incident = validate_success(
        api.create_incident(
            world.event_id,
            incident_payload(
                world.zf_id,
                IncidentCategory.MEDICAL,
                Severity.MODERATE,
                description="patron collapse near the pit rail",
            ),
            COMMANDER_HEADERS,
        ),
        expected_status=201,
    )
    set_clock(api, TRIAGE_CLOCK)
    triaged = validate_success(
        api.incident_action(incident["id"], action("TRIAGE"), COMMANDER_HEADERS)
    )
    assert triaged["severity_at_report"] == Severity.MODERATE
    assert_decimal(triaged["response_minutes"], 12.00, "response_minutes")
    assert triaged["sla_breached"] is True

    handed_off = validate_success(
        api.incident_action(
            incident["id"],
            action("MEDICAL_HANDOFF", handoff_agency_ref="EMS-77"),
            COMMANDER_HEADERS,
        )
    )
    assert handed_off["status"] == IncidentStatus.MEDICAL_HANDOFF
    assert handed_off["handoff_agency_ref"] == "EMS-77"

    event = validate_success(api.get_event(world.event_id, DIRECTOR_HEADERS))
    assert_gate(event, GatePosture.OPEN, ingress_status=IngressStatus.NORMAL)
    for lane_id in (world.lane1_id, world.lane2_id):
        lane = validate_success(api.get_screening_lane(lane_id, DIRECTOR_HEADERS))
        assert lane["status"] == LaneStatus.OPEN


def test_critical_law_enforcement_handoff_branch_holds_ingress_lanes_and_gate():
    """The same protocol, one branch over, stops the doors and every open lane.

    A CRITICAL law-enforcement incident triaged on the spot has a 0.00 minute
    response and no breach. Its handoff is the only branch that reaches ingress:
    ingress goes to HOLD, every OPEN lane follows it to HOLD with throughput
    forced to zero, and clause 2 of the posture ladder freezes the gate.

    PRD: "This is the only branch that reaches ingress, and only at the top of the severity scale: when `severity` is `CRITICAL`, hop one sets the event's `ingress_status` to `HOLD`; hop two, because ingress went to `HOLD`, transitions every lane on the event whose `status` is `OPEN` to `HOLD`, sweeping lanes in ascending `created_at` order; hop three re-derives the event's `gate_posture`, which clause 2 of the posture ladder resolves to `FROZEN`."
    Design: Difficulty/non_linear_state_machine/incident_medical_branch_vs_le_branch_divergent_side_effects
    """
    api = ApiClient()
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
    triaged = validate_success(
        api.incident_action(incident["id"], action("TRIAGE"), COMMANDER_HEADERS)
    )
    assert_decimal(triaged["response_minutes"], 0.00, "response_minutes")
    assert triaged["sla_breached"] is False

    handed_off = validate_success(
        api.incident_action(
            incident["id"],
            action("LE_HANDOFF", handoff_agency_ref="PD-1120"),
            COMMANDER_HEADERS,
        )
    )
    assert handed_off["status"] == IncidentStatus.LE_HANDOFF

    event = validate_success(api.get_event(world.event_id, DIRECTOR_HEADERS))
    assert_gate(event, GatePosture.FROZEN, ingress_status=IngressStatus.HOLD)
    lane1 = validate_success(api.get_screening_lane(world.lane1_id, DIRECTOR_HEADERS))
    lane2 = validate_success(api.get_screening_lane(world.lane2_id, DIRECTOR_HEADERS))
    assert lane1["status"] == LaneStatus.HOLD
    assert lane2["status"] == LaneStatus.HOLD
    assert lane1["effective_throughput_pph"] == 0
