"""Returns: dual estimate/final refund, the deep approval cascade, loyalty
conservation, the hygiene-over-referential ordering, and return preconditions."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    make_customer, make_product, make_variant, make_order, add_line,
    place_order, fulfill_order, request_return, approve_return,
    setup_fulfilled_order, setup_placed_order, setup_return_requested,
    TEST_USERS,
)
from test_helpers.test_users import make_customer_headers

FULFILL = TEST_USERS["fulfillment_headers"]


def _lines_by_id(api, order_id, cust_id):
    data, _ = validate_paginated(api.list_order_lines(order_id, make_customer_headers(cust_id)))
    return {ln["id"]: ln for ln in data}


def _ledger_sum(api, cust_id):
    data, _ = validate_paginated(api.list_customer_loyalty_transactions(cust_id, make_customer_headers(cust_id)))
    return sum(tx["points_delta"] for tx in data)


# ─── Difficulty/dual_variant_calc/refund_estimate_vs_final_on_order_return ───
def test_return_estimate_is_flat_restock_deduction(api):
    """PRD §3.5: "The estimate is condition-agnostic: it is that base minus a flat
    restock fee of five dollars (500 cents)."

    Design: Difficulty/dual_variant_calc/refund_estimate_vs_final_on_order_return
    """
    ctx = setup_fulfilled_order(12000, hygiene_returnable=True)
    ret = request_return(ctx["order_id"], ctx["cust_id"], [ctx["line_id"]], "SEALED")
    assert ret["refund_estimate_cents"] == 11500  # 12000 - 500


def test_return_final_sealed_is_full_base(api):
    """PRD §3.5: "The `final_refund_cents` is condition-driven over the same
    returned-merchandise base: for a `SEALED` return the final refund is the full
    base."

    Design: Difficulty/dual_variant_calc/refund_estimate_vs_final_on_order_return
    """
    ctx = setup_return_requested(12000, condition="SEALED", hygiene_returnable=True)
    ret = validate_success(api.approve_return(ctx["return_id"], FULFILL), 200)
    assert ret["final_refund_cents"] == 12000


# ─── Difficulty/transitive_cascade/return_approve_depth3_line_order_customer ───
def test_approve_return_cascades_line_and_order_status(api):
    """PRD §3.5: "Each returned line's `status` becomes `RETURNED`."
    PRD §3.5: "if all remaining active lines are now returned, fulfillment becomes
    `RETURNED` and payment becomes `REFUNDED`."

    Design: Difficulty/transitive_cascade/return_approve_depth3_line_order_customer
    """
    ctx = setup_return_requested(10000, condition="SEALED", hygiene_returnable=True)
    api.approve_return(ctx["return_id"], FULFILL)
    lines = _lines_by_id(api, ctx["order_id"], ctx["cust_id"])
    assert lines[ctx["line_id"]]["status"] == "RETURNED"
    order = validate_success(api.get_order(ctx["order_id"], ctx["cust_headers"]), 200)
    assert order["fulfillment_status"] == "RETURNED"
    assert order["payment_status"] == "REFUNDED"


def test_approve_return_claws_back_loyalty_and_tier(api):
    """PRD §3.5: "the server writes a `LoyaltyTransaction` with `reason`
    `REVERSAL` and a `points_delta` equal to the negative of the sum of
    `points_earned` across the returned lines, and decreases the customer's
    `loyalty_points_balance` by that sum. Finally the customer's
    `lifetime_spend_cents` is reduced by the returned lines' net contribution and
    the customer's `tier` is recomputed."

    Design: Difficulty/transitive_cascade/return_approve_depth3_line_order_customer
    """
    ctx = setup_return_requested(10000, condition="SEALED", hygiene_returnable=True)
    api.approve_return(ctx["return_id"], FULFILL)
    cust = validate_success(api.get_customer(ctx["cust_id"], ctx["cust_headers"]), 200)
    assert cust["loyalty_points_balance"] == 0
    assert cust["lifetime_spend_cents"] == 0
    assert cust["tier"] == "BRONZE"


# ─── Difficulty/compensating_invariant/loyalty_points_conserved_earn_then_reversal ───
def test_fulfillment_earns_loyalty_points(api):
    """PRD §3.3: "The server then writes a `LoyaltyTransaction` with `reason`
    `EARN` and a `points_delta` equal to the summed points, and increases the
    customer's `loyalty_points_balance` by that sum."

    Design: Difficulty/compensating_invariant/loyalty_points_conserved_earn_then_reversal
    """
    ctx = setup_fulfilled_order(10000, hygiene_returnable=True)
    cust = validate_success(api.get_customer(ctx["cust_id"], ctx["cust_headers"]), 200)
    assert cust["loyalty_points_balance"] == 100  # round_half_up(10000/100 * 1.0)


def test_earn_then_reversal_conserves_loyalty_to_ledger_sum(api):
    """PRD §3.8: "The customer's `loyalty_points_balance` is not stored
    independently of its history: it always equals the sum of `points_delta`
    across that customer's `LoyaltyTransaction` rows."

    Design: Difficulty/compensating_invariant/loyalty_points_conserved_earn_then_reversal
    """
    ctx = setup_return_requested(10000, condition="SEALED", hygiene_returnable=True)
    api.approve_return(ctx["return_id"], FULFILL)
    cust = validate_success(api.get_customer(ctx["cust_id"], ctx["cust_headers"]), 200)
    assert cust["loyalty_points_balance"] == 0
    assert _ledger_sum(api, ctx["cust_id"]) == 0


# ─── Difficulty/priority_pair_validation_conflict/safety_beats_referential_on_return ───
def _two_fulfilled_nonreturnable_orders(api):
    """Same customer owns order_a (product1) and order_b (product2), both fulfilled,
    both products hygiene_returnable=False. Returns (cust_id, order_a_id, line_b_id)."""
    cust_id = make_customer()["id"]
    p1 = make_product(name="P1", brand="House", concentration="EDT", hygiene_returnable=False)
    v1 = make_variant(p1["id"], kind="FULL_BOTTLE", unit_price_cents=12000, on_hand_qty=5)
    order_a = make_order(cust_id)
    add_line(order_a["id"], cust_id, v1["id"], 1)
    place_order(order_a["id"], cust_id, 0)
    fulfill_order(order_a["id"])
    p2 = make_product(name="P2", brand="House", concentration="EDT", hygiene_returnable=False)
    v2 = make_variant(p2["id"], kind="FULL_BOTTLE", unit_price_cents=12000, on_hand_qty=5)
    order_b = make_order(cust_id)
    line_b = add_line(order_b["id"], cust_id, v2["id"], 1)
    place_order(order_b["id"], cust_id, 0)
    fulfill_order(order_b["id"])
    return cust_id, order_a["id"], line_b["id"]


def test_hygiene_check_precedes_line_membership(api):
    """PRD §3.5: "Per the ordering in Section 2.8, the hygiene check takes
    precedence over the line-membership check."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_referential_on_return
    """
    cust_id, order_a, line_b = _two_fulfilled_nonreturnable_orders(api)
    resp = api.create_return(
        {"order_id": order_a, "line_ids": [line_b], "condition": "OPENED"},
        make_customer_headers(cust_id),
    )
    validate_error(resp, ApiErrorId.ERR_HYGIENE_NON_RETURNABLE, 422)


def test_hygiene_error_wins_over_foreign_line_error(api):
    """PRD §3.5: "if the reported condition is `OPENED`, every returned line's
    variant must belong to a product whose `hygiene_returnable` is true; if any
    does not, the request is rejected with `ERR_HYGIENE_NON_RETURNABLE`." — this
    fires ahead of the line-membership rejection.

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_referential_on_return
    """
    cust_id, order_a, line_b = _two_fulfilled_nonreturnable_orders(api)
    resp = api.create_return(
        {"order_id": order_a, "line_ids": [line_b], "condition": "OPENED"},
        make_customer_headers(cust_id),
    )
    body = resp.json()
    assert body["data"]["error_id"] == "ERR_HYGIENE_NON_RETURNABLE"
    assert body["data"]["error_id"] != "ERR_LINE_NOT_IN_ORDER"
    assert resp.status_code == 422


# ─── Corner instances ─────────────────────────────────
def test_return_before_fulfillment_rejected(api):
    """PRD §3.5: "The request is admitted only if the order's `fulfillment_status`
    is `FULFILLED` or `PARTIALLY_RETURNED`, otherwise it is rejected with
    `ERR_ORDER_NOT_FULFILLED` (HTTP 409)."

    Design: Corner/validations/return_before_fulfill_returns_409
    """
    ctx = setup_placed_order(10000, quantity=1, on_hand_qty=5, hygiene_returnable=True)
    resp = api.create_return(
        {"order_id": ctx["order_id"], "line_ids": [ctx["line_id"]], "condition": "SEALED"},
        ctx["cust_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_FULFILLED, 409)


def test_approve_already_approved_return_rejected(api):
    """PRD §3.5: "Approving it moves the return from `REQUESTED` to `APPROVED`" —
    a second approval finds the return no longer `REQUESTED` and is rejected under
    the state check (PRD §2.8 tier 4, `ERR_INVALID_STATE`).

    Design: Corner/state_machines/approve_already_approved_return_returns_409
    """
    ctx = setup_return_requested(10000, condition="SEALED", hygiene_returnable=True)
    approve_return(ctx["return_id"])
    resp = api.approve_return(ctx["return_id"], FULFILL)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
