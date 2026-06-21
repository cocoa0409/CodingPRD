"""Composite setup helpers.

Each test runs against a freshly-restarted, empty server, so every fixture builds
its preconditions from scratch using only PRD-declared endpoints. Setup calls use
get_success_data() (lenient) so a setup failure surfaces clearly.

Identity threading: Borrower and Investor are entity-backed (PRD §2.1), so any
ownership-gated call uses make_borrower_headers(borrower["id"]) /
make_investor_headers(investor["id"]) with the real entity id — never the shared
TEST_USERS fallback.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_borrower_payload,
    create_loan_application_payload,
    create_investor_payload,
    deposit_payload,
    create_investment_payload,
    create_repayment_payload,
    create_disclosure_payload,
    set_clock_payload,
)
from .test_users import (
    TEST_USERS,
    make_borrower_headers,
    make_investor_headers,
    make_underwriter_headers,
)
from .constants import BIG_DEPOSIT_CENTS

ADMIN = TEST_USERS["platform_admin_headers"]
CO = TEST_USERS["compliance_officer_headers"]
# Distinct underwriter operator identities so segregation-of-duties is satisfied
# by default (scorer != approver, PRD §3.3).
UW_SCORER = make_underwriter_headers("uw_scorer")
UW_APPROVER = make_underwriter_headers("uw_approver")

# A-grade Plaid profile (score 92.0 -> grade A -> apr 0.0599).
A_GRADE_PROFILE = dict(
    plaid_avg_monthly_revenue_cents=3_000_000,
    plaid_monthly_debt_payment_cents=1_000_000,
    plaid_nsf_count_90d=0,
    plaid_account_age_months=48,
)
# An F-grade Plaid profile (score < 40 -> grade F).
F_GRADE_PROFILE = dict(
    plaid_avg_monthly_revenue_cents=300_000,
    plaid_monthly_debt_payment_cents=2_000_000,
    plaid_nsf_count_90d=6,
    plaid_account_age_months=6,
)


# --------------------------------------------------------------------------
# Clock
# --------------------------------------------------------------------------

def set_clock(iso: str):
    """Set the server's logical UTC clock (PRD §3.8)."""
    return get_success_data(api_client.set_clock(set_clock_payload(iso), ADMIN))


# --------------------------------------------------------------------------
# Tier 1 / 2: borrower + application + scored / loan origination
# --------------------------------------------------------------------------

def create_borrower(**overrides) -> dict:
    """Register an ACTIVE borrower. Returns the Borrower object."""
    return get_success_data(api_client.create_borrower(create_borrower_payload(**overrides), ADMIN))


def create_investor(deposit_cents: int = BIG_DEPOSIT_CENTS, **overrides) -> dict:
    """Register an investor and (by default) fund its capital_base. Returns the
    re-read Investor reflecting the deposit."""
    inv = get_success_data(api_client.create_investor(create_investor_payload(**overrides), ADMIN))
    if deposit_cents:
        # Deposit is an Investor-owned operation; thread the real investor id.
        get_success_data(
            api_client.deposit(inv["id"], deposit_payload(deposit_cents),
                               make_investor_headers(inv["id"]))
        )
        inv = get_success_data(api_client.get_investor(inv["id"], ADMIN))
    return inv


def create_application(borrower=None, plaid_profile=None, **app_overrides):
    """Create a borrower (if not supplied) and submit a SUBMITTED application.
    Returns (borrower, application)."""
    if borrower is None:
        borrower = create_borrower()
    profile = dict(A_GRADE_PROFILE if plaid_profile is None else plaid_profile)
    # app_overrides (e.g. individual plaid_* fields or requested_principal_cents)
    # take precedence over the baseline profile so callers can tweak a single
    # subscore input without colliding with the profile's default for that key.
    profile.update(app_overrides)
    payload = create_loan_application_payload(borrower["id"], **profile)
    app = get_success_data(
        api_client.create_loan_application(payload, make_borrower_headers(borrower["id"]))
    )
    return borrower, app


def create_scored_application(borrower=None, plaid_profile=None, scorer_id="uw_scorer",
                              **app_overrides):
    """Submit and SCORE an application. Returns (borrower, scored_application)."""
    borrower, app = create_application(borrower, plaid_profile, **app_overrides)
    scored = get_success_data(
        api_client.score_application(app["id"], make_underwriter_headers(scorer_id))
    )
    return borrower, scored


def create_funding_loan(borrower=None, plaid_profile=None, scorer_id="uw_scorer",
                        approver_id="uw_approver", **app_overrides):
    """Score and APPROVE an A-grade application, originating a FUNDING loan.
    Returns (borrower, application, loan)."""
    borrower, scored = create_scored_application(
        borrower, plaid_profile, scorer_id=scorer_id, **app_overrides
    )
    get_success_data(
        api_client.approve_application(scored["id"], make_underwriter_headers(approver_id))
    )
    loans, _ = list_loans_for_application(scored["id"])
    loan = loans[0]
    return borrower, scored, loan


def list_loans_for_application(application_id: str):
    resp = api_client.list_loans(ADMIN, params={"application_id": application_id})
    body = resp.json()
    data = body["data"]
    meta = body.get("meta", {})
    return data, meta


def get_loan(loan_id: str) -> dict:
    return get_success_data(api_client.get_loan(loan_id, ADMIN))


def get_loan_version(loan_id: str) -> int:
    return get_loan(loan_id)["version"]


# --------------------------------------------------------------------------
# Tier 2/3: file disclosure, fund, disburse
# --------------------------------------------------------------------------

def file_disclosure(loan_id: str, document_type="SERIES_NOTE_PROSPECTUS", officer_id="co_1") -> dict:
    """File a disclosure for a loan as a ComplianceOfficer (PRD §3.8)."""
    return get_success_data(
        api_client.create_disclosure(
            create_disclosure_payload(loan_id, document_type),
            _co_headers(officer_id),
        )
    )


def file_prospectus(loan_id: str, officer_id="co_1") -> dict:
    """File a FILED SERIES_NOTE_PROSPECTUS disclosure for a loan (PRD §3.5/§3.8)."""
    return file_disclosure(loan_id, "SERIES_NOTE_PROSPECTUS", officer_id)


def _co_headers(officer_id="co_1"):
    from .test_users import make_compliance_officer_headers
    return make_compliance_officer_headers(officer_id)


def commit_investment(loan_id: str, investor: dict, amount_cents: int,
                      expected_loan_version: int = None) -> dict:
    """Commit an investment to a FUNDING loan, threading the OCC token. When
    expected_loan_version is None the current loan.version is read first. Returns
    the created Investment."""
    if expected_loan_version is None:
        expected_loan_version = get_loan_version(loan_id)
    payload = create_investment_payload(
        investor["id"], loan_id, amount_cents, expected_loan_version
    )
    return get_success_data(
        api_client.create_investment(payload, make_investor_headers(investor["id"]))
    )


def fund_loan_fully(loan, shares):
    """Fully fund a FUNDING loan with one investment per (investor, amount) share,
    threading the loan version between commits (each commit bumps loan.version,
    PRD §3.4). `shares` is a list of (investor_dict, amount_cents). Returns the
    list of created Investment objects in commit order."""
    investments = []
    for investor, amount in shares:
        v = get_loan_version(loan["id"])
        inv = commit_investment(loan["id"], investor, amount, expected_loan_version=v)
        investments.append(inv)
    return investments


def disburse_loan(loan_id: str) -> dict:
    """Disburse a fully-funded, disclosed loan -> REPAYMENT (PRD §3.5)."""
    return get_success_data(api_client.disburse_loan(loan_id, ADMIN))


# --------------------------------------------------------------------------
# Tier 3: a single composite that lands a disbursed REPAYMENT loan with a known
# set of investors. The workhorse for the bulk of the difficulty/corner setups.
# --------------------------------------------------------------------------

def setup_repayment_loan(investor_shares, funded_at="2026-06-01T00:00:00.000Z",
                         requested_principal_cents=1_200_000, term_months=12,
                         deposit_each=BIG_DEPOSIT_CENTS, max_single_loan_pct=1):
    """Full pipeline to a disbursed loan in REPAYMENT.

    investor_shares: list of amount_cents, one per investor. The sum MUST equal
    requested_principal_cents (fully funded, exact — PRD §3.5).

    Returns dict with keys: borrower, application, loan (re-read in REPAYMENT),
    investors (list), investments (list, parallel to investor_shares).
    """
    set_clock(funded_at)
    borrower, app, loan = create_funding_loan(
        requested_principal_cents=requested_principal_cents, term_months=term_months
    )
    file_prospectus(loan["id"])
    investors = []
    shares = []
    for amount in investor_shares:
        inv = create_investor(deposit_cents=deposit_each,
                              max_single_loan_pct=max_single_loan_pct)
        investors.append(inv)
        shares.append((inv, amount))
    investments = fund_loan_fully(loan, shares)
    disburse_loan(loan["id"])
    loan = get_loan(loan["id"])
    return {
        "borrower": borrower,
        "application": app,
        "loan": loan,
        "investors": investors,
        "investments": investments,
    }


def setup_single_investor_repayment_loan(principal_cents=1_200_000, term_months=12,
                                         funded_at="2026-06-01T00:00:00.000Z"):
    """Disbursed REPAYMENT loan fully funded by a single investor. Returns the
    same dict shape as setup_repayment_loan (one investor / one investment)."""
    return setup_repayment_loan(
        [principal_cents], funded_at=funded_at,
        requested_principal_cents=principal_cents, term_months=term_months,
    )


# --------------------------------------------------------------------------
# Tier 4/5: drive to DEFAULTED / CHARGED_OFF
# --------------------------------------------------------------------------

def assess_late_fee(loan_id: str) -> dict:
    return get_success_data(api_client.assess_late_fee(loan_id, ADMIN))


def drive_to_defaulted(loan_id: str, clock_past_due="2026-09-02T00:00:00.000Z"):
    """From a disbursed REPAYMENT loan (funded_at 2026-06-01), advance the clock
    past period 3's due date and assess three late fees so the loan reaches
    DEFAULTED on the third assessment (PRD §3.7). Returns the re-read loan."""
    set_clock(clock_past_due)
    assess_late_fee(loan_id)
    assess_late_fee(loan_id)
    assess_late_fee(loan_id)
    return get_loan(loan_id)


def drive_to_charged_off(loan_id: str, clock_past_due="2026-09-02T00:00:00.000Z"):
    """Drive a REPAYMENT loan to DEFAULTED then CHARGED_OFF. Returns the re-read loan."""
    drive_to_defaulted(loan_id, clock_past_due=clock_past_due)
    get_success_data(api_client.charge_off_loan(loan_id, ADMIN))
    return get_loan(loan_id)


def setup_charged_off_loan(investor_shares, funded_at="2026-06-01T00:00:00.000Z",
                           requested_principal_cents=1_200_000, term_months=12):
    """Full pipeline to a CHARGED_OFF loan (no scheduled payments before default,
    so outstanding basis == principal). Returns the setup dict from
    setup_repayment_loan with the loan re-read in CHARGED_OFF."""
    ctx = setup_repayment_loan(
        investor_shares, funded_at=funded_at,
        requested_principal_cents=requested_principal_cents, term_months=term_months,
    )
    drive_to_charged_off(ctx["loan"]["id"])
    ctx["loan"] = get_loan(ctx["loan"]["id"])
    return ctx


# --------------------------------------------------------------------------
# Repayment / read helpers
# --------------------------------------------------------------------------

def post_repayment(loan_id: str, amount_cents: int, kind: str = "SCHEDULED",
                   actor_headers=None) -> dict:
    """Record a repayment. SCHEDULED defaults to the borrower-acting PlatformAdmin
    (both authorized, PRD §4); RECOVERY must be PlatformAdmin (PRD §3.7)."""
    if actor_headers is None:
        actor_headers = ADMIN
    payload = create_repayment_payload(loan_id, amount_cents, kind=kind)
    return get_success_data(api_client.create_repayment(loan_id, payload, actor_headers))


def list_repayment_allocations(repayment_id: str):
    resp = api_client.list_repayment_allocations(repayment_id, ADMIN)
    return resp.json()["data"]


def list_investment_allocations(investment_id: str):
    resp = api_client.list_investment_allocations(investment_id, ADMIN)
    return resp.json()["data"]
