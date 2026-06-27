"""Composite setup helpers.

Every fixture builds its preconditions from scratch via PRD-declared endpoints,
because the harness restarts the server (empty DB) before every test. Setup calls
use get_success_data() (lenient) so a broken precondition surfaces as a clear
"Setup failed" rather than a confusing assertion mismatch.

Identity threading: the Borrower role is entity_backed:Account, so every
ownership-gated call uses make_borrower_headers(account["id"]).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    make_borrower_headers,
    make_loan_servicer_headers,
    make_compliance_officer_headers,
    make_platform_admin_headers,
)


DEFAULT_FUNDED_AT = "2026-02-01T00:00:00Z"


# --- Clock -----------------------------------------------------------------

def set_clock(iso8601: str):
    """Advance the logical clock to the given instant (PlatformAdmin)."""
    resp = api_client.set_clock({"to_iso8601": iso8601}, make_platform_admin_headers())
    get_success_data(resp)


def run_delinquency_sweep():
    get_success_data(api_client.run_delinquency_sweep({}, make_platform_admin_headers()))


def run_bureau_sweep():
    get_success_data(api_client.run_bureau_sweep({}, make_platform_admin_headers()))


def run_autopay():
    get_success_data(api_client.run_autopay({}, make_platform_admin_headers()))


# --- Tier 1: account / disclosure progression ------------------------------

def create_account(state_code="CA", email=None):
    """Create a fresh PENDING/BLOCKED account. Returns the account dict."""
    payload = {"full_name": "Test Borrower", "state_code": state_code}
    if email is None:
        # Unique within the (empty-on-startup) DB; counter-free since each test
        # starts clean, but stay distinct within a single test.
        email = f"acct-{state_code.lower()}-{_next()}@example.com"
    payload["email"] = email
    resp = api_client.create_account(payload, make_loan_servicer_headers())
    return get_success_data(resp)


_seq = [0]


def _next():
    _seq[0] += 1
    return _seq[0]


def create_verified_account(state_code="CA", email=None):
    """Account with kyc_status VERIFIED (disclosure still UNACKNOWLEDGED -> posture BLOCKED)."""
    acct = create_account(state_code=state_code, email=email)
    get_success_data(
        api_client.kyc_decision(acct["id"], {"decision": "VERIFIED"}, make_loan_servicer_headers())
    )
    return acct


def issue_disclosure(account_id, product_kind="LOAN", apr_bps=0, admin_fee_cents=0,
                     compliance_user_id="compliance-1"):
    """ComplianceOfficer issues a disclosure. Returns the disclosure dict."""
    resp = api_client.create_disclosure(
        account_id,
        {"product_kind": product_kind, "apr_bps": apr_bps, "admin_fee_cents": admin_fee_cents},
        make_compliance_officer_headers(compliance_user_id),
    )
    return get_success_data(resp)


def acknowledge_disclosure(disclosure_id, account_id):
    get_success_data(
        api_client.acknowledge_disclosure(disclosure_id, {}, make_borrower_headers(account_id))
    )


def setup_eligible_account_with_loan_disclosure(state_code="CA", apr_bps=0):
    """VERIFIED account + acknowledged LOAN disclosure -> posture ELIGIBLE.
    Returns (account, disclosure)."""
    acct = create_verified_account(state_code=state_code)
    disc = issue_disclosure(acct["id"], product_kind="LOAN", apr_bps=apr_bps)
    acknowledge_disclosure(disc["id"], acct["id"])
    # Re-read account so posture/version reflect the acknowledgement.
    acct = get_success_data(api_client.get_account(acct["id"], make_loan_servicer_headers()))
    return acct, disc


def setup_eligible_account_with_card_disclosure(state_code="CA", apr_bps=0):
    """VERIFIED account + acknowledged SECURED_CARD disclosure -> posture ELIGIBLE.
    Returns (account, disclosure)."""
    acct = create_verified_account(state_code=state_code)
    disc = issue_disclosure(acct["id"], product_kind="SECURED_CARD", apr_bps=apr_bps)
    acknowledge_disclosure(disc["id"], acct["id"])
    acct = get_success_data(api_client.get_account(acct["id"], make_loan_servicer_headers()))
    return acct, disc


# --- Tier 1/3: loan lifecycle ---------------------------------------------

def create_pending_loan(account_id, disclosure_id, principal_cents=60000, term_months=12):
    """Create a PENDING loan. Returns the loan dict."""
    resp = api_client.create_loan(
        {
            "account_id": account_id,
            "disclosure_id": disclosure_id,
            "principal_cents": principal_cents,
            "term_months": term_months,
        },
        make_borrower_headers(account_id),
    )
    return get_success_data(resp)


def fund_loan(loan_id, servicer_user_id="servicer-1"):
    """Fund a PENDING loan -> ACTIVE. Returns the funded loan dict (carries version)."""
    resp = api_client.fund_loan(loan_id, {}, make_loan_servicer_headers(servicer_user_id))
    return get_success_data(resp)


def setup_funded_loan(state_code="CA", apr_bps=0, principal_cents=60000, term_months=12,
                      funded_at=DEFAULT_FUNDED_AT, servicer_user_id="servicer-1"):
    """Full chain to an ACTIVE funded loan at a known funded_at.
    Returns (account, disclosure, loan) where loan is the funded entity."""
    set_clock(funded_at)
    acct, disc = setup_eligible_account_with_loan_disclosure(state_code=state_code, apr_bps=apr_bps)
    loan = create_pending_loan(acct["id"], disc["id"], principal_cents=principal_cents,
                               term_months=term_months)
    loan = fund_loan(loan["id"], servicer_user_id=servicer_user_id)
    return acct, disc, loan


def post_payment(loan_id, account_id, amount_cents, expected_loan_version, source="MANUAL"):
    """Post a payment against a loan with an explicit expected_loan_version.
    Returns the payment dict."""
    resp = api_client.create_payment(
        {
            "loan_id": loan_id,
            "amount_cents": amount_cents,
            "source": source,
            "expected_loan_version": expected_loan_version,
        },
        make_borrower_headers(account_id),
    )
    return get_success_data(resp)


def loan_version(loan_id, account_id):
    """Re-read the loan and return its current version."""
    loan = get_success_data(api_client.get_loan(loan_id, make_borrower_headers(account_id)))
    return loan["version"]


def setup_paid_off_loan(state_code="CA", principal_cents=60000, term_months=12,
                        funded_at=DEFAULT_FUNDED_AT, servicer_user_id="servicer-1"):
    """ACTIVE loan paid off via a single lump payment of principal_cents (apr 0).
    Returns (account, disclosure, loan) where loan is the PAID_OFF entity (re-read)."""
    acct, disc, loan = setup_funded_loan(
        state_code=state_code, apr_bps=0, principal_cents=principal_cents,
        term_months=term_months, funded_at=funded_at, servicer_user_id=servicer_user_id,
    )
    post_payment(loan["id"], acct["id"], principal_cents, loan["version"])
    loan = get_success_data(api_client.get_loan(loan["id"], make_borrower_headers(acct["id"])))
    return acct, disc, loan


# --- Tier 2/3: secured card lifecycle -------------------------------------

def create_card(account_id, disclosure_id):
    """Create a PENDING secured card. Returns the card dict."""
    resp = api_client.create_secured_card(
        {"account_id": account_id, "disclosure_id": disclosure_id},
        make_borrower_headers(account_id),
    )
    return get_success_data(resp)


def post_deposit(card_id, account_id, amount_cents, expected_card_version):
    """Post a deposit; returns the deposit dict."""
    resp = api_client.create_deposit(
        card_id,
        {"amount_cents": amount_cents, "expected_card_version": expected_card_version},
        make_borrower_headers(account_id),
    )
    return get_success_data(resp)


def card_version(card_id, account_id):
    card = get_success_data(api_client.get_secured_card(card_id, make_borrower_headers(account_id)))
    return card["version"]


def setup_active_card(account_id, card_disclosure_id, deposit_cents=50000):
    """PENDING card -> deposit -> FUNDED -> activate -> ACTIVE.
    Returns the ACTIVE card dict (re-read)."""
    card = create_card(account_id, card_disclosure_id)
    post_deposit(card["id"], account_id, deposit_cents, card["version"])
    get_success_data(api_client.activate_card(card["id"], {}, make_borrower_headers(account_id)))
    return get_success_data(api_client.get_secured_card(card["id"], make_borrower_headers(account_id)))


def setup_eligible_account_with_active_card(state_code="CA", deposit_cents=50000):
    """VERIFIED + acknowledged SECURED_CARD disclosure + ACTIVE card.
    Returns (account, card_disclosure, card)."""
    acct, cdisc = setup_eligible_account_with_card_disclosure(state_code=state_code)
    card = setup_active_card(acct["id"], cdisc["id"], deposit_cents=deposit_cents)
    return acct, cdisc, card


def setup_graduated_loan_with_active_card(state_code="CA", principal_cents=60000,
                                          deposit_amounts=(50000,),
                                          funded_at=DEFAULT_FUNDED_AT,
                                          servicer_user_id="servicer-1"):
    """End-to-end release-ready scenario on a single account:
      - LOAN apr-0 disclosure acknowledged; loan funded by `servicer_user_id`,
        lump-paid to PAID_OFF (on_time_streak high), then GRADUATED.
      - SECURED_CARD disclosure acknowledged; card with the given POSTED deposits, ACTIVE.
      - Graduation flags the ACTIVE zero-balance card graduation_eligible=true.
    Returns (account, loan, card, total_deposit_cents).
    """
    set_clock(funded_at)
    acct = create_verified_account(state_code=state_code)
    ldisc = issue_disclosure(acct["id"], product_kind="LOAN", apr_bps=0)
    cdisc = issue_disclosure(acct["id"], product_kind="SECURED_CARD", apr_bps=0)
    acknowledge_disclosure(ldisc["id"], acct["id"])
    acknowledge_disclosure(cdisc["id"], acct["id"])

    loan = create_pending_loan(acct["id"], ldisc["id"], principal_cents=principal_cents,
                               term_months=12)
    loan = fund_loan(loan["id"], servicer_user_id=servicer_user_id)
    post_payment(loan["id"], acct["id"], principal_cents, loan["version"])

    # Card: stack the deposits (re-reading version between each), then activate.
    card = create_card(acct["id"], cdisc["id"])
    total_deposit = 0
    ver = card["version"]
    for amt in deposit_amounts:
        post_deposit(card["id"], acct["id"], amt, ver)
        total_deposit += amt
        ver = card_version(card["id"], acct["id"])
    get_success_data(api_client.activate_card(card["id"], {}, make_borrower_headers(acct["id"])))

    # Graduate the loan (must be the same servicer for setup; SoD only bites on release).
    get_success_data(
        api_client.graduate_loan(loan["id"], {}, make_loan_servicer_headers(servicer_user_id))
    )

    loan = get_success_data(api_client.get_loan(loan["id"], make_borrower_headers(acct["id"])))
    card = get_success_data(api_client.get_secured_card(card["id"], make_borrower_headers(acct["id"])))
    return acct, loan, card, total_deposit
