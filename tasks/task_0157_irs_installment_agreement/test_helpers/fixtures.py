"""Composite setup helpers — multi-step preambles tests can reuse.

Most interesting test claims require the system to be in a late state
that takes 5-15 API calls to reach. Each fixture composes the lower-
level steps so the test body can focus on the rule under assertion.

IDENTITY THREADING — PRD §2.1:

    "When X-User-Role is Taxpayer, X-User-ID is the id of the acting
    Taxpayer entity; ownership checks on any resource that references a
    Taxpayer ... compare the resource's taxpayer_id to X-User-ID, and a
    mismatch is rejected with ERR_FORBIDDEN."

After a Taxpayer is created, fixtures act as that Taxpayer by minting
headers via make_taxpayer_headers(taxpayer["id"]) — never by reusing
the shared TEST_USERS["taxpayer_headers"] constant for ownership-gated
operations. The shared constant is reserved for tests that probe auth/
RBAC failure modes without exercising ownership.

CLOCK ANCHORING — PRD §3.2:

    "Test scenarios drive the calendar through a separate clock-advance
    capability that moves the server clock to a supplied
    target_timestamp (ISO 8601 UTC) without cascading any deferred
    work; sweeps must be invoked explicitly after each advance."

The logical clock is shared across all tests within the process. Each
fixture anchors deadlines to instants the test author can advance to.
The _CURRENT_CLOCK tracker mirrors the server clock so absolute
timestamps in setup payloads can be derived without round-trips.

Setup calls use get_success_data (a lenient 2xx validator), so a failed
setup surfaces as 'Setup failed' rather than a confusing test assertion
failure downstream.
"""
from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    add_days,
    add_seconds,
    add_years,
    clock_advance_payload,
    create_cnc_payload,
    create_installment_agreement_payload,
    create_lien_payload,
    create_offer_in_compromise_payload,
    create_payment_payload,
    create_reconsideration_payload,
    create_tax_liability_payload,
    create_taxpayer_payload,
    decide_offer_in_compromise_payload,
    decide_reconsideration_payload,
    iso_instant_utc,
    iso_utc,
    parse_iso,
    record_installment_payment_payload,
    utcnow,
)
from .test_users import (
    IRS_OFFICER_SECONDARY_ID,
    IRS_OFFICER_SHARED_ID,
    OIC_OFFICER_SECONDARY_ID,
    OIC_OFFICER_SHARED_ID,
    TEST_USERS,
    make_irs_officer_headers,
    make_oic_officer_headers,
    make_taxpayer_headers,
)


# ===========================================================================
# Clock helpers — PRD §3.2 logical clock
# ===========================================================================
_CLOCK_LOCK = threading.Lock()
_CURRENT_CLOCK: List[Optional[datetime]] = [None]


def reset_clock_tracker_to(dt: datetime) -> None:
    with _CLOCK_LOCK:
        _CURRENT_CLOCK[0] = dt


def current_clock() -> datetime:
    with _CLOCK_LOCK:
        if _CURRENT_CLOCK[0] is None:
            _CURRENT_CLOCK[0] = utcnow()
        return _CURRENT_CLOCK[0]


def current_clock_iso() -> str:
    return iso_utc(current_clock())


def advance_clock_to(iso_ts: str, *, headers: Optional[Dict[str, str]] = None) -> str:
    """PRD §3.2: 'a separate clock-advance capability that moves the
    server clock to a supplied target_timestamp (ISO 8601 UTC)'."""
    h = headers or TEST_USERS["irs_officer_headers"]
    resp = api_client.advance_clock(
        clock_advance_payload(iso_ts), h,
    )
    get_success_data(resp)
    with _CLOCK_LOCK:
        _CURRENT_CLOCK[0] = parse_iso(iso_ts)
    return iso_ts


def advance_clock_by_days(days: int,
                          headers: Optional[Dict[str, str]] = None) -> str:
    target = iso_utc(current_clock() + timedelta(days=days))
    return advance_clock_to(target, headers=headers)


def advance_clock_by_seconds(seconds: int,
                             headers: Optional[Dict[str, str]] = None) -> str:
    target = iso_utc(current_clock() + timedelta(seconds=seconds))
    return advance_clock_to(target, headers=headers)


def run_sweep(headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """PRD §3.2: 'run the deferred actions (accrual, missed-payment
    detection, CSED expiration, CNC review) on demand.'"""
    h = headers or TEST_USERS["irs_officer_headers"]
    resp = api_client.run_sweep(h)
    return get_success_data(resp)


def set_clock_and_sweep(iso_ts: str) -> None:
    advance_clock_to(iso_ts)
    run_sweep()


# ===========================================================================
# Tier 1 — Single-entity creation helpers
# ===========================================================================
def create_taxpayer(
    *,
    monthly_disposable_income_cents: int = 200_000,
    filing_status: str = "SINGLE",
    tin: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """PRD §3.1: 'The collection lifecycle begins when an IRSOfficer
    registers a Taxpayer.'"""
    h = headers or TEST_USERS["irs_officer_headers"]
    overrides: Dict[str, Any] = {
        "filing_status": filing_status,
        "monthly_disposable_income_cents": monthly_disposable_income_cents,
    }
    if tin is not None:
        overrides["tin"] = tin
    payload = create_taxpayer_payload(**overrides)
    resp = api_client.create_taxpayer(payload, h)
    return get_success_data(resp)


def create_tax_liability(
    taxpayer_id: str,
    *,
    tax_year: int = 2019,
    assessment_date: Optional[str] = None,
    original_assessed_amount_cents: int = 1_000_000,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """PRD §3.1: 'Assessing tax — the second move in the lifecycle —
    creates a TaxLiability.'"""
    h = headers or TEST_USERS["irs_officer_headers"]
    payload = create_tax_liability_payload(
        taxpayer_id,
        tax_year=tax_year,
        assessment_date=assessment_date or current_clock_iso(),
        original_assessed_amount_cents=original_assessed_amount_cents,
    )
    resp = api_client.create_tax_liability(payload, h)
    return get_success_data(resp)


def get_taxpayer(taxpayer_id: str,
                 headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    h = headers or TEST_USERS["irs_officer_headers"]
    return get_success_data(api_client.get_taxpayer(taxpayer_id, h))


def get_tax_liability(liability_id: str,
                      headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    h = headers or TEST_USERS["irs_officer_headers"]
    return get_success_data(api_client.get_tax_liability(liability_id, h))


def get_installment_agreement(agreement_id: str,
                              headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    h = headers or TEST_USERS["irs_officer_headers"]
    return get_success_data(
        api_client.get_installment_agreement(agreement_id, h),
    )


def get_offer_in_compromise(oic_id: str,
                            headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    h = headers or TEST_USERS["irs_officer_headers"]
    return get_success_data(
        api_client.get_offer_in_compromise(oic_id, h),
    )


def get_lien(lien_id: str,
             headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    h = headers or TEST_USERS["irs_officer_headers"]
    return get_success_data(api_client.get_lien(lien_id, h))


def get_cnc_status(cnc_id: str,
                   headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    h = headers or TEST_USERS["irs_officer_headers"]
    return get_success_data(api_client.get_cnc_status(cnc_id, h))


def get_reconsideration(request_id: str,
                        headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    h = headers or TEST_USERS["irs_officer_headers"]
    return get_success_data(
        api_client.get_reconsideration_request(request_id, h),
    )


# ===========================================================================
# Tier 2 — Taxpayer + liability bundle
# ===========================================================================
def create_taxpayer_with_liability(
    *,
    monthly_disposable_income_cents: int = 200_000,
    original_assessed_amount_cents: int = 1_000_000,
    assessment_date: Optional[str] = None,
    tax_year: int = 2019,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Active taxpayer + one OPEN liability. Returns (taxpayer, liability)."""
    taxpayer = create_taxpayer(
        monthly_disposable_income_cents=monthly_disposable_income_cents,
    )
    liability = create_tax_liability(
        taxpayer["id"],
        tax_year=tax_year,
        assessment_date=assessment_date,
        original_assessed_amount_cents=original_assessed_amount_cents,
    )
    return taxpayer, liability


# ===========================================================================
# Tier 3 — Installment Agreement lifecycle shortcuts
# ===========================================================================
def create_pending_installment_agreement(
    taxpayer_id: str,
    liability_ids: List[str],
    *,
    proposed_monthly_payment_cents: int = 200_000,
    payment_method: str = "DDIA",
    ddia_bank_account_last4: Optional[str] = "1234",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """PRD §3.4: 'The agreement is persisted in status PENDING.'"""
    # Default to Taxpayer-owner headers for the ownership-gated draft
    # endpoint; tests may override.
    h = headers or make_taxpayer_headers(taxpayer_id)
    payload = create_installment_agreement_payload(
        taxpayer_id,
        liability_ids,
        proposed_monthly_payment_cents=proposed_monthly_payment_cents,
        payment_method=payment_method,
        ddia_bank_account_last4=(
            ddia_bank_account_last4 if payment_method == "DDIA" else None
        ),
    )
    resp = api_client.create_installment_agreement(payload, h)
    return get_success_data(resp)


def activate_installment_agreement(
    agreement_id: str,
    *,
    activator_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """PRD §3.4: 'Activation is performed by an IRSOfficer, advancing
    agreement.status from PENDING to ACTIVE.'"""
    h = activator_headers or TEST_USERS["irs_officer_headers"]
    resp = api_client.activate_installment_agreement(agreement_id, h)
    return get_success_data(resp)


def create_and_activate_agreement(
    taxpayer_id: str,
    liability_ids: List[str],
    *,
    proposed_monthly_payment_cents: int = 200_000,
    payment_method: str = "DDIA",
    ddia_bank_account_last4: Optional[str] = "1234",
    activator_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Create + activate. Returns the activated agreement object."""
    pending = create_pending_installment_agreement(
        taxpayer_id,
        liability_ids,
        proposed_monthly_payment_cents=proposed_monthly_payment_cents,
        payment_method=payment_method,
        ddia_bank_account_last4=ddia_bank_account_last4,
    )
    return activate_installment_agreement(
        pending["id"],
        activator_headers=activator_headers,
    )


def record_installment_payment(
    agreement_id: str,
    amount_cents: int,
    *,
    received_at: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    h = headers or TEST_USERS["irs_officer_headers"]
    payload = record_installment_payment_payload(
        amount_cents=amount_cents,
        received_at=received_at or current_clock_iso(),
    )
    resp = api_client.record_installment_payment(
        agreement_id, payload, h,
    )
    return get_success_data(resp)


def terminate_installment_agreement(
    agreement_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    h = headers or TEST_USERS["irs_officer_headers"]
    resp = api_client.terminate_installment_agreement(agreement_id, h)
    return get_success_data(resp)


def default_active_agreement_via_missed_payments(
    agreement_id: str,
    *,
    cycles: int = 3,
) -> Dict[str, Any]:
    """PRD §3.4: 'When missed_payment_count reaches three or more ... the
    agreement transitions from ACTIVE to DEFAULTED'.

    Advance the clock by `cycles` × 31 days (each more than 30 days, so
    the next_due_date check fires each time) and run the sweep after
    each advance to accumulate missed_payment_count.
    """
    for _ in range(cycles):
        advance_clock_by_days(31)
        run_sweep()
    return get_installment_agreement(agreement_id)


# ===========================================================================
# Tier 4 — Offer in Compromise lifecycle shortcuts
# ===========================================================================
def create_draft_oic(
    taxpayer_id: str,
    liability_ids: List[str],
    *,
    offer_amount_cents: int = 1_500_000,
    schedule_months: int = 5,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """PRD §3.8: 'A taxpayer (or an IRSOfficer acting on the taxpayer's
    behalf) drafts an OfferInCompromise.'"""
    h = headers or make_taxpayer_headers(taxpayer_id)
    payload = create_offer_in_compromise_payload(
        taxpayer_id,
        liability_ids,
        offer_amount_cents=offer_amount_cents,
        schedule_months=schedule_months,
    )
    resp = api_client.create_offer_in_compromise(payload, h)
    return get_success_data(resp)


def pay_oic_deposit(
    taxpayer_id: str,
    oic_id: str,
    amount_cents: int,
    *,
    received_at: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """PRD §3.8: 'a Payment of payment_kind OIC_DEPOSIT exists for the
    offer with amount_cents at least equal to twenty percent of
    offer_amount_cents.'"""
    h = headers or make_taxpayer_headers(taxpayer_id)
    payload = create_payment_payload(
        taxpayer_id=taxpayer_id,
        amount_cents=amount_cents,
        received_at=received_at or current_clock_iso(),
        payment_kind="OIC_DEPOSIT",
        oic_id=oic_id,
    )
    resp = api_client.create_payment(payload, h)
    return get_success_data(resp)


def submit_oic(
    taxpayer_id: str,
    oic_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """PRD §3.8: 'Submission is a Taxpayer action that moves the offer
    from DRAFT to SUBMITTED.'"""
    h = headers or make_taxpayer_headers(taxpayer_id)
    resp = api_client.submit_offer_in_compromise(oic_id, h)
    return get_success_data(resp)


def take_up_oic(
    oic_id: str,
    *,
    officer_id: str = OIC_OFFICER_SHARED_ID,
) -> Dict[str, Any]:
    """PRD §3.8: 'Take-up is an OICOfficer action that moves the offer
    from SUBMITTED to UNDER_REVIEW.'"""
    h = make_oic_officer_headers(officer_id)
    resp = api_client.take_up_offer_in_compromise(oic_id, h)
    return get_success_data(resp)


def decide_oic(
    oic_id: str,
    decision: str,
    *,
    officer_id: str = OIC_OFFICER_SECONDARY_ID,
) -> Dict[str, Any]:
    """PRD §3.8: 'Decide is also an OICOfficer action and carries a body
    decision of ACCEPT or REJECT. The deciding officer's id must differ
    from the officer who took up the case.'"""
    h = make_oic_officer_headers(officer_id)
    payload = decide_offer_in_compromise_payload(decision=decision)
    resp = api_client.decide_offer_in_compromise(oic_id, payload, h)
    return get_success_data(resp)


def withdraw_oic(
    taxpayer_id: str,
    oic_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """PRD §3.8: 'Withdrawal is a Taxpayer action that moves the offer
    from SUBMITTED to WITHDRAWN.'"""
    h = headers or make_taxpayer_headers(taxpayer_id)
    resp = api_client.withdraw_offer_in_compromise(oic_id, h)
    return get_success_data(resp)


def setup_oic_under_review(
    taxpayer_id: str,
    liability_ids: List[str],
    *,
    offer_amount_cents: int = 1_500_000,
    schedule_months: int = 5,
    deposit_cents: Optional[int] = None,
    take_up_officer_id: str = OIC_OFFICER_SHARED_ID,
) -> Dict[str, Any]:
    """Walk: draft → deposit → submit → take-up. Returns OIC dict in
    UNDER_REVIEW state."""
    oic = create_draft_oic(
        taxpayer_id, liability_ids,
        offer_amount_cents=offer_amount_cents,
        schedule_months=schedule_months,
    )
    pay_oic_deposit(
        taxpayer_id, oic["id"],
        deposit_cents if deposit_cents is not None
        else max(1, (offer_amount_cents + 4) // 5),  # ceil(0.20*offer)
    )
    submit_oic(taxpayer_id, oic["id"])
    return take_up_oic(oic["id"], officer_id=take_up_officer_id)


# ===========================================================================
# Tier 5 — Federal Tax Lien + CNC helpers
# ===========================================================================
def file_lien(
    taxpayer_id: str,
    liability_ids: List[str],
    *,
    filed_date: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """PRD §3.7: 'The IRS files a FederalTaxLien against one or more
    liabilities.'"""
    h = headers or TEST_USERS["irs_officer_headers"]
    payload = create_lien_payload(
        taxpayer_id, liability_ids,
        filed_date=filed_date or current_clock_iso(),
    )
    resp = api_client.create_lien(payload, h)
    return get_success_data(resp)


def withdraw_lien(
    lien_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    h = headers or TEST_USERS["irs_officer_headers"]
    resp = api_client.withdraw_lien(lien_id, h)
    return get_success_data(resp)


def place_cnc(
    taxpayer_id: str,
    liability_ids: List[str],
    *,
    hardship_reason: str = "NEGATIVE_DISPOSABLE_INCOME",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """PRD §3.11: 'An IRSOfficer may place liabilities into Currently
    Not Collectible.'"""
    h = headers or TEST_USERS["irs_officer_headers"]
    payload = create_cnc_payload(
        taxpayer_id, liability_ids,
        hardship_reason=hardship_reason,
    )
    resp = api_client.create_cnc_status(payload, h)
    return get_success_data(resp)


def reverse_cnc(cnc_id: str,
                *,
                headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    h = headers or TEST_USERS["irs_officer_headers"]
    resp = api_client.reverse_cnc_status(cnc_id, h)
    return get_success_data(resp)


# ===========================================================================
# Tier 6 — Reconsideration helpers
# ===========================================================================
def open_reconsideration(
    taxpayer_id: str,
    agreement_id: str,
    *,
    reason: str = "MISSED_PAYMENT_CURE",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """PRD §3.10: 'A taxpayer (or an IRSOfficer acting on the taxpayer's
    behalf) may request reconsideration of a DEFAULTED InstallmentAgreement.'"""
    h = headers or make_taxpayer_headers(taxpayer_id)
    payload = create_reconsideration_payload(
        agreement_id=agreement_id,
        reason=reason,
    )
    resp = api_client.create_reconsideration_request(payload, h)
    return get_success_data(resp)


def decide_reconsideration(
    request_id: str,
    status: str,
    *,
    officer_id: str = IRS_OFFICER_SECONDARY_ID,
) -> Dict[str, Any]:
    """PRD §3.10: 'An IRSOfficer decides the reconsideration with a body
    status of APPROVED or DENIED. The deciding officer's id must differ
    from the IRSOfficer who originally activated the underlying
    agreement.'"""
    h = make_irs_officer_headers(officer_id)
    payload = decide_reconsideration_payload(status=status)
    resp = api_client.decide_reconsideration_request(
        request_id, payload, h,
    )
    return get_success_data(resp)


# ===========================================================================
# Tier 7 — Difficulty-design composite fixtures
#
# Each of the eighteen difficulty-design instances in
# SCAFFOLD_DIFFICULTY_DESIGN.yaml declares a setup recipe; the helpers
# below encapsulate the recurring multi-call preambles those recipes
# share.
# ===========================================================================
def setup_provisional_csed_after_oic_submit(
    *,
    base_clock: str = "2020-01-01T00:00:00.000Z",
    mdi_cents: int = 200_000,
    liability_amount_cents: int = 1_000_000,
    offer_amount_cents: int = 1_500_000,
    schedule_months: int = 5,
    deposit_cents: int = 300_000,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """For dual_variant_calc/csed_provisional_vs_final.

    Pin the clock at base_clock, create taxpayer + liability with
    assessment_date == base_clock, draft + deposit + submit an OIC. The
    returned tuple is (taxpayer, liability, oic) with the OIC in status
    SUBMITTED and an OIC_PENDING tolling event open since base_clock.
    """
    advance_clock_to(base_clock)
    taxpayer = create_taxpayer(
        monthly_disposable_income_cents=mdi_cents,
    )
    liability = create_tax_liability(
        taxpayer["id"],
        assessment_date=base_clock,
        original_assessed_amount_cents=liability_amount_cents,
    )
    oic = create_draft_oic(
        taxpayer["id"], [liability["id"]],
        offer_amount_cents=offer_amount_cents,
        schedule_months=schedule_months,
    )
    pay_oic_deposit(taxpayer["id"], oic["id"], deposit_cents)
    submit_oic(taxpayer["id"], oic["id"])
    return taxpayer, liability, oic


def setup_three_liabilities_for_status_branching(
    *,
    base_clock: str = "2020-01-01T00:00:00.000Z",
    mdi_cents: int = 0,
    each_liability_amount_cents: int = 1_000_000,
    ia_monthly_payment_cents: int = 50_000,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any],
           Dict[str, Any], Dict[str, Any]]:
    """For combinatorial_formula/monthly_accrual_status_branching.

    Returns (taxpayer, liab_open, liab_ia, liab_cnc, ia, cnc).
    liab_open stays OPEN; liab_ia is in an ACTIVE IA; liab_cnc is in
    CNC. All three share the same starting balance.
    """
    advance_clock_to(base_clock)
    # PRD §3.1: monthly_disposable_income_cents must be >= 0. PRD §3.11:
    # CNC requires MDI <= 0 (inclusive — exactly zero is eligible).
    # Use MDI=0 to satisfy both the create-time validation and the CNC
    # eligibility precondition required by this fixture.
    taxpayer = create_taxpayer(monthly_disposable_income_cents=mdi_cents)
    liab_open = create_tax_liability(
        taxpayer["id"],
        assessment_date=base_clock,
        original_assessed_amount_cents=each_liability_amount_cents,
    )
    liab_ia = create_tax_liability(
        taxpayer["id"],
        assessment_date=base_clock,
        original_assessed_amount_cents=each_liability_amount_cents,
    )
    liab_cnc = create_tax_liability(
        taxpayer["id"],
        assessment_date=base_clock,
        original_assessed_amount_cents=each_liability_amount_cents,
    )
    # IA must use DDIA when aggregate debt > $25k; for $10k single
    # liability either method is fine. Use CHECK to keep the fixture
    # simple. PRD §3.4 ddia required ONLY > 2,500,000.
    ia = create_and_activate_agreement(
        taxpayer["id"],
        [liab_ia["id"]],
        proposed_monthly_payment_cents=ia_monthly_payment_cents,
        payment_method="CHECK",
    )
    cnc = place_cnc(taxpayer["id"], [liab_cnc["id"]])
    return taxpayer, liab_open, liab_ia, liab_cnc, ia, cnc


def setup_default_active_via_missed_cycles(
    *,
    base_clock: str = "2020-02-01T00:00:00.000Z",
    activator_id: str = IRS_OFFICER_SHARED_ID,
    mdi_cents: int = 200_000,
    liability_amount_cents: int = 1_000_000,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """For non_linear_state_machine/ia_default_reinstate_cycle.

    Activate an IA, then advance 3 missed monthly cycles + sweep so the
    IA falls to DEFAULTED. Returns (taxpayer, liability, agreement).
    """
    advance_clock_to(base_clock)
    taxpayer = create_taxpayer(monthly_disposable_income_cents=mdi_cents)
    liability = create_tax_liability(
        taxpayer["id"],
        assessment_date=base_clock,
        original_assessed_amount_cents=liability_amount_cents,
    )
    ia = create_and_activate_agreement(
        taxpayer["id"], [liability["id"]],
        proposed_monthly_payment_cents=200_000,
        payment_method="CHECK",
        activator_headers=make_irs_officer_headers(activator_id),
    )
    default_active_agreement_via_missed_payments(ia["id"], cycles=3)
    return taxpayer, liability, get_installment_agreement(ia["id"])


def setup_two_independent_taxpayers_for_ddia_boundary() -> Tuple[
    Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any],
]:
    """For boundary_precision_check/ddia_threshold_25k_strict_greater_than.

    Two taxpayers, each with a single liability — one at the boundary
    (2,500,000) and one one cent over (2,500,001).
    Returns (taxpayer_a, liab_at_boundary, taxpayer_b, liab_above).
    """
    advance_clock_to("2020-01-01T00:00:00.000Z")
    a = create_taxpayer(monthly_disposable_income_cents=300_000)
    liab_a = create_tax_liability(
        a["id"],
        original_assessed_amount_cents=2_500_000,
    )
    b = create_taxpayer(monthly_disposable_income_cents=300_000)
    liab_b = create_tax_liability(
        b["id"],
        original_assessed_amount_cents=2_500_001,
    )
    return a, liab_a, b, liab_b


def setup_two_taxpayers_for_cnc_mdi_boundary() -> Tuple[
    Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any],
]:
    """For boundary_precision_check/cnc_eligibility_mdi_zero_inclusive.

    Two taxpayers with MDI = 0 (eligible) and MDI = 1 (ineligible).
    Returns (a_at_zero, liab_a, b_above_zero, liab_b).
    """
    advance_clock_to("2020-01-01T00:00:00.000Z")
    a = create_taxpayer(monthly_disposable_income_cents=0)
    liab_a = create_tax_liability(
        a["id"], original_assessed_amount_cents=1_000_000,
    )
    b = create_taxpayer(monthly_disposable_income_cents=1)
    liab_b = create_tax_liability(
        b["id"], original_assessed_amount_cents=1_000_000,
    )
    return a, liab_a, b, liab_b


def setup_payment_to_lien_release_chain(
    *,
    base_clock: str = "2020-01-01T00:00:00.000Z",
    liability_amount_cents: int = 300_000,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """For transitive_cascade/payment_to_paid_to_lien_release_depth3.

    Activate IA + file lien, ready to absorb a single payment that
    settles the entire liability. Returns (taxpayer, liability,
    agreement, lien).
    """
    advance_clock_to(base_clock)
    taxpayer = create_taxpayer(monthly_disposable_income_cents=200_000)
    liability = create_tax_liability(
        taxpayer["id"],
        assessment_date=base_clock,
        original_assessed_amount_cents=liability_amount_cents,
    )
    agreement = create_and_activate_agreement(
        taxpayer["id"], [liability["id"]],
        proposed_monthly_payment_cents=200_000,
        payment_method="CHECK",
    )
    lien = file_lien(taxpayer["id"], [liability["id"]])
    return taxpayer, liability, agreement, lien


__all__ = [
    # Clock
    "reset_clock_tracker_to", "current_clock", "current_clock_iso",
    "advance_clock_to", "advance_clock_by_days",
    "advance_clock_by_seconds", "run_sweep", "set_clock_and_sweep",
    # Single-entity helpers
    "create_taxpayer", "create_tax_liability",
    "get_taxpayer", "get_tax_liability",
    "get_installment_agreement", "get_offer_in_compromise",
    "get_lien", "get_cnc_status", "get_reconsideration",
    # Bundles
    "create_taxpayer_with_liability",
    # IA lifecycle
    "create_pending_installment_agreement",
    "activate_installment_agreement",
    "create_and_activate_agreement",
    "record_installment_payment",
    "terminate_installment_agreement",
    "default_active_agreement_via_missed_payments",
    # OIC lifecycle
    "create_draft_oic", "pay_oic_deposit", "submit_oic",
    "take_up_oic", "decide_oic", "withdraw_oic",
    "setup_oic_under_review",
    # Lien
    "file_lien", "withdraw_lien",
    # CNC
    "place_cnc", "reverse_cnc",
    # Reconsideration
    "open_reconsideration", "decide_reconsideration",
    # Difficulty-design composites
    "setup_provisional_csed_after_oic_submit",
    "setup_three_liabilities_for_status_branching",
    "setup_default_active_via_missed_cycles",
    "setup_two_independent_taxpayers_for_ddia_boundary",
    "setup_two_taxpayers_for_cnc_mdi_boundary",
    "setup_payment_to_lien_release_chain",
]
