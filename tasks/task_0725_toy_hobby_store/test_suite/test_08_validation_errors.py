"""Entity uniqueness/required-field, existence, fiscal, state, and RBAC corner cases."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data, ApiErrorId,
    TEST_USERS, make_customer_headers,
    create_active_product, create_store, create_inventory, create_customer,
    create_open_order, add_line, create_fulfilled_order, create_requested_return,
    create_registry,
)

ADMIN = TEST_USERS["catalog_admin_headers"]
MANAGER = TEST_USERS["store_manager_headers"]
ASSOCIATE = TEST_USERS["store_associate_headers"]
ANY = TEST_USERS["any_headers"]


# --- Entities ---
def test_create_product_missing_sku_rejected(api):
    """PRD §3.1: "A `CatalogAdmin` seeds the catalog by creating a product, supplying its
    unique `sku`, its `name`, its `category` ..."
    PRD §2.10: "A malformed body, a missing required field, or a wrong type is rejected
    with `ERR_VALIDATION` as part of the earliest structural evaluation."

    Design: Corner/entities/create_product_missing_required_sku_returns_validation
    """
    validate_error(
        api.create_product(
            {"name": "NoSku", "category": "PLUSH", "age_grade_min_months": 0,
             "safety_labels": ["NONE"], "msrp_cents": 1000}, ADMIN),
        ApiErrorId.ERR_VALIDATION.value,
    )


def test_duplicate_sku_rejected(api):
    """PRD §3.1: "If the submitted `sku` already belongs to another product, creation is
    rejected with `ERR_DUPLICATE_SKU`."

    Design: Corner/entities/duplicate_sku_rejected
    """
    get_success_data(api.create_product(
        {"sku": "DUP-1", "name": "A", "category": "PLUSH", "age_grade_min_months": 0,
         "safety_labels": ["NONE"], "msrp_cents": 1000}, ADMIN))
    validate_error(
        api.create_product(
            {"sku": "DUP-1", "name": "B", "category": "PLUSH", "age_grade_min_months": 0,
             "safety_labels": ["NONE"], "msrp_cents": 2000}, ADMIN),
        ApiErrorId.ERR_DUPLICATE_SKU.value,
    )


def test_duplicate_customer_email_rejected(api):
    """PRD §3.4: "A `StoreAssociate` enrolls a loyalty customer with a `name` and a unique
    `email`; a duplicate email is rejected with `ERR_DUPLICATE_EMAIL`."

    Design: Corner/entities/duplicate_customer_email_rejected
    """
    get_success_data(api.create_customer({"name": "A", "email": "dup@x.com"}, ASSOCIATE))
    validate_error(
        api.create_customer({"name": "B", "email": "dup@x.com"}, ASSOCIATE),
        ApiErrorId.ERR_DUPLICATE_EMAIL.value,
    )


def test_available_qty_computed_on_reserve(api):
    """PRD §2.9: "`available_qty` is the derived remainder, computed as `on_hand_qty` minus
    `reserved_qty` minus `quarantined_qty`, and it is recomputed on every reserve, release,
    receive, or quarantine mutation."
    PRD §3.5: "the requested units are reserved on the matching inventory item:
    `reserved_qty` increases by `qty` and `available_qty` decreases by `qty`."

    Design: Corner/entities/inventory_available_qty_computed_on_reserve
    """
    product = create_active_product(msrp_cents=1000, category="PLUSH")
    store = create_store()
    inv = create_inventory(product["id"], store["id"], on_hand_qty=10)
    customer = create_customer()
    cid = customer["id"]
    order = create_open_order(cid, store["id"])
    add_line(order["id"], cid, product["id"], qty=3, recipient_age_months=60)

    item = validate_success(api.get_inventory(inv["id"], ANY))
    assert item["available_qty"] == 7
    assert item["reserved_qty"] == 3


# --- State machines ---
def test_submit_already_submitted_order_rejected(api):
    """PRD §3.6: "Submitting an order moves it from `OPEN` to `SUBMITTED` and computes
    provisional pricing; it requires the order to be `OPEN` with at least one `ACTIVE`
    line."
    PRD §3.5: "A line may be added only while the order's `fulfillment_status` is `OPEN`;
    otherwise `ERR_ORDER_NOT_OPEN` is returned."

    Design: Corner/state_machines/submit_already_submitted_order_returns_invalid_state
    """
    product = create_active_product(msrp_cents=1000, category="PLUSH")
    store = create_store()
    create_inventory(product["id"], store["id"], on_hand_qty=10)
    customer = create_customer()
    cid = customer["id"]
    order = create_open_order(cid, store["id"])
    add_line(order["id"], cid, product["id"], qty=1, recipient_age_months=60)
    get_success_data(api.submit_order(order["id"], make_customer_headers(cid)))

    validate_error(
        api.submit_order(order["id"], make_customer_headers(cid)),
        ApiErrorId.ERR_ORDER_NOT_OPEN.value,
    )


def test_fulfill_unpaid_ready_order_rejected(api):
    """PRD §3.7: "Fulfillment advances a `READY` order to `FULFILLED` and requires
    `payment_status` of `PAID` (an order not yet ready is refused with
    `ERR_ORDER_NOT_READY`; a ready but unpaid order with `ERR_ORDER_NOT_PAID`)."

    Design: Corner/state_machines/fulfill_unpaid_order_returns_not_paid
    """
    product = create_active_product(msrp_cents=1000, category="PLUSH")
    store = create_store()
    create_inventory(product["id"], store["id"], on_hand_qty=10)
    customer = create_customer()
    cid = customer["id"]
    order = create_open_order(cid, store["id"])
    add_line(order["id"], cid, product["id"], qty=1, recipient_age_months=60)
    get_success_data(api.submit_order(order["id"], make_customer_headers(cid)))
    get_success_data(api.mark_ready_order(order["id"], ASSOCIATE))

    validate_error(
        api.fulfill_order(order["id"], ASSOCIATE),
        ApiErrorId.ERR_ORDER_NOT_PAID.value,
    )


def test_pay_cancelled_layaway_rejected(api):
    """PRD §3.9: "a payment against a plan not in `ACTIVE` state is refused with
    `ERR_LAYAWAY_NOT_ACTIVE`."

    Design: Corner/state_machines/pay_cancelled_layaway_returns_not_active
    """
    customer = create_customer()
    lay = get_success_data(api.create_layaway(
        {"customer_id": customer["id"], "total_cents": 9000, "installment_count": 3}, ASSOCIATE))
    get_success_data(api.cancel_layaway(lay["id"], ASSOCIATE))

    validate_error(
        api.pay_layaway(lay["id"], {"amount_cents": 3000}, ASSOCIATE),
        ApiErrorId.ERR_LAYAWAY_NOT_ACTIVE.value,
    )


def test_convert_quoted_special_order_rejected(api):
    """PRD §3.10: "Attempting to convert an order not in `APPROVED` yields
    `ERR_SPECIAL_ORDER_NOT_APPROVED`."

    Design: Corner/state_machines/convert_unapproved_special_order_returns_not_approved
    """
    from test_helpers import create_quoted_special_order
    product = create_active_product(msrp_cents=5000, is_exclusive=True, category="ACTION_FIGURE")
    customer = create_customer()
    so = create_quoted_special_order(customer["id"], product["id"], requested_qty=1)

    validate_error(
        api.convert_special_order(so["id"], ASSOCIATE),
        ApiErrorId.ERR_SPECIAL_ORDER_NOT_APPROVED.value,
    )


def test_duplicate_event_registration_rejected(api):
    """PRD §3.12: "or if the same customer is already registered, with
    `ERR_DUPLICATE_EVENT_REGISTRATION`."

    Design: Corner/state_machines/duplicate_event_registration_rejected
    """
    from test_helpers import create_event
    product = create_active_product(msrp_cents=1000, category="PLUSH")
    store = create_store()
    event = create_event(store["id"], product["id"], capacity=5)
    customer = create_customer()
    cid = customer["id"]
    get_success_data(api.register_event(event["id"], {"customer_id": cid}, make_customer_headers(cid)))

    validate_error(
        api.register_event(event["id"], {"customer_id": cid}, make_customer_headers(cid)),
        ApiErrorId.ERR_DUPLICATE_EVENT_REGISTRATION.value,
    )


# --- Validations: existence / fiscal / temporal / referential ---
def test_get_missing_order_returns_not_found(api):
    """PRD §2.8: "each identifier segment is checked for existence in order, and the first
    unresolved identifier produces the corresponding not-found error (for example
    `ERR_PRODUCT_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_REGISTRY_NOT_FOUND`, and their
    siblings listed in §5)."

    Design: Corner/validations/get_missing_order_returns_not_found
    """
    validate_error(
        api.get_order("00000000-0000-4000-8000-000000000abc", ANY),
        ApiErrorId.ERR_ORDER_NOT_FOUND.value,
    )


def test_layaway_overpayment_rejected(api):
    """PRD §3.9: "A payment exceeding `remaining_cents` is rejected with
    `ERR_LAYAWAY_OVERPAYMENT`."

    Design: Corner/validations/layaway_overpayment_rejected
    """
    customer = create_customer()
    lay = get_success_data(api.create_layaway(
        {"customer_id": customer["id"], "total_cents": 9000, "installment_count": 3}, ASSOCIATE))

    validate_error(
        api.pay_layaway(lay["id"], {"amount_cents": 10000}, ASSOCIATE),
        ApiErrorId.ERR_LAYAWAY_OVERPAYMENT.value,
    )


def test_return_window_expired_rejected(api):
    """PRD §3.13: "the approval to fall within 30 days of the order's fulfillment — the
    current clock must be at or before the fulfillment instant plus 30 days, inclusive; a
    later approval is refused with `ERR_RETURN_WINDOW_EXPIRED`."

    Design: Corner/validations/return_window_expired_rejected
    """
    product = create_active_product(msrp_cents=1000, category="PLUSH")
    store = create_store()
    create_inventory(product["id"], store["id"], on_hand_qty=10)
    customer = create_customer()
    order, line = create_fulfilled_order(customer["id"], store["id"], product["id"], qty=2)
    ret = create_requested_return(order["id"], line["id"], qty=2)
    # Fulfillment at default clock 2026-03-01; advance 40+ days.
    get_success_data(api.set_clock({"to_iso8601": "2026-04-11T00:00:00Z"}, ADMIN))

    validate_error(
        api.approve_return(ret["id"], {"decision": "APPROVE"}, MANAGER),
        ApiErrorId.ERR_RETURN_WINDOW_EXPIRED.value,
    )


def test_order_overpayment_rejected(api):
    """PRD §3.7: "A payment that would push `amount_paid_cents` beyond `total_cents` — that
    is, beyond the remaining balance — is rejected with `ERR_OVERPAYMENT`."

    Design: Corner/validations/order_overpayment_rejected
    """
    product = create_active_product(msrp_cents=1000, category="PLUSH")
    store = create_store()
    create_inventory(product["id"], store["id"], on_hand_qty=10)
    customer = create_customer()
    cid = customer["id"]
    order = create_open_order(cid, store["id"], fulfillment_type="SHIP_FROM_STORE")
    add_line(order["id"], cid, product["id"], qty=1, recipient_age_months=60)
    get_success_data(api.submit_order(order["id"], make_customer_headers(cid)))

    validate_error(
        api.pay_order(order["id"], {"amount_cents": 2000}, ASSOCIATE),
        ApiErrorId.ERR_OVERPAYMENT.value,
    )


def test_insufficient_inventory_on_add_line(api):
    """PRD §3.5: "If the inventory item does not have `available_qty` of at least `qty`, the
    add is rejected with `ERR_INSUFFICIENT_INVENTORY`."

    Design: Corner/validations/insufficient_inventory_on_add_line
    """
    product = create_active_product(msrp_cents=1000, category="PLUSH")
    store = create_store()
    create_inventory(product["id"], store["id"], on_hand_qty=2)
    customer = create_customer()
    cid = customer["id"]
    order = create_open_order(cid, store["id"])

    validate_error(
        api.add_order_line(order["id"], {"product_id": product["id"], "qty": 5, "recipient_age_months": 60},
                           make_customer_headers(cid)),
        ApiErrorId.ERR_INSUFFICIENT_INVENTORY.value,
    )


def test_add_item_to_closed_registry_rejected(api):
    """PRD §3.12: "Registry items may be added only while the registry is `ACTIVE`, else
    `ERR_REGISTRY_NOT_ACTIVE`."

    Design: Corner/validations/add_registry_item_to_closed_registry_rejected
    """
    product = create_active_product(msrp_cents=1000, category="PLUSH")
    customer = create_customer()
    cid = customer["id"]
    registry = create_registry(cid, registry_type="WISHLIST")
    get_success_data(api.close_registry(registry["id"], make_customer_headers(cid)))

    validate_error(
        api.add_registry_item(registry["id"], {"product_id": product["id"], "desired_qty": 1},
                             make_customer_headers(cid)),
        ApiErrorId.ERR_REGISTRY_NOT_ACTIVE.value,
    )


# --- Endpoints ---
def test_convert_without_allocation_rejected(api):
    """PRD §3.10: "conversion requires that an `ACTIVE` allocation for the product and
    store exists (otherwise `ERR_NO_ALLOCATION`) ..."

    Design: Corner/endpoints/convert_without_allocation_returns_no_allocation
    """
    from test_helpers import create_approved_special_order
    product = create_active_product(msrp_cents=5000, is_exclusive=True, category="ACTION_FIGURE")
    customer = create_customer()
    so = create_approved_special_order(customer["id"], product["id"], requested_qty=1)

    validate_error(
        api.convert_special_order(so["id"], ASSOCIATE),
        ApiErrorId.ERR_NO_ALLOCATION.value,
    )


def test_inventory_filter_by_product_id(api):
    """PRD §2.8: "List endpoints support reverse-reachability filtering by their natural
    foreign keys — for instance inventory and allocations by `product_id` and `store_id`
    ..."

    Design: Corner/endpoints/fk_reverse_reachability_inventory_by_product
    """
    product = create_active_product(msrp_cents=1000, category="PLUSH")
    store = create_store()
    inv = create_inventory(product["id"], store["id"], on_hand_qty=4)

    data, meta = validate_paginated(api.list_inventory(ANY, params={"product_id": product["id"]}))
    assert len(data) == 1
    assert data[0]["id"] == inv["id"]


# --- RBAC ---
def test_customer_cannot_create_product(api):
    """PRD §2.1: "When the headers are well-formed but the role is not permitted to perform
    the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/customer_cannot_create_product
    """
    customer = create_customer()
    validate_error(
        api.create_product(
            {"sku": "RB-1", "name": "X", "category": "PLUSH", "age_grade_min_months": 0,
             "safety_labels": ["NONE"], "msrp_cents": 1000}, make_customer_headers(customer["id"])),
        ApiErrorId.ERR_FORBIDDEN_ROLE.value,
    )


def test_store_associate_cannot_approve_return(api):
    """PRD §2.1: "When the headers are well-formed but the role is not permitted to perform
    the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`."
    PRD §3.13: "A `StoreManager` then approves or rejects it by supplying a `decision` of
    either APPROVE or REJECT."

    Design: Corner/rbac/store_associate_cannot_approve_return
    """
    product = create_active_product(msrp_cents=1000, category="PLUSH")
    store = create_store()
    create_inventory(product["id"], store["id"], on_hand_qty=10)
    customer = create_customer()
    order, line = create_fulfilled_order(customer["id"], store["id"], product["id"], qty=1)
    ret = create_requested_return(order["id"], line["id"], qty=1)

    validate_error(
        api.approve_return(ret["id"], {"decision": "APPROVE"}, ASSOCIATE),
        ApiErrorId.ERR_FORBIDDEN_ROLE.value,
    )


def test_customer_cannot_act_on_other_customers_order(api):
    """PRD §2.1: "Ownership is enforced on every resource that references a customer — an
    order, layaway, registry, or event registration whose `customer_id` does not equal the
    requesting `Customer`'s `X-User-ID` is rejected with `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/customer_cannot_act_on_other_customers_order
    """
    product = create_active_product(msrp_cents=1000, category="PLUSH")
    store = create_store()
    create_inventory(product["id"], store["id"], on_hand_qty=10)
    c1 = create_customer()
    c2 = create_customer()
    order = create_open_order(c1["id"], store["id"])
    add_line(order["id"], c1["id"], product["id"], qty=1, recipient_age_months=60)

    validate_error(
        api.submit_order(order["id"], make_customer_headers(c2["id"])),
        ApiErrorId.ERR_FORBIDDEN_ROLE.value,
    )
