"""Special orders: quote/revise cycle, fulfillment gating, and OCC.

Difficulty instances: special_order_quote_revise_cycle,
order_fulfill_state_beats_stock_fiscal. Corner instance: occ_revise_stale_version_rejected.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
)
import test_helpers as th

SM = TEST_USERS["shop_manager_headers"]
SA = TEST_USERS["sales_associate_headers"]


# --------------------------------------------------------------------------- #
# Difficulty: quote -> revise -> re-quote cycle (non-linear state machine)
# --------------------------------------------------------------------------- #
def test_revise_then_requote_cycles_back_to_quoted(api):
    """PRD §3.8: "A successful revision moves the order from `QUOTED` to `CUSTOMER_REVIEW`, increments `revision_count` by 1, and advances the order's `version` by 1; the negotiation then cycles back to `QUOTED` via a fresh quote."

    Design: Difficulty/non_linear_state_machine/special_order_quote_revise_cycle
    """
    customer, prod, order = th.setup_quoted_special_order(api, quoted_price_cents=15000)
    assert order["status"] == "QUOTED"
    revised = validate_success(
        api.revise_special_order(order["id"], {"expected_special_order_version": order["version"]}, SA)
    )
    assert revised["status"] == "CUSTOMER_REVIEW"
    assert revised["revision_count"] == 1
    requoted = validate_success(
        api.quote_special_order(order["id"], {"quoted_price_cents": 14000}, SM)
    )
    assert requoted["status"] == "QUOTED"
    assert requoted["revision_count"] == 1


def test_two_revision_rounds_accumulate_revision_count(api):
    """PRD §3.8: "A successful revision moves the order from `QUOTED` to `CUSTOMER_REVIEW`, increments `revision_count` by 1, and advances the order's `version` by 1; the negotiation then cycles back to `QUOTED` via a fresh quote."

    Design: Difficulty/non_linear_state_machine/special_order_quote_revise_cycle
    """
    customer, prod, order = th.setup_quoted_special_order(api, quoted_price_cents=15000)
    # Round 1
    r1 = validate_success(
        api.revise_special_order(order["id"], {"expected_special_order_version": order["version"]}, SA)
    )
    q1 = validate_success(api.quote_special_order(order["id"], {"quoted_price_cents": 14000}, SM))
    assert q1["revision_count"] == 1 and q1["status"] == "QUOTED"
    # Round 2 (uses the freshly advanced version)
    r2 = validate_success(
        api.revise_special_order(order["id"], {"expected_special_order_version": q1["version"]}, SA)
    )
    assert r2["status"] == "CUSTOMER_REVIEW"
    q2 = validate_success(api.quote_special_order(order["id"], {"quoted_price_cents": 13000}, SM))
    assert q2["revision_count"] == 2
    assert q2["status"] == "QUOTED"


# --------------------------------------------------------------------------- #
# Difficulty: fulfill state check (409) precedes stock check (402)
# --------------------------------------------------------------------------- #
def test_fulfill_quoted_order_with_zero_stock_returns_invalid_state(api):
    """PRD §3.8: "A `ShopManager` fulfills an approved order, which requires it to be `APPROVED`, else `ERR_ORDER_INVALID_STATE`. Fulfillment additionally requires sufficient stock: the target product's `available_qty` must be at least the order `quantity`, or the request is refused with `ERR_INSUFFICIENT_STOCK`."
    PRD §2.10: "then the target resource being in a state that permits the requested transition (the per-entity invalid-state errors, HTTP 409), and only then the domain-specific business rules described below."

    Design: Difficulty/priority_pair_validation_conflict/order_fulfill_state_beats_stock_fiscal
    """
    customer, prod, order = th.setup_quoted_special_order(
        api, quoted_price_cents=45000, quantity=5)  # product on_hand 0
    resp = api.fulfill_special_order(order["id"], SM)
    validate_error(resp, ApiErrorId.ERR_ORDER_INVALID_STATE.value)
    reread = validate_success(api.get_special_order(order["id"], SA))
    assert reread["status"] == "QUOTED"


def test_fulfill_approved_order_with_zero_stock_returns_insufficient_stock(api):
    """PRD §3.8: "Fulfillment additionally requires sufficient stock: the target product's `available_qty` must be at least the order `quantity`, or the request is refused with `ERR_INSUFFICIENT_STOCK`."

    Design: Difficulty/priority_pair_validation_conflict/order_fulfill_state_beats_stock_fiscal
    """
    customer, prod, order = th.setup_quoted_special_order(
        api, quoted_price_cents=45000, quantity=5)  # product on_hand 0
    approved = validate_success(api.approve_special_order(order["id"], SA))
    assert approved["status"] == "APPROVED"
    resp = api.fulfill_special_order(order["id"], SM)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_STOCK.value)
    reread = validate_success(api.get_special_order(order["id"], SA))
    assert reread["status"] == "APPROVED"


# --------------------------------------------------------------------------- #
# Corner: OCC stale-version revise rejected
# --------------------------------------------------------------------------- #
def test_revise_with_stale_expected_version_rejected(api):
    """PRD §2.8: "Before the revision is applied, the server compares `expected_special_order_version` against the special order's current `version`. If another writer has re-quoted or revised the order since the client last read it — advancing the order's `version` — the submitted value is stale and the revise is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting/occ_revise_stale_version_rejected
    """
    customer, prod, order = th.setup_quoted_special_order(api, quoted_price_cents=20000)
    stale_version = order["version"]
    # An intervening revise + re-quote advances the version past the client's view.
    validate_success(
        api.revise_special_order(order["id"], {"expected_special_order_version": stale_version}, SA)
    )
    validate_success(api.quote_special_order(order["id"], {"quoted_price_cents": 19000}, SM))
    # The order is back in QUOTED, but the version has moved on.
    resp = api.revise_special_order(order["id"], {"expected_special_order_version": stale_version}, SA)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)
    reread = validate_success(api.get_special_order(order["id"], SA))
    assert reread["status"] == "QUOTED"
