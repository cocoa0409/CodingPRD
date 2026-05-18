"""Composite setup helpers — multi-step preambles tests can reuse.

Many tests require the system in a late state (e.g., a taxpayer with
a return computed to READY_TO_FILE, filed, and accepted by IRS; or an
estimated payment that auto-confirmed at a specific clock instant).
Each fixture composes the lower-level steps so the test body can
focus on the rule under assertion.

IDENTITY THREADING — PRD §2.1:

- IRSAdjudicator is OPAQUE; shared TEST_USERS constants are canonical.
- Taxpayer is ENTITY-BACKED. Every Taxpayer-driven call whose success
  depends on owning the targeted resource MUST mint headers via
  make_taxpayer_headers(taxpayer["id"]). The fixtures here return the
  actual Taxpayer row so consumer tests can route Taxpayer-acting
  calls through make_taxpayer_headers.

Setup calls use get_success_data (a lenient 2xx validator), so a
failed setup surfaces as 'Setup failed' rather than a confusing test
assertion failure downstream.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    clock_advance_payload,
    compliance_lock_payload,
    create_1099_b_payload,
    create_1099_div_payload,
    create_1099_int_payload,
    create_1099_nec_payload,
    create_amendment_payload,
    create_credit_payload,
    create_estimated_payment_payload,
    create_schedule_a_payload,
    create_schedule_b_payload,
    create_schedule_c_payload,
    create_schedule_d_payload,
    create_schedule_e_payload,
    create_tax_return_payload,
    create_taxpayer_payload,
    create_w2_payload,
    decide_amendment_payload,
    decide_filing_payload,
    iso_date,
    iso_instant_utc,
    patch_tax_return_payload,
)
from .test_users import (
    TEST_USERS,
    make_taxpayer_headers,
)


# ===========================================================================
# Clock helpers — PRD §2.9
# ===========================================================================
def advance_clock_to(
    to_iso: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /_clock/advance. PRD §2.9: 'both roles may call' the clock
    utility endpoints.
    """
    headers = headers or TEST_USERS["irs_adjudicator_headers"]
    resp = api_client.advance_clock(
        clock_advance_payload(to_iso_timestamp=to_iso), headers,
    )
    return get_success_data(resp)


def get_clock(
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["irs_adjudicator_headers"]
    resp = api_client.get_clock(headers)
    return get_success_data(resp)


# ===========================================================================
# Taxpayer fixtures — PRD §3.1
# ===========================================================================
def create_taxpayer(
    *,
    full_name: Optional[str] = None,
    is_blind: Optional[bool] = None,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /taxpayers. PRD §3.1: registered by Taxpayer or IRSAdjudicator.

    Uses IRSAdjudicator headers by default so the call does not have
    to know the to-be-minted taxpayer id in advance.
    """
    headers = headers or TEST_USERS["irs_adjudicator_headers"]
    payload = create_taxpayer_payload(
        full_name=full_name, is_blind=is_blind, **overrides,
    )
    resp = api_client.create_taxpayer(payload, headers)
    return get_success_data(resp)


def get_taxpayer(
    taxpayer_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or make_taxpayer_headers(taxpayer_id)
    resp = api_client.get_taxpayer(taxpayer_id, headers)
    return get_success_data(resp)


def compliance_lock(
    taxpayer_id: str,
    *,
    reason: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /taxpayers/{id}/compliance-lock. PRD §3.11: IRSAdjudicator
    only."""
    headers = headers or TEST_USERS["irs_adjudicator_headers"]
    resp = api_client.compliance_lock(
        taxpayer_id, compliance_lock_payload(reason=reason), headers,
    )
    return get_success_data(resp)


def compliance_unlock(
    taxpayer_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /taxpayers/{id}/compliance-unlock. PRD §3.11."""
    headers = headers or TEST_USERS["irs_adjudicator_headers"]
    resp = api_client.compliance_unlock(taxpayer_id, headers)
    return get_success_data(resp)


# ===========================================================================
# TaxReturn fixtures — PRD §3.1 / §3.5
# ===========================================================================
def create_tax_return(
    taxpayer: Dict[str, Any],
    *,
    tax_year: Optional[int] = None,
    filing_status: Optional[str] = None,
    dependents_count: Optional[int] = None,
    qualifying_children_under_17: Optional[int] = None,
    deduction_method: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /tax-returns as the owning taxpayer.

    Identity threading: PRD §2.1 — entity-backed Taxpayer header MUST
    resolve to the taxpayer's own id.
    """
    headers = headers or make_taxpayer_headers(taxpayer["id"])
    payload = create_tax_return_payload(
        taxpayer_id=taxpayer["id"],
        tax_year=tax_year,
        filing_status=filing_status,
        dependents_count=dependents_count,
        qualifying_children_under_17=qualifying_children_under_17,
        deduction_method=deduction_method,
        **overrides,
    )
    resp = api_client.create_tax_return(payload, headers)
    return get_success_data(resp)


def get_tax_return(
    taxpayer: Dict[str, Any],
    tax_return_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or make_taxpayer_headers(taxpayer["id"])
    resp = api_client.get_tax_return(tax_return_id, headers)
    return get_success_data(resp)


def patch_tax_return(
    taxpayer: Dict[str, Any],
    tax_return_id: str,
    *,
    filing_status: Optional[str] = None,
    dependents_count: Optional[int] = None,
    qualifying_children_under_17: Optional[int] = None,
    deduction_method: Optional[str] = None,
    version: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    headers = headers or make_taxpayer_headers(taxpayer["id"])
    payload = patch_tax_return_payload(
        filing_status=filing_status,
        dependents_count=dependents_count,
        qualifying_children_under_17=qualifying_children_under_17,
        deduction_method=deduction_method,
        version=version,
        **overrides,
    )
    resp = api_client.patch_tax_return(tax_return_id, payload, headers)
    return get_success_data(resp)


def compute_tax_return(
    taxpayer: Dict[str, Any],
    tax_return_id: str,
    *,
    version: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or make_taxpayer_headers(taxpayer["id"])
    payload: Dict[str, Any] = {}
    if version is not None:
        payload["version"] = version
    resp = api_client.compute_tax_return(tax_return_id, payload, headers)
    return get_success_data(resp)


def efile_tax_return(
    taxpayer: Dict[str, Any],
    tax_return_id: str,
    *,
    version: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or make_taxpayer_headers(taxpayer["id"])
    payload: Dict[str, Any] = {}
    if version is not None:
        payload["version"] = version
    resp = api_client.efile_tax_return(tax_return_id, payload, headers)
    return get_success_data(resp)


def unlock_for_correction(
    taxpayer: Dict[str, Any],
    tax_return_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or make_taxpayer_headers(taxpayer["id"])
    resp = api_client.unlock_for_correction(tax_return_id, headers)
    return get_success_data(resp)


def get_safe_harbor(
    taxpayer: Dict[str, Any],
    tax_return_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or make_taxpayer_headers(taxpayer["id"])
    resp = api_client.get_safe_harbor(tax_return_id, headers)
    return get_success_data(resp)


# ===========================================================================
# IncomeDocument fixtures — PRD §3.2
# ===========================================================================
def add_w2(
    taxpayer: Dict[str, Any],
    tax_return_id: str,
    *,
    wages_cents: int = 0,
    federal_withholding_cents: int = 0,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    headers = headers or make_taxpayer_headers(taxpayer["id"])
    payload = create_w2_payload(
        wages_cents=wages_cents,
        federal_withholding_cents=federal_withholding_cents,
        **overrides,
    )
    resp = api_client.create_income_document(
        tax_return_id, payload, headers,
    )
    return get_success_data(resp)


def add_1099_nec(
    taxpayer: Dict[str, Any],
    tax_return_id: str,
    *,
    nonemployee_comp_cents: int = 0,
    federal_withholding_cents: int = 0,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    headers = headers or make_taxpayer_headers(taxpayer["id"])
    payload = create_1099_nec_payload(
        nonemployee_comp_cents=nonemployee_comp_cents,
        federal_withholding_cents=federal_withholding_cents,
        **overrides,
    )
    resp = api_client.create_income_document(
        tax_return_id, payload, headers,
    )
    return get_success_data(resp)


def add_1099_int(
    taxpayer: Dict[str, Any],
    tax_return_id: str,
    *,
    interest_income_cents: int = 0,
    federal_withholding_cents: int = 0,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    headers = headers or make_taxpayer_headers(taxpayer["id"])
    payload = create_1099_int_payload(
        interest_income_cents=interest_income_cents,
        federal_withholding_cents=federal_withholding_cents,
        **overrides,
    )
    resp = api_client.create_income_document(
        tax_return_id, payload, headers,
    )
    return get_success_data(resp)


def add_1099_div(
    taxpayer: Dict[str, Any],
    tax_return_id: str,
    *,
    ordinary_dividends_cents: int = 0,
    qualified_dividends_cents: int = 0,
    federal_withholding_cents: int = 0,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    headers = headers or make_taxpayer_headers(taxpayer["id"])
    payload = create_1099_div_payload(
        ordinary_dividends_cents=ordinary_dividends_cents,
        qualified_dividends_cents=qualified_dividends_cents,
        federal_withholding_cents=federal_withholding_cents,
        **overrides,
    )
    resp = api_client.create_income_document(
        tax_return_id, payload, headers,
    )
    return get_success_data(resp)


def add_1099_b(
    taxpayer: Dict[str, Any],
    tax_return_id: str,
    *,
    proceeds_cents: int = 0,
    cost_basis_cents: int = 0,
    holding_period: str = "SHORT_TERM",
    federal_withholding_cents: int = 0,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    headers = headers or make_taxpayer_headers(taxpayer["id"])
    payload = create_1099_b_payload(
        proceeds_cents=proceeds_cents,
        cost_basis_cents=cost_basis_cents,
        holding_period=holding_period,
        federal_withholding_cents=federal_withholding_cents,
        **overrides,
    )
    resp = api_client.create_income_document(
        tax_return_id, payload, headers,
    )
    return get_success_data(resp)


# ===========================================================================
# Schedule fixtures — PRD §3.3
# ===========================================================================
def add_schedule_a(
    taxpayer: Dict[str, Any],
    tax_return_id: str,
    *,
    itemized_medical_cents: int = 0,
    itemized_salt_cents: int = 0,
    itemized_mortgage_interest_cents: int = 0,
    itemized_charity_cents: int = 0,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    headers = headers or make_taxpayer_headers(taxpayer["id"])
    payload = create_schedule_a_payload(
        itemized_medical_cents=itemized_medical_cents,
        itemized_salt_cents=itemized_salt_cents,
        itemized_mortgage_interest_cents=itemized_mortgage_interest_cents,
        itemized_charity_cents=itemized_charity_cents,
        **overrides,
    )
    resp = api_client.create_schedule(
        tax_return_id, payload, headers,
    )
    return get_success_data(resp)


def add_schedule_b(
    taxpayer: Dict[str, Any],
    tax_return_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    headers = headers or make_taxpayer_headers(taxpayer["id"])
    payload = create_schedule_b_payload(**overrides)
    resp = api_client.create_schedule(
        tax_return_id, payload, headers,
    )
    return get_success_data(resp)


def add_schedule_c(
    taxpayer: Dict[str, Any],
    tax_return_id: str,
    *,
    schedule_c_gross_receipts_cents: int = 0,
    schedule_c_expenses_cents: int = 0,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    headers = headers or make_taxpayer_headers(taxpayer["id"])
    payload = create_schedule_c_payload(
        schedule_c_gross_receipts_cents=schedule_c_gross_receipts_cents,
        schedule_c_expenses_cents=schedule_c_expenses_cents,
        **overrides,
    )
    resp = api_client.create_schedule(
        tax_return_id, payload, headers,
    )
    return get_success_data(resp)


def add_schedule_d(
    taxpayer: Dict[str, Any],
    tax_return_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    headers = headers or make_taxpayer_headers(taxpayer["id"])
    payload = create_schedule_d_payload(**overrides)
    resp = api_client.create_schedule(
        tax_return_id, payload, headers,
    )
    return get_success_data(resp)


def add_schedule_e(
    taxpayer: Dict[str, Any],
    tax_return_id: str,
    *,
    schedule_e_rental_income_cents: int = 0,
    schedule_e_rental_expenses_cents: int = 0,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    headers = headers or make_taxpayer_headers(taxpayer["id"])
    payload = create_schedule_e_payload(
        schedule_e_rental_income_cents=schedule_e_rental_income_cents,
        schedule_e_rental_expenses_cents=schedule_e_rental_expenses_cents,
        **overrides,
    )
    resp = api_client.create_schedule(
        tax_return_id, payload, headers,
    )
    return get_success_data(resp)


# ===========================================================================
# TaxCredit fixtures — PRD §3.4
# ===========================================================================
def add_credit(
    taxpayer: Dict[str, Any],
    tax_return_id: str,
    *,
    credit_type: str,
    requested_amount_cents: int,
    aotc_student_count: Optional[int] = None,
    aotc_qualified_expenses_cents: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    headers = headers or make_taxpayer_headers(taxpayer["id"])
    payload = create_credit_payload(
        credit_type=credit_type,
        requested_amount_cents=requested_amount_cents,
        aotc_student_count=aotc_student_count,
        aotc_qualified_expenses_cents=aotc_qualified_expenses_cents,
        **overrides,
    )
    resp = api_client.create_credit(tax_return_id, payload, headers)
    return get_success_data(resp)


# ===========================================================================
# Filing / Adjudication / Amendment fixtures — PRD §3.8 / §3.9
# ===========================================================================
def accept_filing(
    efiling_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """IRS accepts a PENDING filing. PRD §3.8."""
    headers = headers or TEST_USERS["irs_adjudicator_headers"]
    resp = api_client.decide_efiling(
        efiling_id,
        decide_filing_payload(outcome="ACCEPTED"),
        headers,
    )
    return get_success_data(resp)


def reject_filing(
    efiling_id: str,
    *,
    rejection_code: str = "R0001",
    rejection_message: Optional[str] = "rejection reason",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["irs_adjudicator_headers"]
    resp = api_client.decide_efiling(
        efiling_id,
        decide_filing_payload(
            outcome="REJECTED",
            rejection_code=rejection_code,
            rejection_message=rejection_message,
        ),
        headers,
    )
    return get_success_data(resp)


def create_amendment(
    taxpayer: Dict[str, Any],
    *,
    original_return_id: str,
    reason_summary: str = "Correcting late W-2",
    restated_filing_status: Optional[str] = None,
    restated_dependents_count: Optional[int] = None,
    restated_qualifying_children_under_17: Optional[int] = None,
    restated_deduction_method: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    headers = headers or make_taxpayer_headers(taxpayer["id"])
    payload = create_amendment_payload(
        original_return_id=original_return_id,
        reason_summary=reason_summary,
        restated_filing_status=restated_filing_status,
        restated_dependents_count=restated_dependents_count,
        restated_qualifying_children_under_17=(
            restated_qualifying_children_under_17
        ),
        restated_deduction_method=restated_deduction_method,
        **overrides,
    )
    resp = api_client.create_amendment(payload, headers)
    return get_success_data(resp)


def submit_amendment(
    taxpayer: Dict[str, Any],
    amendment_id: str,
    *,
    version: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or make_taxpayer_headers(taxpayer["id"])
    payload: Dict[str, Any] = {}
    if version is not None:
        payload["version"] = version
    resp = api_client.submit_amendment(amendment_id, payload, headers)
    return get_success_data(resp)


def accept_amendment(
    amendment_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["irs_adjudicator_headers"]
    resp = api_client.decide_amendment(
        amendment_id,
        decide_amendment_payload(outcome="ACCEPTED"),
        headers,
    )
    return get_success_data(resp)


def reject_amendment(
    amendment_id: str,
    *,
    rejection_message: str = "amendment rejected",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["irs_adjudicator_headers"]
    resp = api_client.decide_amendment(
        amendment_id,
        decide_amendment_payload(
            outcome="REJECTED", rejection_message=rejection_message,
        ),
        headers,
    )
    return get_success_data(resp)


# ===========================================================================
# Estimated payment fixtures — PRD §3.10
# ===========================================================================
def schedule_payment(
    taxpayer: Dict[str, Any],
    *,
    tax_year: int = TEST_DEFAULTS["TAX_YEAR"],
    quarter: str = "Q1",
    amount_cents: int = 100_000,
    scheduled_pay_date: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or make_taxpayer_headers(taxpayer["id"])
    payload = create_estimated_payment_payload(
        taxpayer_id=taxpayer["id"],
        tax_year=tax_year,
        quarter=quarter,
        amount_cents=amount_cents,
        scheduled_pay_date=scheduled_pay_date,
    )
    resp = api_client.create_estimated_payment(payload, headers)
    return get_success_data(resp)


def cancel_payment(
    taxpayer: Dict[str, Any],
    payment_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or make_taxpayer_headers(taxpayer["id"])
    resp = api_client.cancel_estimated_payment(payment_id, headers)
    return get_success_data(resp)


# ===========================================================================
# Re-read helpers — for follow-up assertions
# ===========================================================================
def re_get_tax_return(
    taxpayer: Dict[str, Any],
    tax_return_id: str,
) -> Dict[str, Any]:
    return get_tax_return(taxpayer, tax_return_id)


def re_get_taxpayer(taxpayer_id: str) -> Dict[str, Any]:
    headers = make_taxpayer_headers(taxpayer_id)
    resp = api_client.get_taxpayer(taxpayer_id, headers)
    return get_success_data(resp)


def re_get_efiling(
    taxpayer: Dict[str, Any], efiling_id: str,
) -> Dict[str, Any]:
    headers = make_taxpayer_headers(taxpayer["id"])
    resp = api_client.get_efiling(efiling_id, headers)
    return get_success_data(resp)


def re_get_amendment(
    taxpayer: Dict[str, Any], amendment_id: str,
) -> Dict[str, Any]:
    headers = make_taxpayer_headers(taxpayer["id"])
    resp = api_client.get_amendment(amendment_id, headers)
    return get_success_data(resp)


# ===========================================================================
# Composite Tier-2 / Tier-3 fixtures
# ===========================================================================
def setup_active_taxpayer_with_draft_return(
    *,
    tax_year: int = TEST_DEFAULTS["TAX_YEAR"],
    filing_status: str = "SINGLE",
    deduction_method: str = "STANDARD",
    dependents_count: int = 0,
    qualifying_children_under_17: int = 0,
    is_blind: Optional[bool] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Active Taxpayer + DRAFT TaxReturn. The bread-and-butter setup
    for most tests.

    PRD §3.1: 'Every newly registered taxpayer starts with an
    account_status of ACTIVE.' and 'A return is born in the DRAFT
    state.'
    """
    taxpayer = create_taxpayer(is_blind=is_blind)
    tax_return = create_tax_return(
        taxpayer,
        tax_year=tax_year,
        filing_status=filing_status,
        deduction_method=deduction_method,
        dependents_count=dependents_count,
        qualifying_children_under_17=qualifying_children_under_17,
    )
    return taxpayer, tax_return


def setup_simple_w2_return(
    *,
    wages_cents: int = 8_000_000,
    federal_withholding_cents: int = 600_000,
    filing_status: str = "SINGLE",
    deduction_method: str = "STANDARD",
    dependents_count: int = 0,
    qualifying_children_under_17: int = 0,
    tax_year: int = TEST_DEFAULTS["TAX_YEAR"],
    is_blind: Optional[bool] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Active Taxpayer + DRAFT TaxReturn + one W-2 attached.

    Returns (taxpayer, tax_return, w2_document).
    """
    taxpayer, tax_return = setup_active_taxpayer_with_draft_return(
        tax_year=tax_year,
        filing_status=filing_status,
        deduction_method=deduction_method,
        dependents_count=dependents_count,
        qualifying_children_under_17=qualifying_children_under_17,
        is_blind=is_blind,
    )
    w2 = add_w2(
        taxpayer, tax_return["id"],
        wages_cents=wages_cents,
        federal_withholding_cents=federal_withholding_cents,
    )
    return taxpayer, tax_return, w2


def setup_ready_to_file_return(
    *,
    wages_cents: int = 8_000_000,
    federal_withholding_cents: int = 600_000,
    filing_status: str = "SINGLE",
    deduction_method: str = "STANDARD",
    dependents_count: int = 0,
    qualifying_children_under_17: int = 0,
    tax_year: int = TEST_DEFAULTS["TAX_YEAR"],
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Active Taxpayer + W-2 + computed TaxReturn in READY_TO_FILE.

    Returns (taxpayer, computed_tax_return, w2_document).
    """
    taxpayer, tax_return, w2 = setup_simple_w2_return(
        wages_cents=wages_cents,
        federal_withholding_cents=federal_withholding_cents,
        filing_status=filing_status,
        deduction_method=deduction_method,
        dependents_count=dependents_count,
        qualifying_children_under_17=qualifying_children_under_17,
        tax_year=tax_year,
    )
    computed = compute_tax_return(taxpayer, tax_return["id"])
    return taxpayer, computed, w2


def setup_filed_return(
    *,
    wages_cents: int = 8_000_000,
    federal_withholding_cents: int = 600_000,
    filing_status: str = "SINGLE",
    deduction_method: str = "STANDARD",
    dependents_count: int = 0,
    qualifying_children_under_17: int = 0,
    tax_year: int = TEST_DEFAULTS["TAX_YEAR"],
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Active Taxpayer + W-2 + return computed and e-filed (status
    FILED). PENDING EFiling exists.

    Returns (taxpayer, tax_return_post_efile, efiling).
    """
    taxpayer, tax_return, _ = setup_ready_to_file_return(
        wages_cents=wages_cents,
        federal_withholding_cents=federal_withholding_cents,
        filing_status=filing_status,
        deduction_method=deduction_method,
        dependents_count=dependents_count,
        qualifying_children_under_17=qualifying_children_under_17,
        tax_year=tax_year,
    )
    efiling = efile_tax_return(taxpayer, tax_return["id"])
    tr_after = re_get_tax_return(taxpayer, tax_return["id"])
    return taxpayer, tr_after, efiling


def setup_accepted_return(
    *,
    wages_cents: int = 8_000_000,
    federal_withholding_cents: int = 600_000,
    filing_status: str = "SINGLE",
    deduction_method: str = "STANDARD",
    dependents_count: int = 0,
    qualifying_children_under_17: int = 0,
    tax_year: int = TEST_DEFAULTS["TAX_YEAR"],
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Active Taxpayer + W-2 + filed + IRS-accepted.

    Returns (taxpayer, tax_return_after_accept, efiling_after_accept).
    """
    taxpayer, tr_filed, efiling = setup_filed_return(
        wages_cents=wages_cents,
        federal_withholding_cents=federal_withholding_cents,
        filing_status=filing_status,
        deduction_method=deduction_method,
        dependents_count=dependents_count,
        qualifying_children_under_17=qualifying_children_under_17,
        tax_year=tax_year,
    )
    accept_filing(efiling["id"])
    tr_accepted = re_get_tax_return(taxpayer, tr_filed["id"])
    ef_accepted = re_get_efiling(taxpayer, efiling["id"])
    return taxpayer, tr_accepted, ef_accepted


def setup_rejected_return(
    *,
    wages_cents: int = 8_000_000,
    federal_withholding_cents: int = 600_000,
    filing_status: str = "SINGLE",
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Active Taxpayer + W-2 + filed + IRS-rejected."""
    taxpayer, tr_filed, efiling = setup_filed_return(
        wages_cents=wages_cents,
        federal_withholding_cents=federal_withholding_cents,
        filing_status=filing_status,
    )
    reject_filing(efiling["id"])
    tr_rejected = re_get_tax_return(taxpayer, tr_filed["id"])
    ef_rejected = re_get_efiling(taxpayer, efiling["id"])
    return taxpayer, tr_rejected, ef_rejected


def setup_amendment_draft(
    *,
    wages_cents: int = 8_000_000,
    federal_withholding_cents: int = 600_000,
    filing_status: str = "SINGLE",
    reason_summary: str = "Late W-2",
    restated_filing_status: Optional[str] = None,
    restated_dependents_count: Optional[int] = None,
    restated_qualifying_children_under_17: Optional[int] = None,
    restated_deduction_method: Optional[str] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Accepted original TaxReturn + DRAFT AmendedReturn pointing at it."""
    taxpayer, tr_accepted, _ = setup_accepted_return(
        wages_cents=wages_cents,
        federal_withholding_cents=federal_withholding_cents,
        filing_status=filing_status,
    )
    amendment = create_amendment(
        taxpayer,
        original_return_id=tr_accepted["id"],
        reason_summary=reason_summary,
        restated_filing_status=restated_filing_status,
        restated_dependents_count=restated_dependents_count,
        restated_qualifying_children_under_17=(
            restated_qualifying_children_under_17
        ),
        restated_deduction_method=restated_deduction_method,
    )
    return taxpayer, tr_accepted, amendment


def setup_amendment_submitted(
    *,
    wages_cents: int = 8_000_000,
    federal_withholding_cents: int = 600_000,
    filing_status: str = "SINGLE",
    restated_dependents_count: int = 1,
    restated_qualifying_children_under_17: int = 1,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Accepted original + DRAFT amendment + submitted amendment."""
    taxpayer, tr_accepted, amendment = setup_amendment_draft(
        wages_cents=wages_cents,
        federal_withholding_cents=federal_withholding_cents,
        filing_status=filing_status,
        restated_dependents_count=restated_dependents_count,
        restated_qualifying_children_under_17=(
            restated_qualifying_children_under_17
        ),
    )
    submitted = submit_amendment(taxpayer, amendment["id"])
    tr_amended = re_get_tax_return(taxpayer, tr_accepted["id"])
    return taxpayer, tr_amended, submitted


def setup_locked_taxpayer_with_draft(
    *,
    filing_status: str = "SINGLE",
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Taxpayer locked via compliance hold + DRAFT TaxReturn."""
    taxpayer, tax_return = setup_active_taxpayer_with_draft_return(
        filing_status=filing_status,
    )
    compliance_lock(taxpayer["id"])
    return taxpayer, tax_return


# ---------------------------------------------------------------------------
# Tier-4 setups for the difficulty-design index
# ---------------------------------------------------------------------------
def setup_for_dual_variant_deduction(
    *,
    wages_cents: int = 8_000_000,
    federal_withholding_cents: int = 600_000,
    itemized_salt_cents: int = 500_000,
    itemized_charity_cents: int = 200_000,
    itemized_medical_cents: int = 0,
    itemized_mortgage_interest_cents: int = 0,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """SINGLE taxpayer with a single W-2 and a Schedule A. The return
    is in DRAFT with deduction_method=STANDARD initially.

    Used by difficulty rule 1 instance 1 (deduction_method
    STANDARD vs ITEMIZED).
    """
    taxpayer, tax_return, w2 = setup_simple_w2_return(
        wages_cents=wages_cents,
        federal_withholding_cents=federal_withholding_cents,
        filing_status="SINGLE",
        deduction_method="STANDARD",
    )
    add_schedule_a(
        taxpayer, tax_return["id"],
        itemized_medical_cents=itemized_medical_cents,
        itemized_salt_cents=itemized_salt_cents,
        itemized_mortgage_interest_cents=itemized_mortgage_interest_cents,
        itemized_charity_cents=itemized_charity_cents,
    )
    return taxpayer, tax_return, w2


def setup_for_compliance_lock_cascade(
    *,
    wages_cents: int = 2_000_000,
    federal_withholding_cents: int = 200_000,
) -> Tuple[
    Dict[str, Any], Dict[str, Any],
    Dict[str, Any], Dict[str, Any], Dict[str, Any],
]:
    """SINGLE Taxpayer ACTIVE; two SCHEDULED EstimatedTaxPayments;
    one DRAFT return computed to READY_TO_FILE so a recompute can
    later be attempted.

    Returns (taxpayer, tax_return_ready, w2, payment_q1, payment_q2).
    """
    taxpayer, tax_return, w2 = setup_simple_w2_return(
        wages_cents=wages_cents,
        federal_withholding_cents=federal_withholding_cents,
        filing_status="SINGLE",
    )
    p1 = schedule_payment(
        taxpayer,
        tax_year=tax_return["tax_year"],
        quarter="Q1",
        amount_cents=50_000,
        scheduled_pay_date=iso_date(date(2026, 9, 1)),
    )
    p2 = schedule_payment(
        taxpayer,
        tax_year=tax_return["tax_year"],
        quarter="Q2",
        amount_cents=50_000,
        scheduled_pay_date=iso_date(date(2026, 9, 15)),
    )
    computed = compute_tax_return(taxpayer, tax_return["id"])
    return taxpayer, computed, w2, p1, p2


def setup_for_payment_boundary(
    *,
    scheduled_pay_date: str,
    amount_cents: int = 100_000,
    quarter: str = "Q1",
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """ACTIVE Taxpayer with a single SCHEDULED EstimatedTaxPayment.
    Used by difficulty rule 6 instance 1 (cancel boundary at pay-date).
    """
    taxpayer = create_taxpayer()
    payment = schedule_payment(
        taxpayer,
        tax_year=TEST_DEFAULTS["TAX_YEAR"],
        quarter=quarter,
        amount_cents=amount_cents,
        scheduled_pay_date=scheduled_pay_date,
    )
    return taxpayer, payment


# ---------------------------------------------------------------------------
# Audit log read helper (IRSAdjudicator only)
# ---------------------------------------------------------------------------
def list_audit_logs(
    *,
    actor_role: Optional[str] = None,
    action: Optional[str] = None,
    target_entity: Optional[str] = None,
    target_id: Optional[str] = None,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """GET /audit-logs — PRD §2.11: 'exposed only to the IRSAdjudicator
    role'."""
    headers = headers or TEST_USERS["irs_adjudicator_headers"]
    params: Dict[str, Any] = {}
    if actor_role is not None:
        params["actor_role"] = actor_role
    if action is not None:
        params["action"] = action
    if target_entity is not None:
        params["target_entity"] = target_entity
    if target_id is not None:
        params["target_id"] = target_id
    if limit is not None:
        params["limit"] = limit
    if offset is not None:
        params["offset"] = offset
    resp = api_client.list_audit_logs(headers, params=params or None)
    body = resp.json()
    return body["data"], body["meta"]


__all__ = [
    # Clock
    "advance_clock_to",
    "get_clock",
    # Taxpayer
    "create_taxpayer",
    "get_taxpayer",
    "compliance_lock",
    "compliance_unlock",
    # TaxReturn
    "create_tax_return",
    "get_tax_return",
    "patch_tax_return",
    "compute_tax_return",
    "efile_tax_return",
    "unlock_for_correction",
    "get_safe_harbor",
    # IncomeDocument
    "add_w2",
    "add_1099_nec",
    "add_1099_int",
    "add_1099_div",
    "add_1099_b",
    # Schedule
    "add_schedule_a",
    "add_schedule_b",
    "add_schedule_c",
    "add_schedule_d",
    "add_schedule_e",
    # Credit
    "add_credit",
    # Filing / amendment
    "accept_filing",
    "reject_filing",
    "create_amendment",
    "submit_amendment",
    "accept_amendment",
    "reject_amendment",
    # Estimated payments
    "schedule_payment",
    "cancel_payment",
    # Re-read
    "re_get_tax_return",
    "re_get_taxpayer",
    "re_get_efiling",
    "re_get_amendment",
    # Composite
    "setup_active_taxpayer_with_draft_return",
    "setup_simple_w2_return",
    "setup_ready_to_file_return",
    "setup_filed_return",
    "setup_accepted_return",
    "setup_rejected_return",
    "setup_amendment_draft",
    "setup_amendment_submitted",
    "setup_locked_taxpayer_with_draft",
    "setup_for_dual_variant_deduction",
    "setup_for_compliance_lock_cascade",
    "setup_for_payment_boundary",
    # Audit
    "list_audit_logs",
]
