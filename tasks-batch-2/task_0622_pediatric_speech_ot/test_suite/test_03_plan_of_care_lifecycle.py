"""Plan-of-care lifecycle: activation preconditions, caseload accounting, and
the hold cascade.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    TEST_USERS, make_evaluator_headers, make_therapist_headers,
    set_clock, create_child, create_therapist, create_finalized_evaluation,
    create_active_plan, create_authorization, setup_active_care,
    book_appointment_ok, get_therapist, get_plan, get_authorization, get_appointment,
)
from test_helpers import create_evaluation_payload, create_plan_of_care_payload

ADMIN = TEST_USERS["clinic_admin_headers"]


# ─── cross_entity_state_dependency / plan_activation_requires_evaluation_finalized ─

def test_activate_plan_with_draft_evaluation_rejected(api):
    """PRD §3.3: "This requires the plan to be in `DRAFT` (otherwise
    `ERR_PLAN_NOT_DRAFT`); the source evaluation to be `FINALIZED` and not
    superseded (otherwise `ERR_EVALUATION_NOT_FINALIZED`)".

    Design: Difficulty/cross_entity_state_dependency/plan_activation_requires_evaluation_finalized
    """
    set_clock("2026-06-05T12:00:00Z")
    th = create_therapist(discipline="SLP")
    child = create_child()
    # Evaluation left in DRAFT (never finalized).
    ev = get_success_data(api.create_evaluation(
        create_evaluation_payload(child["id"], discipline="SLP", severity_score=40),
        make_evaluator_headers(th["id"])))
    poc = get_success_data(api.create_plan_of_care(
        create_plan_of_care_payload(child["id"], ev["id"], th["id"], planned_weekly_minutes=60),
        make_evaluator_headers(th["id"])))
    res = api.activate_plan_of_care(poc["id"], make_evaluator_headers(th["id"]))
    validate_error(res, "ERR_EVALUATION_NOT_FINALIZED")


def test_activate_plan_with_finalized_evaluation_succeeds(api):
    """PRD §3.3: "Activating a plan for the first time advances it from `DRAFT` to
    `ACTIVE`." PRD §3.3: "the source evaluation to be `FINALIZED` and not
    superseded (otherwise `ERR_EVALUATION_NOT_FINALIZED`)". Positive control: with
    a FINALIZED evaluation the activation is accepted.

    Design: Difficulty/cross_entity_state_dependency/plan_activation_requires_evaluation_finalized
    """
    set_clock("2026-06-05T12:00:00Z")
    th = create_therapist(discipline="SLP")
    child = create_child()
    ev = create_finalized_evaluation(child["id"], th["id"], discipline="SLP")
    poc = get_success_data(api.create_plan_of_care(
        create_plan_of_care_payload(child["id"], ev["id"], th["id"], planned_weekly_minutes=60),
        make_evaluator_headers(th["id"])))
    activated = validate_success(api.activate_plan_of_care(
        poc["id"], make_evaluator_headers(th["id"])), 200)
    assert activated["status"] == "ACTIVE", activated


# ─── compensating_invariant / caseload_conserved_activate_then_hold ──────────

def test_caseload_returns_to_zero_after_activate_then_hold(api):
    """PRD §3.3: "On success the therapist's `current_caseload` increases by 1".
    PRD §3.3: "Holding frees the slot — the primary therapist's `current_caseload`
    decreases by 1".

    Design: Difficulty/compensating_invariant/caseload_conserved_activate_then_hold
    """
    set_clock("2026-06-05T12:00:00Z")
    th = create_therapist(discipline="SLP", max_caseload=5)
    child = create_child()
    ev = create_finalized_evaluation(child["id"], th["id"], discipline="SLP")
    plan = create_active_plan(child["id"], ev["id"], th["id"])
    assert get_therapist(th["id"])["current_caseload"] == 1

    held = validate_success(api.hold_plan_of_care(
        plan["id"], make_therapist_headers(th["id"])), 200)
    assert held["status"] == "ON_HOLD"
    assert get_therapist(th["id"])["current_caseload"] == 0


def test_hold_after_activation_leaves_plan_on_hold_and_caseload_freed(api):
    """PRD §3.3: "A `Therapist` may place an `ACTIVE` plan `ON_HOLD`." PRD §3.3:
    "Holding frees the slot — the primary therapist's `current_caseload` decreases
    by 1". A second view of the same conservation: plan ends ON_HOLD and the
    therapist record reports caseload 0.

    Design: Difficulty/compensating_invariant/caseload_conserved_activate_then_hold
    """
    ctx = setup_active_care(clock="2026-06-05T12:00:00Z")
    th, plan = ctx["therapist"], ctx["plan"]
    assert get_therapist(th["id"])["current_caseload"] == 1
    validate_success(api.hold_plan_of_care(plan["id"], make_therapist_headers(th["id"])), 200)
    therapist_after = get_therapist(th["id"])
    assert therapist_after["current_caseload"] == 0, therapist_after
    assert get_plan(plan["id"])["status"] == "ON_HOLD"


# ─── Corner: caseload_exceeded_blocks_plan_activation ────────────────────────

def test_caseload_exceeded_blocks_activation(api):
    """PRD §3.3: "the therapist's `current_caseload` to be strictly less than
    `max_caseload` (otherwise `ERR_CASELOAD_EXCEEDED`)."

    Design: Corner/state_machines/caseload_exceeded_blocks_plan_activation
    """
    set_clock("2026-06-05T12:00:00Z")
    th = create_therapist(discipline="SLP", max_caseload=1)
    # Child A activates and fills the single caseload slot.
    child_a = create_child(full_name="Child A")
    ev_a = create_finalized_evaluation(child_a["id"], th["id"], discipline="SLP")
    create_active_plan(child_a["id"], ev_a["id"], th["id"])
    # Child B has a DRAFT plan naming the same therapist.
    child_b = create_child(full_name="Child B")
    ev_b = create_finalized_evaluation(child_b["id"], th["id"], discipline="SLP")
    poc_b = get_success_data(api.create_plan_of_care(
        create_plan_of_care_payload(child_b["id"], ev_b["id"], th["id"], planned_weekly_minutes=60),
        make_evaluator_headers(th["id"])))
    res = api.activate_plan_of_care(poc_b["id"], make_evaluator_headers(th["id"]))
    validate_error(res, "ERR_CASELOAD_EXCEEDED")


# ─── Corner: derived_caseload_increments_on_activation ───────────────────────

def test_derived_caseload_increments_on_activation(api):
    """PRD §3.1 / §2.7: "`current_caseload` is the count of distinct children
    whose `ACTIVE` plan of care names that therapist in `primary_therapist_id`".
    PRD §3.3: "On success the therapist's `current_caseload` increases by 1".

    Design: Corner/cross_cutting_complexity_layers/derived_caseload_increments_on_activation
    """
    set_clock("2026-06-05T12:00:00Z")
    th = create_therapist(discipline="SLP")
    child = create_child()
    ev = create_finalized_evaluation(child["id"], th["id"], discipline="SLP")
    poc = get_success_data(api.create_plan_of_care(
        create_plan_of_care_payload(child["id"], ev["id"], th["id"], planned_weekly_minutes=60),
        make_evaluator_headers(th["id"])))
    assert get_therapist(th["id"])["current_caseload"] == 0
    activated = validate_success(api.activate_plan_of_care(
        poc["id"], make_evaluator_headers(th["id"])), 200)
    assert activated["status"] == "ACTIVE"
    assert get_therapist(th["id"])["current_caseload"] == 1


# ─── Corner: cascade_hold_cancels_future_appointments ────────────────────────

def test_hold_cancels_scheduled_appointment_and_releases_visit(api):
    """PRD §3.3: "every one of this plan's future appointments still in
    `SCHEDULED` status is cancelled, and each such cancellation releases its held
    authorization visit (decreasing that authorization's `reserved_visits` by 1,
    raising `available_visits`". PRD §3.3: "Holding frees the slot — the primary
    therapist's `current_caseload` decreases by 1".

    Design: Corner/cross_cutting_complexity_layers/cascade_hold_cancels_future_appointments
    """
    ctx = setup_active_care(clock="2026-06-05T12:00:00Z", discipline="OT", authorized_visits=3)
    appt = book_appointment_ok(ctx, "2026-06-10T09:00:00Z", "2026-06-10T09:45:00Z")
    assert get_authorization(ctx["auth"]["id"])["reserved_visits"] == 1

    held = validate_success(api.hold_plan_of_care(
        ctx["plan"]["id"], make_therapist_headers(ctx["therapist"]["id"])), 200)
    assert held["status"] == "ON_HOLD"
    assert get_appointment(appt["id"])["status"] == "CANCELLED"
    auth_after = get_authorization(ctx["auth"]["id"])
    assert auth_after["reserved_visits"] == 0, auth_after
    assert auth_after["available_visits"] == 3, auth_after
    assert get_therapist(ctx["therapist"]["id"])["current_caseload"] == 0
