"""Rod & reel service orders (revision cycle, invalid pickup) and special
orders (refund on cancel, eligibility guards)."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    TEST_USERS,
    fixtures,
)

MANAGER = TEST_USERS["manager_headers"]
CLERK = TEST_USERS["clerk_headers"]


# --- Difficulty: non_linear_state_machine / service_order_awaiting_parts_cycle ---

def test_service_order_awaits_parts_then_resumes(api):
    """PRD 3.8: "While in progress, the order may move to `AWAITING_PARTS` when parts must be sourced and back from `AWAITING_PARTS → IN_PROGRESS` when work resumes, forming a revision loop that may repeat."

    Design: Difficulty/non_linear_state_machine/service_order_awaiting_parts_cycle
    """
    _customer, order = fixtures.setup_service_order_in_progress(
        customer_kwargs={"name": "Angler F", "email": "f@x.com"},
        order_kwargs={"item_description": "Shimano reel", "service_type": "REEL_SERVICE",
                      "quoted_cents": 4000},
    )
    awaiting = fixtures.transition_service_order(order["id"], "AWAIT_PARTS")
    assert awaiting["status"] == "AWAITING_PARTS"
    resumed = fixtures.transition_service_order(order["id"], "RESUME")
    assert resumed["status"] == "IN_PROGRESS", "cycle: IN_PROGRESS re-entered from AWAITING_PARTS"


def test_service_order_resumes_then_ready(api):
    """PRD 3.8: "IN_PROGRESS → READY` marks the item ready for pickup."

    Design: Difficulty/non_linear_state_machine/service_order_awaiting_parts_cycle
    """
    _customer, order = fixtures.setup_service_order_in_progress(
        customer_kwargs={"name": "Angler F2", "email": "f2@x.com"},
        order_kwargs={"item_description": "Shimano reel", "service_type": "REEL_SERVICE",
                      "quoted_cents": 4000},
    )
    fixtures.transition_service_order(order["id"], "AWAIT_PARTS")
    fixtures.transition_service_order(order["id"], "RESUME")
    ready = fixtures.transition_service_order(order["id"], "READY")
    assert ready["status"] == "READY", "IN_PROGRESS -> READY after resuming the revision loop"


# --- Corner: state_machines / sm_service_order_pickup_from_received ---

def test_pickup_from_received_rejected(api):
    """PRD 3.8: "READY → PICKED_UP` captures the charge: `final_cents` is set equal to `quoted_cents".
    PRD 2.8: "6. **State** — the target resource is in a state that permits the requested transition or action, else `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/sm_service_order_pickup_from_received_returns_invalid_state
    """
    customer = fixtures.create_customer(name="SO Cust", email="so@x.com")
    order = fixtures.create_service_order(customer["id"], item_description="Rod",
                                          service_type="ROD_REPAIR", quoted_cents=3000)
    resp = api.transition_service_order(order["id"], {"action": "PICKUP"}, CLERK)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# --- Corner: calculations / calc_special_order_refund_from_ordered ---

def test_special_order_refund_from_ordered_retains_restock_fee(api):
    """PRD 3.2: "On creation the order snapshots the product's price into `unit_price_cents`, computes a required `deposit_cents` equal to the unit price times the quantity times one half, rounded half up to whole cents, and enters `REQUESTED`."
    PRD 3.2: "cancelling from `ORDERED` deducts a restock fee equal to the deposit times one fifth, rounded half up, and refunds the deposit minus that fee."

    Design: Corner/calculations/calc_special_order_refund_from_ordered
    """
    customer = fixtures.create_customer(name="SP Cust", email="sp@x.com")
    product = fixtures.create_product(sku="SPCL-1", name="Custom Rod", category="ROD",
                                      unit_price_cents=10000, stock_qty=0,
                                      is_special_order_eligible=True)
    order = fixtures.create_special_order(customer["id"], product["id"], quantity=1)
    assert order["deposit_cents"] == 5000, "round(10000 * 1 * 0.50)"
    fixtures.transition_special_order(order["id"], "ORDER")
    cancelled = fixtures.transition_special_order(order["id"], "CANCEL")
    assert cancelled["refund_cents"] == 4000, "5000 - round(5000 * 0.20) = 5000 - 1000"
    assert cancelled["status"] == "CANCELLED"


# --- Corner: validations / val_special_order_product_inactive ---

def test_special_order_inactive_product_rejected(api):
    """PRD 3.2: "The backing product must be active and flagged special-order eligible; a request against an inactive product is rejected with `ERR_PRODUCT_INACTIVE`, and one against a product that is not eligible is rejected with `ERR_NOT_SPECIAL_ORDER_ELIGIBLE`."

    Design: Corner/validations/val_special_order_product_inactive
    """
    customer = fixtures.create_customer(name="Inact Cust", email="ia@x.com")
    product = fixtures.create_product(sku="INACT-1", name="Discontinued Rod", category="ROD",
                                      unit_price_cents=8000, stock_qty=0,
                                      is_active=False, is_special_order_eligible=True)
    resp = api.create_special_order(
        {"customer_id": customer["id"], "product_id": product["id"], "quantity": 1}, CLERK)
    validate_error(resp, ApiErrorId.ERR_PRODUCT_INACTIVE.value)


# --- Corner: validations / val_special_order_not_eligible ---

def test_special_order_ineligible_product_rejected(api):
    """PRD 3.2: "The backing product must be active and flagged special-order eligible; a request against an inactive product is rejected with `ERR_PRODUCT_INACTIVE`, and one against a product that is not eligible is rejected with `ERR_NOT_SPECIAL_ORDER_ELIGIBLE`."

    Design: Corner/validations/val_special_order_not_eligible
    """
    customer = fixtures.create_customer(name="Elig Cust", email="el@x.com")
    product = fixtures.create_product(sku="NOEL-1", name="Stock Rod", category="ROD",
                                      unit_price_cents=8000, stock_qty=5,
                                      is_special_order_eligible=False)
    resp = api.create_special_order(
        {"customer_id": customer["id"], "product_id": product["id"], "quantity": 1}, CLERK)
    validate_error(resp, ApiErrorId.ERR_NOT_SPECIAL_ORDER_ELIGIBLE.value)
