"""Dispute cases: open flags the order and holds the payout; resolution guards."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    make_seller_headers, make_buyer_headers,
    setup_completed_order_with_scheduled_payout, setup_paid_ready_to_ship_order,
    setup_active_listing, place_order,
    open_dispute_case, seller_respond_case, seller_resolve_case,
    get_order, get_payout,
)

BUYER = make_buyer_headers("buyer_1")


# ==========================================================================
# Difficulty / transitive_cascade / case_open_flags_order_and_holds_payout
# ==========================================================================
def test_open_case_sets_order_has_open_case(api):
    """PRD §3.8: "A newly opened case is `OPEN`, and it sets the order's `has_open_case`
    flag to true."

    Design: Difficulty/transitive_cascade/case_open_flags_order_and_holds_payout
    """
    shop, listing, order, payout = setup_completed_order_with_scheduled_payout()
    validate_success(api.create_case({"order_id": order["id"], "type": "NON_DELIVERY"}, BUYER), 201)
    assert get_order(order["id"], shop["id"])["has_open_case"] is True


def test_open_case_holds_scheduled_payout(api):
    """PRD §3.8: "If that order has already been swept into a payout and that payout is
    `SCHEDULED`, opening the case freezes the payout, moving it from `SCHEDULED` to
    `ON_HOLD`."

    Design: Difficulty/transitive_cascade/case_open_flags_order_and_holds_payout
    """
    shop, listing, order, payout = setup_completed_order_with_scheduled_payout()
    validate_success(api.create_case({"order_id": order["id"], "type": "NON_DELIVERY"}, BUYER), 201)
    assert get_payout(payout["id"], shop["id"])["status"] == "ON_HOLD"


# ==========================================================================
# Corner / validations / invalid_resolution_decision_returns_error
# ==========================================================================
def test_resolve_with_invalid_decision_rejected(api):
    """PRD §3.8: "only once the state is valid is the `decision` value checked, and a
    value outside the pair `REFUND`/`NO_REFUND` is rejected with `ERR_INVALID_RESOLUTION`
    (HTTP 400)."

    Design: Corner/validations/invalid_resolution_decision_returns_error
    """
    shop, listing, order = setup_paid_ready_to_ship_order()
    case = open_dispute_case(order["id"], "buyer_1", "NON_DELIVERY")
    seller_respond_case(case["id"], shop["id"])
    resp = api.resolve_case(case["id"], make_seller_headers(shop["id"]), {"decision": "MAYBE"})
    validate_error(resp, ApiErrorId.ERR_INVALID_RESOLUTION)


# ==========================================================================
# Corner / state_machines / resolve_already_resolved_case_returns_invalid_state
# ==========================================================================
def test_resolve_terminal_case_returns_invalid_state(api):
    """PRD §3.8: "A resolve attempted against a case that is not in a resolvable state is
    rejected first with `ERR_INVALID_STATE`; only once the state is valid is the
    `decision` value checked".

    Design: Corner/state_machines/resolve_already_resolved_case_returns_invalid_state
    """
    shop, listing, order = setup_paid_ready_to_ship_order()
    case = open_dispute_case(order["id"], "buyer_1", "NOT_AS_DESCRIBED")
    seller_respond_case(case["id"], shop["id"])
    seller_resolve_case(case["id"], shop["id"], "NO_REFUND")
    resp = api.resolve_case(case["id"], make_seller_headers(shop["id"]), {"decision": "REFUND"})
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    fetched = validate_success(api.get_case(case["id"], make_seller_headers(shop["id"])))
    assert fetched["status"] == "RESOLVED_NO_REFUND"


# ==========================================================================
# Corner / validations / case_on_unpaid_order_returns_error
# ==========================================================================
def test_open_case_on_unpaid_order_rejected(api):
    """PRD §3.8: "The target order must be paid — its `payment_status` must be `PAID` —
    and must belong to the acting buyer, else `ERR_CASE_NOT_ALLOWED` (HTTP 422)."

    Design: Corner/validations/case_on_unpaid_order_returns_error
    """
    shop, sp, listing = setup_active_listing(
        listing_overrides={"price_cents": 2000, "quantity": 5, "title": "Mug"})
    order = place_order(shop["id"], listing["id"], "buyer_1", quantity=1)
    resp = api.create_case({"order_id": order["id"], "type": "NON_DELIVERY"}, BUYER)
    validate_error(resp, ApiErrorId.ERR_CASE_NOT_ALLOWED)
