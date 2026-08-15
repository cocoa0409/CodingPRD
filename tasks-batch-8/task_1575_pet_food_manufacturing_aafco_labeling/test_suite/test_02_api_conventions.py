"""Response envelope shapes and pagination bounds (PRD §2.2, §2.3)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    brand_owner_payload,
    create_ingredient,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_response_envelope_shapes_for_object_array_error(api, platform_admin_headers):
    """PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies
    the specific error."
    PRD §2.2: "The `message` provides a human-readable explanation of what went
    wrong."
    PRD §2.3: "The `meta` object of a list response carries four pagination fields:
    `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/endpoints/response_envelope_shapes_for_object_array_error
    """
    create_resp = api.create_brand_owner(brand_owner_payload(), platform_admin_headers)
    body = create_resp.json()
    assert body["response_type"] == "object"
    assert isinstance(body["meta"]["api_request_id"], str)
    assert isinstance(body["meta"]["api_request_timestamp"], str)

    list_resp = api.list_brand_owners(platform_admin_headers)
    _data, meta = validate_paginated(list_resp)
    assert list_resp.json()["response_type"] == "array"
    for field in ("limit", "offset", "total_count", "has_more"):
        assert field in meta, f"meta must carry pagination field {field}"

    err_resp = api.get_brand_owner(NON_EXISTENT_UUID, platform_admin_headers)
    err_body = err_resp.json()
    assert err_body["response_type"] == "error"
    assert err_body["data"]["error_id"] == "ERR_NOT_FOUND"
    assert isinstance(err_body["data"]["message"], str) and err_body["data"]["message"]


def test_pagination_params_out_of_bounds_fail(api, formulation_scientist_headers):
    """PRD §2.3: "A `limit` outside the range of 1 to 100, or an `offset` below 0,
    is rejected with `ERR_PAGINATION` (HTTP 400)."

    Design: Corner/errors/pagination_params_out_of_bounds_fail
    """
    create_ingredient()
    for params in ({"limit": 0}, {"limit": 101}, {"offset": -1}):
        resp = api.list_ingredients(formulation_scientist_headers, params=params)
        validate_error(resp, ApiErrorId.ERR_PAGINATION.value)
