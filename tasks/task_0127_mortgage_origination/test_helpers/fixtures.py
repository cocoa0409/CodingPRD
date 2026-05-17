"""Composite setup helpers — multi-step preambles tests can reuse.

The mortgage-origination pipeline has eight states on the
LoanApplication alone and five additional child state machines. A
typical test (e.g. "APR tolerance at 13 bps rejects with
ERR_APR_TOLERANCE_EXCEEDED" or "rate-lock extension cap at 60 vs 61
days") requires the system in a state that takes 8-15 API calls to
reach:

  POST /_clock/advance               (set a deterministic anchor)
  POST /borrowers
  POST /loan-applications            (INTAKE)
  POST .../pre-qualify               (-> PRE_QUALIFIED)
  POST .../income-verifications, /verify  (>=1 VERIFIED)
  POST .../asset-verifications, /verify   (>=1 VERIFIED)
  POST .../appraisal, /complete           (-> COMPLETED with valid_until)
  POST .../title-search, /complete        (-> CLEAR or ISSUES_FOUND)
  POST .../disclosures (LOAN_ESTIMATE)    (initial LE)
  POST .../submit-underwriting            (-> UNDERWRITING)
  POST .../udaap-reviews (PASS on LE)
  POST .../underwrite-decision (APPROVE)  (-> CONDITIONAL_APPROVAL)
  POST .../rate-lock                      (-> LOCKED)
  POST .../disclosures (CLOSING_DISCLOSURE)
  POST .../disclosures/{id}/acknowledge   (Borrower acks)
  POST .../udaap-reviews (PASS on CD)
  POST /_clock/advance                    (>= TRID 3 business days)
  POST .../clear-to-close                 (-> CLEAR_TO_CLOSE)
  POST .../close                          (-> CLOSED)

IDENTITY THREADING — PRD §2.1:

- LoanOfficer / ComplianceOfficer / Admin are OPAQUE. Shared constants
  in TEST_USERS are canonical for the operator-only calls. The fixture
  layer threads the SAME LoanOfficer id into LoanApplication.
  assigned_loan_officer_id at creation so that the SoD checks at
  underwrite-decision and clear-to-close have a meaningful "self"
  reference.
- Borrower is ENTITY-BACKED. Every Borrower-acting call here (only
  POST .../disclosures/{id}/acknowledge in the live workflow) MUST mint
  headers via make_borrower_headers(borrower["id"]).

SEGREGATION OF DUTIES — PRD §2.1 / §3.7 / §3.10:
- "the actor's X-User-ID must not equal the compliance_reviewer_id
  recorded on the application" — on underwrite-decision and
  clear-to-close.
- "the actor's X-User-ID must equal the compliance_reviewer_id on the
  application" — on POST .../udaap-reviews.

Fixtures here ALWAYS assign a ComplianceOfficer at submit-underwriting
that is distinct from the acting LoanOfficer, and use the same
ComplianceOfficer headers when submitting UDAAP reviews so the SoD
checks pass without test friction. Tests that want to exercise the
violating path construct their own headers explicitly.

Setup calls use get_success_data (lenient 2xx validator) so a failed
setup surfaces as "Setup step failed" rather than a misleading test
assertion failure downstream.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    clock_advance_payload,
    complete_appraisal_payload,
    complete_title_search_payload,
    create_asset_verification_payload,
    create_borrower_payload,
    create_income_verification_payload,
    create_loan_application_payload,
    extend_rate_lock_payload,
    issue_disclosure_payload,
    order_appraisal_payload,
    place_rate_lock_payload,
    submit_udaap_review_payload,
    submit_underwriting_payload,
    underwrite_decision_payload,
)
from .test_users import (
    COMPLIANCE_OFFICER_ID,
    LOAN_OFFICER_ID,
    TEST_USERS,
    make_borrower_headers,
    make_compliance_headers,
    make_loan_officer_headers,
)


# ===========================================================================
# Tier 0: low-level helpers
# ===========================================================================
def advance_clock(
    to_iso: str,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /_clock/advance — Admin only (PRD §2.9 / §4).

    PRD §2.9: "The clock only ever moves forward in test scenarios;
    nothing in the business logic rewinds it." If the implementation
    rejects an at-or-before request (some implementations idempotently
    accept; others reject), the fixture silently no-ops so chained
    setup remains idempotent.
    """
    headers = headers or TEST_USERS["admin_headers"]
    resp = api_client.advance_clock(
        clock_advance_payload(to=to_iso), headers,
    )
    if 200 <= resp.status_code < 300:
        return get_success_data(resp)
    # Treat any 4xx on advance as "already at-or-beyond" — for setup
    # idempotence only; the implementation contract is unchanged.
    return {"now": to_iso, "no_op": True}


def parse_iso(s: str) -> datetime:
    """Parse a Z-suffixed or naive ISO8601 into an aware UTC datetime."""
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso_z(dt: datetime) -> str:
    """Render an aware datetime as a Z-suffixed ISO8601 with ms."""
    dt = dt.astimezone(timezone.utc)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    millis = f"{dt.microsecond // 1000:03d}"
    return f"{base}.{millis}Z"


def iso_plus(base: str, **kw: Any) -> str:
    """Add a timedelta to an ISO8601 instant and render in the same
    Z-suffixed millisecond format.
    """
    return iso_z(parse_iso(base) + timedelta(**kw))


def get_loan_application(
    app_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["loan_officer_headers"]
    return get_success_data(
        api_client.get_loan_application(app_id, headers),
    )


def get_rate_lock(
    app_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["loan_officer_headers"]
    return get_success_data(
        api_client.get_rate_lock(app_id, headers),
    )


# ===========================================================================
# Tier 1: Borrower + LoanApplication creation
# ===========================================================================
def create_borrower(
    *,
    annual_income_cents: Optional[int] = None,
    credit_score: Optional[int] = None,
    state_code: Optional[str] = None,
    full_name: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /borrowers — LoanOfficer or Admin (PRD §4)."""
    headers = headers or TEST_USERS["loan_officer_headers"]
    return get_success_data(
        api_client.create_borrower(
            create_borrower_payload(
                full_name=full_name,
                annual_income_cents=annual_income_cents,
                credit_score=credit_score,
                state_code=state_code,
            ),
            headers,
        ),
    )


def create_loan_application(
    borrower_id: str,
    *,
    sale_price_cents: Optional[int] = None,
    requested_loan_amount_cents: Optional[int] = None,
    loan_term_months: Optional[int] = None,
    loan_purpose: Optional[str] = None,
    assigned_loan_officer_id: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /loan-applications — LoanOfficer or Admin (PRD §4).

    Defaults assigned_loan_officer_id to LOAN_OFFICER_ID, the canonical
    operator id the shared loan_officer_headers carries. Tests that
    want SoD violation scenarios pass a distinct value.
    """
    headers = headers or TEST_USERS["loan_officer_headers"]
    return get_success_data(
        api_client.create_loan_application(
            create_loan_application_payload(
                borrower_id=borrower_id,
                sale_price_cents=sale_price_cents,
                requested_loan_amount_cents=requested_loan_amount_cents,
                loan_term_months=loan_term_months,
                loan_purpose=loan_purpose,
                assigned_loan_officer_id=(
                    assigned_loan_officer_id or LOAN_OFFICER_ID
                ),
            ),
            headers,
        ),
    )


def create_borrower_and_application(
    *,
    annual_income_cents: Optional[int] = None,
    credit_score: Optional[int] = None,
    state_code: Optional[str] = None,
    sale_price_cents: Optional[int] = None,
    requested_loan_amount_cents: Optional[int] = None,
    loan_term_months: Optional[int] = None,
    loan_purpose: Optional[str] = None,
    assigned_loan_officer_id: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Create a Borrower and a LoanApplication in INTAKE. Returns
    (borrower, application).
    """
    borrower = create_borrower(
        annual_income_cents=annual_income_cents,
        credit_score=credit_score,
        state_code=state_code,
        headers=headers,
    )
    app = create_loan_application(
        borrower["id"],
        sale_price_cents=sale_price_cents,
        requested_loan_amount_cents=requested_loan_amount_cents,
        loan_term_months=loan_term_months,
        loan_purpose=loan_purpose,
        assigned_loan_officer_id=assigned_loan_officer_id,
        headers=headers,
    )
    return borrower, app


# ===========================================================================
# Tier 1.5: Pre-qualify
# ===========================================================================
def pre_qualify(
    app_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST .../pre-qualify — LoanOfficer (PRD §4)."""
    headers = headers or TEST_USERS["loan_officer_headers"]
    return get_success_data(
        api_client.pre_qualify(app_id, None, headers),
    )


def create_and_pre_qualify(
    *,
    annual_income_cents: Optional[int] = None,
    credit_score: Optional[int] = None,
    state_code: Optional[str] = None,
    sale_price_cents: Optional[int] = None,
    requested_loan_amount_cents: Optional[int] = None,
    loan_term_months: Optional[int] = None,
    loan_purpose: Optional[str] = None,
    assigned_loan_officer_id: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Create Borrower + LoanApplication and transition to
    PRE_QUALIFIED. Returns (borrower, application_in_PRE_QUALIFIED).
    """
    borrower, app = create_borrower_and_application(
        annual_income_cents=annual_income_cents,
        credit_score=credit_score,
        state_code=state_code,
        sale_price_cents=sale_price_cents,
        requested_loan_amount_cents=requested_loan_amount_cents,
        loan_term_months=loan_term_months,
        loan_purpose=loan_purpose,
        assigned_loan_officer_id=assigned_loan_officer_id,
        headers=headers,
    )
    app = pre_qualify(app["id"], headers=headers)
    return borrower, app


# ===========================================================================
# Tier 2: Income / Asset verifications
# ===========================================================================
def create_and_verify_income(
    app_id: str,
    *,
    source_type: str = "W2",
    documented_annual_cents: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Create an IncomeVerification and transition to VERIFIED.

    PRD §3.3: documented_annual_cents must be at least 80% of stated
    income to verify. By default the helper passes the same value as
    the borrower's stated income so the threshold is comfortably met.
    When `documented_annual_cents` is None, the helper looks up the
    application's borrower and uses the borrower's stated
    annual_income_cents — this guarantees the 80% threshold is met for
    any caller-supplied stated income, not just the hard-coded
    TEST_DEFAULTS value.
    """
    headers = headers or TEST_USERS["loan_officer_headers"]
    if documented_annual_cents is None:
        app = get_success_data(
            api_client.get_loan_application(app_id, headers),
        )
        borrower = get_success_data(
            api_client.get_borrower(app["borrower_id"], headers),
        )
        documented_annual_cents = int(borrower["annual_income_cents"])
    ver = get_success_data(api_client.create_income_verification(
        app_id,
        create_income_verification_payload(
            source_type=source_type,
            documented_annual_cents=documented_annual_cents,
        ),
        headers,
    ))
    return get_success_data(api_client.verify_income(
        app_id, ver["id"], None, headers,
    ))


def create_and_verify_asset(
    app_id: str,
    *,
    asset_type: str = "SAVINGS",
    balance_cents: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Create an AssetVerification and transition to VERIFIED.

    PRD §3.3: balance_cents must be at least 1,000 to verify.
    """
    headers = headers or TEST_USERS["loan_officer_headers"]
    av = get_success_data(api_client.create_asset_verification(
        app_id,
        create_asset_verification_payload(
            asset_type=asset_type, balance_cents=balance_cents,
        ),
        headers,
    ))
    return get_success_data(api_client.verify_asset(
        app_id, av["id"], None, headers,
    ))


# ===========================================================================
# Tier 2: Appraisal + Title search
# ===========================================================================
def order_and_complete_appraisal(
    app_id: str,
    *,
    report_date: Optional[str] = None,
    appraised_value_cents: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Order an Appraisal and transition to COMPLETED. Returns the
    COMPLETED Appraisal.
    """
    headers = headers or TEST_USERS["loan_officer_headers"]
    appr = get_success_data(api_client.order_appraisal(
        app_id, order_appraisal_payload(report_date=report_date),
        headers,
    ))
    return get_success_data(api_client.complete_appraisal(
        app_id,
        complete_appraisal_payload(
            appraised_value_cents=appraised_value_cents,
        ),
        headers,
    ))


def order_and_complete_title_search(
    app_id: str,
    *,
    defects_found: Optional[List[str]] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Order a TitleSearch and transition to CLEAR (by default) or
    ISSUES_FOUND (if defects_found is non-empty).
    """
    headers = headers or TEST_USERS["loan_officer_headers"]
    ts = get_success_data(api_client.order_title_search(
        app_id, None, headers,
    ))
    return get_success_data(api_client.complete_title_search(
        app_id,
        complete_title_search_payload(defects_found=defects_found),
        headers,
    ))


# ===========================================================================
# Tier 2: Disclosures
# ===========================================================================
def issue_loan_estimate(
    app_id: str,
    *,
    apr_bps: Optional[int] = None,
    total_loan_costs_cents: Optional[int] = None,
    total_other_costs_cents: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST .../disclosures kind=LOAN_ESTIMATE — LoanOfficer (PRD §4)."""
    headers = headers or TEST_USERS["loan_officer_headers"]
    return get_success_data(api_client.issue_disclosure(
        app_id,
        issue_disclosure_payload(
            kind="LOAN_ESTIMATE",
            apr_bps=apr_bps,
            total_loan_costs_cents=total_loan_costs_cents,
            total_other_costs_cents=total_other_costs_cents,
        ),
        headers,
    ))


def issue_closing_disclosure(
    app_id: str,
    *,
    apr_bps: Optional[int] = None,
    total_loan_costs_cents: Optional[int] = None,
    total_other_costs_cents: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST .../disclosures kind=CLOSING_DISCLOSURE — LoanOfficer."""
    headers = headers or TEST_USERS["loan_officer_headers"]
    return get_success_data(api_client.issue_disclosure(
        app_id,
        issue_disclosure_payload(
            kind="CLOSING_DISCLOSURE",
            apr_bps=apr_bps,
            total_loan_costs_cents=total_loan_costs_cents,
            total_other_costs_cents=total_other_costs_cents,
        ),
        headers,
    ))


def acknowledge_disclosure(
    app_id: str, disclosure_id: str, borrower_id: str,
) -> Dict[str, Any]:
    """POST .../disclosures/{id}/acknowledge — Borrower only.

    PRD §2.1: Borrower is entity-backed; X-User-ID must equal the
    LoanApplication.borrower_id. The borrower_id parameter is threaded
    into make_borrower_headers so the ownership check passes.
    """
    headers = make_borrower_headers(borrower_id)
    return get_success_data(api_client.acknowledge_disclosure(
        app_id, disclosure_id, None, headers,
    ))


# ===========================================================================
# Tier 2: UDAAP review
# ===========================================================================
def submit_udaap_pass(
    app_id: str,
    *,
    compliance_officer_id: str = COMPLIANCE_OFFICER_ID,
    notes: Optional[str] = None,
) -> Dict[str, Any]:
    """POST .../udaap-reviews with outcome=PASS — ComplianceOfficer
    (PRD §3.9 / §4).

    PRD §3.9: "The submitting actor's X-User-ID must equal the
    application's compliance_reviewer_id". The fixture threads the
    given compliance_officer_id (which must already have been assigned
    as compliance_reviewer_id at submit-underwriting) into the headers.
    """
    headers = make_compliance_headers(compliance_officer_id)
    return get_success_data(api_client.submit_udaap_review(
        app_id,
        submit_udaap_review_payload(outcome="PASS", notes=notes),
        headers,
    ))


def submit_udaap(
    app_id: str,
    *,
    outcome: str,
    notes: Optional[str] = None,
    compliance_officer_id: str = COMPLIANCE_OFFICER_ID,
) -> Dict[str, Any]:
    """Generic UDAAP review submission (PASS/FLAG/BLOCK)."""
    headers = make_compliance_headers(compliance_officer_id)
    return get_success_data(api_client.submit_udaap_review(
        app_id,
        submit_udaap_review_payload(outcome=outcome, notes=notes),
        headers,
    ))


# ===========================================================================
# Tier 3: Submit-underwriting (the big precondition gate)
# ===========================================================================
def setup_application_ready_for_underwriting(
    *,
    annual_income_cents: Optional[int] = None,
    credit_score: Optional[int] = None,
    state_code: Optional[str] = None,
    sale_price_cents: Optional[int] = None,
    requested_loan_amount_cents: Optional[int] = None,
    loan_term_months: Optional[int] = None,
    loan_purpose: Optional[str] = None,
    appraised_value_cents: Optional[int] = None,
    appraisal_report_date: Optional[str] = None,
    income_documented_annual_cents: Optional[int] = None,
    asset_balance_cents: Optional[int] = None,
    le_apr_bps: Optional[int] = None,
    le_total_loan_costs_cents: Optional[int] = None,
    le_total_other_costs_cents: Optional[int] = None,
    title_defects: Optional[List[str]] = None,
    clock_anchor: Optional[str] = None,
    assigned_loan_officer_id: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Build out an application that satisfies every submit-underwriting
    precondition listed in PRD §3.7:

      - at least one VERIFIED IncomeVerification
      - at least one VERIFIED AssetVerification
      - a COMPLETED Appraisal
      - a CLEAR or RESOLVED TitleSearch
      - an issued LOAN_ESTIMATE Disclosure

    Returns (borrower, application_in_PRE_QUALIFIED, appraisal, le).
    """
    if clock_anchor is not None:
        advance_clock(clock_anchor)
    borrower, app = create_and_pre_qualify(
        annual_income_cents=annual_income_cents,
        credit_score=credit_score,
        state_code=state_code,
        sale_price_cents=sale_price_cents,
        requested_loan_amount_cents=requested_loan_amount_cents,
        loan_term_months=loan_term_months,
        loan_purpose=loan_purpose,
        assigned_loan_officer_id=assigned_loan_officer_id,
        headers=headers,
    )
    create_and_verify_income(
        app["id"],
        documented_annual_cents=income_documented_annual_cents,
        headers=headers,
    )
    create_and_verify_asset(
        app["id"],
        balance_cents=asset_balance_cents,
        headers=headers,
    )
    appr = order_and_complete_appraisal(
        app["id"],
        report_date=appraisal_report_date,
        appraised_value_cents=appraised_value_cents,
        headers=headers,
    )
    order_and_complete_title_search(
        app["id"],
        defects_found=title_defects,
        headers=headers,
    )
    le = issue_loan_estimate(
        app["id"],
        apr_bps=le_apr_bps,
        total_loan_costs_cents=le_total_loan_costs_cents,
        total_other_costs_cents=le_total_other_costs_cents,
        headers=headers,
    )
    return borrower, app, appr, le


def submit_underwriting(
    app_id: str,
    *,
    compliance_reviewer_id: str = COMPLIANCE_OFFICER_ID,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST .../submit-underwriting — LoanOfficer.

    PRD §3.7 SoD: compliance_reviewer_id must differ from
    assigned_loan_officer_id. Default values (LOAN_OFFICER_ID vs
    COMPLIANCE_OFFICER_ID) already satisfy this.
    """
    headers = headers or TEST_USERS["loan_officer_headers"]
    return get_success_data(api_client.submit_underwriting(
        app_id,
        submit_underwriting_payload(
            compliance_reviewer_id=compliance_reviewer_id,
        ),
        headers,
    ))


def setup_application_in_underwriting(
    **kw: Any,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Application driven all the way to UNDERWRITING state. Returns
    (borrower, application_in_UNDERWRITING, appraisal, le).
    """
    compliance_reviewer_id = kw.pop(
        "compliance_reviewer_id", COMPLIANCE_OFFICER_ID,
    )
    borrower, app, appr, le = setup_application_ready_for_underwriting(**kw)
    app = submit_underwriting(
        app["id"],
        compliance_reviewer_id=compliance_reviewer_id,
        headers=kw.get("headers"),
    )
    return borrower, app, appr, le


# ===========================================================================
# Tier 3: Underwrite decision (APPROVE / COUNTER_OFFER / DENY)
# ===========================================================================
def underwrite_approve(
    app_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST .../underwrite-decision decision=APPROVE — LoanOfficer.

    PRD §3.8 / §2.10: SoD applies — the actor's X-User-ID must not
    equal compliance_reviewer_id. The default
    loan_officer_headers (LOAN_OFFICER_ID) differs from the default
    compliance_reviewer_id (COMPLIANCE_OFFICER_ID) used by fixtures.
    """
    headers = headers or TEST_USERS["loan_officer_headers"]
    return get_success_data(api_client.underwrite_decision(
        app_id, underwrite_decision_payload(decision="APPROVE"),
        headers,
    ))


def underwrite_counter_offer(
    app_id: str,
    *,
    counter_offered_amount_cents: int,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST .../underwrite-decision decision=COUNTER_OFFER —
    LoanOfficer (PRD §3.8).
    """
    headers = headers or TEST_USERS["loan_officer_headers"]
    return get_success_data(api_client.underwrite_decision(
        app_id,
        underwrite_decision_payload(
            decision="COUNTER_OFFER",
            counter_offered_amount_cents=counter_offered_amount_cents,
        ),
        headers,
    ))


def underwrite_deny(
    app_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST .../underwrite-decision decision=DENY — LoanOfficer."""
    headers = headers or TEST_USERS["loan_officer_headers"]
    return get_success_data(api_client.underwrite_decision(
        app_id, underwrite_decision_payload(decision="DENY"),
        headers,
    ))


# ===========================================================================
# Tier 3: Rate lock
# ===========================================================================
def place_rate_lock(
    app_id: str,
    *,
    locked_rate_bps: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST .../rate-lock — LoanOfficer (PRD §3.5)."""
    headers = headers or TEST_USERS["loan_officer_headers"]
    return get_success_data(api_client.place_rate_lock(
        app_id, place_rate_lock_payload(locked_rate_bps=locked_rate_bps),
        headers,
    ))


def extend_rate_lock(
    app_id: str,
    *,
    extra_days: int,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST .../rate-lock/extend — LoanOfficer (PRD §3.5)."""
    headers = headers or TEST_USERS["loan_officer_headers"]
    return get_success_data(api_client.extend_rate_lock(
        app_id, extend_rate_lock_payload(extra_days=extra_days),
        headers,
    ))


# ===========================================================================
# Tier 4: Conditional approval (full stack to CONDITIONAL_APPROVAL)
# ===========================================================================
def setup_application_in_conditional_approval(
    *,
    clock_anchor: str = TEST_DEFAULTS["DEFAULT_CLOCK_ANCHOR"],
    annual_income_cents: Optional[int] = None,
    sale_price_cents: Optional[int] = None,
    requested_loan_amount_cents: Optional[int] = None,
    appraised_value_cents: Optional[int] = None,
    state_code: Optional[str] = None,
    le_apr_bps: Optional[int] = None,
    income_documented_annual_cents: Optional[int] = None,
    appraisal_report_date: Optional[str] = None,
    title_defects: Optional[List[str]] = None,
    compliance_reviewer_id: str = COMPLIANCE_OFFICER_ID,
    headers: Optional[Dict[str, str]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Drive an application all the way to CONDITIONAL_APPROVAL with a
    PASS UDAAP on the LOAN_ESTIMATE. Returns
    (borrower, application_in_CONDITIONAL_APPROVAL, appraisal, le).
    """
    borrower, app, appr, le = setup_application_in_underwriting(
        clock_anchor=clock_anchor,
        annual_income_cents=annual_income_cents,
        sale_price_cents=sale_price_cents,
        requested_loan_amount_cents=requested_loan_amount_cents,
        appraised_value_cents=appraised_value_cents,
        state_code=state_code,
        le_apr_bps=le_apr_bps,
        income_documented_annual_cents=income_documented_annual_cents,
        appraisal_report_date=appraisal_report_date,
        title_defects=title_defects,
        compliance_reviewer_id=compliance_reviewer_id,
        headers=headers,
    )
    submit_udaap_pass(
        app["id"], compliance_officer_id=compliance_reviewer_id,
    )
    app = underwrite_approve(app["id"], headers=headers)
    return borrower, app, appr, le


# ===========================================================================
# Tier 4: Clear-to-close ready (rate lock + CD + ack + UDAAP PASS on CD +
# TRID waiting period elapsed)
# ===========================================================================
def setup_application_ready_for_clear_to_close(
    *,
    clock_anchor: str = TEST_DEFAULTS["DEFAULT_CLOCK_ANCHOR"],
    annual_income_cents: Optional[int] = None,
    sale_price_cents: Optional[int] = None,
    requested_loan_amount_cents: Optional[int] = None,
    appraised_value_cents: Optional[int] = None,
    state_code: Optional[str] = None,
    le_apr_bps: int = 650,
    cd_apr_bps: int = 650,  # same as LE so APR-tolerance never trips
    cd_total_loan_costs_cents: Optional[int] = None,
    cd_total_other_costs_cents: Optional[int] = None,
    locked_rate_bps: int = 650,
    compliance_reviewer_id: str = COMPLIANCE_OFFICER_ID,
    title_defects: Optional[List[str]] = None,
    advance_to_after_trid: bool = True,
    headers: Optional[Dict[str, str]] = None,
) -> Tuple[
    Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any],
    Dict[str, Any],
]:
    """Drive an application to CONDITIONAL_APPROVAL, place a RateLock,
    issue a CLOSING_DISCLOSURE, acknowledge it, submit a PASS UDAAP on
    the CD, and (by default) advance the clock past the TRID 3-business-
    day window so a clear-to-close call will succeed.

    Returns (borrower, application_in_CONDITIONAL_APPROVAL, appraisal,
              le, cd).
    """
    borrower, app, appr, le = setup_application_in_conditional_approval(
        clock_anchor=clock_anchor,
        annual_income_cents=annual_income_cents,
        sale_price_cents=sale_price_cents,
        requested_loan_amount_cents=requested_loan_amount_cents,
        appraised_value_cents=appraised_value_cents,
        state_code=state_code,
        le_apr_bps=le_apr_bps,
        title_defects=title_defects,
        compliance_reviewer_id=compliance_reviewer_id,
        headers=headers,
    )
    place_rate_lock(
        app["id"], locked_rate_bps=locked_rate_bps, headers=headers,
    )
    cd = issue_closing_disclosure(
        app["id"],
        apr_bps=cd_apr_bps,
        total_loan_costs_cents=cd_total_loan_costs_cents,
        total_other_costs_cents=cd_total_other_costs_cents,
        headers=headers,
    )
    acknowledge_disclosure(app["id"], cd["id"], borrower["id"])
    submit_udaap_pass(
        app["id"], compliance_officer_id=compliance_reviewer_id,
    )
    if advance_to_after_trid:
        # PRD §3.6: CD's eligible_to_consummate_at is 3 business days
        # after issued_at, anchored at 00:00:00 UTC. To be safe we
        # advance the clock by 7 calendar days from the issue moment so
        # the inclusive boundary is comfortably crossed in any
        # weekday/weekend/holiday geometry.
        target = iso_plus(cd["issued_at"], days=7)
        advance_clock(target)
    return borrower, app, appr, le, cd


# ===========================================================================
# Tier 5: Full lifecycle through CLOSED
# ===========================================================================
def setup_closed_application(
    **kw: Any,
) -> Tuple[
    Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any],
    Dict[str, Any],
]:
    """Drive an application all the way to CLOSED.

    Returns (borrower, application_in_CLOSED, appraisal, le, cd).
    """
    borrower, app, appr, le, cd = (
        setup_application_ready_for_clear_to_close(**kw)
    )
    headers = kw.get("headers") or TEST_USERS["loan_officer_headers"]
    app = get_success_data(api_client.clear_to_close(
        app["id"], None, headers,
    ))
    app = get_success_data(api_client.close_application(
        app["id"], None, headers,
    ))
    return borrower, app, appr, le, cd


# ===========================================================================
# Tier 4: Rate-lock accumulation (extension cap boundary)
# ===========================================================================
def setup_rate_lock_with_cumulative_extra_days(
    *,
    cumulative_days: int,
    sale_price_cents: Optional[int] = None,
    requested_loan_amount_cents: Optional[int] = None,
    locked_rate_bps: int = 650,
    clock_anchor: str = TEST_DEFAULTS["DEFAULT_CLOCK_ANCHOR"],
    headers: Optional[Dict[str, str]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Build an application + RateLock whose cumulative
    sum-of-extra_days equals `cumulative_days`. PRD §3.5 cap is 60.

    extras allowed per extension: {7, 15, 30}. The fixture chooses a
    greedy combination drawn from {30, 15, 7} that exactly hits
    cumulative_days (it can also hit 0).

    Returns (borrower, application, rate_lock).
    """
    advance_clock(clock_anchor)
    borrower, app = create_and_pre_qualify(
        sale_price_cents=sale_price_cents,
        requested_loan_amount_cents=requested_loan_amount_cents,
        headers=headers,
    )
    rl = place_rate_lock(
        app["id"], locked_rate_bps=locked_rate_bps, headers=headers,
    )
    remaining = cumulative_days
    for tier in (30, 15, 7):
        while remaining >= tier:
            rl = extend_rate_lock(
                app["id"], extra_days=tier, headers=headers,
            )
            remaining -= tier
    assert remaining == 0, (
        f"cumulative_days={cumulative_days} cannot be expressed as "
        "a non-negative integer combination of 30+15+7. Use a value "
        "drawn from {0, 7, 14, 15, 21, 22, 29, 30, 37, 45, 52, 60, ...}."
    )
    return borrower, app, rl


# ===========================================================================
# Tier 4: APR-tolerance boundary helpers
# ===========================================================================
def setup_at_conditional_approval_with_le_apr(
    *,
    le_apr_bps: int,
    clock_anchor: str = TEST_DEFAULTS["DEFAULT_CLOCK_ANCHOR"],
    sale_price_cents: Optional[int] = None,
    requested_loan_amount_cents: Optional[int] = None,
    state_code: Optional[str] = None,
    compliance_reviewer_id: str = COMPLIANCE_OFFICER_ID,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Convenience: application in CONDITIONAL_APPROVAL with the latest
    LOAN_ESTIMATE at a specified apr_bps, ACKNOWLEDGED by the borrower.
    Returns (borrower, application, le).
    """
    borrower, app, _, le = setup_application_in_conditional_approval(
        clock_anchor=clock_anchor,
        sale_price_cents=sale_price_cents,
        requested_loan_amount_cents=requested_loan_amount_cents,
        state_code=state_code,
        le_apr_bps=le_apr_bps,
        compliance_reviewer_id=compliance_reviewer_id,
    )
    # PRD §3.6 acknowledge is by the Borrower entity-backed role.
    le = acknowledge_disclosure(app["id"], le["id"], borrower["id"])
    return borrower, app, le


# ===========================================================================
# Helper for PMI / LTV tests
# ===========================================================================
def setup_completed_appraisal_with_value(
    *,
    sale_price_cents: int,
    requested_loan_amount_cents: int,
    appraised_value_cents: int,
    state_code: str = "CA",
    annual_income_cents: int = 12_000_000,
    clock_anchor: str = TEST_DEFAULTS["DEFAULT_CLOCK_ANCHOR"],
    appraisal_report_date: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Borrower + LoanApplication (PRE_QUALIFIED) + COMPLETED Appraisal.

    Returns (borrower, application_after_appraisal, appraisal).
    """
    advance_clock(clock_anchor)
    borrower, app = create_and_pre_qualify(
        annual_income_cents=annual_income_cents,
        state_code=state_code,
        sale_price_cents=sale_price_cents,
        requested_loan_amount_cents=requested_loan_amount_cents,
        headers=headers,
    )
    appr = order_and_complete_appraisal(
        app["id"],
        report_date=appraisal_report_date,
        appraised_value_cents=appraised_value_cents,
        headers=headers,
    )
    # Re-read the application so the test sees the appraisal-induced
    # cascade (PRD §2.6).
    app = get_loan_application(app["id"], headers=headers)
    return borrower, app, appr


__all__ = [
    # low-level
    "advance_clock",
    "parse_iso",
    "iso_z",
    "iso_plus",
    "get_loan_application",
    "get_rate_lock",
    # Tier 1
    "create_borrower",
    "create_loan_application",
    "create_borrower_and_application",
    "pre_qualify",
    "create_and_pre_qualify",
    # Tier 2
    "create_and_verify_income",
    "create_and_verify_asset",
    "order_and_complete_appraisal",
    "order_and_complete_title_search",
    "issue_loan_estimate",
    "issue_closing_disclosure",
    "acknowledge_disclosure",
    "submit_udaap_pass",
    "submit_udaap",
    # Tier 3
    "setup_application_ready_for_underwriting",
    "submit_underwriting",
    "setup_application_in_underwriting",
    "underwrite_approve",
    "underwrite_counter_offer",
    "underwrite_deny",
    "place_rate_lock",
    "extend_rate_lock",
    # Tier 4
    "setup_application_in_conditional_approval",
    "setup_application_ready_for_clear_to_close",
    "setup_rate_lock_with_cumulative_extra_days",
    "setup_at_conditional_approval_with_le_apr",
    "setup_completed_appraisal_with_value",
    # Tier 5
    "setup_closed_application",
]
