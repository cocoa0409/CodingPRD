"""Response envelope shape and list pagination (PRD sections 2.2, 2.3)."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    create_licensee,
    is_iso8601_timestamp,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_success_and_error_envelope_shape(api, analyst_headers):
    """PRD section 2.2: "The `api_request_id` is a server-generated unique
    identifier for the request that starts with `req_`." and "The
    `response_type` is either "object" for a single resource or "array" for a
    list of resources." Error format: "The `error_id` is a unique,
    machine-readable string that identifies the specific error." and "The
    `message` provides a human-readable explanation of what went wrong."

    Design: Corner/endpoints/response_envelope_shape
    """
    licensee = create_licensee(legal_name="Env Co")

    resp = api.get_licensee(licensee["id"], analyst_headers)
    body = resp.json()
    assert resp.status_code == 200
    assert isinstance(body["meta"]["api_request_id"], str)
    assert body["meta"]["api_request_id"].startswith("req_")
    assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
    assert body["response_type"] == "object"
    assert body["data"]["id"] == licensee["id"]

    err_resp = api.get_licensee(NON_EXISTENT_UUID, analyst_headers)
    err_body = err_resp.json()
    assert err_resp.status_code == 404
    assert err_body["response_type"] == "error"
    assert err_body["data"]["error_id"] == ApiErrorId.ERR_LICENSEE_NOT_FOUND.value
    assert isinstance(err_body["data"]["message"], str) and err_body["data"]["message"]


def test_list_pagination_limit_offset(api, analyst_headers):
    """PRD section 2.3: "`limit` controls the maximum number of items
    returned; it defaults to 10, with a minimum of 1 and a maximum of 100.
    `offset` controls how many items are skipped and defaults to 0." and "The
    `meta` object of a list response carries the pagination fields `limit`,
    `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/pagination_envelope_on_list
    """
    create_licensee(legal_name="Pg A")
    create_licensee(legal_name="Pg B")

    resp = api.list_licensees(analyst_headers, params={"limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert len(data) == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is True

    resp2 = api.list_licensees(analyst_headers, params={"limit": 1, "offset": 1})
    data2, meta2 = validate_paginated(resp2)
    assert len(data2) == 1
    assert meta2["total_count"] == 2
    assert meta2["has_more"] is False
