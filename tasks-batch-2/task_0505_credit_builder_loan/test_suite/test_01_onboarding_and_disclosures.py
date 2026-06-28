"""Onboarding, account CRUD, disclosure lifecycle, and APR-cap validation.

Each test builds its own preconditions; the server restarts (empty DB) before every test.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, validate_error_is_one_of,
    ApiErrorId,
    assert_account, assert_disclosure,
    make_loan_servicer_headers, make_compliance_officer_headers, make_borrower_headers,
    create_verified_account,
)


# =========================================================================
# Corner / entities
# =========================================================================

def test_create_account_returns_system_fields(api):
    """PRD §3.1: "A new account begins with `kyc_status` of `PENDING`, `disclosure_status` of `UNACKNOWLEDGED`, `status` of `OPEN`, a `posture` of `BLOCKED`, and a released-funds `wallet_cents` of 0."

    Design: Corner/entities/create_account_returns_201_with_system_fields
    """
    resp = api.create_account(
        {"email": "c1@x.com", "full_name": "C One", "state_code": "CA"},
        make_loan_servicer_headers(),
    )
    data = validate_success(resp, expected_status=201)
    assert_account(data)
    assert data["kyc_status"] == "PENDING"
    assert data["posture"] == "BLOCKED"
    assert data["status"] == "OPEN"
    assert data["wallet_cents"] == 0
    assert data["version"] == 1


def test_get_account_returns_stored_entity(api):
    """PRD §3.1: "A `LoanServicer` registers a borrower by creating an `Account` with the borrower's contact `email`, legal `full_name`, and two-letter `state_code`."

    Design: Corner/entities/get_account_returns_stored_entity
    """
    created = validate_success(
        api.create_account(
            {"email": "c2@x.com", "full_name": "C Two", "state_code": "CA"},
            make_loan_servicer_headers(),
        ),
        expected_status=201,
    )
    fetched = validate_success(api.get_account(created["id"], make_loan_servicer_headers()))
    assert fetched["id"] == created["id"]
    assert fetched["email"] == "c2@x.com"


def test_list_accounts_paginated_envelope(api):
    """PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope."

    Design: Corner/entities/list_accounts_paginated_envelope
    """
    api.create_account(
        {"email": "c3a@x.com", "full_name": "C 3a", "state_code": "CA"},
        make_loan_servicer_headers(),
    )
    api.create_account(
        {"email": "c3b@x.com", "full_name": "C 3b", "state_code": "NY"},
        make_loan_servicer_headers(),
    )
    resp = api.list_accounts(make_loan_servicer_headers(), params={"limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1


def test_get_account_not_found(api):
    """PRD §2.5: "a referenced account, loan, card, disclosure, payment, quote, or enrollment that does not exist yields `ERR_NOT_FOUND` before any business rule is evaluated."

    Design: Corner/entities/get_account_not_found
    """
    resp = api.get_account("11111111-1111-4111-8111-111111111111", make_loan_servicer_headers())
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


# =========================================================================
# Corner / validations (disclosure APR cap)
# =========================================================================

def test_apr_cap_exceeded_on_disclosure_issue(api):
    """PRD §3.1: "the cap is 3600 basis points for `CA`, 2500 for `NY`, 9999 for `TX`, and 3000 for `FL`; if `apr_bps` exceeds the cap for the account's `state_code`, issuance is rejected with `ERR_APR_CAP_EXCEEDED` (HTTP 422)."

    Design: Corner/validations/apr_cap_exceeded_on_disclosure_issue
    """
    acct = create_verified_account(state_code="NY")
    resp = api.create_disclosure(
        acct["id"],
        {"product_kind": "LOAN", "apr_bps": 2600, "admin_fee_cents": 0},
        make_compliance_officer_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_APR_CAP_EXCEEDED)


def test_apr_at_cap_accepted(api):
    """PRD §3.1: "the cap is 3600 basis points for `CA`, 2500 for `NY`, 9999 for `TX`, and 3000 for `FL`; if `apr_bps` exceeds the cap for the account's `state_code`, issuance is rejected with `ERR_APR_CAP_EXCEEDED` (HTTP 422)."

    Design: Corner/validations/apr_at_cap_accepted
    """
    acct = create_verified_account(state_code="NY")
    resp = api.create_disclosure(
        acct["id"],
        {"product_kind": "LOAN", "apr_bps": 2500, "admin_fee_cents": 0},
        make_compliance_officer_headers(),
    )
    data = validate_success(resp, expected_status=201)
    assert data["apr_bps"] == 2500
    assert data["status"] == "ISSUED"


def test_unsupported_state_invalid_request(api):
    """PRD §3.1: "the `state_code` must be one of the supported states — `CA`, `NY`, `TX`, or `FL`."

    Design: Corner/errors/unsupported_state_invalid_request
    """
    resp = api.create_account(
        {"email": "x2@x.com", "full_name": "X Two", "state_code": "ZZ"},
        make_loan_servicer_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


# =========================================================================
# Corner / state_machines (disclosure lifecycle)
# =========================================================================

def test_disclosure_supersede_on_reissue(api):
    """PRD §3.1: "Issuing a new disclosure for the same account and the same `product_kind` automatically supersedes any prior disclosure that was still `ISSUED` for that pair, moving the older one to `SUPERSEDED` so it can no longer be acknowledged."

    Design: Corner/state_machines/disclosure_supersede_on_reissue
    """
    acct = create_verified_account(state_code="CA")
    disc1 = validate_success(
        api.create_disclosure(
            acct["id"], {"product_kind": "LOAN", "apr_bps": 1599, "admin_fee_cents": 0},
            make_compliance_officer_headers(),
        ),
        expected_status=201,
    )
    disc2 = validate_success(
        api.create_disclosure(
            acct["id"], {"product_kind": "LOAN", "apr_bps": 1499, "admin_fee_cents": 0},
            make_compliance_officer_headers(),
        ),
        expected_status=201,
    )
    refetched1 = validate_success(api.get_disclosure(disc1["id"], make_compliance_officer_headers()))
    refetched2 = validate_success(api.get_disclosure(disc2["id"], make_compliance_officer_headers()))
    assert refetched1["status"] == "SUPERSEDED"
    assert refetched2["status"] == "ISSUED"


def test_acknowledge_superseded_disclosure_invalid_state(api):
    """PRD §3.1: "Issuing a new disclosure for the same account and the same `product_kind` automatically supersedes any prior disclosure that was still `ISSUED` for that pair, moving the older one to `SUPERSEDED` so it can no longer be acknowledged."
    PRD §3.1: "Acknowledgement is only valid while the disclosure `status` is `ISSUED` and the acting borrower owns the disclosure's `account_id`"

    Design: Corner/state_machines/acknowledge_superseded_disclosure_invalid_state
    """
    acct = create_verified_account(state_code="CA")
    disc1 = validate_success(
        api.create_disclosure(
            acct["id"], {"product_kind": "LOAN", "apr_bps": 1599, "admin_fee_cents": 0},
            make_compliance_officer_headers(),
        ),
        expected_status=201,
    )
    validate_success(
        api.create_disclosure(
            acct["id"], {"product_kind": "LOAN", "apr_bps": 1499, "admin_fee_cents": 0},
            make_compliance_officer_headers(),
        ),
        expected_status=201,
    )
    resp = api.acknowledge_disclosure(disc1["id"], {}, make_borrower_headers(acct["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
