"""CRUD, input validation, not-found, RBAC, and simple loyalty corners.

Every test translates exactly one non-stub instance from the corner-design index
(queue B), subject to the PRD-first coverage + unique-derivability filter.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    create_customer_payload, create_product_payload,
    assert_customer, assert_product, assert_license_type,
    new_customer, new_license_type,
    make_customer_headers,
    TEST_USERS,
)

CLERK = TEST_USERS["clerk_headers"]
MANAGER = TEST_USERS["manager_headers"]
NONEXISTENT = "00000000-0000-4000-8000-000000000000"


def test_create_customer_returns_201_with_default_loyalty(api, clerk_headers):
    """PRD §3.1: "A freshly registered account begins `ACTIVE`, with `loyalty_points_balance`
    and `lifetime_points_earned` at zero and `loyalty_tier` at `BRONZE`."

    Design: Corner/entities/create_customer_returns_201_with_defaults
    """
    res = api.create_customer(create_customer_payload(full_name="New Cust"), clerk_headers)
    cust = validate_success(res, 201)
    assert_customer(cust)
    assert cust["loyalty_points_balance"] == 0
    assert cust["lifetime_points_earned"] == 0
    assert cust["loyalty_tier"] == "BRONZE"
    assert cust["status"] == "ACTIVE"


def test_get_customer_nonexistent_returns_not_found(api, clerk_headers):
    """PRD §2.9: "the first unresolved reference yields the resource-specific not-found
    error (HTTP 404) — ERR_CUSTOMER_NOT_FOUND, ERR_PRODUCT_NOT_FOUND, ..."

    Design: Corner/entities/get_customer_not_found_returns_404
    """
    res = api.get_customer(NONEXISTENT, clerk_headers)
    validate_error(res, "ERR_CUSTOMER_NOT_FOUND", 404)


def test_create_customer_missing_required_field_rejected(api, clerk_headers):
    """PRD §2.9: "structural validation of the body: required fields present, enum values
    in range, constrained integers non-negative, and any end_at strictly after its start_at;
    a malformed body yields ERR_VALIDATION (400)."

    Design: Corner/entities/create_customer_missing_required_field_returns_validation
    """
    payload = create_customer_payload()
    del payload["date_of_birth"]
    res = api.create_customer(payload, clerk_headers)
    validate_error(res, "ERR_VALIDATION", 400)


def test_product_created_active_with_version_one(api, manager_headers):
    """PRD §2.5: "an integer version that starts at 1 and increments by one on every mutation."
    PRD §3.2: "A product begins ACTIVE and may later be DISCONTINUED."

    Design: Corner/entities/product_system_fields_ignored_on_create
    """
    res = api.create_product(
        create_product_payload(sku="ROD-1", name="Ugly Stik", category="ROD",
                               unit_price_cents=5999, stock_qty=10),
        manager_headers,
    )
    prod = validate_success(res, 201)
    assert_product(prod)
    assert prod["status"] == "ACTIVE"
    assert prod["version"] == 1


def test_license_type_immutable_carries_no_version(api, manager_headers, clerk_headers):
    """PRD §2.5: "Two entities are the exception: `LicenseType` carries only `id` and
    `created_at` — it has no `updated_at` and no `version`."

    Design: Corner/entities/license_type_creation_and_fetch_immutable_no_version
    """
    lt = get_success_data(api.create_license_type(
        {"code": "CA-IMM", "state_code": "CA", "license_class": "NONRESIDENT",
         "base_price_cents": 8000, "min_age": 0, "season_start_date": "2026-01-01",
         "season_end_date": "2026-12-31", "validity_days": 365}, manager_headers))
    res = api.get_license_type(lt["id"], clerk_headers)
    fetched = validate_success(res, 200)
    assert_license_type(fetched)
    assert fetched["base_price_cents"] == 8000
    assert "version" not in fetched
    assert "updated_at" not in fetched


def test_booking_against_nonexistent_charter_not_found(api, clerk_headers):
    """PRD §2.9: "the first unresolved reference yields the resource-specific not-found
    error (HTTP 404) — ... ERR_CHARTER_NOT_FOUND ..."

    Design: Corner/errors/charter_not_found_on_booking
    """
    cust = new_customer()
    res = api.create_booking(
        {"charter_id": "00000000-0000-4000-8000-0000000000ab",
         "customer_id": cust["id"], "seats": 1}, clerk_headers)
    validate_error(res, "ERR_CHARTER_NOT_FOUND", 404)


def test_transition_nonexistent_service_order_not_found(api, clerk_headers):
    """PRD §2.9: "the first unresolved reference yields the resource-specific not-found
    error (HTTP 404) — ... ERR_SERVICE_ORDER_NOT_FOUND ..."

    Design: Corner/errors/service_order_not_found_on_transition
    """
    res = api.transition_service_order(
        "00000000-0000-4000-8000-0000000000cd", {"to_status": "DIAGNOSED"}, clerk_headers)
    validate_error(res, "ERR_SERVICE_ORDER_NOT_FOUND", 404)


def test_clerk_cannot_suspend_customer(api, clerk_headers):
    """PRD §2.1: "the manager-exclusive powers (customer suspension and loyalty adjustment,
    guide creation and suspension, and license-type configuration)."
    PRD §3.1: "A customer's account status moves between ACTIVE and SUSPENDED, and only a
    manager may move it, supplying the desired status."

    Design: Corner/rbac/clerk_cannot_suspend_customer
    """
    cust = new_customer()
    res = api.set_customer_status(cust["id"], {"status": "SUSPENDED"}, clerk_headers)
    validate_error(res, "ERR_UNAUTHORIZED", 403)


def test_customer_cannot_create_license_type(api):
    """PRD §3.3: "Only a manager configures a license product, called a license type."
    PRD §2.1: "When a recognized caller attempts an operation their role is not permitted
    to perform ... the request is rejected with ERR_UNAUTHORIZED (HTTP 403)."

    Design: Corner/rbac/customer_cannot_create_license_type
    """
    cust = new_customer()
    res = api.create_license_type(
        {"code": "X", "state_code": "CA", "license_class": "RESIDENT",
         "base_price_cents": 1000, "min_age": 0, "season_start_date": "2026-01-01",
         "season_end_date": "2026-12-31", "validity_days": 365},
        make_customer_headers(cust["id"]))
    validate_error(res, "ERR_UNAUTHORIZED", 403)


def test_loyalty_deduction_below_zero_rejected(api, manager_headers):
    """PRD §3.1: "A deduction may not drive the spendable balance below zero — if it would,
    the adjustment is rejected with ERR_INSUFFICIENT_POINTS (HTTP 402)."

    Design: Corner/validations/loyalty_adjustment_below_zero_rejected
    """
    cust = new_customer()
    res = api.adjust_loyalty(cust["id"], {"points_delta": -100, "reason": "overdraw"}, manager_headers)
    validate_error(res, "ERR_INSUFFICIENT_POINTS", 402)
    refreshed = get_success_data(api.get_customer(cust["id"], manager_headers))
    assert refreshed["loyalty_points_balance"] == 0


def test_loyalty_tier_exactly_500_is_silver(api, manager_headers):
    """PRD §2.7: "a customer below 2,000 but with at least 500 lifetime points is SILVER ...
    Both thresholds are inclusive — exactly 500 lifetime points is SILVER, and exactly 2,000
    is GOLD."

    Design: Corner/calculations/loyalty_tier_boundary_exactly_500_is_silver
    """
    cust = new_customer()
    res = api.adjust_loyalty(cust["id"], {"points_delta": 500, "reason": "boundary"}, manager_headers)
    updated = validate_success(res, 200)
    assert updated["lifetime_points_earned"] == 500
    assert updated["loyalty_tier"] == "SILVER"
