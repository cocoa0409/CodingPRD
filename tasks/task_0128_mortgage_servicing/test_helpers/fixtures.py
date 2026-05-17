"""Composite setup helpers — multi-step preambles tests can reuse.

The mortgage-servicing pipeline is long: borrower create -> hardship
attest -> loan originate -> (optional) clock advance to land at a
specific posture -> (optional) foreclosure-case open -> mediation /
forbearance / PMI lifecycle / escrow analysis.

IDENTITY THREADING — PRD §2.1:

- Servicer / LossMitigationUnderwriter / PmiUnderwriter /
  ForeclosureAttorney / PlatformAdmin are OPAQUE. Shared TEST_USERS
  constants are canonical for every operator-only call.

- Borrower is ENTITY-BACKED. Every Borrower-driven call whose success
  depends on owning the targeted resource MUST mint headers via
  make_borrower_headers(borrower["id"]) — never via the shared
  BORROWER_FALLBACK_ID. The fixtures here return the actual Borrower
  row so consumer tests / consumer fixtures can route borrower-acting
  calls through this header builder.

SEGREGATION OF DUTIES — PRD §2.1: "a single X-User-ID cannot both
extend a mediation offer and accept the same offer on the same
MediationCase, and a single X-User-ID cannot both post the curing
payment batch and finalise the same ForbearancePlan as COMPLETED."
The default LMU id used in these fixtures is lmu-001; fixtures that
intentionally trigger ERR_SEGREGATION_OF_DUTIES pass equal ids
explicitly via make_lmu_headers / make_borrower_headers.

Setup calls use get_success_data (a lenient 2xx validator), so a
failed setup surfaces as 'Setup failed' rather than a confusing test
assertion failure downstream.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    clock_advance_payload,
    create_borrower_payload,
    create_disbursement_payload,
    create_escrow_analysis_payload,
    create_forbearance_plan_payload,
    create_foreclosure_case_payload,
    create_loan_payload,
    create_payment_payload,
    create_pmi_removal_request_payload,
    extend_mediation_offer_payload,
    iso_datetime_utc_midnight,
    reinstate_foreclosure_payload,
    reject_mediation_offer_payload,
    schedule_auction_payload,
    today_utc,
)
from .test_users import (
    TEST_USERS,
    make_borrower_headers,
)


def _server_now_iso() -> str:
    """Return the server's logical clock as an ISO 8601 string.

    PRD §2.9 says the system is deterministic against a server-side
    logical clock advanced via /_clock/advance. Tests that have just
    invoked advance_clock(N) need received_date / scheduled_date values
    aligned with the *server's* now (which is offset from wall time by
    cumulative advance). The implementation exposes the logical clock
    via the test-only /__test__/now endpoint; if unavailable we fall
    back to wall today.
    """
    try:
        resp = api_client._request(
            "GET", "/__test__/now", None,
            TEST_USERS["platform_admin_headers"],
        )
        if resp.status_code == 200:
            body = resp.json()
            return body.get("now") or body.get("data", {}).get("now")
    except Exception:
        pass
    # Fallback to wall time today at midnight.
    return today_utc().isoformat() + "T00:00:00.000Z"


# ===========================================================================
# Borrower + loan creation — PRD §3.1
# ===========================================================================
def create_borrower(
    *,
    full_name: Optional[str] = None,
    email: Optional[str] = None,
    servicer_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /borrowers. Returns the created Borrower dict.

    PRD §4: Authorized roles are Servicer and PlatformAdmin.
    """
    servicer_headers = servicer_headers or TEST_USERS["servicer_headers"]
    resp = api_client.create_borrower(
        create_borrower_payload(full_name=full_name, email=email),
        servicer_headers,
    )
    return get_success_data(resp)


def attest_hardship(
    borrower_id: str,
    *,
    servicer_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /borrowers/{id}/hardship-attestation. PRD §3.1: stamps
    hardship_attested_at to now. Authorized roles per PRD §4 are
    Servicer and Borrower; this helper defaults to Servicer for setup."""
    servicer_headers = servicer_headers or TEST_USERS["servicer_headers"]
    resp = api_client.attest_hardship(borrower_id, servicer_headers)
    return get_success_data(resp)


def get_borrower(
    borrower_id: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["servicer_headers"]
    resp = api_client.get_borrower(borrower_id, headers)
    return get_success_data(resp)


def create_loan(
    *,
    borrower_id: str,
    origination_date: Optional[str] = None,
    original_principal_cents: int = 20_000_000,
    original_appraised_value_cents: int = 25_000_000,
    interest_rate_bps: int = 625,
    term_months: int = 360,
    pmi_monthly_cents: Optional[int] = None,
    monthly_escrow_payment_cents: Optional[int] = None,
    servicer_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /loans. Returns the originated Loan dict."""
    servicer_headers = servicer_headers or TEST_USERS["servicer_headers"]
    payload = create_loan_payload(
        borrower_id=borrower_id,
        origination_date=origination_date,
        original_principal_cents=original_principal_cents,
        original_appraised_value_cents=original_appraised_value_cents,
        interest_rate_bps=interest_rate_bps,
        term_months=term_months,
        pmi_monthly_cents=pmi_monthly_cents,
        monthly_escrow_payment_cents=monthly_escrow_payment_cents,
    )
    resp = api_client.create_loan(payload, servicer_headers)
    return get_success_data(resp)


def get_loan(
    loan_id: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["servicer_headers"]
    resp = api_client.get_loan(loan_id, headers)
    return get_success_data(resp)


# ===========================================================================
# Clock control — PRD §2.9, §3.8
# ===========================================================================
def advance_clock(
    days: int,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /_clock/advance days=N. Triggers time-gated transitions in
    deterministic order per PRD §2.9."""
    headers = headers or TEST_USERS["platform_admin_headers"]
    resp = api_client.clock_advance(
        clock_advance_payload(days=days), headers,
    )
    return get_success_data(resp)


def run_sweep(
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /_sweep/run. PRD §3.8: same evaluation as /_clock/advance
    days=0."""
    headers = headers or TEST_USERS["platform_admin_headers"]
    resp = api_client.sweep_run(headers)
    return get_success_data(resp)


# ===========================================================================
# Payment helpers — PRD §3.2
# ===========================================================================
def post_payment(
    loan_id: str,
    *,
    amount_cents: int,
    received_date: Optional[str] = None,
    version: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /loans/{id}/payments. Default actor is Servicer (operator
    posting on the borrower's behalf — PRD §3.2 explicitly allows this:
    'A Borrower posts a payment against their own loan, or a Servicer
    posts on the borrower's behalf'). Setup helpers default to the
    Servicer headers to avoid the borrower-ownership burden.
    """
    headers = headers or TEST_USERS["servicer_headers"]
    if received_date is None:
        received_date = _server_now_iso()
    payload = create_payment_payload(
        received_date=received_date,
        amount_cents=amount_cents,
        version=version,
    )
    resp = api_client.create_payment(loan_id, payload, headers)
    return get_success_data(resp)


def reverse_payment(
    loan_id: str,
    payment_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /loans/{loan_id}/payments/{id}/reverse — Servicer only."""
    headers = headers or TEST_USERS["servicer_headers"]
    resp = api_client.reverse_payment(loan_id, payment_id, headers)
    return get_success_data(resp)


# ===========================================================================
# Disbursement helpers — PRD §3.3
# ===========================================================================
def schedule_disbursement(
    loan_id: str,
    *,
    type: str,
    scheduled_date: str,
    amount_cents: int,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /loans/{id}/disbursements — Servicer only."""
    headers = headers or TEST_USERS["servicer_headers"]
    payload = create_disbursement_payload(
        type=type,
        scheduled_date=scheduled_date,
        amount_cents=amount_cents,
    )
    resp = api_client.create_disbursement(loan_id, payload, headers)
    return get_success_data(resp)


def retry_disbursement(
    loan_id: str,
    disbursement_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["servicer_headers"]
    resp = api_client.retry_disbursement(loan_id, disbursement_id, headers)
    return get_success_data(resp)


def cancel_disbursement(
    loan_id: str,
    disbursement_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["servicer_headers"]
    resp = api_client.cancel_disbursement(loan_id, disbursement_id, headers)
    return get_success_data(resp)


# ===========================================================================
# Escrow analysis helpers — PRD §3.3
# ===========================================================================
def create_escrow_analysis(
    loan_id: str,
    *,
    analysis_date: str,
    starting_balance_cents: int,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["servicer_headers"]
    payload = create_escrow_analysis_payload(
        analysis_date=analysis_date,
        starting_balance_cents=starting_balance_cents,
    )
    resp = api_client.create_escrow_analysis(loan_id, payload, headers)
    return get_success_data(resp)


def finalize_escrow_analysis(
    loan_id: str,
    analysis_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["servicer_headers"]
    resp = api_client.finalize_escrow_analysis(
        loan_id, analysis_id, headers,
    )
    return get_success_data(resp)


# ===========================================================================
# Forbearance helpers — PRD §3.4
# ===========================================================================
def create_forbearance_plan(
    loan_id: str,
    *,
    start_date: str,
    months: int,
    repayment_method: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /loans/{id}/forbearance-plans — LossMitigationUnderwriter only."""
    headers = headers or TEST_USERS["lmu_headers"]
    payload = create_forbearance_plan_payload(
        start_date=start_date,
        months=months,
        repayment_method=repayment_method,
    )
    resp = api_client.create_forbearance_plan(loan_id, payload, headers)
    return get_success_data(resp)


def cancel_forbearance_plan(
    loan_id: str,
    plan_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["lmu_headers"]
    resp = api_client.cancel_forbearance_plan(loan_id, plan_id, headers)
    return get_success_data(resp)


# ===========================================================================
# PMI helpers — PRD §3.5
# ===========================================================================
def create_pmi_removal_request(
    loan_id: str,
    *,
    trigger: str = "BORROWER_REQUEST",
    current_appraised_value_cents: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /loans/{id}/pmi-removal-requests — Servicer or Borrower.
    Defaults to Servicer for setup (no ownership burden)."""
    headers = headers or TEST_USERS["servicer_headers"]
    payload = create_pmi_removal_request_payload(
        trigger=trigger,
        current_appraised_value_cents=current_appraised_value_cents,
    )
    resp = api_client.create_pmi_removal_request(loan_id, payload, headers)
    return get_success_data(resp)


def approve_pmi_removal(
    loan_id: str,
    request_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /loans/{loan_id}/pmi-removal-requests/{id}/approve —
    PmiUnderwriter only."""
    headers = headers or TEST_USERS["pmi_underwriter_headers"]
    resp = api_client.approve_pmi_removal_request(
        loan_id, request_id, headers,
    )
    return get_success_data(resp)


def deny_pmi_removal(
    loan_id: str,
    request_id: str,
    *,
    denial_reason: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /loans/{loan_id}/pmi-removal-requests/{id}/deny."""
    from .factories import deny_pmi_removal_payload
    headers = headers or TEST_USERS["pmi_underwriter_headers"]
    resp = api_client.deny_pmi_removal_request(
        loan_id, request_id,
        deny_pmi_removal_payload(denial_reason=denial_reason),
        headers,
    )
    return get_success_data(resp)


# ===========================================================================
# Foreclosure helpers — PRD §3.6
# ===========================================================================
def open_foreclosure_case(
    loan_id: str,
    *,
    foreclosure_costs_cents: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /foreclosure-cases — ForeclosureAttorney only."""
    headers = headers or TEST_USERS["foreclosure_attorney_headers"]
    payload = create_foreclosure_case_payload(
        loan_id=loan_id,
        foreclosure_costs_cents=foreclosure_costs_cents,
    )
    resp = api_client.create_foreclosure_case(payload, headers)
    return get_success_data(resp)


def file_foreclosure(
    case_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["foreclosure_attorney_headers"]
    resp = api_client.file_foreclosure(case_id, headers)
    return get_success_data(resp)


def schedule_auction(
    case_id: str,
    *,
    auction_date: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["foreclosure_attorney_headers"]
    payload = schedule_auction_payload(auction_date=auction_date)
    resp = api_client.schedule_auction(case_id, payload, headers)
    return get_success_data(resp)


def reinstate_foreclosure(
    case_id: str,
    *,
    payment_amount_cents: int,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /foreclosure-cases/{id}/reinstate — Servicer or Borrower.
    Defaults to Servicer for setup."""
    headers = headers or TEST_USERS["servicer_headers"]
    payload = reinstate_foreclosure_payload(
        payment_amount_cents=payment_amount_cents,
    )
    resp = api_client.reinstate_foreclosure(case_id, payload, headers)
    return get_success_data(resp)


def get_foreclosure_quote(
    case_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["servicer_headers"]
    resp = api_client.get_foreclosure_quote(case_id, headers)
    return get_success_data(resp)


# ===========================================================================
# Mediation helpers — PRD §3.7
# ===========================================================================
def request_mediation(
    case_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /foreclosure-cases/{id}/mediation-cases — Servicer or
    Borrower."""
    headers = headers or TEST_USERS["servicer_headers"]
    resp = api_client.request_mediation(case_id, headers)
    return get_success_data(resp)


def open_mediation(
    mediation_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["lmu_headers"]
    resp = api_client.open_mediation(mediation_id, headers)
    return get_success_data(resp)


def extend_mediation_offer(
    mediation_id: str,
    *,
    offered_new_rate_bps: Optional[int] = None,
    offered_term_extension_months: Optional[int] = None,
    offered_principal_forbearance_cents: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /mediation-cases/{id}/extend-offer."""
    headers = headers or TEST_USERS["lmu_headers"]
    payload = extend_mediation_offer_payload(
        offered_new_rate_bps=offered_new_rate_bps,
        offered_term_extension_months=offered_term_extension_months,
        offered_principal_forbearance_cents=(
            offered_principal_forbearance_cents
        ),
    )
    resp = api_client.extend_mediation_offer(mediation_id, payload, headers)
    return get_success_data(resp)


def accept_mediation_offer(
    mediation_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /mediation-cases/{id}/accept-offer — Borrower or Servicer.
    Defaults to Servicer for setup."""
    headers = headers or TEST_USERS["servicer_headers"]
    resp = api_client.accept_mediation_offer(mediation_id, headers)
    return get_success_data(resp)


def reject_mediation_offer(
    mediation_id: str,
    *,
    rejection_reason: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["lmu_headers"]
    payload = reject_mediation_offer_payload(
        rejection_reason=rejection_reason,
    )
    resp = api_client.reject_mediation_offer(mediation_id, payload, headers)
    return get_success_data(resp)


def complete_mediation(
    mediation_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /mediation-cases/{id}/complete — LMU only. PRD §3.7 requires
    segregation of duties: the LMU completing must NOT be the same
    X-User-ID as the one who extended the most recent offer. Default
    uses lmu_headers_alt so the same fixture used for extend (lmu_headers)
    does not collide."""
    headers = headers or TEST_USERS["lmu_headers_alt"]
    resp = api_client.complete_mediation(mediation_id, headers)
    return get_success_data(resp)


def fail_mediation(
    mediation_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["lmu_headers"]
    resp = api_client.fail_mediation(mediation_id, headers)
    return get_success_data(resp)


# ===========================================================================
# Tier 2: Composite setups — borrower + loan in known states
# ===========================================================================
def setup_borrower_with_hardship(
    *,
    full_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a Borrower and attest hardship. Returns the Borrower
    snapshot. Required precondition for forbearance and mediation
    (PRD §3.4, §3.6)."""
    b = create_borrower(full_name=full_name)
    attest_hardship(b["id"])
    return get_borrower(b["id"])


def setup_borrower_and_current_loan(
    *,
    original_principal_cents: int = 20_000_000,
    original_appraised_value_cents: int = 25_000_000,
    interest_rate_bps: int = 625,
    term_months: int = 360,
    pmi_monthly_cents: Optional[int] = None,
    monthly_escrow_payment_cents: Optional[int] = None,
    with_hardship: bool = False,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Create a Borrower (optionally hardship-attested) and a Loan in
    CURRENT posture. Returns (borrower, loan)."""
    b = setup_borrower_with_hardship() if with_hardship else create_borrower()
    loan = create_loan(
        borrower_id=b["id"],
        original_principal_cents=original_principal_cents,
        original_appraised_value_cents=original_appraised_value_cents,
        interest_rate_bps=interest_rate_bps,
        term_months=term_months,
        pmi_monthly_cents=pmi_monthly_cents,
        monthly_escrow_payment_cents=monthly_escrow_payment_cents,
    )
    return b, loan


def setup_loan_in_delinquent(
    *,
    delinquency_days: int = 35,
    with_hardship: bool = False,
    original_principal_cents: int = 20_000_000,
    pmi_monthly_cents: Optional[int] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Borrower + CURRENT loan, then advance the clock so the loan
    becomes DELINQUENT. Returns (borrower, loan).

    PRD §3.4: 'When a clock advance lifts delinquency_days to at least
    1 and there is no ForbearancePlan in status ACTIVE covering the
    loan, the system transitions Loan.posture from CURRENT to
    DELINQUENT.'

    The loan's next_due_date is origination_date + 1 month per PRD §3.1,
    so to reach exactly `delinquency_days` past due we advance
    30 + delinquency_days days.
    """
    b, loan = setup_borrower_and_current_loan(
        original_principal_cents=original_principal_cents,
        pmi_monthly_cents=pmi_monthly_cents,
        with_hardship=with_hardship,
    )
    advance_clock(30 + delinquency_days)
    loan = get_loan(loan["id"])
    return b, loan


def setup_loan_in_default(
    *,
    with_hardship: bool = True,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Borrower (hardship-attested by default) + Loan in DEFAULT posture
    (delinquency_days >= 120). Returns (borrower, loan).

    PRD §3.4: 'When delinquency reaches at least 120 days and no ACTIVE
    plan covers the loan, the system transitions the loan from
    DELINQUENT to DEFAULT'.
    """
    b, loan = setup_borrower_and_current_loan(with_hardship=with_hardship)
    # Advance 30 (to hit next_due_date) + 120 (to reach default threshold)
    # = 150 days. We bump a small buffer to be safe.
    advance_clock(30 + 121)
    loan = get_loan(loan["id"])
    return b, loan


def setup_foreclosure_case_at_noi_issued(
    *,
    with_hardship: bool = True,
    foreclosure_costs_cents: int = 0,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Default loan + open ForeclosureCase (status=NOI_ISSUED).
    Returns (borrower, loan, foreclosure_case)."""
    b, loan = setup_loan_in_default(with_hardship=with_hardship)
    fc = open_foreclosure_case(
        loan["id"],
        foreclosure_costs_cents=foreclosure_costs_cents,
    )
    return b, loan, fc


def setup_foreclosure_case_filed(
    *,
    foreclosure_costs_cents: int = 0,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """ForeclosureCase advanced to FILED status. Requires NOI window
    (>= 30d) to have elapsed since noi_sent_at. Returns (borrower,
    loan, case)."""
    b, loan, fc = setup_foreclosure_case_at_noi_issued(
        with_hardship=True,
        foreclosure_costs_cents=foreclosure_costs_cents,
    )
    # Advance past the 30-day NOI window so /file is permitted.
    advance_clock(31)
    fc = get_success_data(api_client.file_foreclosure(
        fc["id"], TEST_USERS["foreclosure_attorney_headers"],
    ))
    return b, loan, fc


def setup_foreclosure_case_auction_scheduled(
    *,
    auction_offset_days: int = 30,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Foreclosure case advanced to AUCTION_SCHEDULED. PRD §3.6 requires
    >= 60d after filed_at, and auction_date >= now + 30d (statutory
    notice). auction_offset_days lets tests pick exactly where in the
    permissible window the auction falls (measured from the SERVER'S
    logical clock at the moment of scheduling).

    Implementation note: this fixture invokes /_clock/advance several
    times during setup (30 + 121 + 31 + 61 = 243 days). PRD §2.9 says
    the logical clock is the only authoritative time source for
    business-rule evaluation. We therefore track the cumulative
    `advanced_days` and compute auction_date as
    wall_today + advanced_days + auction_offset_days so that on the
    implementation's logical clock, auction_date == logical_now +
    auction_offset_days.

    Returns (borrower, loan, case).
    """
    # Track cumulative advances so we can express auction_date in the
    # server's logical clock frame.
    advanced_days = 0
    # setup_foreclosure_case_filed runs: default (30 + 121) + 31 file.
    b, loan, fc = setup_foreclosure_case_filed()
    advanced_days += 30 + 121 + 31
    # Advance 61 more days so the filed_at +60d gate is satisfied.
    advance_clock(61)
    advanced_days += 61
    today = today_utc()
    auction_date = iso_datetime_utc_midnight(
        today + timedelta(days=advanced_days + auction_offset_days),
    )
    fc = schedule_auction(fc["id"], auction_date=auction_date)
    return b, loan, fc


def setup_mediation_open(
    ) -> Tuple[Dict[str, Any], Dict[str, Any],
               Dict[str, Any], Dict[str, Any]]:
    """Borrower (hardship) + DEFAULT loan + ForeclosureCase NOI_ISSUED
    + MediationCase moved to OPEN. Returns (borrower, loan, case,
    mediation)."""
    b, loan, fc = setup_foreclosure_case_at_noi_issued(with_hardship=True)
    m = request_mediation(fc["id"])
    m = open_mediation(m["id"])
    return b, loan, fc, m


def setup_mediation_offer_extended(
    *,
    offered_new_rate_bps: Optional[int] = 400,
    offered_term_extension_months: Optional[int] = 60,
    offered_principal_forbearance_cents: Optional[int] = 1_000_000,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """MediationCase advanced to OFFER_EXTENDED with the supplied
    HAMP offer terms. Returns (borrower, loan, case, mediation).
    """
    b, loan, fc, m = setup_mediation_open()
    m = extend_mediation_offer(
        m["id"],
        offered_new_rate_bps=offered_new_rate_bps,
        offered_term_extension_months=offered_term_extension_months,
        offered_principal_forbearance_cents=(
            offered_principal_forbearance_cents
        ),
    )
    return b, loan, fc, m


# ===========================================================================
# Tier 3: Forbearance plan setups
# ===========================================================================
def setup_active_forbearance_plan(
    *,
    months: int = 3,
    repayment_method: str = "LUMP_SUM",
    pmi_monthly_cents: Optional[int] = None,
    monthly_escrow_payment_cents: Optional[int] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Borrower (hardship) + CURRENT loan + ACTIVE ForbearancePlan.
    Returns (borrower, loan, plan).

    start_date defaults to today so the plan covers next_due_date.
    """
    b, loan = setup_borrower_and_current_loan(
        with_hardship=True,
        pmi_monthly_cents=pmi_monthly_cents,
        monthly_escrow_payment_cents=monthly_escrow_payment_cents,
    )
    start = iso_datetime_utc_midnight(today_utc())
    plan = create_forbearance_plan(
        loan["id"],
        start_date=start,
        months=months,
        repayment_method=repayment_method,
    )
    loan = get_loan(loan["id"])
    return b, loan, plan


# ===========================================================================
# Tier 4: PMI removal setups
# ===========================================================================
def setup_pmi_pending_borrower_request(
    *,
    pmi_monthly_cents: int = 8_000,
    current_appraised_value_cents: int = 25_000_000,
    original_principal_cents: int = 20_000_000,
    original_appraised_value_cents: int = 25_000_000,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Borrower + Loan with active PMI + PENDING BORROWER_REQUEST
    PmiRemovalRequest. Returns (borrower, loan, request)."""
    b, loan = setup_borrower_and_current_loan(
        original_principal_cents=original_principal_cents,
        original_appraised_value_cents=original_appraised_value_cents,
        pmi_monthly_cents=pmi_monthly_cents,
    )
    req = create_pmi_removal_request(
        loan["id"],
        trigger="BORROWER_REQUEST",
        current_appraised_value_cents=current_appraised_value_cents,
    )
    loan = get_loan(loan["id"])
    return b, loan, req


# ===========================================================================
# Tier 5: Escrow setups
# ===========================================================================
def setup_loan_with_disbursements(
    *,
    pmi_monthly_cents: Optional[int] = None,
    disbursements: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], List[Dict[str, Any]]]:
    """Create a CURRENT loan and seed it with the supplied
    Disbursements. Each entry in `disbursements` is a dict with keys
    type, days_out, amount_cents. Returns (borrower, loan, [disbursement])."""
    b, loan = setup_borrower_and_current_loan(
        pmi_monthly_cents=pmi_monthly_cents,
    )
    seeded = []
    today = today_utc()
    for spec in (disbursements or []):
        scheduled = iso_datetime_utc_midnight(
            today + timedelta(days=int(spec["days_out"])),
        )
        d = schedule_disbursement(
            loan["id"],
            type=spec["type"],
            scheduled_date=scheduled,
            amount_cents=int(spec["amount_cents"]),
        )
        seeded.append(d)
    loan = get_loan(loan["id"])
    return b, loan, seeded


# ===========================================================================
# Tier 6: Difficulty-design composite setups
# ===========================================================================
def setup_escrow_provisional_for_finalize_divergence(
    ) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Difficulty: dual_variant_calc/escrow_projection_provisional_vs_finalized.

    Recipe per SCAFFOLD_DIFFICULTY_DESIGN:
      - Loan P=20000000, rate=625, term=360, pmi=0, appraised=25000000
      - Disbursement type=PROPERTY_TAX, scheduled now+90d, amount 480000
      - POST /escrow-analyses analysis_date=now, starting_balance=0 -> A1
    Returns (borrower, loan, provisional_analysis).
    """
    b, loan = setup_borrower_and_current_loan(
        original_principal_cents=20_000_000,
        original_appraised_value_cents=25_000_000,
        interest_rate_bps=625,
        term_months=360,
        pmi_monthly_cents=0,
    )
    today = today_utc()
    schedule_disbursement(
        loan["id"],
        type="PROPERTY_TAX",
        scheduled_date=iso_datetime_utc_midnight(today + timedelta(days=90)),
        amount_cents=480_000,
    )
    loan = get_loan(loan["id"])
    a1 = create_escrow_analysis(
        loan["id"],
        analysis_date=iso_datetime_utc_midnight(today),
        starting_balance_cents=int(loan["escrow_balance_cents"]),
    )
    return b, loan, a1


def setup_loan_at_delinquency_days(
    delinquency_days: int,
    *,
    pmi_monthly_cents: Optional[int] = None,
    original_principal_cents: int = 20_000_000,
    interest_rate_bps: int = 625,
    term_months: int = 360,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Reach an exact delinquency_days posture by advancing the clock
    30 + delinquency_days days. Returns (borrower, loan)."""
    b, loan = setup_borrower_and_current_loan(
        original_principal_cents=original_principal_cents,
        interest_rate_bps=interest_rate_bps,
        term_months=term_months,
        pmi_monthly_cents=pmi_monthly_cents,
    )
    if delinquency_days > 0:
        advance_clock(30 + delinquency_days)
    loan = get_loan(loan["id"])
    return b, loan


def setup_loan_with_escrow_balance(
    target_escrow_balance_cents: int,
    *,
    pmi_monthly_cents: Optional[int] = None,
    monthly_escrow_payment_cents: Optional[int] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Drive the loan's escrow_balance_cents to a known value by
    posting a payment whose allocation_escrow_cents equals the target.

    This relies on the standard waterfall placing the residual into
    suspense after escrow demand is met; for a CURRENT loan with zero
    past-due P&I, escrow allocation will only consume up to the
    past-due escrow demand. We therefore post a large payment that
    exceeds P&I + escrow demand and rely on the escrow demand being
    capped by `monthly_escrow_payment_cents` per installment.

    A reliable alternative — used here — is to set
    monthly_escrow_payment_cents at creation and then advance the
    clock by one installment so the next_due_date passes, creating
    past-due escrow demand the payment can fund.

    Returns (borrower, loan).
    """
    monthly_escrow_payment_cents = (
        monthly_escrow_payment_cents
        or max(target_escrow_balance_cents, 1)
    )
    b, loan = setup_borrower_and_current_loan(
        pmi_monthly_cents=pmi_monthly_cents,
        monthly_escrow_payment_cents=monthly_escrow_payment_cents,
    )
    # Advance one installment so escrow demand becomes past-due. After
    # the advance the server's logical clock is wall_today + 30d, so the
    # payment's received_date must match that for the waterfall to see
    # the now-past-due installment per PRD §3.2 ("summed across all
    # installments due as of received_date").
    advance_clock(30)
    sched = int(loan.get("scheduled_payment_cents", 0))
    # Pay scheduled P&I + target escrow so the escrow allocation
    # equals target_escrow_balance_cents.
    post_payment(
        loan["id"],
        amount_cents=sched + target_escrow_balance_cents,
        received_date=iso_datetime_utc_midnight(today_utc() + timedelta(days=30)),
    )
    loan = get_loan(loan["id"])
    return b, loan


__all__ = [
    "create_borrower",
    "attest_hardship",
    "get_borrower",
    "create_loan",
    "get_loan",
    "advance_clock",
    "run_sweep",
    "post_payment",
    "reverse_payment",
    "schedule_disbursement",
    "retry_disbursement",
    "cancel_disbursement",
    "create_escrow_analysis",
    "finalize_escrow_analysis",
    "create_forbearance_plan",
    "cancel_forbearance_plan",
    "create_pmi_removal_request",
    "approve_pmi_removal",
    "deny_pmi_removal",
    "open_foreclosure_case",
    "file_foreclosure",
    "schedule_auction",
    "reinstate_foreclosure",
    "get_foreclosure_quote",
    "request_mediation",
    "open_mediation",
    "extend_mediation_offer",
    "accept_mediation_offer",
    "reject_mediation_offer",
    "complete_mediation",
    "fail_mediation",
    "setup_borrower_with_hardship",
    "setup_borrower_and_current_loan",
    "setup_loan_in_delinquent",
    "setup_loan_in_default",
    "setup_foreclosure_case_at_noi_issued",
    "setup_foreclosure_case_filed",
    "setup_foreclosure_case_auction_scheduled",
    "setup_mediation_open",
    "setup_mediation_offer_extended",
    "setup_active_forbearance_plan",
    "setup_pmi_pending_borrower_request",
    "setup_loan_with_disbursements",
    "setup_escrow_provisional_for_finalize_divergence",
    "setup_loan_at_delinquency_days",
    "setup_loan_with_escrow_balance",
]
