"""Access control and reference-entity CRUD: authentication, role authorization,
account ownership, not-found resolution, and accountholder creation/validation.
"""
from test_helpers import (
    validate_success, validate_error,
    assert_accountholder, ApiErrorId, NON_EXISTENT_UUID,
    create_accountholder_payload, create_account_payload,
)
from test_helpers.fixtures import (
    ADMIN, set_clock, create_accountholder, create_employer, open_account,
    attest_coverage, verify_account, setup_active_account,
)
from test_helpers.test_users import make_accountholder_headers, make_employer_headers
from test_helpers.api_client import api_client

ADMIN_HDR = ADMIN


# ── create_accountholder_returns_201_with_fields (Corner/entities) ───────────

def test_create_accountholder_returns_201_with_minted_fields(api):
    """PRD §2.4: "Every resource is addressed by an `id`, a server-minted UUID with no
    type prefix."
    PRD §2.4: "`version`, an integer that starts at creation".
    PRD §3.1: "An accountholder is created with a `full_name`, a contact `email`, and a
    `date_of_birth`."

    Design: Corner/entities/create_accountholder_returns_201_with_fields
    """
    res = api.create_accountholder(
        create_accountholder_payload(full_name="Pat Quy", email="pat.quy@x.com",
                                     date_of_birth="1980-01-01"), ADMIN_HDR)
    holder = validate_success(res, 201)
    assert_accountholder(holder)
    assert holder["full_name"] == "Pat Quy"
    assert holder["version"] == 1


# ── create_accountholder_missing_email_returns_invalid_request (Corner) ──────

def test_create_accountholder_missing_email_rejected(api):
    """PRD §2.9: "Body validation comes next: required fields must be present and
    well-typed, all monetary amounts must be positive integers, and every enum value
    must be valid, else `ERR_INVALID_REQUEST` (HTTP 422)."

    POST /hsa/accountholders omitting the required email returns ERR_INVALID_REQUEST.

    Design: Corner/entities/create_accountholder_missing_email_returns_invalid_request
    """
    payload = create_accountholder_payload(full_name="No Email",
                                           date_of_birth="1980-01-01")
    del payload["email"]
    res = api.create_accountholder(payload, ADMIN_HDR)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)


# ── get_account_nonexistent_returns_not_found (Corner/entities) ──────────────

def test_get_nonexistent_account_returns_not_found(api):
    """PRD §2.7: "the platform validates the identifiers left to right and rejects the
    first one that does not resolve with `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/get_account_nonexistent_returns_not_found
    """
    res = api.get_account(NON_EXISTENT_UUID, ADMIN_HDR)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND)


# ── missing_role_header_returns_unauthenticated (Corner/errors) ──────────────

def test_missing_role_header_returns_unauthenticated(api):
    """PRD §2.1: "If `X-User-Role` is missing or is not one of the recognized role names,
    the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/errors/missing_role_header_returns_unauthenticated
    """
    headers = {"X-User-ID": "anon", "Content-Type": "application/json"}
    res = api.create_accountholder(
        create_accountholder_payload(full_name="No Role", email="no.role@x.com",
                                     date_of_birth="1980-01-01"), headers)
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED)


# ── wrong_role_open_account_returns_forbidden (Corner/errors) ────────────────

def test_accountholder_opening_account_returns_forbidden(api):
    """PRD §2.1: "If the role is recognized but is not permitted to perform the requested
    operation, the request is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    POST /hsa/accounts is AccountAdmin-only; an Accountholder calling it -> ERR_FORBIDDEN.

    Design: Corner/errors/wrong_role_open_account_returns_forbidden
    """
    holder = create_accountholder(date_of_birth="1980-06-16")
    res = api.create_account(create_account_payload(holder["id"], plan_year=2026),
                             make_accountholder_headers(holder["id"]))
    validate_error(res, ApiErrorId.ERR_FORBIDDEN)


# ── holder_acts_on_other_account_returns_not_account_owner (Corner/errors) ───

def test_holder_requesting_distribution_on_others_account_rejected(api):
    """PRD §2.1: "for holder-scoped writes — verifying an account, requesting a
    distribution, and activating, suspending, or closing a card — the acting
    `Accountholder` must own the target HSA, meaning the account's `accountholder_id`
    equals `X-User-ID`; a mismatch is rejected with `ERR_NOT_ACCOUNT_OWNER` (HTTP 403)."

    Holder hB requesting a distribution on hA's account -> ERR_NOT_ACCOUNT_OWNER.

    Design: Corner/errors/holder_acts_on_other_account_returns_not_account_owner
    """
    holder_b = create_accountholder(full_name="Holder B", email="hb@x.com",
                                    date_of_birth="1980-08-18")
    account, holder_a = setup_active_account(coverage_tier="SELF_ONLY",
                                             date_of_birth="1980-07-17")
    res = api.create_distribution(
        account["id"], {"method": "REIMBURSEMENT", "amount_cents": 10000},
        make_accountholder_headers(holder_b["id"]))
    validate_error(res, ApiErrorId.ERR_NOT_ACCOUNT_OWNER)


# ── employer_cannot_post_contribution (Corner/rbac) ──────────────────────────

def test_employer_cannot_post_contribution(api):
    """PRD §2.1: "An employer may only create payroll contributions on, and read
    contributions of, accounts it sponsors; ownership ties the account's `employer_id` to
    `X-User-ID`."
    PRD §3.4: "Posting a pending contribution is an admin action that actually settles
    the money and runs the IRS guardrail."

    An Employer may create a PAYROLL contribution but posting it is an admin action; an
    Employer calling post -> ERR_FORBIDDEN.

    Design: Corner/rbac/employer_cannot_post_contribution
    """
    holder = create_accountholder(date_of_birth="1980-11-21")
    employer = create_employer()
    account = open_account(holder["id"], plan_year=2026, employer_id=employer["id"])
    attest_coverage(account["id"], "SELF_ONLY", 1, 12)
    verify_account(account["id"], holder["id"], account["verification_token"])
    emp_hdr = make_employer_headers(employer["id"])
    contrib = validate_success(
        api.create_contribution(account["id"],
                                {"channel": "PAYROLL", "amount_cents": 30000}, emp_hdr),
        201)
    res = api.post_contribution(account["id"], contrib["id"], emp_hdr)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN)
