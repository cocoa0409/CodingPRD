"""Special-order allocation/cancellation invariants, recall gate at allocate,
fulfillment consuming reserved units, and insufficient-inventory rejection."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    TEST_USERS, make_customer_headers,
    create_special_order_payload,
    make_store, make_product, make_customer, make_lot,
    setup_allocated_special_order, issue_recall,
)

INVMGR = TEST_USERS["inventory_manager_headers"]
CLERK = TEST_USERS["store_clerk_headers"]


# ---------------------------------------------------------------------------
# Difficulty: compensating_invariant / allocate then cancel conserves free units
# ---------------------------------------------------------------------------
def test_special_order_allocate_then_cancel_conserves_free_units(api):
    """PRD §3.11: "On success the system reserves `quantity` units FEFO,
    increasing each chosen lot's `quantity_reserved` and bumping that lot's
    `version`".
    PRD §3.11: "Cancelling an `ALLOCATED` order is compensating: for each lot
    reserved for the order, its `quantity_reserved` is reduced by the reserved
    amount (releasing the reservation) and that lot's `version` is bumped."

    Design: Difficulty/compensating_invariant/special_order_allocate_then_cancel_conserves_free_units
    """
    store = make_store()
    product = make_product()
    lot = make_lot(store["id"], product["id"], quantity_on_hand=50)
    customer = make_customer(store["id"])
    order = validate_success(
        api.create_special_order(
            create_special_order_payload(
                customer["id"], product["id"], store["id"],
                quantity=3, deposit_pct=0.25,
            ), CLERK,
        ), 201,
    )
    validate_success(api.allocate_special_order(order["id"], INVMGR), 200)
    # Compensating cancel by the owning customer.
    cancelled = validate_success(
        api.cancel_special_order(order["id"], make_customer_headers(customer["id"])),
        200,
    )
    assert cancelled["status"] == "CANCELLED"
    lot_after = validate_success(api.get_inventory_lot(lot["id"], INVMGR), 200)
    # Free units conserved: reservation released, on_hand untouched.
    assert lot_after["quantity_reserved"] == 0
    assert lot_after["quantity_on_hand"] == 50


def test_special_order_allocate_reserves_free_units(api):
    """PRD §3.11: "On success the system reserves `quantity` units FEFO,
    increasing each chosen lot's `quantity_reserved` and bumping that lot's
    `version`; the order moves to `ALLOCATED` and its `version` is bumped."

    Design: Difficulty/compensating_invariant/special_order_allocate_then_cancel_conserves_free_units
    """
    store = make_store()
    product = make_product()
    lot = make_lot(store["id"], product["id"], quantity_on_hand=50)
    customer = make_customer(store["id"])
    order = validate_success(
        api.create_special_order(
            create_special_order_payload(
                customer["id"], product["id"], store["id"], quantity=3,
            ), CLERK,
        ), 201,
    )
    allocated = validate_success(api.allocate_special_order(order["id"], INVMGR), 200)
    assert allocated["status"] == "ALLOCATED"
    lot_after = validate_success(api.get_inventory_lot(lot["id"], INVMGR), 200)
    assert lot_after["quantity_reserved"] == 3
    assert lot_after["quantity_on_hand"] == 50


# ---------------------------------------------------------------------------
# Difficulty: cross_entity_state_dependency / allocate requires product CLEAR
# ---------------------------------------------------------------------------
def test_special_order_allocate_requires_product_clear(api):
    """PRD §3.11: "Allocation requires the order to be `REQUESTED` (otherwise
    `ERR_SPECIAL_ORDER_STATE_INVALID`), the product's `recall_state` to be
    `CLEAR` (otherwise `ERR_PRODUCT_RECALLED`)".

    Design: Difficulty/cross_entity_state_dependency/special_order_allocate_requires_product_clear
    """
    store = make_store()
    product = make_product()
    make_lot(store["id"], product["id"], quantity_on_hand=50)
    customer = make_customer(store["id"])
    order = validate_success(
        api.create_special_order(
            create_special_order_payload(
                customer["id"], product["id"], store["id"],
                quantity=3, deposit_pct=0.25,
            ), CLERK,
        ), 201,
    )
    issue_recall(product["id"], severity="MANDATORY")
    res = api.allocate_special_order(order["id"], INVMGR)
    validate_error(res, ApiErrorId.ERR_PRODUCT_RECALLED)


def test_special_order_allocate_clear_product_succeeds(api):
    """PRD §3.11: "Allocation requires the order to be `REQUESTED` ..., the
    product's `recall_state` to be `CLEAR` ..., and the ordered free units across
    `AVAILABLE` lots for the store and product to total at least the order's
    `quantity` ... On success ... the order moves to `ALLOCATED`".

    Design: Difficulty/cross_entity_state_dependency/special_order_allocate_requires_product_clear
    """
    store = make_store()
    product = make_product()
    make_lot(store["id"], product["id"], quantity_on_hand=50)
    customer = make_customer(store["id"])
    order = validate_success(
        api.create_special_order(
            create_special_order_payload(
                customer["id"], product["id"], store["id"], quantity=3,
            ), CLERK,
        ), 201,
    )
    # No recall: product is CLEAR, allocation succeeds.
    allocated = validate_success(api.allocate_special_order(order["id"], INVMGR), 200)
    assert allocated["status"] == "ALLOCATED"


# ---------------------------------------------------------------------------
# Corner: endpoints / fulfill consumes reserved units
# ---------------------------------------------------------------------------
def test_special_order_fulfill_consumes_reserved_units(api):
    """PRD §3.11: "On success, for each lot reserved for this order, its
    `quantity_reserved` and its `quantity_on_hand` are both reduced by the
    reserved amount ...; the order moves to `FULFILLED`."

    Design: Corner/endpoints/special_order_fulfill_consumes_reserved_units
    """
    ctx = setup_allocated_special_order(quantity=3, lot_qty=10)
    order = ctx["order"]
    lot = ctx["lot"]
    fulfilled = validate_success(api.fulfill_special_order(order["id"], CLERK), 200)
    assert fulfilled["status"] == "FULFILLED"
    lot_after = validate_success(api.get_inventory_lot(lot["id"], INVMGR), 200)
    assert lot_after["quantity_on_hand"] == 7
    assert lot_after["quantity_reserved"] == 0


# ---------------------------------------------------------------------------
# Corner: validations / insufficient inventory on allocate
# ---------------------------------------------------------------------------
def test_insufficient_inventory_on_allocate_rejected(api):
    """PRD §3.11: "the ordered free units across `AVAILABLE` lots for the store
    and product to total at least the order's `quantity` (otherwise
    `ERR_INSUFFICIENT_INVENTORY`)."
    PRD §2.9: "If the sum of free units across all candidate lots is less than
    the requested count, the operation is rejected with `ERR_INSUFFICIENT_INVENTORY`
    and no units are taken".

    Design: Corner/validations/insufficient_inventory_on_allocate_rejected
    """
    store = make_store()
    product = make_product()
    lot = make_lot(store["id"], product["id"], quantity_on_hand=5)
    customer = make_customer(store["id"])
    order = validate_success(
        api.create_special_order(
            create_special_order_payload(
                customer["id"], product["id"], store["id"],
                quantity=10, deposit_pct=0.25,
            ), CLERK,
        ), 201,
    )
    res = api.allocate_special_order(order["id"], INVMGR)
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_INVENTORY)
    lot_after = validate_success(api.get_inventory_lot(lot["id"], INVMGR), 200)
    assert lot_after["quantity_reserved"] == 0, "no reservation on failed allocate"
