"""Onboarding, authorizations, and request-level validation.

Corner (queue B) translations covering account/LOA lifecycle preconditions and
the request-validation ladder (auth, existence, well-formedness).
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    make_agent_headers, ops_headers,
)
import test_helpers.fixtures as fx
import test_helpers.factories as fac


def test_sign_already_signed_loa_is_invalid_state(api):
    """PRD §3.1: "The owning customer then signs it, moving DRAFT → SIGNED".
    PRD §2.6: "For a transition endpoint, the target resource must currently be
    in a state from which the requested transition is defined, else
    ERR_INVALID_STATE (HTTP 409)."

    Design: Corner/state_machines/sign_already_signed_loa_invalid_state
    """
    agent = fx.new_agent(api)
    customer = fx.new_customer(api, agent["id"])
    account = fx.new_account(api, customer["id"], agent["id"])
    loa = fx.draft_loa(api, account["id"], agent["id"])
    fx.sign_loa(api, loa["id"], customer["id"])

    resp = api.sign_authorization(loa["id"], fx.make_customer_headers(customer["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    after = get_success_data(api.get_authorization(loa["id"], make_agent_headers(agent["id"])))
    assert after["status"] == "SIGNED"


def test_verify_account_without_signed_loa_rejected(api):
    """PRD §3.1: "Verification requires that a SIGNED, non-expired Authorization
    exists for the account (else ERR_LOA_NOT_SIGNED)".

    Design: Corner/validations/account_verify_without_signed_loa_rejected
    """
    agent = fx.new_agent(api)
    customer = fx.new_customer(api, agent["id"])
    account = fx.new_account(api, customer["id"], agent["id"])
    fx.draft_loa(api, account["id"], agent["id"])  # drafted, never signed
    fx.add_usage(api, account["id"], agent["id"], "2025-12", 5000, is_actual=False)

    resp = api.verify_account(account["id"], make_agent_headers(agent["id"]))
    validate_error(resp, ApiErrorId.ERR_LOA_NOT_SIGNED.value)

    after = get_success_data(api.get_account(account["id"], make_agent_headers(agent["id"])))
    assert after["status"] == "PENDING_LOA"


def test_verify_account_without_usage_rejected(api):
    """PRD §3.1: "Verification requires that a SIGNED, non-expired Authorization
    exists for the account (else ERR_LOA_NOT_SIGNED) and that at least one
    UsageRecord exists for it (else ERR_NO_USAGE_DATA)."

    Design: Corner/validations/account_verify_without_usage_rejected
    """
    agent = fx.new_agent(api)
    customer = fx.new_customer(api, agent["id"])
    account = fx.new_account(api, customer["id"], agent["id"])
    loa = fx.draft_loa(api, account["id"], agent["id"])
    fx.sign_loa(api, loa["id"], customer["id"])  # signed, but no usage rows

    resp = api.verify_account(account["id"], make_agent_headers(agent["id"]))
    validate_error(resp, ApiErrorId.ERR_NO_USAGE_DATA.value)

    after = get_success_data(api.get_account(account["id"], make_agent_headers(agent["id"])))
    assert after["status"] == "PENDING_LOA"


def test_duplicate_account_number_same_utility_rejected(api):
    """PRD §3.1: "Account numbers must be unique per utility: if the supplied
    account_number already exists under the same utility_name, creation is
    rejected with ERR_DUPLICATE_ACCOUNT_NUMBER."

    Design: Corner/entities/duplicate_account_number_same_utility
    """
    agent = fx.new_agent(api)
    customer = fx.new_customer(api, agent["id"])
    hdr = make_agent_headers(agent["id"])
    first = fac.create_account_payload(customer["id"], agent["id"],
                                       utility_name="Oncor", account_number="ACC-DUP")
    get_success_data(api.create_account(first, hdr))

    dup = fac.create_account_payload(customer["id"], agent["id"],
                                     utility_name="Oncor", account_number="ACC-DUP")
    resp = api.create_account(dup, hdr)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_ACCOUNT_NUMBER.value)


def test_create_account_missing_required_field_rejected(api):
    """PRD §2.6: "For any write, the body must have all required fields present,
    valid enum values, non-negative integers where integers are expected, and
    parseable dates, else ERR_VALIDATION (HTTP 422)."

    Design: Corner/entities/create_account_missing_required_field
    """
    agent = fx.new_agent(api)
    payload = {
        "broker_agent_id": agent["id"],
        "utility_name": "Oncor",
        "account_number": "ACC-MISS",
        "commodity": "ELECTRICITY",
        "state_code": "TX",
        "estimated_annual_usage_kwh": 60000,
    }  # customer_id omitted
    resp = api.create_account(payload, make_agent_headers(agent["id"]))
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_get_account_not_found(api):
    """PRD §2.6: "All resources referenced by the path and body must exist,
    validated left-to-right in path order, else ERR_NOT_FOUND (HTTP 404)."

    Design: Corner/entities/get_account_not_found
    """
    agent = fx.new_agent(api)
    resp = api.get_account("00000000-0000-0000-0000-000000000000",
                           make_agent_headers(agent["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_missing_user_headers_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or carrying a malformed value,
    is rejected with ERR_UNAUTHENTICATED."

    Design: Corner/validations/missing_user_headers_unauthenticated
    """
    agent = fx.new_agent(api)
    customer = fx.new_customer(api, agent["id"])
    account = fx.new_account(api, customer["id"], agent["id"])

    resp = api.get_account(account["id"], headers={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_supplier_cannot_create_account_forbidden(api):
    """PRD §2.1: "When the headers are present but the role is not permitted to
    perform the requested operation, the request is rejected with ERR_FORBIDDEN."

    Design: Corner/validations/supplier_cannot_create_account_forbidden
    """
    agent = fx.new_agent(api)
    customer = fx.new_customer(api, agent["id"])
    supplier = fx.new_supplier(api)

    payload = fac.create_account_payload(customer["id"], agent["id"], account_number="ACC-SUP")
    resp = api.create_account(payload, fx.make_supplier_headers(supplier["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)
