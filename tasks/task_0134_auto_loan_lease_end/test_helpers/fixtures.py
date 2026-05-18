"""Composite setup helpers — multi-step preambles tests can reuse.

Many tests require the system in a late state (e.g., a Loan ACTIVE
with 12 paid payments; a Lease MATURED with assessment ISSUED; a
Customer at the FICO tier boundary). Each fixture composes the
lower-level steps so the test body can focus on the rule under
assertion.

IDENTITY THREADING — PRD §2.1:

- PlatformAdmin / LoanOfficer / FinanceManager / CollectionsAgent are
  OPAQUE; shared headers in TEST_USERS are canonical for these.
- Customer is ENTITY-BACKED. Every Customer-driven call whose success
  depends on owning the targeted resource MUST mint headers via
  make_customer_headers(customer["id"]). The fixtures here return the
  actual Customer row so consumer tests can route Customer-acting
  calls through make_customer_headers.

PRD §2.1: "a Customer calling pay on a payment whose parent contract's
customer_id does not equal X-User-ID is treated as an unauthorized
actor and rejected." This rule applies to every Customer-actor
endpoint: pay, lease-end, assessment/settle, assessment/dispute,
gap-riders/cancel. Fixtures pay payments / submit elections / settle
assessments by minting headers from the actual Customer.id.

Setup calls use get_success_data (lenient 2xx validator), so a failed
setup surfaces as 'Setup failed' rather than a confusing test
assertion failure downstream.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    APR_UPLIFT_BPS,
    DAYS_PER_PERIOD,
    DEFAULT_GRACE_DAYS_BEHAVIORAL,
    DISPOSITION_FEE_CENTS,
    PENALTY_PER_MILE_CENTS,
    PURCHASE_OPTION_FEE_CENTS,
    TEST_DEFAULTS,
    TIER_1_APR_BPS,
    TIER_1_MF_MICRO,
    TIER_2_APR_BPS,
    TIER_2_MF_MICRO,
    TIER_3_APR_BPS,
    TIER_3_MF_MICRO,
    UPLIFT_THRESHOLD,
)
from .factories import (
    claim_gap_rider_payload,
    clock_advance_payload,
    create_customer_payload,
    create_gap_rider_payload,
    create_lease_contract_payload,
    create_loan_contract_payload,
    create_vehicle_payload,
    lease_end_payload,
    patch_assessment_payload,
    random_vin,
    resolve_assessment_payload,
)
from .test_users import (
    TEST_USERS,
    make_customer_headers,
)


# ===========================================================================
# Customers — PRD §3.1
# ===========================================================================
def create_customer(
    *,
    full_name: Optional[str] = None,
    fico_score: Optional[int] = None,
    actor_headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /customers — PlatformAdmin or LoanOfficer (opaque). Returns
    the Customer row."""
    headers = actor_headers or TEST_USERS["platform_admin_headers"]
    payload = create_customer_payload(
        full_name=full_name, fico_score=fico_score, **overrides,
    )
    resp = api_client.create_customer(payload, headers)
    return get_success_data(resp)


def get_customer(customer: Dict[str, Any]) -> Dict[str, Any]:
    """Re-fetch the customer row. Use the customer's own headers so any
    ownership check passes."""
    headers = make_customer_headers(customer["id"])
    resp = api_client.get_customer(customer["id"], headers)
    return get_success_data(resp)


def suspend_customer(customer: Dict[str, Any]) -> Dict[str, Any]:
    """POST /customers/{id}/suspend — PlatformAdmin only."""
    resp = api_client.suspend_customer(
        customer["id"], TEST_USERS["platform_admin_headers"],
    )
    return get_success_data(resp)


def reinstate_customer(customer: Dict[str, Any]) -> Dict[str, Any]:
    """POST /customers/{id}/reinstate — PlatformAdmin only."""
    resp = api_client.reinstate_customer(
        customer["id"], TEST_USERS["platform_admin_headers"],
    )
    return get_success_data(resp)


def advance_clock(
    customer: Dict[str, Any], days_advanced: int,
) -> Dict[str, Any]:
    """POST /customers/{id}/clock/advance — PlatformAdmin or LoanOfficer."""
    resp = api_client.advance_clock(
        customer["id"],
        clock_advance_payload(days_advanced=days_advanced),
        TEST_USERS["platform_admin_headers"],
    )
    return get_success_data(resp)


# ===========================================================================
# Vehicles — PRD §3.2
# ===========================================================================
def create_vehicle(
    *,
    msrp_cents: Optional[int] = None,
    residual_factor_bps: Optional[int] = None,
    vin: Optional[str] = None,
    model: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /vehicles — PlatformAdmin only."""
    headers = TEST_USERS["platform_admin_headers"]
    resp = api_client.create_vehicle(
        create_vehicle_payload(
            vin=vin, model=model, msrp_cents=msrp_cents,
            residual_factor_bps=residual_factor_bps, **overrides,
        ),
        headers,
    )
    return get_success_data(resp)


def get_vehicle(vehicle: Dict[str, Any]) -> Dict[str, Any]:
    resp = api_client.get_vehicle(
        vehicle["id"], TEST_USERS["platform_admin_headers"],
    )
    return get_success_data(resp)


# ===========================================================================
# Loan contracts — PRD §3.3
# ===========================================================================
def create_loan_contract(
    customer: Dict[str, Any], vehicle: Dict[str, Any],
    *,
    down_payment_cents: Optional[int] = None,
    term_months: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /customers/{id}/loan-contracts — LoanOfficer only."""
    headers = TEST_USERS["loan_officer_headers"]
    resp = api_client.create_loan_contract(
        customer["id"],
        create_loan_contract_payload(
            vehicle_id=vehicle["id"],
            down_payment_cents=down_payment_cents,
            term_months=term_months,
            **overrides,
        ),
        headers,
    )
    return get_success_data(resp)


def approve_loan_contract(
    customer: Dict[str, Any], contract: Dict[str, Any],
) -> Dict[str, Any]:
    resp = api_client.approve_loan_contract(
        customer["id"], contract["id"],
        TEST_USERS["loan_officer_headers"],
    )
    return get_success_data(resp)


def activate_loan_contract(
    customer: Dict[str, Any], contract: Dict[str, Any],
) -> Dict[str, Any]:
    resp = api_client.activate_loan_contract(
        customer["id"], contract["id"],
        TEST_USERS["loan_officer_headers"],
    )
    return get_success_data(resp)


def create_approve_activate_loan(
    customer: Dict[str, Any], vehicle: Dict[str, Any],
    *, down_payment_cents: Optional[int] = None,
    term_months: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Create → approve → activate. Returns the ACTIVE loan."""
    loan = create_loan_contract(
        customer, vehicle, down_payment_cents=down_payment_cents,
        term_months=term_months, **overrides,
    )
    approve_loan_contract(customer, loan)
    active = activate_loan_contract(customer, loan)
    return active


def get_loan_contract(
    customer: Dict[str, Any], contract_id: str,
) -> Dict[str, Any]:
    resp = api_client.get_loan_contract(
        customer["id"], contract_id,
        TEST_USERS["loan_officer_headers"],
    )
    return get_success_data(resp)


# ===========================================================================
# Lease contracts — PRD §3.4
# ===========================================================================
def create_lease_contract(
    customer: Dict[str, Any], vehicle: Dict[str, Any],
    *,
    down_payment_cents: Optional[int] = None,
    term_months: Optional[int] = None,
    mileage_allowance: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /customers/{id}/lease-contracts — LoanOfficer only."""
    headers = TEST_USERS["loan_officer_headers"]
    resp = api_client.create_lease_contract(
        customer["id"],
        create_lease_contract_payload(
            vehicle_id=vehicle["id"],
            down_payment_cents=down_payment_cents,
            term_months=term_months,
            mileage_allowance=mileage_allowance,
            **overrides,
        ),
        headers,
    )
    return get_success_data(resp)


def approve_lease_contract(
    customer: Dict[str, Any], contract: Dict[str, Any],
) -> Dict[str, Any]:
    resp = api_client.approve_lease_contract(
        customer["id"], contract["id"],
        TEST_USERS["loan_officer_headers"],
    )
    return get_success_data(resp)


def activate_lease_contract(
    customer: Dict[str, Any], contract: Dict[str, Any],
) -> Dict[str, Any]:
    resp = api_client.activate_lease_contract(
        customer["id"], contract["id"],
        TEST_USERS["loan_officer_headers"],
    )
    return get_success_data(resp)


def create_approve_activate_lease(
    customer: Dict[str, Any], vehicle: Dict[str, Any],
    *, down_payment_cents: Optional[int] = None,
    term_months: Optional[int] = None,
    mileage_allowance: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Create → approve → activate. Returns the ACTIVE lease."""
    lease = create_lease_contract(
        customer, vehicle, down_payment_cents=down_payment_cents,
        term_months=term_months, mileage_allowance=mileage_allowance,
        **overrides,
    )
    approve_lease_contract(customer, lease)
    return activate_lease_contract(customer, lease)


def get_lease_contract(
    customer: Dict[str, Any], contract_id: str,
) -> Dict[str, Any]:
    resp = api_client.get_lease_contract(
        customer["id"], contract_id,
        TEST_USERS["loan_officer_headers"],
    )
    return get_success_data(resp)


# ===========================================================================
# Payments — PRD §3.5
# ===========================================================================
def list_payments(
    customer: Dict[str, Any],
    *, contract_id: Optional[str] = None,
    status: Optional[str] = None, limit: int = 100, offset: int = 0,
) -> List[Dict[str, Any]]:
    """List ALL payments for a customer (paginated to a single page).
    Use loan-officer headers (shared read access)."""
    params: Dict[str, Any] = {"limit": limit, "offset": offset}
    if contract_id is not None:
        params["contract_id"] = contract_id
    if status is not None:
        params["status"] = status
    resp = api_client.list_payments(
        customer["id"], TEST_USERS["loan_officer_headers"],
        params=params,
    )
    # validate_paginated would require imports; return raw data via
    # get_success_data and the meta envelope.
    data = get_success_data(resp)
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "data" in data:
        return data["data"]
    # Some implementations may return the body envelope; the framework
    # already unwrapped to `data`, so a list is expected.
    return data  # type: ignore[return-value]


def list_payments_full(
    customer: Dict[str, Any],
    *, contract_id: Optional[str] = None,
    status: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Iterate through all pages and return the full payment list,
    sorted by created_at ASC per PRD §2.3."""
    all_rows: List[Dict[str, Any]] = []
    offset = 0
    page_size = 100  # PRD §2.3 max.
    while True:
        page = list_payments(
            customer, contract_id=contract_id, status=status,
            limit=page_size, offset=offset,
        )
        if not page:
            break
        all_rows.extend(page)
        if len(page) < page_size:
            break
        offset += page_size
    return all_rows


def get_payment(
    customer: Dict[str, Any], payment_id: str,
) -> Dict[str, Any]:
    resp = api_client.get_payment(
        customer["id"], payment_id,
        TEST_USERS["loan_officer_headers"],
    )
    return get_success_data(resp)


def pay_payment(
    customer: Dict[str, Any], payment: Dict[str, Any],
) -> Dict[str, Any]:
    """POST .../payments/{id}/pay — Customer only.
    PRD §2.1: ownership check compares Payment's parent contract's
    customer_id to X-User-ID. The fixture mints headers from the
    customer's id so ownership passes."""
    headers = make_customer_headers(customer["id"])
    resp = api_client.pay_payment(customer["id"], payment["id"], headers)
    return get_success_data(resp)


def pay_next_unpaid_payment(
    customer: Dict[str, Any], contract: Dict[str, Any],
) -> Dict[str, Any]:
    """Pay the payment with the lowest period_index that is not yet
    PAID on this contract."""
    payments = list_payments_full(customer, contract_id=contract["id"])
    candidates = [p for p in payments if p["status"] != "PAID"]
    candidates.sort(key=lambda p: p["period_index"])
    if not candidates:
        raise AssertionError("Setup failed: no unpaid payments left")
    return pay_payment(customer, candidates[0])


# ===========================================================================
# Gap riders — PRD §3.7
# ===========================================================================
def create_gap_rider(
    customer: Dict[str, Any], contract: Dict[str, Any],
    *, contract_type: str,
) -> Dict[str, Any]:
    """POST /customers/{id}/gap-riders — FinanceManager or Customer
    shared. Use Customer headers so ownership check (customer owns the
    parent contract) passes."""
    headers = make_customer_headers(customer["id"])
    resp = api_client.create_gap_rider(
        customer["id"],
        create_gap_rider_payload(
            contract_id=contract["id"], contract_type=contract_type,
        ),
        headers,
    )
    return get_success_data(resp)


def cancel_gap_rider(
    customer: Dict[str, Any], rider: Dict[str, Any],
) -> Dict[str, Any]:
    """POST .../gap-riders/{id}/cancel — Customer only (exclusive)."""
    headers = make_customer_headers(customer["id"])
    resp = api_client.cancel_gap_rider(
        customer["id"], rider["id"], headers,
    )
    return get_success_data(resp)


def claim_gap_rider(
    customer: Dict[str, Any], rider: Dict[str, Any], payout_cents: int,
) -> Dict[str, Any]:
    """POST .../gap-riders/{id}/claim — FinanceManager only
    (exclusive)."""
    resp = api_client.claim_gap_rider(
        customer["id"], rider["id"],
        claim_gap_rider_payload(payout_cents=payout_cents),
        TEST_USERS["finance_manager_headers"],
    )
    return get_success_data(resp)


# ===========================================================================
# Lease end assessment — PRD §3.9
# ===========================================================================
def patch_assessment(
    customer: Dict[str, Any], lease: Dict[str, Any],
    odometer_reading: int,
) -> Dict[str, Any]:
    """PATCH .../assessment — FinanceManager only (exclusive)."""
    resp = api_client.patch_assessment(
        customer["id"], lease["id"],
        patch_assessment_payload(odometer_reading=odometer_reading),
        TEST_USERS["finance_manager_headers"],
    )
    return get_success_data(resp)


def submit_lease_end(
    customer: Dict[str, Any], lease: Dict[str, Any], election: str,
) -> Dict[str, Any]:
    """POST .../lease-end — Customer only (exclusive)."""
    headers = make_customer_headers(customer["id"])
    resp = api_client.submit_lease_end(
        customer["id"], lease["id"],
        lease_end_payload(election=election), headers,
    )
    return get_success_data(resp)


def settle_assessment(
    customer: Dict[str, Any], lease: Dict[str, Any],
) -> Dict[str, Any]:
    """POST .../assessment/settle — Customer only (exclusive)."""
    headers = make_customer_headers(customer["id"])
    resp = api_client.settle_assessment(
        customer["id"], lease["id"], headers,
    )
    return get_success_data(resp)


def dispute_assessment(
    customer: Dict[str, Any], lease: Dict[str, Any],
) -> Dict[str, Any]:
    """POST .../assessment/dispute — Customer only (exclusive)."""
    headers = make_customer_headers(customer["id"])
    resp = api_client.dispute_assessment(
        customer["id"], lease["id"], headers,
    )
    return get_success_data(resp)


def resolve_assessment(
    customer: Dict[str, Any], lease: Dict[str, Any],
    revised_odometer_reading: int,
) -> Dict[str, Any]:
    """POST .../assessment/resolve — FinanceManager only (exclusive)."""
    resp = api_client.resolve_assessment(
        customer["id"], lease["id"],
        resolve_assessment_payload(
            revised_odometer_reading=revised_odometer_reading,
        ),
        TEST_USERS["finance_manager_headers"],
    )
    return get_success_data(resp)


# ===========================================================================
# Composite scenarios — Tier 2 / 3 / 4 (full lifecycle preambles)
# ===========================================================================

def setup_tier1_customer_and_vehicle(
    *, fico_score: int = TEST_DEFAULTS["FICO_TIER_1"],
    msrp_cents: int = TEST_DEFAULTS["MSRP_CENTS"],
    residual_factor_bps: int = TEST_DEFAULTS["RESIDUAL_FACTOR_BPS"],
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Create a TIER_1 customer + an AVAILABLE vehicle. Returns (cust,
    veh)."""
    customer = create_customer(fico_score=fico_score)
    vehicle = create_vehicle(
        msrp_cents=msrp_cents,
        residual_factor_bps=residual_factor_bps,
    )
    return customer, vehicle


def setup_tier2_customer_and_lease_vehicle(
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """TIER_2 customer + 5800 bps vehicle aligned with the difficulty
    design's lease purchase example."""
    customer = create_customer(fico_score=TEST_DEFAULTS["FICO_TIER_2"])
    vehicle = create_vehicle(
        msrp_cents=TEST_DEFAULTS["LEASE_MSRP_CENTS"],
        residual_factor_bps=TEST_DEFAULTS["LEASE_RESIDUAL_FACTOR_BPS"],
    )
    return customer, vehicle


def setup_active_loan(
    *,
    fico_score: int = TEST_DEFAULTS["FICO_TIER_1"],
    msrp_cents: int = TEST_DEFAULTS["MSRP_CENTS"],
    down_payment_cents: int = TEST_DEFAULTS["LOAN_DOWN_PAYMENT_CENTS"],
    term_months: int = TEST_DEFAULTS["LOAN_TERM_MONTHS"],
    residual_factor_bps: int = TEST_DEFAULTS["RESIDUAL_FACTOR_BPS"],
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Customer + Vehicle + ACTIVE LoanContract. Returns
    (customer, vehicle, active_loan)."""
    customer, vehicle = setup_tier1_customer_and_vehicle(
        fico_score=fico_score, msrp_cents=msrp_cents,
        residual_factor_bps=residual_factor_bps,
    )
    loan = create_approve_activate_loan(
        customer, vehicle,
        down_payment_cents=down_payment_cents,
        term_months=term_months,
    )
    return customer, vehicle, loan


def setup_active_lease(
    *,
    fico_score: int = TEST_DEFAULTS["FICO_TIER_2"],
    msrp_cents: int = TEST_DEFAULTS["LEASE_MSRP_CENTS"],
    residual_factor_bps: int = TEST_DEFAULTS["LEASE_RESIDUAL_FACTOR_BPS"],
    down_payment_cents: int = TEST_DEFAULTS["LEASE_DOWN_PAYMENT_CENTS"],
    term_months: int = TEST_DEFAULTS["LEASE_TERM_MONTHS"],
    mileage_allowance: int = TEST_DEFAULTS["MILEAGE_ALLOWANCE"],
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Customer + Vehicle + ACTIVE LeaseContract. Returns
    (customer, vehicle, active_lease)."""
    customer = create_customer(fico_score=fico_score)
    vehicle = create_vehicle(
        msrp_cents=msrp_cents,
        residual_factor_bps=residual_factor_bps,
    )
    lease = create_approve_activate_lease(
        customer, vehicle,
        down_payment_cents=down_payment_cents,
        term_months=term_months,
        mileage_allowance=mileage_allowance,
    )
    return customer, vehicle, lease


def pay_n_loan_payments(
    customer: Dict[str, Any], loan: Dict[str, Any], n: int,
) -> Dict[str, Any]:
    """Advance clock by 30 days N times, paying the next due Payment
    after each advance. Returns the refreshed loan row."""
    for _ in range(n):
        advance_clock(customer, DAYS_PER_PERIOD)
        pay_next_unpaid_payment(customer, loan)
    return get_loan_contract(customer, loan["id"])


def pay_n_lease_payments(
    customer: Dict[str, Any], lease: Dict[str, Any], n: int,
) -> Dict[str, Any]:
    """Advance clock by 30 days N times, paying the next due Payment
    after each advance. Returns the refreshed lease row."""
    for _ in range(n):
        advance_clock(customer, DAYS_PER_PERIOD)
        pay_next_unpaid_payment(customer, lease)
    return get_lease_contract(customer, lease["id"])


def setup_loan_with_n_paid_payments(
    n: int,
    *,
    fico_score: int = TEST_DEFAULTS["FICO_TIER_1"],
    msrp_cents: int = TEST_DEFAULTS["MSRP_CENTS"],
    down_payment_cents: int = TEST_DEFAULTS["LOAN_DOWN_PAYMENT_CENTS"],
    term_months: int = TEST_DEFAULTS["LOAN_TERM_MONTHS"],
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Active loan with N consecutive PAID payments. Returns
    (customer, vehicle, loan)."""
    customer, vehicle, loan = setup_active_loan(
        fico_score=fico_score, msrp_cents=msrp_cents,
        down_payment_cents=down_payment_cents, term_months=term_months,
    )
    if n > 0:
        loan = pay_n_loan_payments(customer, loan, n)
    return customer, vehicle, loan


def setup_loan_paid_off(
    *,
    fico_score: int = TEST_DEFAULTS["FICO_TIER_1"],
    msrp_cents: int = TEST_DEFAULTS["MSRP_CENTS"],
    down_payment_cents: int = TEST_DEFAULTS["LOAN_DOWN_PAYMENT_CENTS"],
    term_months: int = TEST_DEFAULTS["LOAN_TERM_MONTHS"],
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Drive a loan all the way to PAID_OFF. Returns (cust, veh, loan)."""
    customer, vehicle, loan = setup_active_loan(
        fico_score=fico_score, msrp_cents=msrp_cents,
        down_payment_cents=down_payment_cents, term_months=term_months,
    )
    loan = pay_n_loan_payments(customer, loan, term_months)
    return customer, vehicle, loan


def setup_loan_defaulted_via_clock(
    *,
    fico_score: int = TEST_DEFAULTS["FICO_TIER_1"],
    msrp_cents: int = TEST_DEFAULTS["MSRP_CENTS"],
    down_payment_cents: int = TEST_DEFAULTS["LOAN_DOWN_PAYMENT_CENTS"],
    term_months: int = TEST_DEFAULTS["LOAN_TERM_MONTHS"],
    paid_periods_before_default: int = 0,
    skip_days: int = 180,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Originate a loan, optionally pay some periods, then skip a
    large window of days so that >=3 payments default and the loan
    auto-transitions to DEFAULTED with APR uplift fired. Returns
    (cust, veh, loan-after-cascade)."""
    customer, vehicle, loan = setup_active_loan(
        fico_score=fico_score, msrp_cents=msrp_cents,
        down_payment_cents=down_payment_cents, term_months=term_months,
    )
    if paid_periods_before_default > 0:
        loan = pay_n_loan_payments(
            customer, loan, paid_periods_before_default,
        )
    # Skip far past 3 due dates without paying. With DAYS_PER_PERIOD=30
    # and a grace of ~15 days, 180 days well exceeds the threshold for
    # 6 missed periods, guaranteeing ≥3 defaults.
    advance_clock(customer, skip_days)
    return customer, vehicle, get_loan_contract(customer, loan["id"])


def setup_lease_matured(
    *,
    fico_score: int = TEST_DEFAULTS["FICO_TIER_2"],
    msrp_cents: int = TEST_DEFAULTS["LEASE_MSRP_CENTS"],
    residual_factor_bps: int = TEST_DEFAULTS["LEASE_RESIDUAL_FACTOR_BPS"],
    down_payment_cents: int = TEST_DEFAULTS["LEASE_DOWN_PAYMENT_CENTS"],
    term_months: int = TEST_DEFAULTS["LEASE_TERM_MONTHS"],
    mileage_allowance: int = TEST_DEFAULTS["MILEAGE_ALLOWANCE"],
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Lease driven through every payment + one extra clock tick so it
    auto-transitions to MATURED. Returns (cust, veh, lease)."""
    customer, vehicle, lease = setup_active_lease(
        fico_score=fico_score, msrp_cents=msrp_cents,
        residual_factor_bps=residual_factor_bps,
        down_payment_cents=down_payment_cents,
        term_months=term_months, mileage_allowance=mileage_allowance,
    )
    lease = pay_n_lease_payments(customer, lease, term_months)
    # After paying all payments, clock_day_index = term_months*30.
    # maturity_day_index = origination(0) + term_months*30 = same value.
    # Per PRD §3.9 the lease auto-matures on the next clock tick that
    # makes Customer.clock_day_index >= maturity_day_index AND
    # payments_made_count == payments_scheduled_count.
    # In case the implementation requires a strict > (not >=), nudge.
    advance_clock(customer, 1)
    return customer, vehicle, get_lease_contract(customer, lease["id"])


def setup_lease_matured_with_assessment_issued(
    *,
    odometer_reading: int = TEST_DEFAULTS["MILEAGE_ALLOWANCE"],
    **lease_overrides: Any,
) -> Tuple[
    Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any],
]:
    """Matured lease + PATCH odometer_reading to ISSUE the assessment.
    Returns (cust, veh, lease, assessment)."""
    customer, vehicle, lease = setup_lease_matured(**lease_overrides)
    assessment = patch_assessment(
        customer, lease, odometer_reading=odometer_reading,
    )
    return customer, vehicle, lease, assessment


def setup_lease_ready_for_assessment_patch(
    *,
    mileage_allowance: int = TEST_DEFAULTS["MILEAGE_ALLOWANCE"],
    **lease_overrides: Any,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Matured lease with DRAFT assessment ready to be PATCH'd."""
    return setup_lease_matured(
        mileage_allowance=mileage_allowance, **lease_overrides,
    )


# ===========================================================================
# Difficulty-design fixture builders (Tier 4 / Tier 5)
# ===========================================================================
def setup_two_overlapping_lease_originations(
    customer: Dict[str, Any],
    *,
    term_months: int = TEST_DEFAULTS["LEASE_TERM_MONTHS"],
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Two distinct vehicles, an approved+active first lease (L1), and a
    second lease (L2) created but NOT yet approved. Used by the
    lease-window-overlap test.
    Returns (vehicle1, L1, L2)."""
    v1 = create_vehicle(
        msrp_cents=TEST_DEFAULTS["LEASE_MSRP_CENTS"],
        residual_factor_bps=TEST_DEFAULTS["LEASE_RESIDUAL_FACTOR_BPS"],
    )
    v2 = create_vehicle(
        msrp_cents=TEST_DEFAULTS["LEASE_MSRP_CENTS"],
        residual_factor_bps=TEST_DEFAULTS["LEASE_RESIDUAL_FACTOR_BPS"],
    )
    L1 = create_approve_activate_lease(
        customer, v1,
        down_payment_cents=TEST_DEFAULTS["LEASE_DOWN_PAYMENT_CENTS"],
        term_months=term_months,
        mileage_allowance=TEST_DEFAULTS["MILEAGE_ALLOWANCE"],
    )
    L2 = create_lease_contract(
        customer, v2,
        down_payment_cents=TEST_DEFAULTS["LEASE_DOWN_PAYMENT_CENTS"],
        term_months=term_months,
        mileage_allowance=TEST_DEFAULTS["MILEAGE_ALLOWANCE"],
    )
    return v1, L1, L2


__all__ = [
    # Customers
    "create_customer",
    "get_customer",
    "suspend_customer",
    "reinstate_customer",
    "advance_clock",
    # Vehicles
    "create_vehicle",
    "get_vehicle",
    # Loan contracts
    "create_loan_contract",
    "approve_loan_contract",
    "activate_loan_contract",
    "create_approve_activate_loan",
    "get_loan_contract",
    # Lease contracts
    "create_lease_contract",
    "approve_lease_contract",
    "activate_lease_contract",
    "create_approve_activate_lease",
    "get_lease_contract",
    # Payments
    "list_payments",
    "list_payments_full",
    "get_payment",
    "pay_payment",
    "pay_next_unpaid_payment",
    # Gap riders
    "create_gap_rider",
    "cancel_gap_rider",
    "claim_gap_rider",
    # Assessment
    "patch_assessment",
    "submit_lease_end",
    "settle_assessment",
    "dispute_assessment",
    "resolve_assessment",
    # Composite scenarios
    "setup_tier1_customer_and_vehicle",
    "setup_tier2_customer_and_lease_vehicle",
    "setup_active_loan",
    "setup_active_lease",
    "pay_n_loan_payments",
    "pay_n_lease_payments",
    "setup_loan_with_n_paid_payments",
    "setup_loan_paid_off",
    "setup_loan_defaulted_via_clock",
    "setup_lease_matured",
    "setup_lease_matured_with_assessment_issued",
    "setup_lease_ready_for_assessment_patch",
    "setup_two_overlapping_lease_originations",
]
