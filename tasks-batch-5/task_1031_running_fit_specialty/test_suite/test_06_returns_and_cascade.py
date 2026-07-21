"""Wear/return non-linear lifecycle, the return-approval cascade, and the
fulfilled-order precondition.

Queue A (Difficulty): non_linear_state_machine (return cycle),
transitive_cascade (return approval), cross_entity_state_dependency (return
requires fulfilled).
Queue B (Corner): state_machines (approve-not-inspected).
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    fixtures as fx,
)


# ---------------------------------------------------------------------------
# Difficulty: non_linear_state_machine / wear_return_reject_resubmit_cycle
# ---------------------------------------------------------------------------
def test_return_resubmit_reverts_to_requested(api, sm):
    """PRD 3.5: "A rejected return is not the end of the road: the member may
    resubmit it, reverting `REJECTED` back to `REQUESTED` for a fresh inspection"

    Design: Difficulty/non_linear_state_machine/wear_return_reject_resubmit_cycle
    """
    _m, _p, _o, _line, ret = fx.setup_return_under_inspection()
    rid = ret["id"]
    get_success_data(api.reject_return(rid, {"reason": "insufficient evidence"}, sm))
    resubmitted = validate_success(api.resubmit_return(rid, sm), 200)
    assert resubmitted["status"] == "REQUESTED"


def test_return_reject_resubmit_cycle_ends_approved(api, sm):
    """PRD 3.5: "From `UNDER_INSPECTION` the manager either approves the return
    (to the terminal `APPROVED`) or rejects it (to `REJECTED`), recording
    `inspection_notes`; a rejection has no order, inventory, or loyalty effect of
    its own."

    Design: Difficulty/non_linear_state_machine/wear_return_reject_resubmit_cycle
    """
    _m, _p, _o, _line, ret = fx.setup_return_under_inspection()
    rid = ret["id"]
    get_success_data(api.reject_return(rid, {"reason": "insufficient evidence"}, sm))
    get_success_data(api.resubmit_return(rid, sm))
    get_success_data(api.start_inspection(rid, sm))
    approved = validate_success(api.approve_return(rid, sm), 200)
    assert approved["status"] == "APPROVED"


# ---------------------------------------------------------------------------
# Difficulty: transitive_cascade / return_approval_cascade_order_member_tier
# ---------------------------------------------------------------------------
def test_return_approval_cascades_order_returned_refunded(api, sm):
    """PRD 3.5: "the order linked through that line (reached via the line's
    `order_id`) has its `fulfillment_status` moved to the terminal `RETURNED`
    and its `payment_status` moved to `REFUNDED`"

    Design: Difficulty/transitive_cascade/return_approval_cascade_order_member_tier
    """
    _m, _p, order, _line, ret = fx.setup_return_under_inspection(price_cents=10000)
    get_success_data(api.approve_return(ret["id"], sm))
    order_after = fx.get_order(order["id"])
    assert order_after["fulfillment_status"] == "RETURNED"
    assert order_after["payment_status"] == "REFUNDED"


def test_return_approval_cascades_member_loyalty_and_tier(api, sm):
    """PRD 3.5: "Third, the member's `loyalty_points_balance` is reduced by that
    returned line's `line_points_earned`, reversing the points that line
    originally earned. Fourth, the member's `tier_qualifying_spend_cents` is
    reduced by the same returned-line net, and the member's `loyalty_tier` is
    recomputed against the new total."

    Design: Difficulty/transitive_cascade/return_approval_cascade_order_member_tier
    """
    member, _p, _order, _line, ret = fx.setup_return_under_inspection(price_cents=10000)
    get_success_data(api.approve_return(ret["id"], sm))
    member_after = fx.get_member(member["id"])
    # Fulfillment settled 1000 pts / 10000 tier-spend; approval reverses both.
    assert member_after["loyalty_points_balance"] == 0
    assert member_after["tier_qualifying_spend_cents"] == 0


# ---------------------------------------------------------------------------
# Difficulty: cross_entity_state_dependency / return_requires_fulfilled_order
# ---------------------------------------------------------------------------
def test_return_requires_fulfilled_order_reserved(api, sm):
    """PRD 3.5: "A return may only be opened when the line's order is
    `FULFILLED`; otherwise it is rejected with `ERR_ORDER_NOT_FULFILLED`."

    Design: Difficulty/cross_entity_state_dependency/return_requires_fulfilled_order
    """
    member = fx.create_member()
    product = fx.create_product(category="SHOE", unit_price_cents=10000, initial_stock=3)
    order = fx.create_reserved_order(member["id"], product["id"], 1, pay=True)
    line = fx.get_first_order_line(order["id"])
    resp = api.create_return(
        {"order_line_id": line["id"], "reason": "changed mind"}, sm
    )
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_FULFILLED.value, 409)


def test_return_requires_fulfilled_order_pending(api, sm):
    """PRD 3.5: "A return may only be opened when the line's order is
    `FULFILLED`; otherwise it is rejected with `ERR_ORDER_NOT_FULFILLED`."

    Design: Difficulty/cross_entity_state_dependency/return_requires_fulfilled_order
    """
    member = fx.create_member()
    product = fx.create_product(category="SHOE", unit_price_cents=10000, initial_stock=3)
    order = fx.create_single_line_order(member["id"], product["id"], 1)
    line = fx.get_first_order_line(order["id"])
    resp = api.create_return(
        {"order_line_id": line["id"], "reason": "changed mind"}, sm
    )
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_FULFILLED.value, 409)


# ---------------------------------------------------------------------------
# Corner: state_machines / c_return_approve_invalid_from_returns_not_inspectable
# ---------------------------------------------------------------------------
def test_approve_return_not_inspected_rejected(api, sm):
    """PRD 3.5: "Attempting to start inspection, approve, or reject a return that
    is not in the state that transition requires yields
    `ERR_RETURN_NOT_INSPECTABLE`"

    Design: Corner/state_machines/c_return_approve_invalid_from_returns_not_inspectable
    """
    _m, _p, order, _shoe = fx.setup_fulfilled_shoe(price_cents=10000)
    line = fx.get_first_order_line(order["id"])
    ret = fx.open_return(line["id"], reason="just checking")  # REQUESTED, not inspected
    resp = api.approve_return(ret["id"], sm)
    validate_error(resp, ApiErrorId.ERR_RETURN_NOT_INSPECTABLE.value, 409)
