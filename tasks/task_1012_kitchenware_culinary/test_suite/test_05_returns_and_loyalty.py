"""Returns, the approval cascade (refund / points reversal / tier downgrade /
restock), loyalty conservation, tier thresholds, the fulfilled-order precondition,
state-over-fiscal precedence, redemption, filtering, and ownership."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    setup_fulfilled_order, setup_requested_return, setup_reserved_order,
    make_store, make_member, make_sku, order_line, create_return_payload,
    pay_order, set_clock, make_member_headers,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
ASSOC = TEST_USERS["associate_headers"]


# ── transitive_cascade / return_approve_line_points_tier ──────
def test_return_approval_refunds_gross_and_restocks(api):
    """PRD §3.4: "The `refund_amount_cents` is the target line's unit price multiplied by
    the returned quantity — the line gross, with no re-proration of any order-level discount."
    PRD §3.4: "a `WALLET` refund adds the refund amount to the member's wallet-credit
    balance, while an `ORIGINAL` refund adds it to the order's `refunded_cents`."

    Design: Difficulty/transitive_cascade/return_approve_line_points_tier
    """
    store, member, sku, order, ret = setup_requested_return(
        state_code="OR", list_price_cents=50000, on_hand_qty=3,
        reason="DEFECTIVE", refund_destination="WALLET", return_qty=1)
    approved = validate_success(api.approve_return(ret["id"], ASSOC), 200)
    assert approved["refund_amount_cents"] == 50000
    assert approved["points_reversed"] == 500  # 50000/100 * 1.00 (STANDARD snapshot)
    member_after = validate_success(api.get_member(member["id"], ADMIN), 200)
    assert member_after["wallet_credit_cents"] == 50000
    sku_after = validate_success(api.get_sku(sku["id"], ADMIN), 200)
    assert sku_after["on_hand_qty"] == 3, "restock raises on_hand back to 3"


def test_return_approval_reverses_spend_points_and_downgrades_tier(api):
    """PRD §3.4: "because the line is returned, the member's annual spend decreases by the
    returned line gross and the member's earned points decrease by the points reversed; the
    spend reduction triggers a tier recomputation that may downgrade the member".

    Design: Difficulty/transitive_cascade/return_approve_line_points_tier
    """
    store, member, sku, order, ret = setup_requested_return(
        state_code="OR", list_price_cents=50000, on_hand_qty=3,
        reason="DEFECTIVE", refund_destination="WALLET", return_qty=1)
    # pre-approval the member is SILVER (annual_spend 50000, earned 500).
    validate_success(api.approve_return(ret["id"], ASSOC), 200)
    member_after = validate_success(api.get_member(member["id"], ADMIN), 200)
    assert member_after["earned_points"] == 0
    assert member_after["annual_spend_cents"] == 0
    assert member_after["tier"] == "STANDARD"


# ── compensating_invariant / loyalty_points_conservation_fulfill_return ──
def test_full_return_reverses_exactly_the_earned_points(api):
    """PRD §3.4: "using the order's original tier snapshot guarantees that points earned and
    points reversed use the same multiplier."

    Design: Difficulty/compensating_invariant/loyalty_points_conservation_fulfill_return
    """
    store, member, sku, order, ret = setup_requested_return(
        state_code="OR", list_price_cents=30000, on_hand_qty=5,
        reason="DEFECTIVE", refund_destination="WALLET", return_qty=1)
    approved = validate_success(api.approve_return(ret["id"], ASSOC), 200)
    assert approved["points_reversed"] == 300  # fulfillment posted 300; reversal is 300


def test_earned_points_return_to_pre_fulfillment_value(api):
    """PRD §3.4: "the member's earned points decrease by the points reversed".
    PRD §3.2: "the `earned_points` bucket holds posted points from fulfilled orders, net of
    any reversals from approved returns."

    Design: Difficulty/compensating_invariant/loyalty_points_conservation_fulfill_return
    """
    store, member, sku, order, ret = setup_requested_return(
        state_code="OR", list_price_cents=30000, on_hand_qty=5,
        reason="DEFECTIVE", refund_destination="WALLET", return_qty=1)
    validate_success(api.approve_return(ret["id"], ASSOC), 200)
    member_after = validate_success(api.get_member(member["id"], ADMIN), 200)
    assert member_after["earned_points"] == 0, "no point drift remains after full return"


# ── boundary_precision_check / member_tier_silver_threshold ───
def test_spend_exactly_at_silver_threshold_promotes(api):
    """PRD §2.9: "a member whose annual spend is at least 50,000 cents but below the gold
    threshold is `SILVER`; any member below the silver threshold is `STANDARD`. Both
    boundaries are inclusive at the lower edge — spend exactly equal to a threshold lands in
    the higher tier."

    Design: Difficulty/boundary_precision_check/member_tier_silver_threshold
    """
    store, member, sku, order = setup_fulfilled_order(
        state_code="OR", list_price_cents=50000, on_hand_qty=3, qty=1)
    member_after = validate_success(api.get_member(member["id"], ADMIN), 200)
    assert member_after["annual_spend_cents"] == 50000
    assert member_after["tier"] == "SILVER"


def test_spend_one_below_silver_threshold_stays_standard(api):
    """PRD §2.9: "any member below the silver threshold is `STANDARD`."

    Design: Difficulty/boundary_precision_check/member_tier_silver_threshold
    """
    store, member, sku, order = setup_fulfilled_order(
        state_code="OR", list_price_cents=49999, on_hand_qty=3, qty=1)
    member_after = validate_success(api.get_member(member["id"], ADMIN), 200)
    assert member_after["annual_spend_cents"] == 49999
    assert member_after["tier"] == "STANDARD"


# ── cross_entity_state_dependency / return_requires_order_fulfilled ──
def test_return_against_reserved_order_rejected(api):
    """PRD §3.4: "the order's fulfillment status must be `FULFILLED`, or the request is
    rejected with `ERR_ORDER_NOT_FULFILLED`".

    Design: Difficulty/cross_entity_state_dependency/return_requires_order_fulfilled
    """
    store, member, sku, order = setup_reserved_order(
        state_code="OR", list_price_cents=10000, on_hand_qty=5, qty=1, category="TABLETOP")
    pay_order(order["id"])  # PAID but still RESERVED
    line_id = order["lines"][0]["line_id"]
    res = api.create_return(create_return_payload(order["id"], member["id"], line_id,
                                                  reason="UNWANTED", refund_destination="WALLET"), ASSOC)
    validate_error(res, "ERR_ORDER_NOT_FULFILLED")


def test_return_against_fulfilled_order_accepted(api):
    """PRD §3.4: "A newly requested return begins in `REQUESTED` status, with the refund
    amount and points reversal deferred until approval."

    Design: Difficulty/cross_entity_state_dependency/return_requires_order_fulfilled
    """
    store, member, sku, order = setup_fulfilled_order(
        state_code="OR", list_price_cents=10000, on_hand_qty=5, qty=1)
    line_id = order["lines"][0]["line_id"]
    res = api.create_return(create_return_payload(order["id"], member["id"], line_id,
                                                  reason="UNWANTED", refund_destination="WALLET"), ASSOC)
    ret = validate_success(res, 201)
    assert ret["status"] == "REQUESTED"


# ── priority_pair_validation_conflict / return_state_over_fiscal ──
def _setup_double_return_first_approved(api):
    store, member, sku, order = setup_fulfilled_order(
        state_code="OR", list_price_cents=50000, on_hand_qty=5, qty=1)
    line_id = order["lines"][0]["line_id"]
    ret1 = validate_success(api.create_return(
        create_return_payload(order["id"], member["id"], line_id,
                              reason="DEFECTIVE", refund_destination="WALLET"), ASSOC), 201)
    ret2 = validate_success(api.create_return(
        create_return_payload(order["id"], member["id"], line_id,
                              reason="UNWANTED", refund_destination="WALLET"), ASSOC), 201)
    validate_success(api.approve_return(ret1["id"], ASSOC), 200)  # line becomes RETURNED
    return ret2


def test_second_approve_returns_state_error(api):
    """PRD §3.4: "the target line must be fulfilled and not already returned, or the request
    is rejected with `ERR_LINE_ALREADY_RETURNED`".

    Design: Difficulty/priority_pair_validation_conflict/return_state_over_fiscal
    """
    ret2 = _setup_double_return_first_approved(api)
    res = api.approve_return(ret2["id"], ASSOC)
    validate_error(res, "ERR_LINE_ALREADY_RETURNED")


def test_state_check_wins_over_fiscal_on_second_approve(api):
    """PRD §2.1: "then state legality of the requested transition (HTTP 409); then time-window
    rules (HTTP 422); then capacity, overlap, and stock constraints (HTTP 409); and finally
    fiscal limits on refunds and redemptions (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/return_state_over_fiscal
    """
    ret2 = _setup_double_return_first_approved(api)
    res = api.approve_return(ret2["id"], ASSOC)
    body = res.json()["data"]
    assert body["error_id"] == "ERR_LINE_ALREADY_RETURNED", (
        f"state check must win over fiscal; got {body['error_id']}")
    assert res.status_code == 409


# ── Corner/calculations/return_window_expired_rejected ────────
def test_return_after_window_expiry_rejected(api):
    """PRD §3.4: "the current logical clock must be no later than the order's fulfillment
    timestamp plus the return window of 30 days, or the request is rejected with
    `ERR_RETURN_WINDOW_EXPIRED`".

    Design: Corner/calculations/return_window_expired_rejected
    """
    store, member, sku, order = setup_fulfilled_order(
        state_code="OR", list_price_cents=20000, on_hand_qty=5, qty=1,
        clock="2026-07-05T00:00:00Z")
    line_id = order["lines"][0]["line_id"]
    set_clock("2026-08-10T00:00:00Z")  # 36 days after fulfillment
    res = api.create_return(create_return_payload(order["id"], member["id"], line_id,
                                                  reason="UNWANTED", refund_destination="WALLET"), ASSOC)
    validate_error(res, "ERR_RETURN_WINDOW_EXPIRED")


# ── Corner/endpoints/returns_filtered_list_by_order_fk ────────
def test_returns_filtered_by_order_id(api):
    """PRD §3.4: "Returns can be listed and optionally filtered by `order_id` and
    `member_id`."

    Design: Corner/endpoints/returns_filtered_list_by_order_fk
    """
    store, member, sku, order, ret = setup_requested_return(
        state_code="OR", list_price_cents=5000, on_hand_qty=5,
        reason="DEFECTIVE", refund_destination="ORIGINAL", return_qty=1)
    data, meta = validate_paginated(api.list_returns(ADMIN, params={"order_id": order["id"]}))
    assert len(data) == 1
    assert data[0]["id"] == ret["id"]


# ── Corner/calculations/redeem_points_to_wallet ───────────────
def test_redeem_points_converts_to_wallet_credit(api):
    """PRD §3.2: "On a valid redemption, the earned-points balance decreases by the redeemed
    points and the wallet-credit balance increases by the same number of cents."

    Design: Corner/calculations/redeem_points_to_wallet
    """
    store, member, sku, order = setup_fulfilled_order(
        state_code="OR", list_price_cents=30000, on_hand_qty=5, qty=1)  # earns 300 points
    res = api.redeem_points(member["id"], {"points": 300}, make_member_headers(member["id"]))
    redeemed = validate_success(res, 200)
    assert redeemed["earned_points"] == 0
    assert redeemed["wallet_credit_cents"] == 300


# ── Corner/validations/redeem_insufficient_points_rejected ────
def test_redeem_more_than_earned_rejected(api):
    """PRD §3.2: "Redemption requires that the requested points not exceed the member's
    earned-points balance; a request for more than is available is rejected with
    `ERR_INSUFFICIENT_POINTS`."

    Design: Corner/validations/redeem_insufficient_points_rejected
    """
    store = make_store(state_code="OR")
    member = make_member(store["id"])  # freshly enrolled, earned_points 0
    res = api.redeem_points(member["id"], {"points": 100}, make_member_headers(member["id"]))
    validate_error(res, "ERR_INSUFFICIENT_POINTS")


# ── Corner/rbac/member_cannot_return_unowned_order ────────────
def test_member_cannot_return_another_members_order(api):
    """PRD §2.1: "When the acting role is `Member`, the platform verifies that the member owns
    the resource being acted upon — that `X-User-ID` equals the resource's `member_id` (or,
    for a return, the owning order's `member_id`). A member acting on a resource they do not
    own is rejected with `ERR_FORBIDDEN_OWNERSHIP`."

    Design: Corner/rbac/member_cannot_return_unowned_order
    """
    store, member_a, sku, order = setup_fulfilled_order(
        state_code="OR", list_price_cents=15000, on_hand_qty=5, qty=1)
    member_b = make_member(store["id"], full_name="Own B")
    line_id = order["lines"][0]["line_id"]
    res = api.create_return(
        create_return_payload(order["id"], member_b["id"], line_id,
                              reason="UNWANTED", refund_destination="WALLET"),
        make_member_headers(member_b["id"]))
    validate_error(res, "ERR_FORBIDDEN_OWNERSHIP")
