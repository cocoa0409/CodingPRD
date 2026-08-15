"""List endpoint envelope and pagination defaults."""
from test_helpers import (
    api_client,
    get_success_data,
    validate_paginated,
)
from test_helpers import TEST_USERS

HR_ADMIN = TEST_USERS["hr_admin_headers"]


def test_list_pagination_defaults_and_envelope(api):
    """PRD §2.3: "`limit` caps the number of items returned; it defaults to 10,
    with a minimum of 1 and a maximum of 100."
    PRD §2.3: "The `meta` object of a list response carries four pagination
    fields: `limit`, `offset`, `total_count`, and `has_more`."
    PRD §2.2: "The `api_request_id` is a server-generated unique identifier for
    the request that starts with `req_`. ... The `response_type` is either
    "object" for a single resource or "array" for a list of resources."

    Design: Corner/endpoints/list_pagination_defaults_and_envelope
    """
    for i in range(1, 13):
        get_success_data(
            api.create_item_bank({"name": f"PgB{i:02d}", "framework": "EWI"}, HR_ADMIN)
        )

    resp = api.list_item_banks(HR_ADMIN)
    data, meta = validate_paginated(resp)
    assert len(data) == 10, "default limit is 10"
    assert meta["limit"] == 10
    assert meta["offset"] == 0, "default offset is 0"
    assert meta["total_count"] == 12
    assert meta["has_more"] is True

    body = resp.json()
    assert body["response_type"] == "array"
    assert isinstance(body["meta"]["api_request_id"], str)
    assert body["meta"]["api_request_id"].startswith("req_")
    assert isinstance(body["meta"]["api_request_timestamp"], str)
