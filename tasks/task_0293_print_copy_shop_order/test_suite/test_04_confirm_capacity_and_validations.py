"""Confirm-time preconditions: capacity, lockability, fulfillment, and business validations."""
import pytest
from test_helpers import (
    api_client, get_success_data,
    validate_success, validate_error,
    create_shop, create_customer, create_product, create_finishing_option,
    create_order, add_line, upload_and_pass_preflight, add_pickup_fulfillment,
    read_order_version, confirm_order, pin_clock,
    setup_confirmable_copies_order, setup_banner_line, book_press,
    setup_proof_line, submit_proof,
    TEST_USERS, make_customer_headers, ApiErrorId,
)

STAFF = TEST_USERS["shop_staff_headers"]
OPERATOR = TEST_USERS["production_operator_headers"]


# ─── Difficulty: boundary_precision (daily capacity) ─────────────────────────
def test_capacity_exact_fill_allowed(api):
    """PRD §3.6: "The boundary is strict-greater: a day filled exactly to capacity is
    allowed, and only the unit that would push it past capacity triggers
    `ERR_CAPACITY_EXCEEDED` (HTTP 409)."

    Design: Difficulty/boundary_precision_check/daily_capacity_exact_fill_allowed_one_over_rejected
    """
    ctx = setup_confirmable_copies_order(
        shop_overrides={"name": "Cap10 Shop", "daily_unit_capacity": 10}, quantity=10)
    confirmed = validate_success(
        confirm_order(ctx["order"]["id"], ctx["customer"]["id"], ctx["version"]), 200)
    assert confirmed["production_status"] == "CONFIRMED", "held 0 + 10 == capacity 10 is allowed"


def test_capacity_one_over_rejected(api):
    """PRD §3.6: "sum the `units` of all `HELD` reservations already standing for that shop
    on that production date, add the line's requested production units, and reject if that
    running total would exceed the shop's `daily_unit_capacity`."

    Design: Difficulty/boundary_precision_check/daily_capacity_exact_fill_allowed_one_over_rejected
    """
    ctx = setup_confirmable_copies_order(
        shop_overrides={"name": "Cap10 Shop 2", "daily_unit_capacity": 10}, quantity=11)
    res = confirm_order(ctx["order"]["id"], ctx["customer"]["id"], ctx["version"])
    validate_error(res, ApiErrorId.ERR_CAPACITY_EXCEEDED, expected_status=409)


# ─── Difficulty: resource_temporal_overlap (daily capacity aggregate) ────────
def _confirm_units_order(shop_id, email, prod_id, quantity):
    """Helper: build + confirm an order consuming `quantity` units on the standard date."""
    cust = create_customer(shop_id, email=email)
    order = create_order(shop_id, cust["id"])
    line = add_line(order["id"], prod_id, quantity, cust["id"])
    upload_and_pass_preflight(line["id"], cust["id"])
    add_pickup_fulfillment(order["id"], cust["id"])
    v = read_order_version(order["id"], cust["id"])
    return cust, order, confirm_order(order["id"], cust["id"], v)


def test_capacity_aggregate_overlap_second_order_rejected(api):
    """PRD §3.6: "Before each reservation is admitted, the day's load is checked: sum the
    `units` of all `HELD` reservations already standing for that shop on that production
    date, add the line's requested production units, and reject if that running total would
    exceed the shop's `daily_unit_capacity`."

    Design: Difficulty/resource_temporal_overlap/daily_capacity_aggregate_overlap_on_production_date
    """
    pin_clock("2026-06-01T09:00:00Z")
    shop = create_shop(name="Agg Shop", daily_unit_capacity=10)
    prod = create_product(shop["id"], name="BW Copy", category="COPIES",
                          base_unit_price_cents=500, unit_size=1,
                          requires_proof=False, requires_press=False)
    _confirm_units_order(shop["id"], "p1@x.com", prod["id"], 6)
    cust2, order2, res = _confirm_units_order(shop["id"], "p2@x.com", prod["id"], 5)
    validate_error(res, ApiErrorId.ERR_CAPACITY_EXCEEDED, expected_status=409)


def test_capacity_aggregate_second_order_fits_exactly(api):
    """PRD §3.6: "The boundary is strict-greater: a day filled exactly to capacity is
    allowed, and only the unit that would push it past capacity triggers
    `ERR_CAPACITY_EXCEEDED` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/daily_capacity_aggregate_overlap_on_production_date
    """
    pin_clock("2026-06-01T09:00:00Z")
    shop = create_shop(name="Agg Shop 2", daily_unit_capacity=10)
    prod = create_product(shop["id"], name="BW Copy", category="COPIES",
                          base_unit_price_cents=500, unit_size=1,
                          requires_proof=False, requires_press=False)
    _confirm_units_order(shop["id"], "q1@x.com", prod["id"], 6)
    cust2, order2, res = _confirm_units_order(shop["id"], "q2@x.com", prod["id"], 4)
    confirmed = validate_success(res, 200)
    assert confirmed["production_status"] == "CONFIRMED", "6 + 4 == capacity 10 is allowed"


# ─── Difficulty: priority_pair (lockability beats capacity) ──────────────────
def test_lockability_beats_capacity_on_confirm(api):
    """PRD §3.9: "Only past that point do the operation-specific business checks run ...
    line-lockable (`ERR_LINE_NOT_LOCKABLE`), fulfillment-exists (`ERR_FULFILLMENT_REQUIRED`),
    fulfillment-fields (`ERR_FULFILLMENT_FIELDS_INVALID`), press overlap
    (`ERR_PRESS_DOUBLE_BOOKED`), booking interval (`ERR_BOOKING_INTERVAL_INVALID`),
    capacity (`ERR_CAPACITY_EXCEEDED`), and payment amount (`ERR_PAYMENT_AMOUNT_MISMATCH`)".

    Design: Difficulty/priority_pair_validation_conflict/lockability_beats_capacity_on_confirm
    """
    pin_clock("2026-06-01T09:00:00Z")
    shop = create_shop(name="Cap1 Shop", daily_unit_capacity=1)
    prod = create_product(shop["id"], name="BW Copy", category="COPIES",
                          base_unit_price_cents=500, unit_size=1,
                          requires_proof=False, requires_press=False)
    # Customer 1 fills the single unit of daily capacity.
    _confirm_units_order(shop["id"], "j1@x.com", prod["id"], 1)
    # Customer 2's line stays OPEN (no preflight) but a fulfillment exists.
    cust2 = create_customer(shop["id"], email="j2@x.com")
    order2 = create_order(shop["id"], cust2["id"])
    add_line(order2["id"], prod["id"], 1, cust2["id"])
    add_pickup_fulfillment(order2["id"], cust2["id"])
    v = read_order_version(order2["id"], cust2["id"])
    res = confirm_order(order2["id"], cust2["id"], v)
    validate_error(res, ApiErrorId.ERR_LINE_NOT_LOCKABLE, expected_status=409)


def test_confirm_open_line_not_lockable(api):
    """PRD §3.6: "Every line must be price-lockable — meaning a line whose product requires
    a proof must be `PROOF_APPROVED`, and a line whose product does not require a proof must
    be `PREFLIGHT_OK` ... if any line falls short, the confirm is rejected with
    `ERR_LINE_NOT_LOCKABLE` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/lockability_beats_capacity_on_confirm
    """
    pin_clock("2026-06-01T09:00:00Z")
    shop = create_shop(name="Lockable Shop", daily_unit_capacity=100)
    cust = create_customer(shop["id"], email="lk@x.com")
    prod = create_product(shop["id"], name="BW Copy", category="COPIES",
                          base_unit_price_cents=500, requires_proof=False, requires_press=False)
    order = create_order(shop["id"], cust["id"])
    add_line(order["id"], prod["id"], 5, cust["id"])  # stays OPEN, no preflight
    add_pickup_fulfillment(order["id"], cust["id"])
    v = read_order_version(order["id"], cust["id"])
    res = confirm_order(order["id"], cust["id"], v)
    validate_error(res, ApiErrorId.ERR_LINE_NOT_LOCKABLE, expected_status=409)


# ─── Difficulty: cross_entity_state_dependency (press lockability) ───────────
def test_confirm_requires_press_booking_for_requires_press_line(api):
    """PRD §3.6: "additionally every line whose product requires a press must already hold
    a confirmed press booking; if any line falls short, the confirm is rejected with
    `ERR_LINE_NOT_LOCKABLE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/line_pricelock_requires_press_booking_for_requires_press_product
    """
    ctx = setup_banner_line(shop_overrides={"name": "Press Dep Shop"}, with_press=False)
    cust = ctx["customer"]
    add_pickup_fulfillment(ctx["order"]["id"], cust["id"])
    v = read_order_version(ctx["order"]["id"], cust["id"])
    res = confirm_order(ctx["order"]["id"], cust["id"], v)
    validate_error(res, ApiErrorId.ERR_LINE_NOT_LOCKABLE, expected_status=409)


def test_confirm_succeeds_when_press_booking_present(api):
    """PRD §3.6: "every line whose product requires a press must already hold a confirmed
    press booking". PRD §3.5: "A successful booking is `CONFIRMED`."

    Design: Difficulty/cross_entity_state_dependency/line_pricelock_requires_press_booking_for_requires_press_product
    """
    ctx = setup_banner_line(shop_overrides={"name": "Press Dep Shop 2"}, with_press=True,
                            cleanup_buffer_minutes=0)
    cust = ctx["customer"]
    get_success_data(book_press(ctx["press"]["id"], ctx["line"]["id"],
                                "2026-06-02T10:00:00Z", "2026-06-02T11:00:00Z"))
    add_pickup_fulfillment(ctx["order"]["id"], cust["id"])
    v = read_order_version(ctx["order"]["id"], cust["id"])
    confirmed = validate_success(confirm_order(ctx["order"]["id"], cust["id"], v), 200)
    assert confirmed["production_status"] == "CONFIRMED"


# ─── Business validations ────────────────────────────────────────────────────
def test_pay_wrong_amount_returns_payment_mismatch(api):
    """PRD §3.7: "The owning customer then pays, supplying an `amount_cents` that must equal
    the order's `total_cents` exactly; a mismatch is rejected with
    `ERR_PAYMENT_AMOUNT_MISMATCH` (HTTP 422)."

    Design: Corner/validations/pay_wrong_amount_returns_payment_mismatch
    """
    ctx = setup_confirmable_copies_order(shop_overrides={"name": "S20"}, quantity=10)
    cust = ctx["customer"]
    cust_headers = make_customer_headers(cust["id"])
    order_id = ctx["order"]["id"]
    confirmed = validate_success(confirm_order(order_id, cust["id"], ctx["version"]), 200)
    total = confirmed["total_cents"]
    get_success_data(api.invoice_order(order_id, STAFF))
    res = api.pay_order(order_id, {"amount_cents": total - 1000}, cust_headers)
    validate_error(res, ApiErrorId.ERR_PAYMENT_AMOUNT_MISMATCH, expected_status=422)
    still = get_success_data(api.get_order(order_id, cust_headers))
    assert still["payment_status"] == "INVOICED", "mismatch leaves payment_status unchanged"


def test_finishing_code_foreign_to_product_rejected(api):
    """PRD §3.2: "Every entry in `finishing_codes` must name a finishing option belonging to
    that line's `product_id`; a stray code is rejected with `ERR_FINISHING_NOT_FOR_PRODUCT`
    (HTTP 422)."

    Design: Corner/validations/finishing_code_foreign_to_product_rejected
    """
    shop = create_shop(name="S21")
    cust = create_customer(shop["id"], email="s21@x.com")
    prod_x = create_product(shop["id"], name="X", category="COPIES",
                            base_unit_price_cents=500, requires_proof=False, requires_press=False)
    prod_y = create_product(shop["id"], name="Y", category="COPIES",
                            base_unit_price_cents=500, requires_proof=False, requires_press=False)
    create_finishing_option(prod_x["id"], "LAMINATE", "FLAT", 200)
    order = create_order(shop["id"], cust["id"])
    res = api.create_order_line(
        {"order_id": order["id"], "product_id": prod_y["id"], "quantity": 10,
         "finishing_codes": ["LAMINATE"]}, make_customer_headers(cust["id"]))
    validate_error(res, ApiErrorId.ERR_FINISHING_NOT_FOR_PRODUCT, expected_status=422)


def test_add_inactive_product_to_line_rejected(api):
    """PRD §3.2: "The product must be active when it is added; adding an inactive product is
    rejected with `ERR_PRODUCT_INACTIVE` (HTTP 409)."

    Design: Corner/validations/add_inactive_product_to_line_rejected
    """
    shop = create_shop(name="S22")
    cust = create_customer(shop["id"], email="s22@x.com")
    prod = create_product(shop["id"], name="P", category="COPIES", base_unit_price_cents=500,
                          active=True, requires_proof=False, requires_press=False)
    get_success_data(api.patch_product(prod["id"], {"active": False}, STAFF))
    order = create_order(shop["id"], cust["id"])
    res = api.create_order_line(
        {"order_id": order["id"], "product_id": prod["id"], "quantity": 10},
        make_customer_headers(cust["id"]))
    validate_error(res, ApiErrorId.ERR_PRODUCT_INACTIVE, expected_status=409)


def test_confirm_without_fulfillment_rejected(api):
    """PRD §3.6: "A fulfillment must already exist for the order, or the confirm is rejected
    with `ERR_FULFILLMENT_REQUIRED` (HTTP 409)."

    Design: Corner/validations/confirm_without_fulfillment_rejected
    """
    pin_clock("2026-06-01T09:00:00Z")
    shop = create_shop(name="S23")
    cust = create_customer(shop["id"], email="s23@x.com")
    prod = create_product(shop["id"], name="P", category="COPIES",
                          base_unit_price_cents=500, requires_proof=False, requires_press=False)
    order = create_order(shop["id"], cust["id"])
    line = add_line(order["id"], prod["id"], 10, cust["id"])
    upload_and_pass_preflight(line["id"], cust["id"])
    v = read_order_version(order["id"], cust["id"])
    res = confirm_order(order["id"], cust["id"], v)
    validate_error(res, ApiErrorId.ERR_FULFILLMENT_REQUIRED, expected_status=409)


def test_ship_fulfillment_missing_address_rejected(api):
    """PRD §3.7: "A `SHIP` fulfillment requires a `ship_address` and a `ship_fee_cents`
    strictly greater than 0 ... A fulfillment that violates these field rules — a ship with
    no address or no fee, or a pickup carrying an address or a non-zero fee — is rejected
    with `ERR_FULFILLMENT_FIELDS_INVALID` (HTTP 422)."

    Design: Corner/validations/ship_fulfillment_missing_address_rejected
    """
    shop = create_shop(name="S24")
    cust = create_customer(shop["id"], email="s24@x.com")
    order = create_order(shop["id"], cust["id"])
    res = api.create_fulfillment(
        {"order_id": order["id"], "method": "SHIP", "ship_fee_cents": 1500},
        make_customer_headers(cust["id"]))
    validate_error(res, ApiErrorId.ERR_FULFILLMENT_FIELDS_INVALID, expected_status=422)


def test_request_changes_without_note_rejected(api):
    """PRD §3.4: "Requesting changes requires a `change_note` describing what to fix; a
    request-changes call with no `change_note` is rejected with `ERR_CHANGE_NOTE_REQUIRED`
    (HTTP 422)."

    Design: Corner/validations/request_changes_without_note_rejected
    """
    ctx = setup_proof_line(shop_overrides={"name": "S26"})
    cust = ctx["customer"]
    proof = submit_proof(ctx["line"]["id"])
    res = api.request_changes(proof["id"], {}, make_customer_headers(cust["id"]))
    validate_error(res, ApiErrorId.ERR_CHANGE_NOTE_REQUIRED, expected_status=422)
