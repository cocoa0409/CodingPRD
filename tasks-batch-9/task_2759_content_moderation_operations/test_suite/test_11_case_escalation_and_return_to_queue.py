"""Escalation, the return-to-queue path and the cycle a case may travel twice."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_fields, assert_instant_equals
from test_helpers.factories import (
    assign_case_payload,
    decide_case_payload,
    escalate_case_payload,
    return_case_payload,
)
from test_helpers.fixtures import (
    build_assigned_case,
    build_escalated_case,
    build_pending_case,
    build_workforce_baseline,
)
from test_helpers.test_users import ADMIN_HEADERS, make_qa_auditor_headers, make_reviewer_headers

TEXT_WEIGHT_TWO = {"media_kind": "TEXT", "graphic_weight": 2}
TEXT_WEIGHT_THREE = {"media_kind": "TEXT", "graphic_weight": 3}


def test_escalate_applies_every_declared_side_effect(api, world):
    """Escalation refunds the holder, rewrites the deadline and leaves the queue alone.

    PRD 3.5: "Escalation records the supplied reason, raises `escalation_tier` to
    2, and releases the reviewer: `assigned_reviewer_id` becomes null, the prior
    holder's `open_case_count` falls by one and their `exposure_points_today` is
    reduced by exactly the case's `exposure_points_charged`, since the case is
    leaving undecided and both workload and exposure must be conserved."

    Design: Corner/state_machines/escalate_applies_every_declared_side_effect
    """
    base = build_workforce_baseline(world)
    scenario = build_assigned_case(
        base, reviewer_id=base.frontline_id, content_overrides=TEXT_WEIGHT_TWO
    )
    assert_instant_equals(scenario.case["sla_due_at"], "2026-08-01T11:00:00Z", "queue sla_due_at")
    world.set_clock("2026-08-01T09:20:00Z")

    escalated = validate_success(
        api.escalate_case(
            scenario.case_id,
            escalate_case_payload(escalation_reason="CALIBRATION"),
            headers=make_reviewer_headers(base.frontline_id),
        )
    )
    assert_fields(
        escalated,
        {
            "status": "ESCALATED",
            "escalation_reason": "CALIBRATION",
            "escalation_tier": 2,
            "assigned_reviewer_id": None,
            "exposure_points_charged": 2,
            "version": 3,
        },
        "escalated case",
    )
    assert_instant_equals(escalated["sla_due_at"], "2026-08-01T09:50:00Z", "escalation sla_due_at")

    reviewer = world.get_reviewer(base.frontline_id)
    assert reviewer["open_case_count"] == 0
    assert reviewer["exposure_points_today"] == 0
    queue = world.get_queue(base.queue_id)
    assert queue["open_case_count"] == 1
    assert queue["unassigned_case_count"] == 0
    content = world.get_content(scenario.content_id)
    assert content["review_status"] == "UNDER_REVIEW"
    assert content["open_case_count"] == 1


def test_return_to_queue_from_assigned_rejected_as_invalid_transition(api, world):
    """Return-to-queue is declared only from ESCALATED, so an assigned case is refused.

    PRD 3.5: "The case must be `ESCALATED`, or the request is
    `ERR_INVALID_CASE_TRANSITION`."

    Design: Corner/state_machines/return_to_queue_from_assigned_rejected_as_invalid_transition
    """
    base = build_workforce_baseline(world)
    scenario = build_assigned_case(
        base, reviewer_id=base.frontline_id, content_overrides=TEXT_WEIGHT_TWO
    )
    assert scenario.case["escalation_tier"] == 0

    validate_error(
        api.return_case_to_queue(
            scenario.case_id,
            return_case_payload(reason="wrong queue"),
            headers=make_qa_auditor_headers(base.auditor_id),
        ),
        ApiErrorId.INVALID_CASE_TRANSITION.value,
    )
    unchanged = world.get_case(scenario.case_id)
    assert_fields(
        unchanged,
        {
            "status": "ASSIGNED",
            "assigned_reviewer_id": base.frontline_id,
            "escalation_tier": 0,
            "version": 2,
        },
        "case after refusal",
    )
    queue = world.get_queue(base.queue_id)
    assert queue["open_case_count"] == 1
    assert queue["unassigned_case_count"] == 0
    reviewer = world.get_reviewer(base.frontline_id)
    assert reviewer["open_case_count"] == 1
    assert reviewer["exposure_points_today"] == 2


def _reviewer_with_two_held_cases(world):
    """One reviewer holding a weight-2 and a weight-3 case, ready to fork."""
    base = build_workforce_baseline(world)
    light = build_assigned_case(
        base, reviewer_id=base.frontline_id, content_overrides=TEXT_WEIGHT_TWO
    )
    heavy = build_assigned_case(
        base, reviewer_id=base.frontline_id, content_overrides=TEXT_WEIGHT_THREE
    )
    loaded = world.get_reviewer(base.frontline_id)
    assert loaded["open_case_count"] == 2
    assert loaded["exposure_points_today"] == 5
    return base, light, heavy


def test_escalate_branch_refunds_exposure_and_rewrites_the_deadline(api, world):
    """The escalate fork releases the holder and never writes the strike ledger.

    PRD 3.5: "The deadline is tightened to the current instant plus 30 minutes,
    and the congestion multiplier is **not** applied on this branch."

    Design: Difficulty/non_linear_state_machine/case_branch_escalate_vs_decide_divergent_side_effects
    """
    base, light, heavy = _reviewer_with_two_held_cases(world)

    escalated = validate_success(
        api.escalate_case(
            light.case_id,
            escalate_case_payload(escalation_reason="IMMINENT_HARM"),
            headers=make_reviewer_headers(base.frontline_id),
        )
    )
    assert_fields(
        escalated,
        {
            "status": "ESCALATED",
            "escalation_tier": 2,
            "escalation_reason": "IMMINENT_HARM",
            "assigned_reviewer_id": None,
            "decided_at": None,
        },
        "escalated case",
    )
    assert_instant_equals(escalated["sla_due_at"], "2026-08-01T09:30:00Z", "escalation sla_due_at")

    reviewer = world.get_reviewer(base.frontline_id)
    assert reviewer["open_case_count"] == 1
    assert reviewer["exposure_points_today"] == 3
    assert world.get_content(light.content_id)["visibility_status"] == "LIVE"
    assert world.get_case(heavy.case_id)["status"] == "ASSIGNED"


def test_decide_branch_keeps_the_exposure_charge_and_writes_the_ledger(api, world):
    """The decide fork keeps the wellness charge and drops the queue's open count.

    PRD 3.5: "The deciding reviewer's `open_case_count` falls by one, but their
    `exposure_points_today` is deliberately **not** reduced: they saw the
    material, so the wellness charge stands. The queue's `open_case_count` falls
    by one."

    Design: Difficulty/non_linear_state_machine/case_branch_escalate_vs_decide_divergent_side_effects
    """
    base, light, heavy = _reviewer_with_two_held_cases(world)
    world.escalate(light.case_id, base.frontline_id, escalation_reason="IMMINENT_HARM")

    decided = validate_success(
        api.decide_case(
            heavy.case_id,
            decide_case_payload(outcome="REMOVE"),
            headers=make_reviewer_headers(base.frontline_id),
        )
    )
    assert_fields(
        decided,
        {
            "status": "DECIDED",
            "decision_source": "HUMAN",
            "decided_by_reviewer_id": base.frontline_id,
            "strike_points_applied": 4,
            "exposure_points_charged": 3,
        },
        "decided case",
    )

    reviewer = world.get_reviewer(base.frontline_id)
    assert reviewer["open_case_count"] == 0
    assert reviewer["exposure_points_today"] == 3
    assert world.get_content(heavy.content_id)["visibility_status"] == "REMOVED"
    assert world.get_content(light.content_id)["visibility_status"] == "LIVE"
    queue = world.get_queue(base.queue_id)
    assert queue["open_case_count"] == 1
    assert queue["unassigned_case_count"] == 0


def test_return_to_queue_recomputes_the_deadline_and_keeps_the_reason(api, world):
    """The return de-escalates to tier 1 and recomputes the congestion deadline.

    PRD 3.5: "On return, `escalation_tier` drops to 1 — de-escalated but still
    flagged — while `escalation_reason` is retained as history rather than
    cleared."

    Design: Difficulty/non_linear_state_machine/case_cycle_escalated_back_to_assigned_and_queue
    """
    base = build_workforce_baseline(world)
    scenario = build_escalated_case(
        base,
        reviewer_id=base.frontline_id,
        escalation_reason="IMMINENT_HARM",
        content_overrides=TEXT_WEIGHT_TWO,
    )
    assert_instant_equals(scenario.case["sla_due_at"], "2026-08-01T09:30:00Z", "escalated deadline")

    returned = validate_success(
        api.return_case_to_queue(
            scenario.case_id,
            return_case_payload(reason="No imminent harm after triage"),
            headers=ADMIN_HEADERS,
        )
    )
    assert_fields(
        returned,
        {
            "status": "PENDING_ASSIGNMENT",
            "assigned_reviewer_id": None,
            "escalation_tier": 1,
            "escalation_reason": "IMMINENT_HARM",
            "reassignment_count": 0,
        },
        "returned case",
    )
    assert_instant_equals(returned["sla_due_at"], "2026-08-01T11:00:00Z", "recomputed sla_due_at")

    queue = world.get_queue(base.queue_id)
    assert queue["open_case_count"] == 1
    assert queue["unassigned_case_count"] == 1
    reviewer = world.get_reviewer(base.frontline_id)
    assert reviewer["open_case_count"] == 0
    assert reviewer["exposure_points_today"] == 0


def test_case_cycles_back_into_assignment_without_counting_a_reassignment(api, world):
    """A pick-up out of PENDING_ASSIGNMENT recharges the holder and counts no reassignment.

    PRD 3.4: "On a first assignment out of `PENDING_ASSIGNMENT` the queue's
    `unassigned_case_count` falls by one while `open_case_count` stays where it
    is."

    Design: Difficulty/non_linear_state_machine/case_cycle_escalated_back_to_assigned_and_queue
    """
    base = build_workforce_baseline(world)
    scenario = build_escalated_case(
        base,
        reviewer_id=base.frontline_id,
        escalation_reason="IMMINENT_HARM",
        content_overrides=TEXT_WEIGHT_TWO,
    )
    world.return_case(scenario.case_id, reason="No imminent harm after triage")
    returned = world.get_case(scenario.case_id)
    assert returned["status"] == "PENDING_ASSIGNMENT"

    reassigned = validate_success(
        api.assign_case(
            scenario.case_id,
            assign_case_payload(returned["version"], target_reviewer_id=base.frontline_id),
            headers=ADMIN_HEADERS,
        )
    )
    assert_fields(
        reassigned,
        {
            "status": "ASSIGNED",
            "assigned_reviewer_id": base.frontline_id,
            "escalation_tier": 1,
            "escalation_reason": "IMMINENT_HARM",
            "reassignment_count": 0,
        },
        "case back in hand",
    )
    assert_instant_equals(reassigned["sla_due_at"], "2026-08-01T11:00:00Z", "sla_due_at on pick-up")

    queue = world.get_queue(base.queue_id)
    assert queue["open_case_count"] == 1
    assert queue["unassigned_case_count"] == 0
    reviewer = world.get_reviewer(base.frontline_id)
    assert reviewer["open_case_count"] == 1
    assert reviewer["exposure_points_today"] == 2


def test_pending_case_cannot_be_returned_to_its_queue(api, world):
    """Only the escalated state offers the return path, so a queued case is refused.

    PRD 3.5: "**Returning a case to its queue** moves it `ESCALATED →
    PENDING_ASSIGNMENT` and is available to a `QAAuditor` or a
    `TrustSafetyAdmin`, who may record a `reason`."

    Design: Corner/state_machines/return_to_queue_from_assigned_rejected_as_invalid_transition
    """
    base = build_workforce_baseline(world)
    scenario = build_pending_case(base, content_overrides=TEXT_WEIGHT_TWO)

    validate_error(
        api.return_case_to_queue(
            scenario.case_id, return_case_payload(reason="never escalated"), headers=ADMIN_HEADERS
        ),
        ApiErrorId.INVALID_CASE_TRANSITION.value,
    )
    unchanged = world.get_case(scenario.case_id)
    assert unchanged["status"] == "PENDING_ASSIGNMENT"
    assert unchanged["escalation_tier"] == 0
    assert unchanged["version"] == 1
    queue = world.get_queue(base.queue_id)
    assert queue["open_case_count"] == 1
    assert queue["unassigned_case_count"] == 1
