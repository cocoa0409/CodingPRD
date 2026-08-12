"""Response envelope, pagination, and the per-family not-found errors."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    api_client,
    assert_farm,
    create_farm,
    create_program_year,
    is_iso8601_timestamp,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import TEST_USERS

ADMIN = TEST_USERS["admin_headers"]


def test_response_envelope_success_shape(api):
    """PRD section 2.2: "The `api_request_id` is a server-generated unique
    identifier for the request that starts with `req_`."
    PRD section 2.2: "The `response_type` is either "object" for a single
    resource or "array" for a list of resources."

    Design: Corner/endpoints/ep_response_envelope_success_shape
    """
    farm = create_farm()
    resp = api.get_farm(farm["id"], ADMIN)
    assert resp.status_code == 200
    body = resp.json()
    assert "meta" in body and "response_type" in body and "data" in body
    assert body["meta"]["api_request_id"].startswith("req_")
    assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
    assert body["response_type"] == "object"
    assert body["data"]["id"] == farm["id"]
    assert_farm(body["data"])


def test_farms_list_pagination_envelope(api):
    """PRD section 2.3: "`limit` caps the number of items returned; it defaults
    to 10, with a minimum of 1 and a maximum of 100. `offset` skips that many
    items before results are returned and defaults to 0."
    PRD section 2.3: "The `meta` object of a list response carries `limit`,
    `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/ent_farms_list_pagination_envelope
    """
    for i in range(3):
        create_farm(legal_name=f"Farm {i}", contact_email=f"f{i}@example.com")

    page1, meta1 = validate_paginated(
        api.list_farms(ADMIN, params={"limit": 2, "offset": 0})
    )
    assert len(page1) == 2, f"page 1 must hold 2 items, got {len(page1)}"
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True
    assert meta1["limit"] == 2 and meta1["offset"] == 0

    page2, meta2 = validate_paginated(
        api.list_farms(ADMIN, params={"limit": 2, "offset": 2})
    )
    assert len(page2) == 1, f"page 2 must hold 1 item, got {len(page2)}"
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False


def test_not_found_family_across_resources(api):
    """PRD section 2.6: "Each resource family reports its own absence:
    `ERR_PROGRAM_YEAR_NOT_FOUND`, `ERR_FARM_NOT_FOUND`, `ERR_DOCUMENT_NOT_FOUND`,
    `ERR_PRODUCT_NOT_FOUND`, `ERR_OFFERING_NOT_FOUND`,
    `ERR_FORECAST_LINE_NOT_FOUND`, `ERR_KITCHEN_NOT_FOUND`, `ERR_WINDOW_NOT_FOUND`,
    `ERR_AGREEMENT_NOT_FOUND`, `ERR_AMENDMENT_NOT_FOUND`, `ERR_DELIVERY_NOT_FOUND`,
    `ERR_INVOICE_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_CLAIM_LINE_NOT_FOUND`,
    and `ERR_SUBSTITUTION_NOT_FOUND`."

    Design: Corner/entities/ent_not_found_family_across_resources
    """
    cases = [
        (api.get_program_year, ApiErrorId.ERR_PROGRAM_YEAR_NOT_FOUND),
        (api.get_farm, ApiErrorId.ERR_FARM_NOT_FOUND),
        (api.get_compliance_document, ApiErrorId.ERR_DOCUMENT_NOT_FOUND),
        (api.get_product, ApiErrorId.ERR_PRODUCT_NOT_FOUND),
        (api.get_offering, ApiErrorId.ERR_OFFERING_NOT_FOUND),
        (api.get_forecast_line, ApiErrorId.ERR_FORECAST_LINE_NOT_FOUND),
        (api.get_kitchen, ApiErrorId.ERR_KITCHEN_NOT_FOUND),
        (api.get_receiving_window, ApiErrorId.ERR_WINDOW_NOT_FOUND),
        (api.get_planting_agreement, ApiErrorId.ERR_AGREEMENT_NOT_FOUND),
        (api.get_amendment, ApiErrorId.ERR_AMENDMENT_NOT_FOUND),
        (api.get_delivery, ApiErrorId.ERR_DELIVERY_NOT_FOUND),
        (api.get_invoice, ApiErrorId.ERR_INVOICE_NOT_FOUND),
        (api.get_claim, ApiErrorId.ERR_CLAIM_NOT_FOUND),
        (api.get_claim_line, ApiErrorId.ERR_CLAIM_LINE_NOT_FOUND),
        (api.get_substitution_request, ApiErrorId.ERR_SUBSTITUTION_NOT_FOUND),
    ]
    for getter, error_id in cases:
        resp = getter(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, error_id)
