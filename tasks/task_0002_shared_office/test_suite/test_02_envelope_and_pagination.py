"""API envelope and pagination tests.

Covers PRD §2.2 (response envelope shape) and §2.3 (pagination bounds and meta).
"""

import pytest

from test_helpers import (
    TEST_USERS,
    create_tenant,
    is_iso8601_timestamp,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_success_envelope_shape(api, admin_headers):
    """PRD §2.2: "All successful API responses (those with 2xx `status` codes) follow
    this standard envelope format in their JSON body." The envelope carries meta
    with api_request_id (starts with req_) and api_request_timestamp (ISO 8601 UTC
    with three fractional digits).

    Claim: success responses expose the prescribed envelope shape.
    """
    res = api.create_tenant({"legal_name": "Envelope Tenant"}, admin_headers)
    assert res.status_code == 201
    body = res.json()
    assert body["response_type"] == "object"
    assert body["data"]["legal_name"] == "Envelope Tenant"
    meta = body["meta"]
    assert isinstance(meta["api_request_id"], str)
    assert meta["api_request_id"].startswith("req_"), (
        "PRD §2.2 mandates api_request_id starts with req_"
    )
    assert is_iso8601_timestamp(meta["api_request_timestamp"])


def test_error_envelope_shape(api, admin_headers):
    """PRD §2.2: "All error API responses (4xx status codes) follow this standard
    envelope format." The data object contains error_id and message.

    Claim: error response carries meta + response_type=error + error_id and message.
    """
    res = api.get_tenant("00000000-0000-4000-8000-000000000000", admin_headers)
    assert res.status_code == 404
    body = res.json()
    assert body["response_type"] == "error"
    assert body["data"]["error_id"] == "ERR_NOT_FOUND"
    assert isinstance(body["data"]["message"], str) and len(body["data"]["message"]) > 0


def test_pagination_defaults_are_10_and_0(api, admin_headers):
    """PRD §2.3: "`limit` defaults to 10, with a minimum of 1 and a maximum of 100;
    `offset` defaults to 0 and must be at least 0."

    Claim: absent limit/offset → meta echoes defaults of 10 and 0.
    """
    for i in range(3):
        create_tenant(legal_name=f"PagDefaultTenant {i}")
    res = api.list_tenants(admin_headers)
    _data, meta = validate_paginated(res)
    assert meta["limit"] == 10
    assert meta["offset"] == 0


def test_pagination_limit_and_offset_respected(api, admin_headers):
    """PRD §2.3: "List endpoints accept two query parameters: `limit` defaults to 10,
    with a minimum of 1 and a maximum of 100; `offset` defaults to 0 and must be at
    least 0." And "All list endpoints sort results by created_at ascending."

    Claim: limit bounds the page size and has_more reflects offset + limit <
    total_count.
    """
    for i in range(3):
        create_tenant(legal_name=f"PagTenant {i}")
    res = api.list_tenants(admin_headers, params={"limit": 1})
    data, meta = validate_paginated(res)
    assert len(data) == 1
    assert meta["limit"] == 1
    assert meta["total_count"] >= 3
    assert meta["has_more"] is True


def test_pagination_has_more_false_on_last_page(api, admin_headers):
    """PRD §2.3: "`has_more` (true when `offset + limit` is strictly less than
    `total_count`)."

    Claim: offset past total_count → has_more is false, data is empty.
    """
    # Any populated system; use admin listing of tenants.
    create_tenant()
    res = api.list_tenants(admin_headers, params={"limit": 100, "offset": 9999})
    data, meta = validate_paginated(res)
    assert data == []
    assert meta["has_more"] is False


@pytest.mark.parametrize("limit", [0, -1, 101, 1000])
def test_pagination_limit_out_of_range_rejected(api, admin_headers, limit):
    """PRD §2.3: "A request with `limit` outside 1 through 100 inclusive, or with a
    negative `offset`, is rejected with `ERR_PAGINATION_OUT_OF_RANGE`."

    Claim: limit outside [1,100] → ERR_PAGINATION_OUT_OF_RANGE (400).
    """
    res = api.list_tenants(admin_headers, params={"limit": limit})
    validate_error(res, "ERR_PAGINATION_OUT_OF_RANGE", expected_status=400)


def test_pagination_negative_offset_rejected(api, admin_headers):
    """PRD §2.3: "A request with `limit` outside 1 through 100 inclusive, or with a
    negative `offset`, is rejected with `ERR_PAGINATION_OUT_OF_RANGE`."

    Claim: offset < 0 → ERR_PAGINATION_OUT_OF_RANGE (400).
    """
    res = api.list_tenants(admin_headers, params={"offset": -1})
    validate_error(res, "ERR_PAGINATION_OUT_OF_RANGE", expected_status=400)


def test_pagination_limit_100_is_allowed_upper_bound(api, admin_headers):
    """PRD §2.3: "`limit` defaults to 10, with a minimum of 1 and a maximum of 100."

    Claim: limit=100 is the exact upper bound, not itself an out-of-range value.
    """
    create_tenant()
    res = api.list_tenants(admin_headers, params={"limit": 100})
    data, meta = validate_paginated(res)
    assert meta["limit"] == 100
