"""Composite setup helpers — multi-step preambles tests can reuse.

The P2P-lending pipeline is long: platform create -> compliance officer
register -> borrower create -> Plaid snapshot attach -> borrower approve
-> listing create -> investor(s) create -> deposit -> investments
pledged -> listing funded -> originate loan -> (optionally) advance
clock to drive delinquency / default / charge-off.

IDENTITY THREADING — PRD §2.1:

- PlatformOperator is OPAQUE. Shared TEST_USERS constants are canonical
  for every operator-only call.

- ComplianceOfficer, Borrower, and Investor are ENTITY-BACKED. Every
  call whose success depends on owning the targeted resource MUST mint
  headers via make_<role>_headers(<entity>["id"]) — never via the
  shared fallback constants. The fixtures return the actual entity rows
  so consumer tests / consumer fixtures can route role-acting calls
  through the per-instance header builders.

  Concretely:
    - approve / suspend / reinstate / ban / publish_disclosure → must
      use make_compliance_officer_headers(officer["id"]).
    - create_listing as Borrower / withdraw / post_payment as Borrower
      → must use make_borrower_headers(borrower["id"]).
    - create_investment as Investor / get own investment → must use
      make_investor_headers(investor["id"]).

Setup calls use get_success_data (a lenient 2xx validator), so a
failed setup surfaces as 'Setup failed' rather than a confusing test
assertion failure downstream.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    CHARGE_OFF_THRESHOLD_MISSED,
    DEFAULT_LATE_FEE_CENTS,
    DEFAULT_MAX_BORROWER_CONCENTRATION_BPS,
    DEFAULT_ORIGINATION_FEE_BPS,
    DEFAULT_SERVICING_FEE_BPS,
    DEFAULT_THRESHOLD_MISSED,
    FUNDING_DEADLINE_OFFSET_DAYS,
    INSTALLMENT_GRACE_DAYS,
    INSTALLMENT_PERIOD_DAYS,
    TEST_DEFAULTS,
)
from .factories import (
    advance_clock_payload,
    create_borrower_payload,
    create_compliance_officer_payload,
    create_investment_payload,
    create_investor_payload,
    create_listing_payload,
    create_payment_payload,
    create_plaid_snapshot_payload,
    create_platform_payload,
    deposit_payload,
)
from .test_users import (
    TEST_USERS,
    make_borrower_headers,
    make_compliance_officer_headers,
    make_investor_headers,
)


# ===========================================================================
# Platform — PRD §3.1
# ===========================================================================
def create_platform(
    *,
    name: Optional[str] = None,
    currency: Optional[str] = None,
    origination_fee_bps: Optional[int] = None,
    servicing_fee_bps: Optional[int] = None,
    late_fee_cents: Optional[int] = None,
    max_borrower_concentration_bps: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /platforms. PRD §3.1: PlatformOperator only.

    All fee/concentration arguments are optional — omit to test
    PRD-declared defaults (origination=300, servicing=100, late=2500,
    concentration=1000)."""
    headers = headers or TEST_USERS["platform_operator_headers"]
    resp = api_client.create_platform(
        create_platform_payload(
            name=name,
            currency=currency,
            origination_fee_bps=origination_fee_bps,
            servicing_fee_bps=servicing_fee_bps,
            late_fee_cents=late_fee_cents,
            max_borrower_concentration_bps=max_borrower_concentration_bps,
        ),
        headers,
    )
    return get_success_data(resp)


def get_platform(
    platform_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["platform_operator_headers"]
    resp = api_client.get_platform(platform_id, headers)
    return get_success_data(resp)


def advance_clock(
    platform_id: str,
    days: int,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /platforms/{id}/advance_clock days=N. PRD §3.1, §2.7: runs
    every system-driven transition for the day range in a single pass."""
    headers = headers or TEST_USERS["platform_operator_headers"]
    resp = api_client.advance_clock(
        platform_id, advance_clock_payload(days=days), headers,
    )
    return get_success_data(resp)


# ===========================================================================
# ComplianceOfficer — PRD §3.9
# ===========================================================================
def create_compliance_officer(
    platform_id: str,
    *,
    display_name: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /platforms/{id}/compliance_officers. PRD §4: PlatformOperator
    only. Returns the officer dict; consumers thread officer['id'] into
    make_compliance_officer_headers for every compliance action."""
    headers = headers or TEST_USERS["platform_operator_headers"]
    resp = api_client.create_compliance_officer(
        platform_id,
        create_compliance_officer_payload(display_name=display_name),
        headers,
    )
    return get_success_data(resp)


# ===========================================================================
# Borrower — PRD §3.2
# ===========================================================================
def create_borrower(
    platform_id: str,
    *,
    legal_name: Optional[str] = None,
    ein: Optional[str] = None,
    annual_revenue_cents: int = TEST_DEFAULTS[
        "BORROWER_ANNUAL_REVENUE_CENTS"
    ],
    requested_amount_cents: int = TEST_DEFAULTS[
        "BORROWER_REQUESTED_AMOUNT_CENTS"
    ],
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /platforms/{id}/borrowers. PRD §4: PlatformOperator only."""
    headers = headers or TEST_USERS["platform_operator_headers"]
    payload = create_borrower_payload(
        legal_name=legal_name,
        ein=ein,
        annual_revenue_cents=annual_revenue_cents,
        requested_amount_cents=requested_amount_cents,
    )
    resp = api_client.create_borrower(platform_id, payload, headers)
    return get_success_data(resp)


def attach_plaid_snapshot(
    platform_id: str,
    borrower_id: str,
    *,
    deposits_last_90d_cents: int = TEST_DEFAULTS[
        "PLAID_DEPOSITS_LAST_90D_CENTS"
    ],
    avg_daily_balance_cents: int = TEST_DEFAULTS[
        "PLAID_AVG_DAILY_BALANCE_CENTS"
    ],
    nsf_count_last_90d: int = TEST_DEFAULTS["PLAID_NSF_COUNT"],
    existing_debt_service_cents: int = TEST_DEFAULTS[
        "PLAID_DEBT_SERVICE_CENTS"
    ],
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /platforms/{id}/borrowers/{b}/plaid_snapshots. PRD §4:
    PlatformOperator only."""
    headers = headers or TEST_USERS["platform_operator_headers"]
    payload = create_plaid_snapshot_payload(
        deposits_last_90d_cents=deposits_last_90d_cents,
        avg_daily_balance_cents=avg_daily_balance_cents,
        nsf_count_last_90d=nsf_count_last_90d,
        existing_debt_service_cents=existing_debt_service_cents,
    )
    resp = api_client.attach_plaid_snapshot(
        platform_id, borrower_id, payload, headers,
    )
    return get_success_data(resp)


def approve_borrower(
    platform_id: str,
    borrower_id: str,
    officer_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /platforms/{id}/borrowers/{b}/approve. PRD §4:
    ComplianceOfficer only. The officer_id parameter is the actual
    ComplianceOfficer.id used to mint per-instance headers — PRD §2.1
    forbids using a shared constant for entity-backed roles on
    ownership-/segregation-gated calls."""
    headers = headers or make_compliance_officer_headers(officer_id)
    resp = api_client.approve_borrower(platform_id, borrower_id, headers)
    return get_success_data(resp)


def suspend_borrower(
    platform_id: str,
    borrower_id: str,
    officer_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /platforms/{id}/borrowers/{b}/suspend. ComplianceOfficer only."""
    headers = headers or make_compliance_officer_headers(officer_id)
    resp = api_client.suspend_borrower(platform_id, borrower_id, headers)
    return get_success_data(resp)


def reinstate_borrower(
    platform_id: str,
    borrower_id: str,
    officer_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /platforms/{id}/borrowers/{b}/reinstate. ComplianceOfficer only."""
    headers = headers or make_compliance_officer_headers(officer_id)
    resp = api_client.reinstate_borrower(platform_id, borrower_id, headers)
    return get_success_data(resp)


def ban_borrower(
    platform_id: str,
    borrower_id: str,
    officer_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /platforms/{id}/borrowers/{b}/ban. ComplianceOfficer only."""
    headers = headers or make_compliance_officer_headers(officer_id)
    resp = api_client.ban_borrower(platform_id, borrower_id, headers)
    return get_success_data(resp)


def get_borrower(
    platform_id: str,
    borrower_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["platform_operator_headers"]
    resp = api_client.get_borrower(platform_id, borrower_id, headers)
    return get_success_data(resp)


# ===========================================================================
# Investor — PRD §3.8
# ===========================================================================
def create_investor(
    platform_id: str,
    *,
    display_name: Optional[str] = None,
    accreditation_status: str = "ACCREDITED",
    committed_capital_cents: int = TEST_DEFAULTS[
        "INVESTOR_COMMITTED_CAPITAL_CENTS"
    ],
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /platforms/{id}/investors. PRD §4: PlatformOperator only.
    Returns the Investor dict; consumers thread investor['id'] into
    make_investor_headers for every pledge / read."""
    headers = headers or TEST_USERS["platform_operator_headers"]
    payload = create_investor_payload(
        display_name=display_name,
        accreditation_status=accreditation_status,
        committed_capital_cents=committed_capital_cents,
    )
    resp = api_client.create_investor(platform_id, payload, headers)
    return get_success_data(resp)


def deposit_to_investor(
    platform_id: str,
    investor_id: str,
    *,
    amount_cents: int,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /platforms/{id}/investors/{inv}/deposits. PRD §4:
    PlatformOperator only. Simulates external funding."""
    headers = headers or TEST_USERS["platform_operator_headers"]
    resp = api_client.deposit_to_investor(
        platform_id, investor_id,
        deposit_payload(amount_cents=amount_cents), headers,
    )
    return get_success_data(resp)


def get_investor(
    platform_id: str,
    investor_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["platform_operator_headers"]
    resp = api_client.get_investor(platform_id, investor_id, headers)
    return get_success_data(resp)


# ===========================================================================
# LoanListing — PRD §3.3
# ===========================================================================
def create_listing(
    platform_id: str,
    borrower_id: str,
    *,
    principal_cents: int = TEST_DEFAULTS["PRINCIPAL_CENTS"],
    term_months: int = TEST_DEFAULTS["TERM_MONTHS"],
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /platforms/{id}/borrowers/{b}/listings. PRD §4: Borrower
    (own) or PlatformOperator. Default uses PlatformOperator (opaque)
    so listing creation in setup does not need to mint per-borrower
    headers; ownership tests pass headers=make_borrower_headers(
    borrower['id']) explicitly."""
    headers = headers or TEST_USERS["platform_operator_headers"]
    payload = create_listing_payload(
        principal_cents=principal_cents, term_months=term_months,
    )
    resp = api_client.create_listing(
        platform_id, borrower_id, payload, headers,
    )
    return get_success_data(resp)


def withdraw_listing(
    platform_id: str,
    listing_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /platforms/{id}/listings/{l}/withdraw. PRD §4: Borrower
    (own) or PlatformOperator."""
    headers = headers or TEST_USERS["platform_operator_headers"]
    resp = api_client.withdraw_listing(platform_id, listing_id, headers)
    return get_success_data(resp)


def originate_listing(
    platform_id: str,
    listing_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /platforms/{id}/listings/{l}/originate. PRD §4:
    PlatformOperator only."""
    headers = headers or TEST_USERS["platform_operator_headers"]
    resp = api_client.originate_listing(platform_id, listing_id, headers)
    return get_success_data(resp)


def get_listing(
    platform_id: str,
    listing_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["platform_operator_headers"]
    resp = api_client.get_listing(platform_id, listing_id, headers)
    return get_success_data(resp)


# ===========================================================================
# Investment — PRD §3.3
# ===========================================================================
def create_investment(
    platform_id: str,
    listing_id: str,
    investor_id: str,
    *,
    amount_cents: int,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /platforms/{id}/listings/{l}/investments. PRD §4: Investor
    only.

    investor_id is the actual Investor.id used to mint per-instance
    headers — PRD §2.1 requires X-User-ID to resolve to that exact
    investor. Falling back to a shared constant would make every
    investor-scoped check refuse every pledge."""
    headers = headers or make_investor_headers(investor_id)
    resp = api_client.create_investment(
        platform_id, listing_id,
        create_investment_payload(amount_cents=amount_cents), headers,
    )
    return get_success_data(resp)


def get_investment(
    platform_id: str,
    investment_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["platform_operator_headers"]
    resp = api_client.get_investment(platform_id, investment_id, headers)
    return get_success_data(resp)


# ===========================================================================
# Loan / Installment — PRD §3.4, §3.5
# ===========================================================================
def get_loan(
    platform_id: str,
    loan_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["platform_operator_headers"]
    resp = api_client.get_loan(platform_id, loan_id, headers)
    return get_success_data(resp)


def list_installments(
    platform_id: str,
    loan_id: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["platform_operator_headers"]
    # PRD §2.3: list endpoints default limit is 10. Tests that assert on
    # the full set of installments (term_months can be up to 60) MUST
    # override the default. Pass limit=100 (PRD's max) so the helper
    # returns every row, regardless of term_months.
    merged_params: Dict[str, Any] = {"limit": 100}
    if params:
        merged_params.update(params)
    resp = api_client.list_installments(
        platform_id, loan_id, headers, params=merged_params,
    )
    return get_success_data(resp)


# ===========================================================================
# Payment — PRD §3.5
# ===========================================================================
def post_payment(
    platform_id: str,
    loan_id: str,
    *,
    amount_cents: int,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /platforms/{id}/loans/{l}/payments. PRD §4: Borrower (own)
    or PlatformOperator. Setup default is PlatformOperator (opaque) so
    the helper does not need a borrower_id; ownership-positive tests
    pass headers=make_borrower_headers(borrower['id']) explicitly."""
    headers = headers or TEST_USERS["platform_operator_headers"]
    resp = api_client.create_payment(
        platform_id, loan_id,
        create_payment_payload(amount_cents=amount_cents), headers,
    )
    return get_success_data(resp)


def get_payment(
    platform_id: str,
    payment_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["platform_operator_headers"]
    resp = api_client.get_payment(platform_id, payment_id, headers)
    return get_success_data(resp)


# ===========================================================================
# Disclosure — PRD §3.7
# ===========================================================================
def list_disclosures(
    platform_id: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["platform_operator_headers"]
    resp = api_client.list_disclosures(platform_id, headers, params=params)
    return get_success_data(resp)


def get_disclosure(
    platform_id: str,
    disclosure_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["platform_operator_headers"]
    resp = api_client.get_disclosure(platform_id, disclosure_id, headers)
    return get_success_data(resp)


def publish_disclosure(
    platform_id: str,
    disclosure_id: str,
    officer_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /platforms/{id}/disclosures/{d}/publish. PRD §4:
    ComplianceOfficer only.

    officer_id is the actual ComplianceOfficer.id used to mint
    per-instance headers — PRD §2.1 requires X-User-ID to resolve to
    that officer for segregation-of-duties checks."""
    headers = headers or make_compliance_officer_headers(officer_id)
    resp = api_client.publish_disclosure(
        platform_id, disclosure_id, headers,
    )
    return get_success_data(resp)


# ===========================================================================
# Helpers — disclosure lookup
# ===========================================================================
def find_disclosure(
    platform_id: str,
    *,
    subject_type: Optional[str] = None,
    subject_id: Optional[str] = None,
    kind: Optional[str] = None,
    published: Optional[bool] = None,
) -> Optional[Dict[str, Any]]:
    """Find the first disclosure matching the given filters. Returns
    None if none match. Used by tests asserting that a transition
    emitted a draft disclosure of a specific kind."""
    params: Dict[str, Any] = {}
    if subject_type is not None:
        params["subject_type"] = subject_type
    if subject_id is not None:
        params["subject_id"] = subject_id
    if kind is not None:
        params["kind"] = kind
    if published is not None:
        params["published"] = published
    resp = api_client.list_disclosures(
        platform_id, TEST_USERS["platform_operator_headers"],
        params=params,
    )
    body = resp.json()
    rows = body.get("data", []) if isinstance(body, dict) else []
    if isinstance(rows, list) and rows:
        return rows[0]
    return None


# ===========================================================================
# Tier 2: Composite setups — Platform + Officer + Approved Borrower
# ===========================================================================
def setup_platform_with_officer(
    *,
    origination_fee_bps: Optional[int] = None,
    servicing_fee_bps: Optional[int] = None,
    late_fee_cents: Optional[int] = None,
    max_borrower_concentration_bps: Optional[int] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Create a Platform and register one ComplianceOfficer beneath it.

    Returns (platform, officer). The officer['id'] is the X-User-ID for
    every subsequent compliance action via
    make_compliance_officer_headers(officer['id'])."""
    platform = create_platform(
        origination_fee_bps=origination_fee_bps,
        servicing_fee_bps=servicing_fee_bps,
        late_fee_cents=late_fee_cents,
        max_borrower_concentration_bps=max_borrower_concentration_bps,
    )
    officer = create_compliance_officer(platform["id"])
    return platform, officer


def setup_borrower_pending_kyc(
    *,
    platform: Optional[Dict[str, Any]] = None,
    officer: Optional[Dict[str, Any]] = None,
    annual_revenue_cents: int = TEST_DEFAULTS[
        "BORROWER_ANNUAL_REVENUE_CENTS"
    ],
    requested_amount_cents: int = TEST_DEFAULTS[
        "BORROWER_REQUESTED_AMOUNT_CENTS"
    ],
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Platform + Officer + Borrower in PENDING_KYC (no snapshot yet).
    Returns (platform, officer, borrower)."""
    if platform is None or officer is None:
        platform, officer = setup_platform_with_officer()
    borrower = create_borrower(
        platform["id"],
        annual_revenue_cents=annual_revenue_cents,
        requested_amount_cents=requested_amount_cents,
    )
    return platform, officer, borrower


def setup_approved_borrower(
    *,
    platform: Optional[Dict[str, Any]] = None,
    officer: Optional[Dict[str, Any]] = None,
    annual_revenue_cents: int = TEST_DEFAULTS[
        "BORROWER_ANNUAL_REVENUE_CENTS"
    ],
    requested_amount_cents: int = TEST_DEFAULTS[
        "BORROWER_REQUESTED_AMOUNT_CENTS"
    ],
    # Plaid inputs that yield a non-UNGRADED final_grade by default.
    deposits_last_90d_cents: int = 9_000_000,  # ~$30k/day cashflow
    avg_daily_balance_cents: int = 5_000_000,
    nsf_count_last_90d: int = 0,
    existing_debt_service_cents: int = 1_000_00,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Platform + Officer + APPROVED Borrower.

    Walks the full borrower onboarding:
    1. create platform + officer (or reuse provided ones)
    2. create borrower (status=PENDING_KYC, final_grade=UNGRADED)
    3. attach a PlaidSnapshot whose inputs land final_grade in A..E
    4. approve borrower (officer-driven; per-instance headers minted
       inside approve_borrower).

    Returns (platform, officer, borrower) with borrower.status=APPROVED."""
    platform, officer, borrower = setup_borrower_pending_kyc(
        platform=platform,
        officer=officer,
        annual_revenue_cents=annual_revenue_cents,
        requested_amount_cents=requested_amount_cents,
    )
    attach_plaid_snapshot(
        platform["id"], borrower["id"],
        deposits_last_90d_cents=deposits_last_90d_cents,
        avg_daily_balance_cents=avg_daily_balance_cents,
        nsf_count_last_90d=nsf_count_last_90d,
        existing_debt_service_cents=existing_debt_service_cents,
    )
    approved = approve_borrower(
        platform["id"], borrower["id"], officer["id"],
    )
    return platform, officer, approved


def setup_funded_investor(
    platform_id: str,
    *,
    committed_capital_cents: int = TEST_DEFAULTS[
        "INVESTOR_COMMITTED_CAPITAL_CENTS"
    ],
    deposit_cents: int = TEST_DEFAULTS["INVESTOR_DEPOSIT_CENTS"],
    accreditation_status: str = "ACCREDITED",
    display_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Create an Investor under the platform and deposit cash so the
    investor's cash_balance_cents = deposit_cents at return. Returns
    the refreshed investor dict (cash_balance_cents reflects the
    deposit). PRD §3.8."""
    investor = create_investor(
        platform_id,
        display_name=display_name,
        accreditation_status=accreditation_status,
        committed_capital_cents=committed_capital_cents,
    )
    deposit_to_investor(
        platform_id, investor["id"], amount_cents=deposit_cents,
    )
    return get_investor(platform_id, investor["id"])


# ===========================================================================
# Tier 3: Listing + investments setups
# ===========================================================================
def setup_open_listing(
    *,
    platform: Optional[Dict[str, Any]] = None,
    officer: Optional[Dict[str, Any]] = None,
    borrower: Optional[Dict[str, Any]] = None,
    principal_cents: int = TEST_DEFAULTS["PRINCIPAL_CENTS"],
    term_months: int = TEST_DEFAULTS["TERM_MONTHS"],
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Platform + Officer + APPROVED Borrower + one OPEN LoanListing.

    Returns (platform, officer, borrower, listing)."""
    if borrower is None:
        platform, officer, borrower = setup_approved_borrower(
            platform=platform, officer=officer,
        )
    elif platform is None or officer is None:
        raise ValueError(
            "if borrower is supplied, platform and officer must be too",
        )
    listing = create_listing(
        platform["id"], borrower["id"],
        principal_cents=principal_cents, term_months=term_months,
    )
    return platform, officer, borrower, listing


def setup_funded_listing(
    *,
    platform: Optional[Dict[str, Any]] = None,
    officer: Optional[Dict[str, Any]] = None,
    borrower: Optional[Dict[str, Any]] = None,
    principal_cents: int = TEST_DEFAULTS["PRINCIPAL_CENTS"],
    term_months: int = TEST_DEFAULTS["TERM_MONTHS"],
    investor_committed_capital_cents: int = 100_000_00,
) -> Tuple[
    Dict[str, Any], Dict[str, Any], Dict[str, Any],
    Dict[str, Any], Dict[str, Any], Dict[str, Any],
]:
    """Platform + Officer + Borrower + Investor + one FUNDED listing.

    Walks: setup_open_listing -> create funded investor ->
    invest the entire principal so pledged_cents == principal_cents
    drives the system transition OPEN -> FUNDED.

    Returns (platform, officer, borrower, investor, listing, investment).
    listing.status will be 'FUNDED'."""
    platform, officer, borrower, listing = setup_open_listing(
        platform=platform, officer=officer, borrower=borrower,
        principal_cents=principal_cents, term_months=term_months,
    )
    investor = setup_funded_investor(
        platform["id"],
        committed_capital_cents=investor_committed_capital_cents,
        deposit_cents=max(
            investor_committed_capital_cents, principal_cents,
        ),
    )
    investment = create_investment(
        platform["id"], listing["id"], investor["id"],
        amount_cents=principal_cents,
    )
    # Refresh listing — should now be FUNDED.
    listing = get_listing(platform["id"], listing["id"])
    return platform, officer, borrower, investor, listing, investment


def setup_originated_loan(
    *,
    platform: Optional[Dict[str, Any]] = None,
    officer: Optional[Dict[str, Any]] = None,
    borrower: Optional[Dict[str, Any]] = None,
    principal_cents: int = TEST_DEFAULTS["PRINCIPAL_CENTS"],
    term_months: int = TEST_DEFAULTS["TERM_MONTHS"],
    investor_committed_capital_cents: int = 100_000_00,
) -> Tuple[
    Dict[str, Any], Dict[str, Any], Dict[str, Any],
    Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any],
]:
    """Full happy-path setup ending with an ACTIVE Loan.

    Walks setup_funded_listing -> originate. Returns (platform, officer,
    borrower, investor, listing, investment, loan)."""
    (platform, officer, borrower, investor, listing,
     investment) = setup_funded_listing(
        platform=platform, officer=officer, borrower=borrower,
        principal_cents=principal_cents, term_months=term_months,
        investor_committed_capital_cents=(
            investor_committed_capital_cents
        ),
    )
    loan = originate_listing(platform["id"], listing["id"])
    return platform, officer, borrower, investor, listing, investment, loan


def setup_originated_loan_three_investors(
    *,
    principal_cents: int = 100_000,
    term_months: int = TEST_DEFAULTS["TERM_MONTHS"],
    shares: Tuple[int, int, int] = (30_000, 30_000, 40_000),
    late_fee_cents: Optional[int] = None,
) -> Tuple[
    Dict[str, Any], Dict[str, Any], Dict[str, Any],
    List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any],
    Dict[str, Any],
]:
    """Originate a Loan with EXACTLY three CONVERTED investments at the
    given shares (in cents). Sum of shares MUST equal principal_cents.

    Used to test charge-off loss distribution invariants (per-investor
    delta sums to total_loss; pinned chronological order; residual
    cent on the last-created investment).

    `late_fee_cents` overrides the platform's late_fee_cents at creation.
    Setting it to 0 lets charge-off-loss tests assert exact per-investor
    share equality against principal-share-bps without accrued-late-fee
    drift inflating total_loss (PRD §3.6).

    Returns (platform, officer, borrower, investors, investments,
    listing, loan)."""
    assert sum(shares) == principal_cents, (
        f"shares {shares} must sum to principal_cents "
        f"{principal_cents}"
    )
    platform, officer = setup_platform_with_officer(
        late_fee_cents=late_fee_cents,
    )
    _, _, borrower, listing = setup_open_listing(
        platform=platform, officer=officer,
        principal_cents=principal_cents, term_months=term_months,
    )
    investors: List[Dict[str, Any]] = []
    investments: List[Dict[str, Any]] = []
    for share in shares:
        # Each investor's cap on this borrower must allow `share`.
        # cap = floor(committed * concentration_bps / 10000). With
        # concentration=1000 (10%), committed_capital must be >= 10x
        # share. We grant 100x share to leave wide headroom.
        committed = max(share * 100, 10_000_00)
        inv = setup_funded_investor(
            platform["id"],
            committed_capital_cents=committed,
            deposit_cents=max(committed, share),
        )
        investors.append(inv)
        investment = create_investment(
            platform["id"], listing["id"], inv["id"],
            amount_cents=share,
        )
        investments.append(investment)
    listing = get_listing(platform["id"], listing["id"])
    loan = originate_listing(platform["id"], listing["id"])
    return (
        platform, officer, borrower, investors, investments, listing,
        loan,
    )


# ===========================================================================
# Tier 4: Time-progression setups (drive loan posture via advance_clock)
# ===========================================================================
def setup_loan_in_delinquent(
    **kwargs: Any,
) -> Tuple[
    Dict[str, Any], Dict[str, Any], Dict[str, Any],
    Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any],
]:
    """Originate a loan, then advance the clock past installment 1's
    due_day_index + grace WITHOUT posting any payment so the loan
    transitions ACTIVE -> DELINQUENT (consecutive_missed_installments
    crosses 0 -> 1). PRD §3.6.

    The first installment's due_day_index = origination_day_index +
    1 * 30 = 30. Grace is 5 days. Advancing 36 days from origination
    lands clock_day_index at 36 = 31+5, which is strictly greater than
    due + grace = 35, so the installment moves DUE -> LATE and the
    loan moves ACTIVE -> DELINQUENT.

    Returns (platform, officer, borrower, investor, listing,
    investment, loan)."""
    (platform, officer, borrower, investor, listing, investment,
     loan) = setup_originated_loan(**kwargs)
    # Advance to just past installment 1's due_day_index + 5 grace.
    # origination_day_index is recorded by the server at origination,
    # so we advance INSTALLMENT_PERIOD_DAYS + INSTALLMENT_GRACE_DAYS + 1
    # = 36 days. The system sweep will move installment 1 SCHEDULED ->
    # DUE -> LATE and the loan ACTIVE -> DELINQUENT.
    advance_clock(
        platform["id"],
        INSTALLMENT_PERIOD_DAYS + INSTALLMENT_GRACE_DAYS + 1,
    )
    loan = get_loan(platform["id"], loan["id"])
    return platform, officer, borrower, investor, listing, investment, loan


def setup_loan_in_default(
    **kwargs: Any,
) -> Tuple[
    Dict[str, Any], Dict[str, Any], Dict[str, Any],
    Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any],
]:
    """Originate a loan, then advance the clock far enough to accrue
    consecutive_missed_installments >= 3, driving the loan to DEFAULT.
    PRD §3.6.

    Strategy: advance past installments 1, 2, 3 with no payment. Each
    becomes LATE after due+grace. After the third installment is LATE,
    consecutive_missed_installments >= 3 -> DEFAULT.

    Returns (platform, officer, borrower, investor, listing,
    investment, loan)."""
    (platform, officer, borrower, investor, listing, investment,
     loan) = setup_originated_loan(**kwargs)
    # Advance past installment 3's due + grace: 3 * 30 + 5 + 1 = 96
    # days. Within the sweep, installments 1, 2, 3 all reach LATE in
    # ascending order; consecutive_missed_installments accrues 3 and
    # the loan moves through DELINQUENT to DEFAULT in the same sweep.
    advance_clock(
        platform["id"],
        3 * INSTALLMENT_PERIOD_DAYS + INSTALLMENT_GRACE_DAYS + 1,
    )
    loan = get_loan(platform["id"], loan["id"])
    return platform, officer, borrower, investor, listing, investment, loan


def setup_loan_charged_off(
    **kwargs: Any,
) -> Tuple[
    Dict[str, Any], Dict[str, Any], Dict[str, Any],
    Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any],
]:
    """Originate a loan, then advance the clock far enough to accrue
    consecutive_missed_installments >= 5, driving the loan to
    CHARGED_OFF. PRD §3.6.

    Returns (platform, officer, borrower, investor, listing,
    investment, loan)."""
    (platform, officer, borrower, investor, listing, investment,
     loan) = setup_originated_loan(**kwargs)
    # Advance past installment 5's due + grace: 5 * 30 + 5 + 1 = 156
    # days. The sweep takes the loan ACTIVE -> DELINQUENT (1 miss) ->
    # DEFAULT (3 misses) -> CHARGED_OFF (5 misses) in one pass.
    advance_clock(
        platform["id"],
        5 * INSTALLMENT_PERIOD_DAYS + INSTALLMENT_GRACE_DAYS + 1,
    )
    loan = get_loan(platform["id"], loan["id"])
    return platform, officer, borrower, investor, listing, investment, loan


def setup_loan_charged_off_three_investors(
    *,
    principal_cents: int = 100_000,
    term_months: int = TEST_DEFAULTS["TERM_MONTHS"],
    shares: Tuple[int, int, int] = (30_000, 30_000, 40_000),
) -> Tuple[
    Dict[str, Any], Dict[str, Any], Dict[str, Any],
    List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any],
    Dict[str, Any],
]:
    """Originate a 3-investor loan and drive it to CHARGED_OFF via
    advance_clock (no payments). Returns (platform, officer, borrower,
    investors, investments, listing, loan) with loan.status =
    'CHARGED_OFF'.

    PRD §3.6 sets `charged_off_loss_cents` to
    `principal_outstanding_cents + accrued_late_fees_cents` at the
    charge-off moment. Default `late_fee_cents` is 2500 (PRD §3.1), so
    five missed installments would add 12,500 cents of late fees and
    inflate total_loss beyond principal — making per-investor share
    decrements (which the PRD distributes pro-rata over the inflated
    total_loss) NOT equal the original pledges. To let tests assert the
    clean "no late-fee residual" case where each investor's
    outstanding_principal_cents falls by exactly their original pledge,
    we configure the platform with late_fee_cents=0. This is PRD-allowed
    (PRD §3.1: late_fee_cents is an optional parameter)."""
    (platform, officer, borrower, investors, investments, listing,
     loan) = setup_originated_loan_three_investors(
        principal_cents=principal_cents,
        term_months=term_months,
        shares=shares,
        late_fee_cents=0,
    )
    advance_clock(
        platform["id"],
        5 * INSTALLMENT_PERIOD_DAYS + INSTALLMENT_GRACE_DAYS + 1,
    )
    loan = get_loan(platform["id"], loan["id"])
    return (
        platform, officer, borrower, investors, investments, listing,
        loan,
    )


# ===========================================================================
# Tier 5: Disclosure setups
# ===========================================================================
def setup_disclosure_in_draft(
    kind: str,
    **kwargs: Any,
) -> Tuple[
    Dict[str, Any], Dict[str, Any], Dict[str, Any],
    Optional[Dict[str, Any]], Dict[str, Any],
]:
    """Drive the system to emit a DRAFT Disclosure of the requested
    `kind`, then return (platform, officer, borrower, loan_or_None,
    disclosure). PRD §3.7 enumerates kinds:

    - LISTING_OPENED — emitted at listing create
    - LISTING_FUNDED — emitted at OPEN -> FUNDED
    - LOAN_ORIGINATED — emitted at FUNDED -> ORIGINATED
    - DELINQUENCY_NOTICE — emitted on first ACTIVE -> DELINQUENT
    - DEFAULT_NOTICE — emitted on DELINQUENT -> DEFAULT
    - CHARGE_OFF_NOTICE — emitted on DEFAULT -> CHARGED_OFF

    Returns the first matching DRAFT disclosure (published=false).
    Raises if not found."""
    loan: Optional[Dict[str, Any]] = None
    if kind == "LISTING_OPENED":
        platform, officer, borrower, listing = setup_open_listing(
            **kwargs,
        )
        d = find_disclosure(
            platform["id"], subject_type="LISTING",
            subject_id=listing["id"], kind=kind, published=False,
        )
    elif kind == "LISTING_FUNDED":
        (platform, officer, borrower, investor, listing,
         investment) = setup_funded_listing(**kwargs)
        d = find_disclosure(
            platform["id"], subject_type="LISTING",
            subject_id=listing["id"], kind=kind, published=False,
        )
    elif kind == "LOAN_ORIGINATED":
        (platform, officer, borrower, investor, listing, investment,
         loan) = setup_originated_loan(**kwargs)
        d = find_disclosure(
            platform["id"], subject_type="LOAN",
            subject_id=loan["id"], kind=kind, published=False,
        )
    elif kind == "DELINQUENCY_NOTICE":
        (platform, officer, borrower, investor, listing, investment,
         loan) = setup_loan_in_delinquent(**kwargs)
        d = find_disclosure(
            platform["id"], subject_type="LOAN",
            subject_id=loan["id"], kind=kind, published=False,
        )
    elif kind == "DEFAULT_NOTICE":
        (platform, officer, borrower, investor, listing, investment,
         loan) = setup_loan_in_default(**kwargs)
        d = find_disclosure(
            platform["id"], subject_type="LOAN",
            subject_id=loan["id"], kind=kind, published=False,
        )
    elif kind == "CHARGE_OFF_NOTICE":
        (platform, officer, borrower, investor, listing, investment,
         loan) = setup_loan_charged_off(**kwargs)
        d = find_disclosure(
            platform["id"], subject_type="LOAN",
            subject_id=loan["id"], kind=kind, published=False,
        )
    else:
        raise ValueError(f"unsupported disclosure kind: {kind!r}")
    assert d is not None, (
        f"setup_disclosure_in_draft: no DRAFT {kind} disclosure found"
    )
    return platform, officer, borrower, loan, d


__all__ = [
    # Platform
    "create_platform",
    "get_platform",
    "advance_clock",
    # ComplianceOfficer
    "create_compliance_officer",
    # Borrower
    "create_borrower",
    "attach_plaid_snapshot",
    "approve_borrower",
    "suspend_borrower",
    "reinstate_borrower",
    "ban_borrower",
    "get_borrower",
    # Investor
    "create_investor",
    "deposit_to_investor",
    "get_investor",
    # LoanListing
    "create_listing",
    "withdraw_listing",
    "originate_listing",
    "get_listing",
    # Investment
    "create_investment",
    "get_investment",
    # Loan / Installment
    "get_loan",
    "list_installments",
    # Payment
    "post_payment",
    "get_payment",
    # Disclosure
    "list_disclosures",
    "get_disclosure",
    "publish_disclosure",
    "find_disclosure",
    # Composite setups
    "setup_platform_with_officer",
    "setup_borrower_pending_kyc",
    "setup_approved_borrower",
    "setup_funded_investor",
    "setup_open_listing",
    "setup_funded_listing",
    "setup_originated_loan",
    "setup_originated_loan_three_investors",
    "setup_loan_in_delinquent",
    "setup_loan_in_default",
    "setup_loan_charged_off",
    "setup_loan_charged_off_three_investors",
    "setup_disclosure_in_draft",
]
