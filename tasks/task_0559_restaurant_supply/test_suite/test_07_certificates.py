"""Tax-exempt certificate lifecycle: reject/resubmit cycle, approval eligibility,
clock-driven expiry, and the account reinstate guard.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS, make_buyer_headers,
    certificate_payload,
    fixtures,
)

AM = TEST_USERS["account_manager_headers"]
WH = TEST_USERS["warehouse_headers"]


# --------------------------------------------------------------------------- #
# non_linear_state_machine / tax_cert_rejected_resubmit_cycle
# --------------------------------------------------------------------------- #
def _submitted_certificate(api):
    acct = fixtures.create_account(api)
    cert = validate_success(
        api.create_certificate(acct["id"], certificate_payload(cert_number="TX-1001",
                                                               expiry_date="2027-01-01T00:00:00Z"),
                               make_buyer_headers(acct["id"])), 201)
    return acct, cert


def test_reject_moves_certificate_to_rejected(api):
    """PRD §3.2: "Rejection also requires the certificate to be `SUBMITTED` (otherwise
    `ERR_CERT_NOT_SUBMITTED`) and simply transitions it `SUBMITTED → REJECTED` with no effect on
    the account."

    Design: Difficulty/non_linear_state_machine/tax_cert_rejected_resubmit_cycle
    """
    _acct, cert = _submitted_certificate(api)
    rejected = validate_success(api.reject_certificate(cert["id"], AM))
    assert rejected["status"] == "REJECTED"


def test_resubmit_rejected_certificate_returns_to_submitted(api):
    """PRD §3.2: "The owning `Buyer` may resubmit it, which requires the certificate to be
    `REJECTED` (otherwise `ERR_CERT_NOT_REJECTED`) and requires the acting `Buyer`'s `X-User-ID` to
    equal the certificate's `account_id` (otherwise `ERR_NOT_ACCOUNT_OWNER`); the certificate cycles
    `REJECTED → SUBMITTED` for a fresh review."

    Design: Difficulty/non_linear_state_machine/tax_cert_rejected_resubmit_cycle
    """
    acct, cert = _submitted_certificate(api)
    validate_success(api.reject_certificate(cert["id"], AM))
    resubmitted = validate_success(api.resubmit_certificate(cert["id"], make_buyer_headers(acct["id"])))
    assert resubmitted["status"] == "SUBMITTED"


# --------------------------------------------------------------------------- #
# state_machines / resubmit_submitted_cert_returns_not_rejected (corner)
# --------------------------------------------------------------------------- #
def test_resubmit_submitted_certificate_rejected(api):
    """PRD §3.2: "The owning `Buyer` may resubmit it, which requires the certificate to be
    `REJECTED` (otherwise `ERR_CERT_NOT_REJECTED`)".

    Design: Corner/state_machines/resubmit_submitted_cert_returns_not_rejected
    """
    acct, cert = _submitted_certificate(api)  # freshly SUBMITTED, never rejected
    resp = api.resubmit_certificate(cert["id"], make_buyer_headers(acct["id"]))
    validate_error(resp, ApiErrorId.ERR_CERT_NOT_REJECTED.value)


# --------------------------------------------------------------------------- #
# validations / approve_expired_dated_certificate_rejected (corner)
# --------------------------------------------------------------------------- #
def test_approve_certificate_with_past_expiry_rejected(api):
    """PRD §3.2: "requires the certificate's `expiry_date` to be strictly after the current logical
    clock instant (otherwise `ERR_CERT_ALREADY_EXPIRED`)".

    Design: Corner/validations/approve_expired_dated_certificate_rejected
    """
    fixtures.set_clock(api, "2026-05-01T00:00:00Z")
    acct = fixtures.create_account(api, credit_limit_cents=100000)
    cert = validate_success(
        api.create_certificate(acct["id"], certificate_payload(cert_number="TX-5005",
                                                               expiry_date="2026-04-01T00:00:00Z"),
                               make_buyer_headers(acct["id"])), 201)
    resp = api.approve_certificate(cert["id"], AM)
    validate_error(resp, ApiErrorId.ERR_CERT_ALREADY_EXPIRED.value)


# --------------------------------------------------------------------------- #
# state_machines / clock_advance_expires_approved_certificate (corner)
# --------------------------------------------------------------------------- #
def test_clock_advance_expires_approved_certificate(api):
    """PRD §2.6: "any `TaxExemptCertificate` currently in `APPROVED` state whose `expiry_date` is
    at or before the new clock instant transitions to `EXPIRED`, and each such certificate's owning
    account moves its `tax_exempt_status` to `EXPIRED` with the account's `version` incremented."

    Design: Corner/state_machines/clock_advance_expires_approved_certificate
    """
    fixtures.set_clock(api, "2026-05-01T00:00:00Z")
    acct = fixtures.create_account(api, credit_limit_cents=100000)
    cert = validate_success(
        api.create_certificate(acct["id"], certificate_payload(cert_number="TX-3003",
                                                               expiry_date="2026-06-01T00:00:00Z"),
                               make_buyer_headers(acct["id"])), 201)
    validate_success(api.approve_certificate(cert["id"], AM))
    fixtures.set_clock(api, "2026-07-01T00:00:00Z")
    cert_after = validate_success(api.get_certificate(cert["id"], WH))
    acct_after = validate_success(api.get_account(acct["id"], WH))
    assert cert_after["status"] == "EXPIRED"
    assert acct_after["tax_exempt_status"] == "EXPIRED"


# --------------------------------------------------------------------------- #
# state_machines / reinstate_active_account_returns_not_suspended (corner)
# --------------------------------------------------------------------------- #
def test_reinstate_active_account_rejected(api):
    """PRD §3.1: "Lifting a hold moves a `SUSPENDED` account back to `ACTIVE`, and requires the
    account to currently be `SUSPENDED`, otherwise `ERR_ACCOUNT_NOT_SUSPENDED`."

    Design: Corner/state_machines/reinstate_active_account_returns_not_suspended
    """
    acct = fixtures.create_account(api, credit_limit_cents=100000)
    resp = api.reinstate_account(acct["id"], AM)
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_NOT_SUSPENDED.value)
