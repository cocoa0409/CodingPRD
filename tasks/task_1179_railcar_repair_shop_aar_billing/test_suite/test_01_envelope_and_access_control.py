"""Response envelope shape, shop configuration defaults, and role gating."""
from test_helpers import (
    ApiErrorId, TEST_USERS, api_client, create_price_master_entry_payload,
    create_shop_payload, validate_error, validate_paginated, validate_success,
)

ADMIN = TEST_USERS["shop_admin"]
BILLING = TEST_USERS["billing_clerk"]


def test_shop_create_applies_config_defaults():
    """PRD §3.1: "`stall_daily_hours` defaults to 8 bookable hours per stall
    per calendar day, `dwell_free_hours` defaults to 48 hours of free dwell
    after arrival, `warranty_days` defaults to ninety days of warranty coverage
    measured from work-order completion, `counter_window_days` defaults to
    thirty days during which counter-bills are accepted after a card's
    submission".
    PRD §3.1: "A freshly created shop reads `current_posture` as `OPEN`."

    Design: Corner/entities/shop_create_applies_config_defaults
    """
    created = validate_success(
        api_client.create_shop(
            create_shop_payload(name="Defaults Shop", stalls=3,
                                dwell_rate_cents_per_hour=750),
            ADMIN),
        expected_status=201)
    shop = validate_success(api_client.get_shop(created["id"], ADMIN))
    assert shop["stall_daily_hours"] == 8, "stall_daily_hours default"
    assert shop["dwell_free_hours"] == 48, "dwell_free_hours default"
    assert shop["warranty_days"] == 90, "warranty_days default"
    assert shop["counter_window_days"] == 30, "counter_window_days default"
    assert shop["current_posture"] == "OPEN", "fresh shop posture"
    assert shop["version"] == 1, "fresh shop version"


def test_success_envelope_shape_on_create():
    """PRD §2.2: "The `response_type` is either "object" for a single resource
    or "array" for a list of resources."
    PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."

    Design: Corner/endpoints/success_envelope_shape_on_create
    """
    resp = api_client.create_shop(
        create_shop_payload(name="Envelope Shop", stalls=1, dwell_rate_cents_per_hour=100),
        ADMIN)
    assert resp.status_code == 201, f"expected 201, got {resp.status_code}: {resp.text}"
    body = resp.json()
    assert isinstance(body["meta"].get("api_request_id"), str)
    assert isinstance(body["meta"].get("api_request_timestamp"), str)
    assert body["response_type"] == "object"
    shop_id = body["data"]["id"]

    get_body = api_client.get_shop(shop_id, ADMIN).json()
    assert get_body["response_type"] == "object"
    assert get_body["data"]["name"] == "Envelope Shop"


def test_error_envelope_shape_on_failure():
    """PRD §2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."
    PRD §2.2: "The `message` provides a human-readable explanation of what went
    wrong."

    Design: Corner/errors/error_envelope_shape_on_failure
    """
    validate_success(
        api_client.create_shop(
            create_shop_payload(name="Shop", stalls=1, dwell_rate_cents_per_hour=100),
            ADMIN),
        expected_status=201)
    resp = api_client.get_part("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", ADMIN)
    error = validate_error(resp, ApiErrorId.ERR_NOT_FOUND, expected_status=404)
    assert isinstance(error["message"], str) and error["message"].strip()
    body = resp.json()
    assert body["response_type"] == "error"
    assert set(body["meta"].keys()) == {"api_request_id", "api_request_timestamp"}


def test_missing_auth_header_rejected():
    """PRD §2.1: "A request missing either header, carrying a malformed header,
    or naming an undeclared role is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (400)."

    Design: Corner/rbac/missing_auth_header_rejected
    """
    resp = api_client.create_shop(
        create_shop_payload(name="NoAuth Shop", stalls=1, dwell_rate_cents_per_hour=100),
        {"Content-Type": "application/json"})
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
                   expected_status=400)


def test_price_master_create_forbidden_for_billing_clerk():
    """PRD §2.1: "A valid caller attempting an operation outside their role's
    permissions is rejected with `ERR_FORBIDDEN_FOR_ROLE` (403)."

    Design: Corner/rbac/price_master_create_forbidden_for_billing_clerk
    """
    shop = validate_success(
        api_client.create_shop(
            create_shop_payload(name="Shop", stalls=1, dwell_rate_cents_per_hour=100),
            ADMIN),
        expected_status=201)
    resp = api_client.create_price_master_entry(
        create_price_master_entry_payload(shop["id"], description="x"),
        BILLING)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE, expected_status=403)
    _data, meta = validate_paginated(
        api_client.list_price_master_entries(ADMIN, params={"shop_id": shop["id"]}))
    assert meta["total_count"] == 0, "forbidden create must not persist an entry"
