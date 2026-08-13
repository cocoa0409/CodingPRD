"""Response envelope, pagination, and the logical clock (PRD §2.2, §2.3, §2.4)."""
from test_helpers import (
    api_client, TEST_USERS, ApiErrorId, NON_EXISTENT_UUID,
    validate_success, validate_error, validate_paginated,
    create_slot_pool, create_account,
)

MGR = TEST_USERS["sales_manager_headers"]


def test_success_envelope_shape_on_single_object(api):
    """PRD §2.2: "The `api_request_id` is a server-generated unique identifier
    for the request that starts with `req_`."
    PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."

    Design: Corner/endpoints/success_envelope_shape_on_single_object
    """
    slot = create_slot_pool(build_month="2026-10", capacity=2)
    resp = api.get_factory_build_slot(slot["id"], MGR)
    body = resp.json()
    assert resp.status_code == 200
    assert body["meta"]["api_request_id"].startswith("req_")
    assert body["meta"]["api_request_timestamp"]
    assert body["response_type"] == "object"
    assert body["data"]["id"] == slot["id"]


def test_list_pagination_defaults_and_fields(api):
    """PRD §2.3: "The `limit` defaults to 10, with a minimum of 1 and a maximum
    of 100; the `offset` defaults to 0. List responses include the pagination
    fields `limit`, `offset`, `total_count`, and `has_more` inside `meta`."

    Design: Corner/endpoints/list_pagination_defaults_and_fields
    """
    for i in range(12):
        create_account(name=f"A{i:02d}")
    data, meta = validate_paginated(api.list_customer_accounts(MGR))
    assert len(data) == 10, f"default page size must be 10, got {len(data)}"
    assert meta["total_count"] == 12
    assert meta["has_more"] is True
    assert meta["offset"] == 0
    assert meta["limit"] == 10


def test_list_filter_and_offset_interaction(api):
    """PRD §3.1: "Listing accounts supports filtering by `account_type`,
    `fleet_tier`, and `status`."
    PRD §2.3: "All list endpoints accept the query parameters `limit` and
    `offset`."

    Design: Corner/endpoints/list_filter_and_offset_interaction
    """
    create_account("FLEET", credit_limit_cents=900000, name="F1")
    create_account("FLEET", credit_limit_cents=900000, name="F2")
    create_account("RETAIL", name="R1")
    data, meta = validate_paginated(api.list_customer_accounts(
        MGR, params={"account_type": "FLEET", "limit": 1, "offset": 1}))
    assert meta["total_count"] == 2, "filter must apply before counting"
    assert len(data) == 1
    assert meta["has_more"] is False
    assert all(a["account_type"] == "FLEET" for a in data)


def test_clock_advance_and_monotonic_regression_rejected(api):
    """PRD §2.4: "A `DealershipAdmin` advances the clock through a test-driving
    capability that sets the current time to a supplied `to_iso8601` instant;
    the supplied instant must be strictly after the current clock value, and a
    regression is rejected with `ERR_CLOCK_REGRESSION` (HTTP 409)."

    Design: Corner/endpoints/clock_default_and_monotonic_regression_rejected
    """
    admin = TEST_USERS["admin_headers"]
    resp = api.set_clock({"to_iso8601": "2026-08-02T00:00:00Z"}, admin)
    data = validate_success(resp, 200)
    assert data["current_utc"] == "2026-08-02T00:00:00Z"
    # Earlier instant: regression.
    validate_error(api.set_clock({"to_iso8601": "2026-08-01T12:00:00Z"}, admin),
                   ApiErrorId.ERR_CLOCK_REGRESSION)
    # Equal instant is not strictly after: also a regression.
    validate_error(api.set_clock({"to_iso8601": "2026-08-02T00:00:00Z"}, admin),
                   ApiErrorId.ERR_CLOCK_REGRESSION)


def test_error_envelope_shape_on_failure(api):
    """PRD §2.2: "All error API responses (4xx status codes) follow this
    standard envelope format" with "response_type": "error" and data carrying
    "error_id" plus "message" — "The `message` provides a human-readable
    explanation of what went wrong."

    Design: Corner/endpoints/error_envelope_shape_on_failure
    """
    resp = api.get_factory_order(NON_EXISTENT_UUID, MGR)
    body = resp.json()
    assert resp.status_code == 404
    assert body["response_type"] == "error"
    assert body["data"]["error_id"] == "ERR_FACTORY_ORDER_NOT_FOUND"
    assert isinstance(body["data"]["message"], str) and body["data"]["message"]
