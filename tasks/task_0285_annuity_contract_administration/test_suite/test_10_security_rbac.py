"""Role-based access control and authentication.

Each test translates exactly one corner-design rbac instance (queue B).
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    setup_active_fixed_contract,
    create_product_payload, create_contract_payload, create_crediting_event_payload,
    create_withdrawal_payload,
    TEST_USERS,
)

ADMIN = TEST_USERS["contract_admin_headers"]
CREDITING = TEST_USERS["crediting_officer_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


def test_crediting_officer_cannot_create_contract(api):
    """PRD §2.1: "`ContractAdmin` — sets up products, contracts, premiums".
    PRD §2.1: "When the headers are well-formed but the declared role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/crediting_officer_cannot_create_contract
    """
    product = validate_success(api.create_product(create_product_payload(), ADMIN), 201)
    res = api.create_contract(create_contract_payload(product["id"]), CREDITING)
    validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)


def test_contract_admin_cannot_settle_withdrawal(api):
    """PRD §2.1: "`ComplianceOfficer` — settles or rejects withdrawals".
    PRD §2.1: "When the headers are well-formed but the declared role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/contract_admin_cannot_settle_withdrawal
    """
    product, contract, _ = setup_active_fixed_contract(
        gross_premium_cents=2_000_000, fixed_annual_rate_bps=0,
        free_withdrawal_corridor_bps=10000,
        surrender_charge_schedule=[{"contract_year": 0, "charge_bps": 0}])
    wd = validate_success(api.create_withdrawal(create_withdrawal_payload(
        contract["id"], 100000, contract["version"]), ADMIN), 201)
    res = api.settle_withdrawal(wd["id"], ADMIN)
    validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)


def test_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or carrying a malformed
    value, is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_auth_headers_unauthenticated
    """
    res = api.list_contracts({})
    validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)


def test_compliance_officer_cannot_post_crediting_event(api):
    """PRD §2.1: "`CreditingOfficer` — posts crediting events (guaranteed
    interest, index-segment, and sub-account returns)".
    PRD §2.1: "When the headers are well-formed but the declared role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/compliance_officer_cannot_post_crediting_event
    """
    product, contract, _ = setup_active_fixed_contract(
        gross_premium_cents=2_000_000, fixed_annual_rate_bps=350)
    res = api.create_crediting_event(
        create_crediting_event_payload(contract["id"], "FIXED_GUARANTEED"), COMPLIANCE)
    validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)
