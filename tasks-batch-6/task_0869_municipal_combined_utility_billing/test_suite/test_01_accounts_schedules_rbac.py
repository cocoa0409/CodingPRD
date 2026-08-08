"""Account onboarding, rate-schedule input validation, and RBAC gate tests."""
from test_helpers import (
    validate_success, validate_error, is_valid_uuid,
    account_payload, water_rate_schedule_payload,
    TEST_USERS, NO_AUTH_HEADERS, make_customer_headers,
    open_account,
)

BS = TEST_USERS["billing_specialist_headers"]
MT = TEST_USERS["meter_tech_headers"]
NON_EXISTENT_ACCOUNT = "00000000-0000-4000-8000-000000000000"


def test_open_account_returns_active_with_computed_defaults(api):
    """PRD §3.1: "A freshly opened account begins in `status` `ACTIVE` with `version` 1,
    with `assistance_program` null, `assistance_discount_pct` 0, and all of
    `current_balance_cents`, `delinquent_balance_cents`, `deposit_on_hand_cents` at 0
    and `move_out_date` null."

    Design: Corner/entities/account_create_returns_201_with_computed_defaults
    """
    data = validate_success(api.create_account(account_payload(account_holder_name="New Nan"), BS), 201)
    assert data["status"] == "ACTIVE"
    assert data["current_balance_cents"] == 0
    assert data["delinquent_balance_cents"] == 0
    assert data["deposit_on_hand_cents"] == 0
    assert data["version"] == 1


def test_open_account_ignores_client_supplied_status_and_mints_uuid(api):
    """PRD §3.1: "A freshly opened account begins in `status` `ACTIVE` with `version` 1".
    PRD §2.4: "Every resource carries a server-minted `id` that is a UUID with no type prefix."

    Design: Corner/entities/account_system_fields_ignore_client_input
    """
    data = validate_success(
        api.create_account(account_payload(occupant_type="COMMERCIAL", status="LIEN_TRANSFERRED"), BS),
        201,
    )
    assert data["status"] == "ACTIVE", "client-supplied status must be ignored"
    assert is_valid_uuid(data["id"]), "id must be a UUID with no type prefix"


def test_open_account_missing_occupant_type_rejected(api):
    """PRD §3.1: "and the `occupant_type`, either `RESIDENTIAL` or `COMMERCIAL`."
    PRD §2.11: "field constraints (`ERR_READING_REGRESSION`, `ERR_VALIDATION`)".

    Design: Corner/entities/account_missing_required_field_returns_invalid_request
    """
    payload = {"account_holder_name": "No Class", "service_address": "101 Oak"}
    validate_error(api.create_account(payload, BS), "ERR_VALIDATION")


def test_get_nonexistent_account_returns_not_found(api):
    """PRD §2.9: "If a path-referenced `Account` does not exist, the response is
    `ERR_ACCOUNT_NOT_FOUND` (404)".

    Design: Corner/entities/account_get_not_found_returns_404
    """
    validate_error(api.get_account(NON_EXISTENT_ACCOUNT, BS), "ERR_ACCOUNT_NOT_FOUND")


def test_rate_schedule_invalid_service_type_enum_rejected(api):
    """PRD §3.1: "A billing specialist defines a schedule for one utility by supplying its
    `service_type` — one of `WATER`, `SEWER`, `ELECTRIC`, or `REFUSE`".
    PRD §2.11: "field constraints (`ERR_READING_REGRESSION`, `ERR_VALIDATION`)".

    Design: Corner/entities/rate_schedule_invalid_enum_service_type_returns_422
    """
    payload = water_rate_schedule_payload(service_type="GAS")
    validate_error(api.create_rate_schedule(payload, BS), "ERR_VALIDATION")


def test_customer_cannot_generate_bill(api):
    """PRD §2.1: "If the headers are well-formed but the named role is not permitted to
    invoke the requested operation, the request is rejected with `ERR_UNAUTHORIZED`
    (HTTP 403)."

    Design: Corner/rbac/customer_cannot_generate_bill_returns_403
    """
    account = open_account(api, account_holder_name="Cust Cam")
    resp = api.create_bill(
        account["id"],
        {"period_start": "2026-04-01T00:00:00Z", "period_end": "2026-05-01T00:00:00Z"},
        make_customer_headers(account["id"]),
    )
    validate_error(resp, "ERR_UNAUTHORIZED")


def test_metertech_cannot_open_account(api):
    """PRD §2.1: "If the headers are well-formed but the named role is not permitted to
    invoke the requested operation, the request is rejected with `ERR_UNAUTHORIZED`
    (HTTP 403)."

    Design: Corner/rbac/metertech_cannot_create_account_returns_403
    """
    validate_error(api.create_account(account_payload(account_holder_name="Tech Tom"), MT), "ERR_UNAUTHORIZED")


def test_missing_auth_headers_rejected(api):
    """PRD §2.1: "If either header is missing or malformed, the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_auth_headers_returns_401
    """
    validate_error(api.list_accounts(NO_AUTH_HEADERS), "ERR_UNAUTHENTICATED")
