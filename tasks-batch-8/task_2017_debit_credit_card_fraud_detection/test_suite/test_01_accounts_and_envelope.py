"""Account entity surface, response envelope, pagination, immediate consistency."""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    TEST_USERS,
    create_account,
    set_clock,
    create_card,
    create_manual_alert,
    claim_alert,
    create_and_complete_contact,
    resolve_alert,
    get_success_data,
)

MANAGER = TEST_USERS["manager_headers"]
ANALYST = TEST_USERS["analyst_headers"]


def test_account_created_with_system_defaults(api):
    """PRD §3.1: "New accounts begin with `account_status` equal to `ACTIVE`, zero
    balances, zero `open_alert_count`, and `risk_tier` equal to `LOW`."
    PRD §2.4: "The `version` field is an integer that starts at its initial value
    on creation and increments by one on every mutation".

    Design: Corner/entities/account_created_with_system_defaults
    """
    acct = create_account("ACCT-EN1", cardholder_name="Ent One", home_country="US")
    fetched = validate_success(api.get_account(acct["id"], MANAGER))
    assert fetched["account_status"] == "ACTIVE"
    assert fetched["credit_balance_cents"] == 0
    assert fetched["open_alert_count"] == 0
    assert fetched["rolling_90d_loss_cents"] == 0
    assert fetched["risk_tier"] == "LOW"
    assert fetched["version"] == 1


def test_account_system_fields_input_ignored(api):
    """PRD §2.4: "Every top-level resource ... carries a standard set of
    system-managed fields." PRD §2.4: "The `version` field is an integer that
    starts at its initial value on creation".

    Design: Corner/entities/account_system_fields_input_ignored
    """
    payload = {
        "account_number": "ACCT-EN2",
        "cardholder_name": "Ent Two",
        "home_country": "US",
        "version": 99,
    }
    created = validate_success(api.create_account(payload, MANAGER), expected_status=201)
    assert created["version"] == 1, f"client-supplied version must be ignored; got {created['version']}"
    fetched = validate_success(api.get_account(created["id"], MANAGER))
    assert fetched["version"] == 1


def test_account_missing_required_field_returns_invalid_request(api):
    """PRD §2.6: "request shape — required fields, enum membership, `amount_cents`
    at least 1 where required, well-formed dates"; §2.6 places this at
    "(priority 6)", and per §5 `ERR_INVALID_REQUEST` maps to HTTP 400.

    Design: Corner/entities/account_missing_required_field_returns_invalid_request
    """
    resp = api.create_account({"cardholder_name": "No Number", "home_country": "US"}, MANAGER)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    data, meta = validate_paginated(api.list_accounts(MANAGER))
    assert meta["total_count"] == 0, f"no account may be created by the rejected request, got {meta['total_count']}"


def test_card_get_nonexistent_returns_not_found(api):
    """PRD §2.7: "the first identifier in the path that does not resolve to an
    existing resource produces `ERR_NOT_FOUND` (HTTP 404)".

    Design: Corner/entities/card_get_nonexistent_returns_not_found
    """
    resp = api.get_card("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", MANAGER)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


def test_list_pagination_defaults_and_has_more(api):
    """PRD §2.3: "The `limit` parameter caps the number of items returned; it
    defaults to 10, with a minimum of 1 and a maximum of 100. The `offset`
    parameter skips a number of items and defaults to 0."

    Design: Corner/entities/list_pagination_defaults_and_has_more
    """
    create_account("ACCT-PG1", cardholder_name="Pg One")
    create_account("ACCT-PG2", cardholder_name="Pg Two")

    data, meta = validate_paginated(api.list_accounts(MANAGER))
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert len(data) == 2

    data2, meta2 = validate_paginated(api.list_accounts(MANAGER, params={"limit": 1, "offset": 0}))
    assert len(data2) == 1
    assert meta2["total_count"] == 2
    assert meta2["has_more"] is True


def test_response_envelope_success_and_error_shape(api):
    """PRD §2.2: 'The `response_type` is either "object" for a single resource or
    "array" for a list of resources.' and "The `error_id` is a unique,
    machine-readable string that identifies the specific error." plus "The
    `message` provides a human-readable explanation of what went wrong."

    Design: Corner/endpoints/response_envelope_success_and_error_shape
    """
    acct = create_account("ACCT-EP1", cardholder_name="Ep One")

    ok_resp = api.get_account(acct["id"], MANAGER)
    ok_body = ok_resp.json()
    assert ok_resp.status_code == 200
    assert "api_request_id" in ok_body["meta"]
    assert "api_request_timestamp" in ok_body["meta"]
    assert ok_body["response_type"] == "object"
    assert ok_body["data"]["id"] == acct["id"]

    err_resp = api.get_card("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", MANAGER)
    err_body = err_resp.json()
    assert err_body["response_type"] == "error"
    assert err_body["data"]["error_id"] == "ERR_NOT_FOUND"
    assert "message" in err_body["data"] and err_body["data"]["message"]


def test_immediate_read_after_write_consistency(api):
    """PRD §2.11: "The customer credit ledger, `credit_balance_cents`, is the sum of
    `provisional_credit_cents` across the account's chargeback cases ... plus the
    sum of `fraud_credit_cents` across the account's alerts currently in
    `RESOLVED_FRAUD`."

    Design: Corner/consistency_model/immediate_read_after_write_consistency
    """
    set_clock("2026-08-01T00:00:00Z")
    acct = create_account("ACCT-CM1", cardholder_name="Cm One")
    card = create_card(acct["id"], "PT-CM1")
    alert = create_manual_alert(acct["id"], card["id"])
    claim_alert(alert["id"])
    create_and_complete_contact(alert["id"], "CONFIRMED_FRAUD")

    resolved = resolve_alert(alert["id"], "FRAUD", fraud_credit_cents=5000)
    assert resolved["alert_status"] == "RESOLVED_FRAUD"

    fetched = validate_success(api.get_account(acct["id"], MANAGER))
    assert fetched["credit_balance_cents"] == 5000, (
        f"fraud credit must be visible immediately after resolve, got {fetched['credit_balance_cents']}"
    )
