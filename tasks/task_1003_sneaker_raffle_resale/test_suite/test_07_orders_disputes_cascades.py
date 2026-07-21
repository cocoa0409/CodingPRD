"""Buyer verification cascade, refund clawback, money conservation, dispute
guards, and same-SKU release cooldown."""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId, TEST_USERS,
    setup_fixed_order, setup_shipped_order, setup_verified_order,
    setup_verified_order_with_open_dispute, file_dispute,
    create_sku, create_release_payload, create_dispute_payload,
    advance_clock, make_buyer_headers,
)

ADMIN = TEST_USERS["admin_headers"]
CS = TEST_USERS["cs_headers"]


# --------------------------------------------------------------------------- #
# Verify credits seller then recomputes level (Difficulty depth-3 cascade)
# --------------------------------------------------------------------------- #
def test_verify_credits_seller_balance_and_count(api):
    """PRD §3.7: "For a resale order (`FIXED` or `BID_MATCH`), verification then
    cascades through the seller's `Account`: the `final_payout_cents` is added to
    the seller's `balance_cents`, the seller's `completed_sales_count` is
    incremented by one, the seller's `seller_level` is recomputed from that new
    count, and finally the seller's `trust_score` is recomputed."

    Design: Difficulty/transitive_cascade/verify_credits_seller_then_recomputes_level_depth3
    """
    ctx = setup_verified_order(api, ask_price_cents=30000,
                               listed_condition="DEADSTOCK", auth_condition="DEADSTOCK")
    assert ctx["order"]["final_payout_cents"] == 27300
    seller = get_success_data(api.get_account(ctx["seller"]["id"], ADMIN))
    assert seller["balance_cents"] == 27300
    assert seller["completed_sales_count"] == 1


def test_verify_captures_payment_and_recomputes_level(api):
    """PRD §3.7: "Verification first advances the payment axis to `CAPTURED`."
    PRD §3.7: "The seller level is derived purely from `completed_sales_count`:
    `STANDARD` for a count from 0 up to but not including 5, `PRO` for a count
    from 5 up to but not including 20, and `ELITE` for a count of 20 or more."

    Design: Difficulty/transitive_cascade/verify_credits_seller_then_recomputes_level_depth3
    """
    ctx = setup_verified_order(api, ask_price_cents=30000,
                               listed_condition="DEADSTOCK", auth_condition="DEADSTOCK")
    assert ctx["order"]["payment_status"] == "CAPTURED"
    seller = get_success_data(api.get_account(ctx["seller"]["id"], ADMIN))
    assert seller["seller_level"] == "STANDARD"  # count 1 -> [0,5)


# --------------------------------------------------------------------------- #
# Refund clawback reverses the credit (Difficulty depth-3 cascade)
# --------------------------------------------------------------------------- #
def _refunded(api):
    ctx = setup_verified_order_with_open_dispute(
        api, reason="INAUTHENTIC", ask_price_cents=30000,
        listed_condition="DEADSTOCK", auth_condition="DEADSTOCK",
    )
    get_success_data(api.resolve_dispute(ctx["dispute"]["id"],
                                         {"outcome": "REFUND", "resolution_note": "counterfeit"},
                                         CS))
    order = get_success_data(api.get_order(ctx["order"]["id"], make_buyer_headers(ctx["buyer"]["id"])))
    seller = get_success_data(api.get_account(ctx["seller"]["id"], ADMIN))
    return order, seller


def test_refund_marks_order_refunded_and_debits_seller(api):
    """PRD §3.8: "A `REFUND` outcome moves the dispute to `RESOLVED_REFUND` and
    reverses the sale: the order's `payment_status` is set to `REFUNDED`, and for
    a resale order (`FIXED` or `BID_MATCH`) the clawback cascade mirrors the
    verification credit in reverse — the order's `final_payout_cents` is
    subtracted from the seller's `balance_cents`, the seller's
    `completed_sales_count` is decremented by one, and the seller's `seller_level`
    and `trust_score` are recomputed from the reduced count."

    Design: Difficulty/transitive_cascade/refund_claws_back_seller_then_recomputes_level_depth3
    """
    order, seller = _refunded(api)
    assert order["payment_status"] == "REFUNDED"
    assert seller["balance_cents"] == 0


def test_refund_decrements_completed_sales_count(api):
    """PRD §3.8: "the seller's `completed_sales_count` is decremented by one".

    Design: Difficulty/transitive_cascade/refund_claws_back_seller_then_recomputes_level_depth3
    """
    _order, seller = _refunded(api)
    assert seller["completed_sales_count"] == 0


# --------------------------------------------------------------------------- #
# Money conserved across verify then refund (Difficulty compensating invariant)
# --------------------------------------------------------------------------- #
def test_seller_balance_returns_to_zero_after_verify_then_refund(api):
    """PRD §3.7: "the `final_payout_cents` is added to the seller's
    `balance_cents`".
    PRD §3.8: "the order's `final_payout_cents` is subtracted from the seller's
    `balance_cents`".

    Design: Difficulty/compensating_invariant/money_conserved_across_verify_then_refund
    """
    order, seller = _refunded(api)
    assert seller["balance_cents"] == 0
    assert order["payment_status"] == "REFUNDED"


def test_credit_then_debit_net_to_zero_without_drift(api):
    """PRD §3.7: "the `final_payout_cents` is added to the seller's
    `balance_cents`".
    PRD §3.8: "the order's `final_payout_cents` is subtracted from the seller's
    `balance_cents`".

    Design: Difficulty/compensating_invariant/money_conserved_across_verify_then_refund
    """
    ctx = setup_verified_order(api, ask_price_cents=30000,
                               listed_condition="DEADSTOCK", auth_condition="DEADSTOCK")
    credited = get_success_data(api.get_account(ctx["seller"]["id"], ADMIN))
    assert credited["balance_cents"] == 27300  # after verify credit
    dispute = file_dispute(api, ctx["order"]["id"], ctx["buyer"]["id"], reason="INAUTHENTIC")
    get_success_data(api.resolve_dispute(dispute["id"],
                                         {"outcome": "REFUND", "resolution_note": "counterfeit"}, CS))
    after = get_success_data(api.get_account(ctx["seller"]["id"], ADMIN))
    assert after["balance_cents"] == 0  # exact reversal, no drift


# --------------------------------------------------------------------------- #
# Same-SKU release cooldown (Difficulty resource temporal overlap)
# --------------------------------------------------------------------------- #
def test_second_same_sku_release_within_cooldown_rejected(api):
    """PRD §3.2: "the interval spanning from its `entry_opens_at` through its
    `purchase_closes_at` must stay at least 24 hours clear of the corresponding
    span of any non-cancelled release of that same SKU, and a violation is
    rejected with `ERR_RELEASE_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/release_same_sku_cooldown_buffer_rejected
    """
    sku = create_sku(api, release_category="LIMITED")
    get_success_data(api.create_release(create_release_payload(
        sku_id=sku["id"], allocated_quantity=5,
        entry_opens_at="2026-07-05T00:00:00Z", entry_closes_at="2026-07-06T00:00:00Z",
        purchase_opens_at="2026-07-06T01:00:00Z", purchase_closes_at="2026-07-07T00:00:00Z"), ADMIN))
    # second span opens only 6h after the first span's close -> < 24h clear.
    resp = api.create_release(create_release_payload(
        sku_id=sku["id"], allocated_quantity=3,
        entry_opens_at="2026-07-07T06:00:00Z", entry_closes_at="2026-07-08T00:00:00Z",
        purchase_opens_at="2026-07-08T01:00:00Z", purchase_closes_at="2026-07-09T00:00:00Z"), ADMIN)
    validate_error(resp, ApiErrorId.ERR_RELEASE_WINDOW_OVERLAP.value)


def test_second_same_sku_release_clear_of_cooldown_accepted(api):
    """PRD §3.2: "the interval spanning from its `entry_opens_at` through its
    `purchase_closes_at` must stay at least 24 hours clear of the corresponding
    span of any non-cancelled release of that same SKU, and a violation is
    rejected with `ERR_RELEASE_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/release_same_sku_cooldown_buffer_rejected
    """
    sku = create_sku(api, release_category="LIMITED")
    get_success_data(api.create_release(create_release_payload(
        sku_id=sku["id"], allocated_quantity=5,
        entry_opens_at="2026-07-05T00:00:00Z", entry_closes_at="2026-07-06T00:00:00Z",
        purchase_opens_at="2026-07-06T01:00:00Z", purchase_closes_at="2026-07-07T00:00:00Z"), ADMIN))
    # second span opens exactly 24h after the first span's close -> at least 24h clear.
    resp = api.create_release(create_release_payload(
        sku_id=sku["id"], allocated_quantity=3,
        entry_opens_at="2026-07-08T00:00:00Z", entry_closes_at="2026-07-08T12:00:00Z",
        purchase_opens_at="2026-07-08T13:00:00Z", purchase_closes_at="2026-07-09T00:00:00Z"), ADMIN)
    validate_success(resp, expected_status=201)


# --------------------------------------------------------------------------- #
# Order / dispute state guards (Corner)
# --------------------------------------------------------------------------- #
def test_verify_before_ship_returns_order_state_invalid(api):
    """PRD §3.7: "attempting to verify an order not in `SHIPPED_TO_BUYER` is
    rejected with `ERR_ORDER_STATE_INVALID`".

    Design: Corner/state_machines/verify_before_ship_returns_order_state_invalid
    """
    ctx = setup_fixed_order(api, ask_price_cents=30000)
    resp = api.verify_order(ctx["order"]["id"], make_buyer_headers(ctx["buyer"]["id"]))
    validate_error(resp, ApiErrorId.ERR_ORDER_STATE_INVALID.value)


def test_dispute_before_ship_returns_not_disputable(api):
    """PRD §3.8: "Disputes are only accepted against an order whose
    `fulfillment_status` is `SHIPPED_TO_BUYER` or `VERIFIED`; filing against an
    order in any other fulfillment state is rejected with
    `ERR_ORDER_NOT_DISPUTABLE`."

    Design: Corner/state_machines/dispute_before_ship_returns_not_disputable
    """
    ctx = setup_fixed_order(api, ask_price_cents=30000)
    payload = create_dispute_payload(order_id=ctx["order"]["id"],
                                     filed_by_account_id=ctx["buyer"]["id"], reason="NOT_RECEIVED")
    resp = api.create_dispute(payload, make_buyer_headers(ctx["buyer"]["id"]))
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_DISPUTABLE.value)


def test_dispute_after_deadline_returns_window_expired(api):
    """PRD §3.8: "The filing must also be timely: the logical clock must be at or
    before the order's `dispute_deadline`, and a clock past that deadline is
    rejected with `ERR_DISPUTE_WINDOW_EXPIRED`."

    Design: Corner/state_machines/dispute_after_deadline_returns_window_expired
    """
    ctx = setup_shipped_order(api, ask_price_cents=30000)  # shipped at clock 2026-07-01 -> deadline 07-04
    advance_clock(api, "2026-07-05T00:00:00Z")             # past the 3-day dispute window
    payload = create_dispute_payload(order_id=ctx["order"]["id"],
                                     filed_by_account_id=ctx["buyer"]["id"], reason="NOT_AS_DESCRIBED")
    resp = api.create_dispute(payload, make_buyer_headers(ctx["buyer"]["id"]))
    validate_error(resp, ApiErrorId.ERR_DISPUTE_WINDOW_EXPIRED.value)


def test_resolve_already_resolved_dispute_rejected(api):
    """PRD §3.8: "Resolving a dispute that is not `OPEN` is rejected with
    `ERR_DISPUTE_ALREADY_RESOLVED`."

    Design: Corner/state_machines/resolve_twice_returns_dispute_already_resolved
    """
    ctx = setup_shipped_order(api, ask_price_cents=30000)
    dispute = file_dispute(api, ctx["order"]["id"], ctx["buyer"]["id"], reason="NOT_AS_DESCRIBED")
    get_success_data(api.resolve_dispute(dispute["id"],
                                         {"outcome": "DENY", "resolution_note": "no evidence"}, CS))
    resp = api.resolve_dispute(dispute["id"],
                               {"outcome": "REFUND", "resolution_note": "second attempt"}, CS)
    validate_error(resp, ApiErrorId.ERR_DISPUTE_ALREADY_RESOLVED.value)
