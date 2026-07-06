"""Cross-entity state dependencies and boundary-precision checks."""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    TEST_USERS, make_customer_headers,
    create_active_product, create_store, create_inventory, create_customer,
    create_allocation, create_open_order, create_approved_special_order,
    create_event,
)

ADMIN = TEST_USERS["catalog_admin_headers"]
MANAGER = TEST_USERS["store_manager_headers"]
ASSOCIATE = TEST_USERS["store_associate_headers"]
ANY = TEST_USERS["any_headers"]


def test_convert_blocked_when_allocation_too_small(api):
    """PRD §3.10: "conversion requires that an `ACTIVE` allocation for the product and
    store exists (otherwise `ERR_NO_ALLOCATION`) and that its `available_alloc_qty` is at
    least `requested_qty` (otherwise `ERR_INSUFFICIENT_ALLOCATION`)."

    Design: Difficulty/cross_entity_state_dependency/special_order_convert_blocked_by_allocation_availability
    """
    product = create_active_product(msrp_cents=5000, is_exclusive=True, category="ACTION_FIGURE")
    store = create_store()
    create_allocation(product["id"], store["id"], allocated_qty=3)
    customer = create_customer()
    so = create_approved_special_order(customer["id"], product["id"], requested_qty=5)

    validate_error(
        api.convert_special_order(so["id"], ASSOCIATE),
        ApiErrorId.ERR_INSUFFICIENT_ALLOCATION.value,
    )


def test_convert_succeeds_when_allocation_exactly_meets_request(api):
    """PRD §3.10: "conversion requires that an `ACTIVE` allocation for the product and
    store exists (otherwise `ERR_NO_ALLOCATION`) and that its `available_alloc_qty` is at
    least `requested_qty` (otherwise `ERR_INSUFFICIENT_ALLOCATION`)."

    Design: Difficulty/cross_entity_state_dependency/special_order_convert_blocked_by_allocation_availability
    """
    product = create_active_product(msrp_cents=5000, is_exclusive=True, category="ACTION_FIGURE")
    store = create_store()
    create_allocation(product["id"], store["id"], allocated_qty=5)
    customer = create_customer()
    so = create_approved_special_order(customer["id"], product["id"], requested_qty=5)

    validate_success(api.convert_special_order(so["id"], ASSOCIATE))
    fetched = validate_success(api.get_special_order(so["id"], ANY))
    assert fetched["status"] == "CONVERTED"


def test_age_grade_gate_passes_at_exact_minimum(api):
    """PRD §3.5: "The age-grade gate passes only when `recipient_age_months` is greater
    than or equal to the product's `age_grade_min_months` — the boundary is inclusive, so
    an exact match passes — and otherwise fails with `ERR_AGE_GRADE_VIOLATION`."

    Design: Difficulty/boundary_precision_check/age_grade_inclusive_boundary_passes_at_equal
    """
    product = create_active_product(msrp_cents=1000, category="PLUSH", age_grade_min_months=36)
    store = create_store()
    create_inventory(product["id"], store["id"], on_hand_qty=10)
    customer = create_customer()
    cid = customer["id"]
    order = create_open_order(cid, store["id"])

    line = validate_success(
        api.add_order_line(order["id"], {"product_id": product["id"], "qty": 1, "recipient_age_months": 36},
                           make_customer_headers(cid)),
        expected_status=201,
    )
    assert line["status"] == "ACTIVE"


def test_age_grade_gate_fails_one_below_minimum(api):
    """PRD §3.5: "The age-grade gate passes only when `recipient_age_months` is greater
    than or equal to the product's `age_grade_min_months` — the boundary is inclusive, so
    an exact match passes — and otherwise fails with `ERR_AGE_GRADE_VIOLATION`."

    Design: Difficulty/boundary_precision_check/age_grade_inclusive_boundary_passes_at_equal
    """
    product = create_active_product(msrp_cents=1000, category="PLUSH", age_grade_min_months=36)
    store = create_store()
    create_inventory(product["id"], store["id"], on_hand_qty=10)
    customer = create_customer()
    cid = customer["id"]
    order = create_open_order(cid, store["id"])

    validate_error(
        api.add_order_line(order["id"], {"product_id": product["id"], "qty": 1, "recipient_age_months": 35},
                           make_customer_headers(cid)),
        ApiErrorId.ERR_AGE_GRADE_VIOLATION.value,
    )


def test_event_full_at_exact_capacity(api):
    """PRD §3.12: "Registration is refused if the event is full — `registered_count` has
    reached `capacity` — with `ERR_EVENT_FULL`, or if the same customer is already
    registered, with `ERR_DUPLICATE_EVENT_REGISTRATION`."

    Design: Difficulty/boundary_precision_check/event_capacity_full_at_exact_count
    """
    product = create_active_product(msrp_cents=1000, category="PLUSH")
    store = create_store()
    event = create_event(store["id"], product["id"], capacity=1)
    c1 = create_customer()
    c2 = create_customer()

    validate_success(api.register_event(event["id"], {"customer_id": c1["id"]},
                                        make_customer_headers(c1["id"])))
    validate_error(
        api.register_event(event["id"], {"customer_id": c2["id"]}, make_customer_headers(c2["id"])),
        ApiErrorId.ERR_EVENT_FULL.value,
    )


def test_register_succeeds_below_capacity(api):
    """PRD §3.12: "A `Customer` registers for a scheduled event by supplying their
    `customer_id`; registration appends the id to `registered_customer_ids` and increments
    `registered_count`."

    Design: Difficulty/boundary_precision_check/event_capacity_full_at_exact_count
    """
    product = create_active_product(msrp_cents=1000, category="PLUSH")
    store = create_store()
    event = create_event(store["id"], product["id"], capacity=1)
    c1 = create_customer()

    data = validate_success(api.register_event(event["id"], {"customer_id": c1["id"]},
                                              make_customer_headers(c1["id"])))
    assert data["registered_count"] == 1
