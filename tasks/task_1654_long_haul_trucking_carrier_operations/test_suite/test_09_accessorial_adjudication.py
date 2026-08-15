"""Accessorial capture and adjudication: the PENDING/SUBMITTED/DISPUTED cycle,
terminal REJECTED lockdown, per-action state guards, and the one-open-claim-
per-leg rule (PRD §3.6)."""
from test_helpers import (
    ApiErrorId,
    api_client,
    create_manual_accessorial,
    make_dispatcher_headers,
    make_load_planner_headers,
    setup_delivered_trip,
    setup_refdata,
    tender_load,
    validate_error,
    validate_success,
)

DISPATCHER = make_dispatcher_headers()
LOAD_PLANNER = make_load_planner_headers()


def _load_with_lumper(quantity=3013):
    ctx = setup_refdata()
    load = tender_load(ctx["customer"]["id"], ctx["lane"]["id"])
    charge = create_manual_accessorial(load["id"], type="LUMPER",
                                       quantity=quantity)
    return charge


# ---------------------------------------------------------------------------
# Queue A: non_linear_state_machine / accessorial_dispute_resubmit_cycle
# ---------------------------------------------------------------------------

def test_dispute_resubmit_cycle_states(api):
    """PRD §3.6: "Submission by a `Dispatcher` or an eligible `Driver` moves it
    from `PENDING` to `SUBMITTED`, and a disputed charge re-enters the same way
    — submission is admissible only from `PENDING` or `DISPUTED`, and from
    anywhere else is rejected with `ERR_ACCESSORIAL_NOT_SUBMITTABLE`."
    PRD §3.6: "The `DISPUTED` to `SUBMITTED` resubmission is the cycle's only
    loop."

    Design: Difficulty/non_linear_state_machine/accessorial_dispute_resubmit_cycle
    """
    charge = _load_with_lumper()
    assert charge["status"] == "PENDING"
    cid = charge["id"]
    submitted = validate_success(api_client.submit_accessorial(cid, DISPATCHER))
    assert submitted["status"] == "SUBMITTED"
    disputed = validate_success(api_client.dispute_accessorial(cid, LOAD_PLANNER))
    assert disputed["status"] == "DISPUTED"
    resubmitted = validate_success(api_client.submit_accessorial(cid, DISPATCHER))
    assert resubmitted["status"] == "SUBMITTED"
    approved = validate_success(api_client.approve_accessorial(cid, LOAD_PLANNER))
    assert approved["status"] == "APPROVED"


def test_lumper_amount_stable_across_dispute_cycle(api):
    """PRD §3.6: "`LUMPER` passes its `quantity` straight through as the
    amount. A manual charge is created in `PENDING` status with `source`
    `MANUAL`."
    (The adjudication cycle never recomputes the passthrough amount.)

    Design: Difficulty/non_linear_state_machine/accessorial_dispute_resubmit_cycle
    """
    charge = _load_with_lumper(3013)
    assert charge["amount_cents"] == 3013
    cid = charge["id"]
    validate_success(api_client.submit_accessorial(cid, DISPATCHER))
    validate_success(api_client.dispute_accessorial(cid, LOAD_PLANNER))
    validate_success(api_client.submit_accessorial(cid, DISPATCHER))
    approved = validate_success(api_client.approve_accessorial(cid, LOAD_PLANNER))
    assert approved["amount_cents"] == 3013


def test_submit_rejected_charge_blocked(api):
    """PRD §3.6: "submission is admissible only from `PENDING` or `DISPUTED`,
    and from anywhere else is rejected with
    `ERR_ACCESSORIAL_NOT_SUBMITTABLE`."
    PRD §3.6: "rejection is possible from `SUBMITTED` or `DISPUTED` (otherwise
    `ERR_ACCESSORIAL_NOT_REJECTABLE`) and lands in the terminal `REJECTED`
    state."

    Design: Corner/state_machines/accessorial_rejected_terminal_lockdown
    """
    charge = _load_with_lumper()
    cid = charge["id"]
    validate_success(api_client.submit_accessorial(cid, DISPATCHER))
    rejected = validate_success(api_client.reject_accessorial(cid, LOAD_PLANNER))
    assert rejected["status"] == "REJECTED"
    resp = api_client.submit_accessorial(cid, DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_ACCESSORIAL_NOT_SUBMITTABLE)


def test_adjudication_actions_require_submitted_state(api):
    """PRD §3.6: "A `LoadPlanner` then decides: approval moves `SUBMITTED` to
    `APPROVED` (from any other state, `ERR_ACCESSORIAL_NOT_APPROVABLE`);
    disputing moves `SUBMITTED` to `DISPUTED` (from any other state,
    `ERR_ACCESSORIAL_NOT_DISPUTABLE`); and rejection is possible from
    `SUBMITTED` or `DISPUTED` (otherwise `ERR_ACCESSORIAL_NOT_REJECTABLE`)".

    Design: Corner/errors/accessorial_action_state_errors
    """
    charge = _load_with_lumper()
    cid = charge["id"]
    assert charge["status"] == "PENDING"
    validate_error(api_client.approve_accessorial(cid, LOAD_PLANNER),
                   ApiErrorId.ERR_ACCESSORIAL_NOT_APPROVABLE)
    validate_error(api_client.dispute_accessorial(cid, LOAD_PLANNER),
                   ApiErrorId.ERR_ACCESSORIAL_NOT_DISPUTABLE)
    validate_error(api_client.reject_accessorial(cid, LOAD_PLANNER),
                   ApiErrorId.ERR_ACCESSORIAL_NOT_REJECTABLE)


def test_duplicate_detention_leg_type_rejected(api):
    """PRD §3.6: "One hard rule protects against double-billing a dock: a load
    may carry at most one non-`REJECTED` `DETENTION_PICKUP` charge, and
    likewise at most one non-`REJECTED` `DETENTION_DELIVERY` charge; a second
    open claim of the same leg type is rejected with
    `ERR_DUPLICATE_ACCESSORIAL_TYPE`."
    PRD §3.6: "manual detention prices by the same increment rule as automatic
    detention, the `quantity` minutes divided into 15-minute increments rounded
    up at 1500 cents per increment".

    Design: Corner/validations/duplicate_detention_type_rejected
    """
    ctx = setup_delivered_trip(cdl_number="CDL-V11", unit_number="T-V11")
    # chain auto-created a PENDING DETENTION_DELIVERY (60 min -> 6000)
    resp = api_client.create_load_accessorial(
        ctx["load"]["id"],
        {"type": "DETENTION_DELIVERY", "quantity": 200,
         "trip_id": ctx["trip"]["id"]},
        DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_ACCESSORIAL_TYPE)

    pickup = create_manual_accessorial(
        ctx["load"]["id"], type="DETENTION_PICKUP", quantity=150,
        trip_id=ctx["trip"]["id"])
    assert pickup["amount_cents"] == 15000, "ceil(150/15) * 1500"
    assert pickup["status"] == "PENDING"
