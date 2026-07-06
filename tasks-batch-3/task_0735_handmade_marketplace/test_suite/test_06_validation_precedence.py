"""Validation ordering: state check precedes vacation on create; vacation precedes inventory on pay."""
from test_helpers import (
    validate_error, ApiErrorId,
    make_buyer_headers,
    setup_inactive_listing_vacation_shop, setup_order_then_vacation,
)

BUYER = make_buyer_headers("buyer_1")


# ==========================================================================
# Difficulty / priority_pair_validation_conflict / order_create_state_beats_vacation_constraint
# ==========================================================================
def test_order_create_listing_state_check_wins_over_vacation(api):
    """PRD §3.4: "Then the listing must be purchasable — its `status` must be `ACTIVE` —
    otherwise `ERR_LISTING_NOT_PURCHASABLE` (HTTP 409). Then the owning shop must not be
    closed to business: an order cannot be placed while the shop's `status` is `VACATION`,
    `SUSPENDED`, or `CLOSED`, which is rejected with `ERR_SHOP_ON_VACATION` (HTTP 422)."
    PRD §3.4: "These checks are applied strictly in this sequence, so an earlier failure
    surfaces its own code even when a later condition would also fail."

    Design: Difficulty/priority_pair_validation_conflict/order_create_state_beats_vacation_constraint
    """
    shop, listing = setup_inactive_listing_vacation_shop()
    resp = api.create_order(
        {"shop_id": shop["id"], "listing_id": listing["id"], "quantity": 1}, BUYER)
    validate_error(resp, ApiErrorId.ERR_LISTING_NOT_PURCHASABLE)


def test_order_create_conflict_not_reported_as_vacation(api):
    """PRD §3.4: "These checks are applied strictly in this sequence, so an earlier
    failure surfaces its own code even when a later condition would also fail."

    Design: Difficulty/priority_pair_validation_conflict/order_create_state_beats_vacation_constraint
    """
    shop, listing = setup_inactive_listing_vacation_shop()
    resp = api.create_order(
        {"shop_id": shop["id"], "listing_id": listing["id"], "quantity": 1}, BUYER)
    err = validate_error(resp, ApiErrorId.ERR_LISTING_NOT_PURCHASABLE)
    assert err["error_id"] != ApiErrorId.ERR_SHOP_ON_VACATION.value, \
        "the earlier state failure must pre-empt the vacation constraint"


# ==========================================================================
# Difficulty / priority_pair_validation_conflict / order_pay_vacation_constraint_beats_inventory_fiscal
# ==========================================================================
def test_pay_vacation_check_wins_over_inventory(api):
    """PRD §3.5: "The owning shop must not be on `VACATION`, `SUSPENDED`, or `CLOSED` — a
    shop closed to business rejects payment with `ERR_SHOP_ON_VACATION`."
    PRD §3.5: "Finally the available supply must cover the order ... a shortfall is
    rejected with `ERR_INSUFFICIENT_INVENTORY` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/order_pay_vacation_constraint_beats_inventory_fiscal
    """
    shop, listing, order = setup_order_then_vacation(order_quantity=5, listing_quantity=1)
    resp = api.pay_order(order["id"], BUYER)
    validate_error(resp, ApiErrorId.ERR_SHOP_ON_VACATION)


def test_pay_conflict_not_reported_as_inventory(api):
    """PRD §3.5: "it is guarded by several preconditions applied in order."
    PRD §3.5: "The owning shop must not be on `VACATION`, `SUSPENDED`, or `CLOSED` — a
    shop closed to business rejects payment with `ERR_SHOP_ON_VACATION`."

    Design: Difficulty/priority_pair_validation_conflict/order_pay_vacation_constraint_beats_inventory_fiscal
    """
    shop, listing, order = setup_order_then_vacation(order_quantity=5, listing_quantity=1)
    resp = api.pay_order(order["id"], BUYER)
    err = validate_error(resp, ApiErrorId.ERR_SHOP_ON_VACATION)
    assert err["error_id"] != ApiErrorId.ERR_INSUFFICIENT_INVENTORY.value, \
        "the vacation precondition must pre-empt the inventory precondition"
