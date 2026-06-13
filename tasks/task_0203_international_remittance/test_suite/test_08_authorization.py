"""Authorization, validation ordering, and segregation-of-duties enforcement.

Covers the existence-before-body-validation precedence, the role-exclusivity
denials (screen / fund), and the missing-user-context rejection.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    setup_corridor, setup_sender, setup_recipient,
    create_locked_quote, create_transfer_from_quote,
    create_quote_payload, NON_EXISTENT_UUID, TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]
AGENT = TEST_USERS["remittance_agent_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]
OPERATOR = TEST_USERS["payout_operator_headers"]


# ─── priority pair: NOT_FOUND beats INVALID_REQUEST on quote create ─────────

def test_quote_nonexistent_corridor_beats_bad_principal(api):
    """PRD §3.9: "then that every path identifier and body foreign key resolves to an
    existing resource, checked left-to-right (`ERR_NOT_FOUND`); then that the body is
    well-formed — required fields present, enum values valid, and all amounts strictly
    greater than zero (`ERR_INVALID_REQUEST`)."

    Design: Difficulty/priority_pair_validation_conflict/not_found_beats_invalid_request_on_quote
    """
    sender = setup_sender()
    # corridor_id does not exist AND send_principal_minor is 0 (non-positive).
    # Existence is checked before body well-formedness -> ERR_NOT_FOUND wins.
    res = api.create_quote(create_quote_payload(
        NON_EXISTENT_UUID, sender["id"], send_principal_minor=0, payout_method="BANK"), AGENT)
    validate_error(res, "ERR_NOT_FOUND")


def test_quote_existing_corridor_bad_principal_is_invalid_request(api):
    """PRD §3.9: "then that the body is well-formed — required fields present, enum
    values valid, and all amounts strictly greater than zero (`ERR_INVALID_REQUEST`)."

    Design: Difficulty/priority_pair_validation_conflict/not_found_beats_invalid_request_on_quote
    """
    corridor = setup_corridor(with_fx=False, rolling_window_cap_minor=4000000)
    sender = setup_sender()
    # Corridor now resolves; the non-positive principal is the only failure left.
    res = api.create_quote(create_quote_payload(
        corridor["id"], sender["id"], send_principal_minor=0, payout_method="BANK"), AGENT)
    validate_error(res, "ERR_INVALID_REQUEST")


# ─── RBAC: agent cannot screen (corner: rbac) ───────────────────────────────

def test_remittance_agent_cannot_screen_transfer(api):
    """PRD §2.1: "When a caller's role is well-formed but is not permitted to perform
    the requested operation, the request is rejected with `ERR_FORBIDDEN_FOR_ROLE`."

    Design: Corner/rbac/remittance_agent_cannot_screen_transfer_returns_403
    """
    corridor = setup_corridor(rolling_window_cap_minor=4000000)
    sender = setup_sender()
    recipient = setup_recipient(sender["id"])
    quote = create_locked_quote(corridor["id"], sender["id"], 50000)
    transfer = create_transfer_from_quote(quote, recipient["id"])
    validate_success(api.fund_transfer(transfer["id"], AGENT), 200)
    # screen is ComplianceOfficer-exclusive; an agent calling it is forbidden.
    res = api.screen_transfer(transfer["id"], AGENT)
    validate_error(res, "ERR_FORBIDDEN_FOR_ROLE")
    after = validate_success(api.get_transfer(transfer["id"], AGENT), 200)
    assert after["compliance_status"] == "SCREENING", after["compliance_status"]


# ─── RBAC: operator cannot fund (corner: rbac) ──────────────────────────────

def test_payout_operator_cannot_fund_transfer(api):
    """PRD §2.1: "When a caller's role is well-formed but is not permitted to perform
    the requested operation, the request is rejected with `ERR_FORBIDDEN_FOR_ROLE`."

    Design: Corner/rbac/payout_operator_cannot_fund_transfer_returns_403
    """
    corridor = setup_corridor(rolling_window_cap_minor=4000000)
    sender = setup_sender()
    recipient = setup_recipient(sender["id"])
    quote = create_locked_quote(corridor["id"], sender["id"], 50000)
    transfer = create_transfer_from_quote(quote, recipient["id"])
    # fund is RemittanceAgent-exclusive; a payout operator calling it is forbidden.
    res = api.fund_transfer(transfer["id"], OPERATOR)
    validate_error(res, "ERR_FORBIDDEN_FOR_ROLE")
    after = validate_success(api.get_transfer(transfer["id"], AGENT), 200)
    assert after["funding_status"] == "UNFUNDED", after["funding_status"]


# ─── missing user context header (corner: rbac) ─────────────────────────────

def test_missing_user_context_header_rejected(api):
    """PRD §2.1: "Every request to the API must carry two mandatory HTTP headers:
    `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity
    in which they act. If either header is missing or malformed, the request is rejected
    with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

    Design: Corner/rbac/missing_user_context_header_returns_400
    """
    res = api.list_corridors(headers={})
    validate_error(res, "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER")
