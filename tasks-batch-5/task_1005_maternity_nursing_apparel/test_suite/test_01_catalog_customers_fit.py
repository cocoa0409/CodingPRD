"""Catalog + customer onboarding + fit guide: registration defaults, input
validation, not-found, the bump-friendly size recommendation, trimester
derivation, and variant listing pagination.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    NON_EXISTENT_UUID,
    make_shopper_headers,
    set_clock,
    new_customer,
    new_product,
    new_variant,
)


def test_register_customer_defaults_bronze_zero_points(api, guest_headers):
    """PRD §3.2: "On creation the system-managed balances all start empty:
    `loyalty_points` at 0, `lifetime_points` at 0, `store_credit_cents` at 0,
    and `current_trimester` at 0."
    PRD §3.4: "anyone below 2000 is `BRONZE`."

    Design: Corner/entities/create_customer_success_defaults
    """
    resp = api.create_customer({"email": "new@x.com", "full_name": "New Person",
                                "nursing_flag": True}, guest_headers)
    data = validate_success(resp, 201)
    assert data["loyalty_points"] == 0
    assert data["loyalty_tier"] == "BRONZE"
    assert data["version"] == 1


def test_get_customer_unknown_id_returns_404(api, platform_admin_headers):
    """PRD §2.8: "the request is rejected at the first identifier that names no
    existing resource, with the not-found error for that resource type
    (`ERR_PRODUCT_NOT_FOUND`, `ERR_VARIANT_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`
    ...)."

    Design: Corner/entities/get_customer_not_found_returns_404
    """
    resp = api.get_customer(NON_EXISTENT_UUID, platform_admin_headers)
    validate_error(resp, ApiErrorId.ERR_CUSTOMER_NOT_FOUND.value)


def test_create_order_missing_variant_id_rejected(api):
    """PRD §2.8: "Body well-formedness (`ERR_VALIDATION`, HTTP 422) covers every
    create and modify request: required fields must be present, values must have
    the correct type, enum-valued fields must name a valid member, a BUY
    `quantity` must be at least 1, and a RENTAL `rental_weeks` must be at least
    1."

    Design: Corner/entities/create_order_missing_variant_id_returns_validation
    """
    cust = new_customer(api)
    resp = api.create_order(
        {"customer_id": cust["id"], "order_type": "BUY", "quantity": 1,
         "expected_variant_version": 1},
        make_shopper_headers(cust["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_create_product_missing_category_rejected(api, platform_admin_headers):
    """PRD §2.8: "required fields must be present, values must have the correct
    type, enum-valued fields must name a valid member."
    PRD §3.1: "A product is created with a `name`, a merchandising `category`
    that is one of `MATERNITY`, `NURSING`, `POSTPARTUM`, or `CAPSULE`, and a
    `buy_price_cents` retail price that doubles as the deposit basis for any
    rental of the item."

    Design: Corner/entities/create_product_missing_category_returns_validation
    """
    resp = api.create_product({"name": "No Category", "buy_price_cents": 5000},
                              platform_admin_headers)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_client_supplied_loyalty_points_ignored_on_create(api, guest_headers):
    """PRD §3.2: "On creation the system-managed balances all start empty:
    `loyalty_points` at 0, `lifetime_points` at 0, `store_credit_cents` at 0,
    and `current_trimester` at 0."

    Design: Corner/entities/system_fields_input_ignored_on_customer_create
    """
    resp = api.create_customer({"email": "sys@x.com", "full_name": "Sys",
                                "loyalty_points": 9999}, guest_headers)
    data = validate_success(resp, 201)
    assert data["loyalty_points"] == 0


def test_fit_recommended_size_bust_boundary_94_is_M(api):
    """PRD §3.2: "from 94 up to but not including 102 cm is `M`."
    PRD §3.2: "Each band boundary is lower-inclusive, so a bust of exactly 94 cm
    lands in `M`, not `S`."
    PRD §3.2: "if she is in trimester 0 or 1, the base band stands."

    Design: Corner/calculations/fit_recommended_size_bust_boundary_94
    """
    cust = new_customer(api)  # no due_date -> current_trimester 0, no bump
    resp = api.create_fit_profile(
        {"customer_id": cust["id"], "bust_cm": 94, "waist_cm": 80, "hip_cm": 100,
         "pre_pregnancy_size": "M"},
        make_shopper_headers(cust["id"]),
    )
    data = validate_success(resp, 201)
    assert data["recommended_size"] == "M"


def test_fit_recommended_size_second_trimester_bumps_M_to_L(api):
    """PRD §3.2: "if the owning customer's `current_trimester` is 2 or 3, the
    recommendation is bumped up exactly one size along the order `XS`, `S`, `M`,
    `L`, `XL`."
    PRD §3.2: "from 94 up to but not including 102 cm is `M`."

    Design: Corner/calculations/fit_recommended_size_second_trimester_bump
    """
    set_clock(api, "2026-07-01T00:00:00Z")
    cust = new_customer(api, due_date="2026-10-01T00:00:00Z")  # -> trimester 2
    resp = api.create_fit_profile(
        {"customer_id": cust["id"], "bust_cm": 94, "waist_cm": 82, "hip_cm": 102,
         "pre_pregnancy_size": "M"},
        make_shopper_headers(cust["id"]),
    )
    data = validate_success(resp, 201)
    assert data["recommended_size"] == "L"


def test_current_trimester_third_trimester(api, platform_admin_headers):
    """PRD §2.7: "If the gestational age is under 13 weeks the trimester is 1; if
    it is at least 13 but under 27 weeks it is 2; otherwise it is 3."
    PRD §2.7: "Subtract that number of weeks-to-due from the full-term length of
    40 weeks to get the gestational age in weeks."

    Design: Corner/calculations/current_trimester_third_trimester
    """
    set_clock(api, "2026-07-01T00:00:00Z")
    cust = new_customer(api, due_date="2026-08-01T00:00:00Z")
    resp = api.get_customer(cust["id"], platform_admin_headers)
    data = validate_success(resp, 200)
    assert data["current_trimester"] == 3


def test_variants_list_pagination(api, guest_headers, platform_admin_headers):
    """PRD §2.3: "The `limit` parameter caps how many items are returned."
    PRD §2.3: "Every list response echoes `limit`, `offset`, `total_count`, and
    `has_more` inside the `meta` object of the envelope."

    Design: Corner/endpoints/variants_list_pagination
    """
    product = new_product(api)
    for lbl, tf in [("S", [1]), ("M", [2]), ("L", [3])]:
        new_variant(api, product["id"], size_label=lbl, trimester_fit=tf)
    resp = api.list_product_variants(product["id"], guest_headers,
                                     params={"limit": 2, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 3
    assert len(data) == 2
    assert meta["has_more"] is True
