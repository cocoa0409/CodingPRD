"""Envelope shape, authentication, pagination, and not-found / FK rules (PRD §2)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    create_draft_sheet,
    create_product,
    create_product_payload,
    create_rate_sheet_payload,
    single_tier,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_unauthenticated_request_returns_401(api):
    """PRD §2.1: "A request missing either header, or presenting an
    `X-User-Role` value outside the declared role set, is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/unauthenticated_request_returns_401
    """
    resp = api.list_rate_sheets(headers=None)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, 401)


def test_list_pagination_and_envelope_shape(api, admin_headers, analyst_headers):
    """PRD §2.3: "Paginated list responses include four fields in the `meta`
    object of the envelope: `limit`, `offset`, `total_count`, and `has_more`."
    PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."

    Design: Corner/endpoints/list_pagination_and_envelope_shape
    """
    for code, klass, cap in [("P1", "SAVINGS", 500), ("P2", "SAVINGS", 500),
                             ("P3", "CD", 900)]:
        create_product(product_code=code, product_class=klass, rate_cap_bp=cap)

    resp1 = api.list_deposit_products(analyst_headers, params={"limit": 2})
    body1 = resp1.json()
    assert body1["response_type"] == "array"
    assert isinstance(body1["meta"].get("api_request_id"), str)
    assert body1["meta"]["api_request_id"].startswith("req_")
    page1, meta1 = validate_paginated(resp1)
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True
    assert meta1["limit"] == 2
    assert meta1["offset"] == 0

    resp2 = api.list_deposit_products(analyst_headers, params={"limit": 2, "offset": 2})
    page2, meta2 = validate_paginated(resp2)
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False
    assert meta2["offset"] == 2


def test_create_product_missing_required_field_returns_invalid_request(api, admin_headers):
    """PRD §2.10: "Request schema: required fields present, types and enum
    values valid, dates well-formed (`ERR_INVALID_REQUEST`, 400)."
    PRD §3.1: "The `rate_cap_bp` is the absolute internal ceiling for the
    product: no tier rate, promo rate, or stacked effective rate may exceed it."

    Design: Corner/entities/create_product_missing_required_field_returns_invalid_request
    """
    payload = create_product_payload(product_code="BAD")
    del payload["rate_cap_bp"]
    resp = api.create_deposit_product(payload, admin_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)


def test_get_missing_sheet_returns_not_found(api, analyst_headers):
    """PRD §2.8: "A path identifier that does not correspond to an existing
    resource is rejected with `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/get_missing_sheet_returns_not_found
    """
    resp = api.get_rate_sheet(NON_EXISTENT_UUID, analyst_headers)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)


def test_body_fk_references_validated(api, admin_headers, analyst_headers,
                                      banker_headers):
    """PRD §2.8: "Foreign keys carried in request bodies are validated after
    path existence, each mapping to its own HTTP 422 error: a missing
    `product_id` reference yields `ERR_PRODUCT_NOT_FOUND`, a missing `sheet_id`
    yields `ERR_SHEET_NOT_FOUND`, a missing `account_id` yields
    `ERR_ACCOUNT_NOT_FOUND`, a missing `promo_offer_id` yields
    `ERR_PROMO_NOT_FOUND`, and a missing `bundle_id` yields `ERR_BUNDLE_NOT_FOUND`."

    Each probe below carries exactly one bogus foreign key so the surfaced
    error is the mapped one.

    Design: Corner/entities/body_fk_references_validated
    """
    # Bogus product_id on sheet creation.
    resp = api.create_rate_sheet(
        create_rate_sheet_payload(NON_EXISTENT_UUID), analyst_headers)
    validate_error(resp, ApiErrorId.ERR_PRODUCT_NOT_FOUND, 422)

    # Bogus account_id on exception creation, with a real sheet so the only
    # missing reference is the account.
    product = create_product(product_code="FKCD", product_class="CD",
                             term_months=12, rate_cap_bp=900,
                             allows_promos=False, allows_exceptions=True)
    sheet = create_draft_sheet(product["id"], tiers=single_tier(400))
    resp = api.create_exception_pricing_request(
        {"account_id": NON_EXISTENT_UUID, "sheet_id": sheet["id"],
         "requested_rate_bp": 500, "term_days": 30},
        banker_headers)
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_NOT_FOUND, 422)

    # Bogus bundle_id on enrollment creation.
    resp = api.create_bundle_enrollment(
        {"bundle_id": NON_EXISTENT_UUID, "customer_ref": "CX"}, admin_headers)
    validate_error(resp, ApiErrorId.ERR_BUNDLE_NOT_FOUND, 422)
