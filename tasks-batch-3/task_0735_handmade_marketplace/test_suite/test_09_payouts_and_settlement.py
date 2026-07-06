"""Payout sweep math, estimated-vs-settled net, hold release gating, eligibility, and OCC."""
from test_helpers import (
    validate_success, validate_error, validate_error_is_one_of, ApiErrorId, TEST_USERS,
    make_seller_headers, make_buyer_headers,
    setup_two_completed_orders_and_payout, setup_payout_with_refunded_order,
    setup_completed_order_with_scheduled_payout, setup_completed_order_capture_stale_version,
    create_shop, get_shop_version,
    open_dispute_case, seller_respond_case, seller_resolve_case,
)

ADMIN = TEST_USERS["platform_admin_headers"]
BUYER = make_buyer_headers("buyer_1")


# ==========================================================================
# Difficulty / dual_variant_calc / payout_estimated_vs_settled_net
# ==========================================================================
def test_estimated_net_at_payout_creation_counts_all_orders(api):
    """PRD §3.9: "The `estimated_net_cents` is the forward-looking net: the sum of
    `order_net_cents` across every swept order, including any order that currently has an
    open dispute."

    Design: Difficulty/dual_variant_calc/payout_estimated_vs_settled_net
    """
    shop, listing, orders, payout = setup_two_completed_orders_and_payout()
    assert payout["estimated_net_cents"] == 90, "two 45-net orders -> 90"


def test_settled_net_drops_refunded_order_at_mark_paid(api):
    """PRD §3.9: "At mark-paid the `settled_net_cents` is computed by processing the swept
    orders in `created_at` ascending order and summing `order_net_cents`, but excluding
    any order that still has an open dispute and any order whose `payment_status` is
    `REFUNDED`."
    PRD §3.9: "On settlement the payout's `net_cents` is set to `settled_net_cents`".

    Design: Difficulty/dual_variant_calc/payout_estimated_vs_settled_net
    """
    shop, listing, orders, payout, case = setup_payout_with_refunded_order()
    paid = validate_success(api.mark_paid_payout(payout["id"], ADMIN))
    assert paid["settled_net_cents"] == 45, "refunded second order is dropped -> 45"
    assert paid["net_cents"] == 45


# ==========================================================================
# Difficulty / combinatorial_formula / payout_fees_round_per_order_then_sum
# ==========================================================================
def test_payout_fees_sum_already_rounded_per_order_fees(api):
    """PRD §3.9: "The `fees_cents` is the sum of each swept order's already-rounded
    `order_fee_cents` — fees are totalled per order and then summed, never recomputed as a
    percentage of the combined gross."

    Design: Difficulty/combinatorial_formula/payout_fees_round_per_order_then_sum
    """
    shop, listing, orders, payout = setup_two_completed_orders_and_payout()
    assert payout["fees_cents"] == 110, "55 + 55 per-order fees, not a re-rounded aggregate"


def test_payout_gross_and_estimated_net(api):
    """PRD §3.9: "The `gross_cents` is the sum of each swept order's `order_total_cents`."
    PRD §3.9: "The `estimated_net_cents` is the forward-looking net: the sum of
    `order_net_cents` across every swept order, including any order that currently has an
    open dispute."

    Design: Difficulty/combinatorial_formula/payout_fees_round_per_order_then_sum
    """
    shop, listing, orders, payout = setup_two_completed_orders_and_payout()
    assert payout["gross_cents"] == 200
    assert payout["estimated_net_cents"] == 90


# ==========================================================================
# Difficulty / cross_entity_state_dependency / payout_release_hold_requires_case_resolved
# ==========================================================================
def test_release_hold_blocked_while_case_open(api):
    """PRD §3.9: "it can be returned from `ON_HOLD` to `SCHEDULED` only by a platform
    operator explicitly releasing the hold, which is permitted only once no swept order
    still has `has_open_case` true."

    Design: Difficulty/cross_entity_state_dependency/payout_release_hold_requires_case_resolved
    """
    shop, listing, order, payout = setup_completed_order_with_scheduled_payout()
    open_dispute_case(order["id"], "buyer_1", "NON_DELIVERY")  # payout -> ON_HOLD
    resp = api.release_hold_payout(payout["id"], ADMIN)
    # PRD names the release-hold precondition but not the specific rejection code; both
    # the business error and the generic state error are PRD-faithful outcomes.
    validate_error_is_one_of(resp, [ApiErrorId.ERR_PAYOUT_HAS_OPEN_CASE,
                                    ApiErrorId.ERR_INVALID_STATE])


def test_release_hold_after_case_resolved_returns_scheduled(api):
    """PRD §3.9: "it can be returned from `ON_HOLD` to `SCHEDULED` only by a platform
    operator explicitly releasing the hold, which is permitted only once no swept order
    still has `has_open_case` true."

    Design: Difficulty/cross_entity_state_dependency/payout_release_hold_requires_case_resolved
    """
    shop, listing, order, payout = setup_completed_order_with_scheduled_payout()
    case = open_dispute_case(order["id"], "buyer_1", "NON_DELIVERY")
    seller_respond_case(case["id"], shop["id"], message="resolving")
    seller_resolve_case(case["id"], shop["id"], "NO_REFUND")
    released = validate_success(api.release_hold_payout(payout["id"], ADMIN))
    assert released["status"] == "SCHEDULED"


# ==========================================================================
# Corner / validations / payout_no_eligible_orders_returns_error
# ==========================================================================
def test_payout_create_with_no_eligible_orders_rejected(api):
    """PRD §3.9: "There must be at least one such eligible order, otherwise the create is
    rejected with `ERR_PAYOUT_NOT_ELIGIBLE` (HTTP 422); this eligibility check precedes
    the concurrency check."

    Design: Corner/validations/payout_no_eligible_orders_returns_error
    """
    shop = create_shop()
    version = get_shop_version(shop["id"])
    resp = api.create_payout(
        {"shop_id": shop["id"], "expected_shop_version": version},
        make_seller_headers(shop["id"]))
    validate_error(resp, ApiErrorId.ERR_PAYOUT_NOT_ELIGIBLE)


# ==========================================================================
# Corner / cross_cutting_complexity_layers / occ_stale_shop_version_on_payout_create
# ==========================================================================
def test_payout_create_with_stale_shop_version_rejected_then_fresh_succeeds(api):
    """PRD §2.9: "If `expected_shop_version` is lower than the shop's current `version`,
    the create is rejected with `ERR_STALE_SHOP_VERSION` (HTTP 412): a stale value means
    another payout has already been created against this shop and has claimed those
    orders, so re-sweeping under the client's outdated view would double-pay."
    PRD §3.9: "Creation sweeps every order of the shop whose `fulfillment_status` is
    `COMPLETED` and whose `payout_id` is still null, setting each swept order's
    `payout_id` and recording the `order_count`."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_shop_version_on_payout_create
    """
    shop, listing, order, stale_version = setup_completed_order_capture_stale_version()
    seller = make_seller_headers(shop["id"])
    stale = api.create_payout(
        {"shop_id": shop["id"], "expected_shop_version": stale_version}, seller)
    validate_error(stale, ApiErrorId.ERR_STALE_SHOP_VERSION)

    fresh_version = get_shop_version(shop["id"])
    payout = validate_success(api.create_payout(
        {"shop_id": shop["id"], "expected_shop_version": fresh_version}, seller), 201)
    assert payout["order_count"] == 1
