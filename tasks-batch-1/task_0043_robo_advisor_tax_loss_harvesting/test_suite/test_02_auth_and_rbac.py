"""Authentication and role-based access control.

Translates queue-B (Corner) instances from the `rbac` section.
"""
from test_helpers import (
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    build_user_headers,
    create_account_payload,
    set_clock,
    create_active_account,
    create_model,
)

ADVISOR = TEST_USERS["advisor_headers"]
COMPLIANCE = TEST_USERS["compliance_headers"]


def test_advisor_cannot_freeze_account(api):
    """PRD §2.1: "The `Compliance` role provides oversight: it freezes and unfreezes accounts, rejects and reverses harvests, delists securities, and audits the system." PRD §2.1: "When the headers are well-formed but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN`."

    Design: Corner/rbac/advisor_cannot_freeze_account
    """
    set_clock("2026-05-01T00:00:00.000Z")
    create_model(name="RB", targets=[{"asset_class": "US_EQUITY", "target_pct": 100}])
    acct = create_active_account("rbac1@x.com")
    res = api.freeze_account(acct["id"], ADVISOR)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)
    after = get_success_data(api.get_account(acct["id"], ADVISOR))
    assert after["status"] == "ACTIVE"


def test_compliance_cannot_open_account(api):
    """PRD §4: opening an account via POST /accounts is authorized for Advisor
    only. PRD §2.1: "When the headers are well-formed but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN`."

    Design: Corner/rbac/compliance_cannot_open_account
    """
    res = api.create_account(create_account_payload(client_email="rbac2@x.com"), COMPLIANCE)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)


def test_missing_role_header_returns_401(api):
    """PRD §2.1: "A request missing either header, or carrying an `X-User-Role` that is not one of the two recognized roles, is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_role_header_returns_401
    """
    headers = build_user_headers("test-user", "")
    res = api.list_accounts(headers)
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED.value)
