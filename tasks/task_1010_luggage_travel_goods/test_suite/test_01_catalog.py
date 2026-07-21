"""Catalog: product/customer creation, reference records, listing, and the airline fit guide."""
import test_helpers as H


# ==========================================================================
# Queue B — entities
# ==========================================================================
def test_create_product_defaults_to_active(api, associate_headers):
    """PRD §3.1: "A new product begins life in `status` `ACTIVE`."

    Design: Corner/entities/product_create_returns_201_with_fields
    """
    resp = api.create_product(H.create_product_payload(sku="P-1", name="Alpha", category="BACKPACK"),
                              associate_headers)
    data = H.validate_success(resp, expected_status=201)
    H.assert_product(data)
    assert data["status"] == "ACTIVE"
    assert data["sku"] == "P-1"


def test_create_product_invalid_category_rejected(api, associate_headers):
    """PRD §2.8: "16. **Request well-formedness** — required fields are present and every enum
    value is a member of its declared set, else `ERR_INVALID_REQUEST` (422)."

    Design: Corner/entities/create_product_invalid_category_enum_returns_invalid_request
    """
    resp = api.create_product(H.create_product_payload(category="SUITCASE"), associate_headers)
    H.validate_error(resp, H.ApiErrorId.ERR_INVALID_REQUEST)


def test_create_customer_missing_email_rejected(api, associate_headers):
    """PRD §2.8: "16. **Request well-formedness** — required fields are present and every enum
    value is a member of its declared set, else `ERR_INVALID_REQUEST` (422)."

    Design: Corner/entities/create_customer_missing_email_returns_invalid_request
    """
    resp = api.create_customer({"full_name": "No Email"}, associate_headers)
    H.validate_error(resp, H.ApiErrorId.ERR_INVALID_REQUEST)


def test_duplicate_customer_email_rejected(api, associate_headers):
    """PRD §3.2: "The `email` is globally unique across all customers; a collision is rejected
    with `ERR_DUPLICATE`."

    Design: Corner/validations/duplicate_customer_email_returns_duplicate
    """
    H.new_customer(api, email="dup@x.com")
    resp = api.create_customer(H.create_customer_payload(email="dup@x.com"), associate_headers)
    H.validate_error(resp, H.ApiErrorId.ERR_DUPLICATE)


def test_airline_reference_record_omits_version(api, manager_headers):
    """PRD §2.4: "Three resource types are lightweight reference records that are immutable after
    creation and therefore carry **only** `id` and `created_at`: airlines, service benches, and
    monogram stations all omit `updated_at` and `version` entirely."

    Design: Corner/entities/airline_created_without_version_field
    """
    resp = api.create_airline(H.create_airline_payload(iata_code="DL", name="Delta Air"), manager_headers)
    data = H.validate_success(resp, expected_status=201)
    H.assert_airline_reference_shape(data)


def test_list_products_paginated_envelope(api, associate_headers):
    """PRD §2.3: "Every list response includes `limit`, `offset`, `total_count`, and `has_more`
    in the `meta` object of the envelope."

    Design: Corner/entities/list_products_paginated_envelope
    """
    H.new_product(api)
    H.new_product(api)
    resp = api.list_products(associate_headers, params={"limit": 1, "offset": 0})
    data, meta = H.validate_paginated(resp)
    assert meta["total_count"] >= 2
    assert meta["has_more"] is True
    assert len(data) == 1


# ==========================================================================
# Queue B — calculations: airline fit
# ==========================================================================
def test_airline_fit_checked_within_limit(api, associate_headers, manager_headers):
    """PRD §3.1: "The linear dimension is the sum of the product's `length_mm`, `width_mm`, and
    `height_mm`, and the product fits as checked baggage when that linear sum is less than or equal
    to the airline's `checked_linear_limit_mm`, again inclusive at the boundary."

    Design: Corner/calculations/airline_fit_checked_linear_within_limit
    """
    airline = H.new_airline(api, iata_code="AA", name="American",
                            carry_on_max_length_mm=560, carry_on_max_width_mm=350,
                            carry_on_max_height_mm=230, checked_linear_limit_mm=1580)
    product = H.new_product(api, length_mm=700, width_mm=450, height_mm=300)
    data = H.validate_success(api.airline_fit(product["id"], airline["id"], associate_headers))
    assert data["linear_mm"] == 1450
    assert data["fits_checked"] is True
    assert data["fits_carry_on"] is False


# ==========================================================================
# Queue A — boundary precision: inclusive carry-on fit
# ==========================================================================
def test_airline_fit_carry_on_exact_boundary_fits(api, associate_headers):
    """PRD §3.1: "The product fits as carry-on when its `length_mm` is less than or equal to the
    airline's `carry_on_max_length_mm`, **and** its `width_mm` is less than or equal to
    `carry_on_max_width_mm`, **and** its `height_mm` is less than or equal to
    `carry_on_max_height_mm`; every boundary is inclusive, so exact equality on a dimension still fits."

    Design: Difficulty/boundary_precision_check/airline_fit_inclusive_dimension_equality
    """
    airline = H.new_airline(api, carry_on_max_length_mm=560, carry_on_max_width_mm=350,
                            carry_on_max_height_mm=230, checked_linear_limit_mm=1580)
    product = H.new_product(api, length_mm=560, width_mm=350, height_mm=230)
    data = H.validate_success(api.airline_fit(product["id"], airline["id"], associate_headers))
    assert data["fits_carry_on"] is True


def test_airline_fit_carry_on_one_mm_over_fails(api, associate_headers):
    """PRD §3.1: "The product fits as carry-on when its `length_mm` is less than or equal to the
    airline's `carry_on_max_length_mm`, **and** its `width_mm` is less than or equal to
    `carry_on_max_width_mm`, **and** its `height_mm` is less than or equal to
    `carry_on_max_height_mm`; every boundary is inclusive, so exact equality on a dimension still fits."

    Design: Difficulty/boundary_precision_check/airline_fit_inclusive_dimension_equality
    """
    airline = H.new_airline(api, carry_on_max_length_mm=560, carry_on_max_width_mm=350,
                            carry_on_max_height_mm=230, checked_linear_limit_mm=1580)
    product = H.new_product(api, length_mm=561, width_mm=350, height_mm=230)
    data = H.validate_success(api.airline_fit(product["id"], airline["id"], associate_headers))
    assert data["fits_carry_on"] is False
