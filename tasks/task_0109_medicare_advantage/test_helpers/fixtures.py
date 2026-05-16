"""Composite setup helpers — multi-step preambles tests can reuse.

The Medicare pipeline is long: clock advance -> beneficiary intake
(auto-mints IEP period in SCHEDULED) -> clock crosses iep_start_date
(period -> OPEN, beneficiary -> IEP_OPEN) -> plan create -> enrollment
create (PENDING) -> activate (consumes IEP, mints DrugPhaseLedger for
PART_D, mints LEP for late activation) -> drug claim submit ->
adjudicate -> ledger updated. Many tests need the system in a late
pipeline state.

IDENTITY THREADING — PRD §2.1:

- PlanAdmin / BenefitsCounselor / Auditor are OPAQUE. Shared constants
  (admin_headers, counselor_headers, auditor_headers) are canonical for
  every operator-only call.

- Beneficiary is ENTITY-BACKED. Every Beneficiary-driven read whose
  success depends on owning the targeted resource MUST mint headers via
  make_beneficiary_headers(beneficiary["id"]) — never via the shared
  BENEFICIARY_FALLBACK_ID constant. The fixtures here return the actual
  Beneficiary row so consumer tests can route beneficiary-acting reads
  through this header builder.

SEGREGATION OF DUTIES — PRD §3.8: 'The admin who performs adjudication
cannot be the same operator who submitted the claim'. Submission uses
counselor_headers; adjudication uses admin_headers (different X-User-ID).

Setup calls use get_success_data (a lenient 2xx validator), so a
failed setup surfaces as 'Setup failed' rather than a confusing test
assertion failure downstream.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    add_months,
    clock_advance_payload,
    create_beneficiary_payload,
    create_drug_claim_payload,
    create_enrollment_payload,
    create_enrollment_period_payload,
    create_medigap_plan_payload,
    create_medigap_policy_payload,
    create_part_d_plan_payload,
    create_plan_payload,
    create_star_rating_payload,
    first_of_month,
    iso_date,
    iso_day_end_utc,
    iso_day_start_utc,
    iso_instant_utc,
    last_of_month,
    random_medicare_id,
    random_plan_code,
    terminate_enrollment_payload,
    transfer_enrollment_payload,
    version_body,
)
from .test_users import TEST_USERS, make_beneficiary_headers


# ===========================================================================
# Clock helpers — PRD §3.2 (PlanAdmin or Auditor for advance)
# ===========================================================================
def advance_clock_to(to_iso: str,
                     headers: Optional[Dict[str, str]] = None
                     ) -> Dict[str, Any]:
    """POST /_clock/advance.

    PRD §3.2: 'operators with the PlanAdmin or Auditor role can advance
    this clock'. Default to admin headers.
    """
    headers = headers or TEST_USERS["admin_headers"]
    resp = api_client.clock_advance(
        clock_advance_payload(to=to_iso), headers,
    )
    return get_success_data(resp)


def read_clock(headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    headers = headers or TEST_USERS["admin_headers"]
    resp = api_client.get_clock(headers)
    return get_success_data(resp)


# ===========================================================================
# Tier 1: Beneficiary intake — PRD §3.1
# ===========================================================================
def create_beneficiary(
    *,
    full_name: Optional[str] = None,
    date_of_birth: Optional[str] = None,
    medicare_id: Optional[str] = None,
    has_esrd: Optional[bool] = None,
    has_disability: Optional[bool] = None,
    ssdi_start_date: Optional[str] = None,
    state_code: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /beneficiaries — PlanAdmin only per PRD §4."""
    headers = headers or TEST_USERS["admin_headers"]
    resp = api_client.create_beneficiary(
        create_beneficiary_payload(
            full_name=full_name, date_of_birth=date_of_birth,
            medicare_id=medicare_id, has_esrd=has_esrd,
            has_disability=has_disability,
            ssdi_start_date=ssdi_start_date,
            state_code=state_code,
        ),
        headers,
    )
    return get_success_data(resp)


def re_get_beneficiary(beneficiary_id: str,
                       headers: Optional[Dict[str, str]] = None
                       ) -> Dict[str, Any]:
    """GET /beneficiaries/{id} as admin (always permitted)."""
    headers = headers or TEST_USERS["admin_headers"]
    resp = api_client.get_beneficiary(beneficiary_id, headers)
    return get_success_data(resp)


# ===========================================================================
# Tier 1: Plan catalogue — PRD §3.3
# ===========================================================================
def create_plan(
    *,
    plan_type: str = "PART_C",
    plan_year: int = 2026,
    monthly_premium_cents: int = 10_000,
    state_code: Optional[str] = None,
    star_rating: float = 4.0,
    is_active: Optional[bool] = None,
    plan_code: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /plans — PlanAdmin only per PRD §4."""
    headers = headers or TEST_USERS["admin_headers"]
    payload = create_plan_payload(
        plan_code=plan_code,
        plan_type=plan_type,
        plan_year=plan_year,
        monthly_premium_cents=monthly_premium_cents,
        state_code=state_code,
        star_rating=star_rating,
        is_active=is_active,
        **overrides,
    )
    resp = api_client.create_plan(payload, headers)
    return get_success_data(resp)


def create_part_d_plan(
    *,
    plan_year: int = 2026,
    monthly_premium_cents: int = 4_000,
    annual_deductible_cents: int = 40_000,
    initial_coverage_limit_cents: int = 400_000,
    catastrophic_threshold_cents: int = 150_000,
    star_rating: float = 4.0,
    plan_code: Optional[str] = None,
    is_active: Optional[bool] = None,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PART_D plan with PRD §3.8 thresholds pre-populated."""
    headers = headers or TEST_USERS["admin_headers"]
    payload = create_part_d_plan_payload(
        plan_code=plan_code, plan_year=plan_year,
        monthly_premium_cents=monthly_premium_cents,
        annual_deductible_cents=annual_deductible_cents,
        initial_coverage_limit_cents=initial_coverage_limit_cents,
        catastrophic_threshold_cents=catastrophic_threshold_cents,
        star_rating=star_rating, **overrides,
    )
    if is_active is not None:
        payload["is_active"] = is_active
    resp = api_client.create_plan(payload, headers)
    return get_success_data(resp)


def create_medigap_plan(
    *,
    plan_year: int = 2026,
    state_code: str = "CA",
    monthly_premium_cents: int = 20_000,
    star_rating: float = 4.0,
    plan_code: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """MEDIGAP plan — PRD §3.3 requires state_code."""
    headers = headers or TEST_USERS["admin_headers"]
    payload = create_medigap_plan_payload(
        plan_code=plan_code, plan_year=plan_year,
        state_code=state_code,
        monthly_premium_cents=monthly_premium_cents,
        star_rating=star_rating, **overrides,
    )
    resp = api_client.create_plan(payload, headers)
    return get_success_data(resp)


def publish_star_rating(
    *,
    plan: Dict[str, Any],
    measurement_year: int = 2026,
    clinical_quality_score: float = 80.0,
    member_experience_score: float = 80.0,
    customer_service_score: float = 80.0,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /plans/{id}/star-ratings — PlanAdmin."""
    headers = headers or TEST_USERS["admin_headers"]
    payload = create_star_rating_payload(
        measurement_year=measurement_year,
        clinical_quality_score=clinical_quality_score,
        member_experience_score=member_experience_score,
        customer_service_score=customer_service_score,
    )
    resp = api_client.publish_star_rating(plan["id"], payload, headers)
    return get_success_data(resp)


# ===========================================================================
# Tier 1: EnrollmentPeriod — PRD §3.2
# ===========================================================================
def create_enrollment_period(
    *,
    beneficiary: Dict[str, Any],
    period_type: str,
    window_start: str,
    window_end: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /beneficiaries/{id}/enrollment-periods — PlanAdmin only."""
    headers = headers or TEST_USERS["admin_headers"]
    payload = create_enrollment_period_payload(
        period_type=period_type,
        window_start=window_start,
        window_end=window_end,
    )
    resp = api_client.create_enrollment_period(
        beneficiary["id"], payload, headers,
    )
    return get_success_data(resp)


def list_enrollment_periods(
    beneficiary_id: str,
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """GET /beneficiaries/{id}/enrollment-periods.

    Returns the period rows as a Python list. get_success_data returns
    the response.data payload as-is; for list endpoints that is a list.
    """
    headers = headers or TEST_USERS["admin_headers"]
    resp = api_client.list_enrollment_periods(
        beneficiary_id, headers, params,
    )
    data = get_success_data(resp)
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "data" in data and isinstance(
        data["data"], list,
    ):
        return data["data"]
    return data  # type: ignore[return-value]


def get_iep_period(beneficiary_id: str) -> Optional[Dict[str, Any]]:
    """Return the beneficiary's IEP period row (created automatically
    on intake per PRD §3.1), or None if not present.
    """
    rows = list_enrollment_periods(
        beneficiary_id, params={"period_type": "IEP"},
    )
    if not isinstance(rows, list):
        return None
    for p in rows:
        if p.get("period_type") == "IEP":
            return p
    return None


# ===========================================================================
# Tier 1: Enrollment lifecycle — PRD §3.4 / §3.9
# ===========================================================================
def create_enrollment(
    *,
    beneficiary: Dict[str, Any],
    plan: Dict[str, Any],
    enrollment_period: Dict[str, Any],
    effective_date: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /enrollments — BenefitsCounselor only per PRD §4."""
    headers = headers or TEST_USERS["counselor_headers"]
    payload = create_enrollment_payload(
        beneficiary_id=beneficiary["id"],
        plan_id=plan["id"],
        enrollment_period_id=enrollment_period["id"],
        effective_date=effective_date,
    )
    resp = api_client.create_enrollment(payload, headers)
    return get_success_data(resp)


def activate_enrollment(
    enrollment_id: str,
    *,
    version: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /enrollments/{id}/activate — BenefitsCounselor."""
    headers = headers or TEST_USERS["counselor_headers"]
    resp = api_client.activate_enrollment(
        enrollment_id, version_body(version), headers,
    )
    return get_success_data(resp)


def reject_enrollment(
    enrollment_id: str,
    *,
    version: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /enrollments/{id}/reject — PlanAdmin."""
    headers = headers or TEST_USERS["admin_headers"]
    resp = api_client.reject_enrollment(
        enrollment_id, version_body(version), headers,
    )
    return get_success_data(resp)


def terminate_enrollment(
    enrollment_id: str,
    *,
    termination_date: str,
    version: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /enrollments/{id}/terminate — BenefitsCounselor."""
    headers = headers or TEST_USERS["counselor_headers"]
    payload = terminate_enrollment_payload(
        termination_date=termination_date, version=version,
    )
    resp = api_client.terminate_enrollment(
        enrollment_id, payload, headers,
    )
    return get_success_data(resp)


def transfer_enrollment(
    enrollment_id: str,
    *,
    new_plan_id: str,
    version: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /enrollments/{id}/transfer — BenefitsCounselor."""
    headers = headers or TEST_USERS["counselor_headers"]
    payload = transfer_enrollment_payload(
        new_plan_id=new_plan_id, version=version,
    )
    resp = api_client.transfer_enrollment(
        enrollment_id, payload, headers,
    )
    return get_success_data(resp)


def re_get_enrollment(enrollment_id: str,
                      headers: Optional[Dict[str, str]] = None
                      ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["admin_headers"]
    resp = api_client.get_enrollment(enrollment_id, headers)
    return get_success_data(resp)


def get_cost_summary(enrollment_id: str,
                     headers: Optional[Dict[str, str]] = None
                     ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["admin_headers"]
    resp = api_client.get_cost_summary(enrollment_id, headers)
    return get_success_data(resp)


def mark_deceased(
    beneficiary_id: str,
    *,
    version: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /beneficiaries/{id}/mark-deceased — PlanAdmin."""
    headers = headers or TEST_USERS["admin_headers"]
    resp = api_client.mark_beneficiary_deceased(
        beneficiary_id, version_body(version), headers,
    )
    return get_success_data(resp)


# ===========================================================================
# Tier 1: Medigap lifecycle — PRD §3.7
# ===========================================================================
def create_medigap_policy(
    *,
    beneficiary: Dict[str, Any],
    plan: Dict[str, Any],
    underwriting_uplift_decimal: Optional[float] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /medigap-policies — BenefitsCounselor only per PRD §4."""
    headers = headers or TEST_USERS["counselor_headers"]
    payload = create_medigap_policy_payload(
        beneficiary_id=beneficiary["id"],
        plan_id=plan["id"],
        underwriting_uplift_decimal=underwriting_uplift_decimal,
    )
    resp = api_client.create_medigap_policy(payload, headers)
    return get_success_data(resp)


def evaluate_gi_medigap(policy_id: str,
                        *, version: Optional[int] = None,
                        headers: Optional[Dict[str, str]] = None
                        ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["admin_headers"]
    resp = api_client.evaluate_gi_medigap(
        policy_id, version_body(version), headers,
    )
    return get_success_data(resp)


def begin_underwriting_medigap(policy_id: str,
                               *, version: Optional[int] = None,
                               headers: Optional[Dict[str, str]] = None
                               ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["admin_headers"]
    resp = api_client.begin_underwriting_medigap(
        policy_id, version_body(version), headers,
    )
    return get_success_data(resp)


def revise_medigap_application(policy_id: str,
                               *, version: Optional[int] = None,
                               headers: Optional[Dict[str, str]] = None
                               ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["counselor_headers"]
    resp = api_client.revise_medigap_application(
        policy_id, version_body(version), headers,
    )
    return get_success_data(resp)


def issue_medigap(policy_id: str,
                  *, version: Optional[int] = None,
                  headers: Optional[Dict[str, str]] = None
                  ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["admin_headers"]
    resp = api_client.issue_medigap(
        policy_id, version_body(version), headers,
    )
    return get_success_data(resp)


def cancel_medigap(policy_id: str,
                   *, version: Optional[int] = None,
                   headers: Optional[Dict[str, str]] = None
                   ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["counselor_headers"]
    resp = api_client.cancel_medigap(
        policy_id, version_body(version), headers,
    )
    return get_success_data(resp)


def deny_medigap(policy_id: str,
                 *, version: Optional[int] = None,
                 headers: Optional[Dict[str, str]] = None
                 ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["admin_headers"]
    resp = api_client.deny_medigap(
        policy_id, version_body(version), headers,
    )
    return get_success_data(resp)


def re_get_medigap(policy_id: str,
                   headers: Optional[Dict[str, str]] = None
                   ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["admin_headers"]
    resp = api_client.get_medigap_policy(policy_id, headers)
    return get_success_data(resp)


# ===========================================================================
# Tier 1: DrugClaim lifecycle — PRD §3.8
# Submission uses counselor headers; adjudication uses admin headers
# (PRD §3.8 segregation-of-duties — different X-User-ID).
# ===========================================================================
def submit_drug_claim(
    *,
    beneficiary: Dict[str, Any],
    enrollment: Dict[str, Any],
    tier: str = "TIER_3",
    fill_date: Optional[str] = None,
    gross_cost_cents: int = 5_000,
    ndc_code: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /drug-claims — BenefitsCounselor.

    Submission and adjudication MUST be performed by different
    X-User-IDs (PRD §3.8). The default counselor_headers and
    admin_headers constants differ.
    """
    headers = headers or TEST_USERS["counselor_headers"]
    payload = create_drug_claim_payload(
        beneficiary_id=beneficiary["id"],
        enrollment_id=enrollment["id"],
        tier=tier, fill_date=fill_date,
        gross_cost_cents=gross_cost_cents, ndc_code=ndc_code,
    )
    resp = api_client.create_drug_claim(payload, headers)
    return get_success_data(resp)


def adjudicate_drug_claim(claim_id: str,
                          *, version: Optional[int] = None,
                          headers: Optional[Dict[str, str]] = None
                          ) -> Dict[str, Any]:
    """POST /drug-claims/{id}/adjudicate — PlanAdmin (different operator
    than the counselor who submitted)."""
    headers = headers or TEST_USERS["admin_headers"]
    resp = api_client.adjudicate_drug_claim(
        claim_id, version_body(version), headers,
    )
    return get_success_data(resp)


def reverse_drug_claim(claim_id: str,
                       *, version: Optional[int] = None,
                       headers: Optional[Dict[str, str]] = None
                       ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["admin_headers"]
    resp = api_client.reverse_drug_claim(
        claim_id, version_body(version), headers,
    )
    return get_success_data(resp)


def re_get_drug_claim(claim_id: str,
                      headers: Optional[Dict[str, str]] = None
                      ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["admin_headers"]
    resp = api_client.get_drug_claim(claim_id, headers)
    return get_success_data(resp)


def get_drug_phase_ledger(beneficiary_id: str,
                          *, plan_year: Optional[int] = None,
                          headers: Optional[Dict[str, str]] = None
                          ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["admin_headers"]
    params = {"plan_year": plan_year} if plan_year is not None else None
    resp = api_client.get_drug_phase_ledger(
        beneficiary_id, headers, params,
    )
    return get_success_data(resp)


def get_drug_cost_estimate(beneficiary_id: str,
                           *, gross_cost_cents: int, tier: str,
                           headers: Optional[Dict[str, str]] = None
                           ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["admin_headers"]
    params = {"gross_cost_cents": gross_cost_cents, "tier": tier}
    resp = api_client.get_drug_cost_estimate(
        beneficiary_id, headers, params,
    )
    return get_success_data(resp)


# ===========================================================================
# Tier 2: Convenience setups that combine several Tier-1 calls
# ===========================================================================
def setup_clock_at(year: int, month: int, day: int) -> str:
    """Advance clock to the start of the given UTC day. Returns ISO."""
    iso = iso_instant_utc(year, month, day, 0, 0, 0)
    advance_clock_to(iso)
    return iso


def setup_iep_open_beneficiary(
    *,
    dob_iso: str = "1961-04-15",
    state_code: str = "CA",
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Create a beneficiary whose IEP window is OPEN at the current
    clock; advance the clock to the first day of the IEP window so
    the auto-transition fires (PRE_ELIGIBLE -> IEP_OPEN).

    Returns (beneficiary_after_iep_open, iep_period).

    PRD §3.1: medicare_eligibility_date = first_of_month(dob + 65
    years); iep_start_date = first_of_month(eligibility_date - 3
    months); iep_end_date = last_of_month(eligibility_date + 3 months)
    inclusive 23:59:59 UTC.
    """
    dob = date.fromisoformat(dob_iso)
    eligibility = first_of_month(add_months(dob, 65 * 12))
    iep_start = first_of_month(add_months(eligibility, -3))
    # Advance clock to the day after iep_start (which is always day 1
    # since iep_start = first_of_month(...)). Day 2 is safely inside
    # the IEP window for any month and triggers the auto-transition
    # PRE_ELIGIBLE -> IEP_OPEN.
    setup_clock_at(iep_start.year, iep_start.month, 2)
    beneficiary = create_beneficiary(
        date_of_birth=dob_iso, state_code=state_code,
    )
    # Re-read after auto-transition has fired.
    after = re_get_beneficiary(beneficiary["id"])
    iep_period = get_iep_period(beneficiary["id"])
    return after, iep_period


def setup_iep_open_beneficiary_with_fresh_clock(
    *,
    clock_iso: str,
    dob_iso: str = "1961-04-15",
    state_code: str = "CA",
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Caller advances the clock first via setup_clock_at, then this
    helper creates the beneficiary. PRD §3.2 auto-transitions IEP
    SCHEDULED -> OPEN if the new clock value crosses iep_start_date.

    Returns (beneficiary, iep_period_after).
    """
    advance_clock_to(clock_iso)
    beneficiary = create_beneficiary(
        date_of_birth=dob_iso, state_code=state_code,
    )
    after = re_get_beneficiary(beneficiary["id"])
    iep_period = get_iep_period(beneficiary["id"])
    return after, iep_period


def setup_active_part_b_enrollment(
    *,
    dob_iso: str = "1961-04-15",
    plan_year: int = 2026,
    monthly_premium_cents: int = 18_000,
    state_code: str = "CA",
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Reach an ACTIVE Part B enrollment during the IEP window.

    Returns (beneficiary, plan, enrollment_period, enrollment_active).
    """
    dob = date.fromisoformat(dob_iso)
    eligibility = first_of_month(add_months(dob, 65 * 12))
    iep_start = first_of_month(add_months(eligibility, -3))
    setup_clock_at(iep_start.year, iep_start.month, min(15, 28))
    beneficiary = create_beneficiary(
        date_of_birth=dob_iso, state_code=state_code,
    )
    beneficiary = re_get_beneficiary(beneficiary["id"])
    iep_period = get_iep_period(beneficiary["id"])
    plan = create_plan(
        plan_type="PART_B", plan_year=plan_year,
        monthly_premium_cents=monthly_premium_cents,
    )
    # effective_date inside IEP window — pick the eligibility month
    # first day.
    effective_date = iso_date(eligibility)
    pending = create_enrollment(
        beneficiary=beneficiary, plan=plan,
        enrollment_period=iep_period, effective_date=effective_date,
    )
    active = activate_enrollment(pending["id"])
    return beneficiary, plan, iep_period, active


def setup_active_part_d_enrollment(
    *,
    dob_iso: str = "1961-04-15",
    plan_year: int = 2026,
    monthly_premium_cents: int = 4_000,
    annual_deductible_cents: int = 40_000,
    initial_coverage_limit_cents: int = 400_000,
    catastrophic_threshold_cents: int = 150_000,
    state_code: str = "CA",
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Reach an ACTIVE Part D enrollment during the IEP window.

    On activation (PRD §3.4), a fresh DrugPhaseLedger is created with
    current_phase=DEDUCTIBLE and all four counters at zero.

    Returns (beneficiary, plan, iep_period, enrollment_active).
    """
    dob = date.fromisoformat(dob_iso)
    eligibility = first_of_month(add_months(dob, 65 * 12))
    iep_start = first_of_month(add_months(eligibility, -3))
    setup_clock_at(iep_start.year, iep_start.month, min(15, 28))
    beneficiary = create_beneficiary(
        date_of_birth=dob_iso, state_code=state_code,
    )
    beneficiary = re_get_beneficiary(beneficiary["id"])
    iep_period = get_iep_period(beneficiary["id"])
    plan = create_part_d_plan(
        plan_year=plan_year,
        monthly_premium_cents=monthly_premium_cents,
        annual_deductible_cents=annual_deductible_cents,
        initial_coverage_limit_cents=initial_coverage_limit_cents,
        catastrophic_threshold_cents=catastrophic_threshold_cents,
    )
    effective_date = iso_date(eligibility)
    pending = create_enrollment(
        beneficiary=beneficiary, plan=plan,
        enrollment_period=iep_period, effective_date=effective_date,
    )
    active = activate_enrollment(pending["id"])
    return beneficiary, plan, iep_period, active


def setup_pending_part_b_enrollment_via_aep(
    *,
    dob_iso: str = "1956-06-15",
    aep_start_iso: str = "2025-10-15T00:00:00.000Z",
    aep_end_iso: str = "2026-01-31T23:59:59.000Z",
    clock_inside_aep_iso: str = "2025-10-20T00:00:00.000Z",
    plan_year: int = 2026,
    monthly_premium_cents: int = 18_000,
    state_code: str = "CA",
    effective_date_iso: str = "2026-01-01",
) -> Tuple[Dict[str, Any], Dict[str, Any],
           Dict[str, Any], Dict[str, Any]]:
    """Build a PENDING Part B enrollment via an AEP period for a
    beneficiary whose IEP has long since closed (months_late > 0).

    Returns (beneficiary, plan, aep_period, enrollment_pending).
    """
    # Advance clock so beneficiary intake will compute past-eligibility.
    advance_clock_to(clock_inside_aep_iso)
    # First push past the IEP boundary by setting clock far in future
    # via above? PRD §3.2 auto-evaluates lifecycle at each clock advance.
    beneficiary = create_beneficiary(
        date_of_birth=dob_iso, state_code=state_code,
    )
    beneficiary = re_get_beneficiary(beneficiary["id"])
    aep_period = create_enrollment_period(
        beneficiary=beneficiary, period_type="AEP",
        window_start=aep_start_iso, window_end=aep_end_iso,
    )
    plan = create_plan(
        plan_type="PART_B", plan_year=plan_year,
        monthly_premium_cents=monthly_premium_cents,
    )
    pending = create_enrollment(
        beneficiary=beneficiary, plan=plan,
        enrollment_period=aep_period,
        effective_date=effective_date_iso,
    )
    return beneficiary, plan, aep_period, pending


def setup_medigap_applied(
    *,
    state_code: str = "CA",
    plan_premium_cents: int = 20_000,
    underwriting_uplift_decimal: Optional[float] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Create a Beneficiary + Medigap Plan + APPLIED policy.

    Returns (beneficiary, plan, policy).
    """
    # Place clock somewhere stable (IEP irrelevant for Medigap).
    setup_clock_at(2026, 6, 1)
    beneficiary = create_beneficiary(
        date_of_birth="1956-06-15", state_code=state_code,
    )
    plan = create_medigap_plan(
        state_code=state_code,
        monthly_premium_cents=plan_premium_cents,
    )
    policy = create_medigap_policy(
        beneficiary=beneficiary, plan=plan,
        underwriting_uplift_decimal=underwriting_uplift_decimal,
    )
    return beneficiary, plan, policy


def setup_medigap_with_open_gi_period(
    *,
    state_code: str = "CA",
    plan_premium_cents: int = 20_000,
    gi_window_start: str = "2026-05-01T00:00:00.000Z",
    gi_window_end: str = "2026-09-30T23:59:59.000Z",
    clock_iso: str = "2026-06-01T00:00:00.000Z",
) -> Tuple[Dict[str, Any], Dict[str, Any],
           Dict[str, Any], Dict[str, Any]]:
    """Reach (beneficiary, medigap_plan, OPEN MEDIGAP_GI period, APPLIED
    policy). The GI period covers the clock at applied_at.

    Returns (beneficiary, plan, gi_period, policy).
    """
    advance_clock_to(clock_iso)
    beneficiary = create_beneficiary(
        date_of_birth="1956-06-15", state_code=state_code,
    )
    plan = create_medigap_plan(
        state_code=state_code,
        monthly_premium_cents=plan_premium_cents,
    )
    gi_period = create_enrollment_period(
        beneficiary=beneficiary, period_type="MEDIGAP_GI",
        window_start=gi_window_start, window_end=gi_window_end,
    )
    policy = create_medigap_policy(
        beneficiary=beneficiary, plan=plan,
    )
    return beneficiary, plan, gi_period, policy


def setup_part_d_with_one_adjudicated_claim(
    *,
    dob_iso: str = "1961-04-15",
    plan_year: int = 2026,
    fill_date_iso: str = "2026-05-10",
    tier: str = "TIER_3",
    gross_cost_cents: int = 50_000,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any],
           Dict[str, Any], Dict[str, Any]]:
    """Reach an ACTIVE Part D enrollment with one ADJUDICATED claim.

    Plan: D=40000, I=400000, C=150000. Returns
    (beneficiary, plan, iep_period, enrollment_active, claim_adjudicated).
    """
    beneficiary, plan, iep, active = setup_active_part_d_enrollment(
        dob_iso=dob_iso, plan_year=plan_year,
        monthly_premium_cents=4_000,
        annual_deductible_cents=40_000,
        initial_coverage_limit_cents=400_000,
        catastrophic_threshold_cents=150_000,
    )
    claim = submit_drug_claim(
        beneficiary=beneficiary, enrollment=active, tier=tier,
        fill_date=fill_date_iso, gross_cost_cents=gross_cost_cents,
    )
    adjudicated = adjudicate_drug_claim(claim["id"])
    return beneficiary, plan, iep, active, adjudicated


def setup_part_d_with_empty_ledger(
    *,
    dob_iso: str = "1961-04-15",
    plan_year: int = 2026,
    annual_deductible_cents: int = 40_000,
    initial_coverage_limit_cents: int = 400_000,
    catastrophic_threshold_cents: int = 150_000,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Active Part D enrollment with an empty DrugPhaseLedger. Returns
    (beneficiary, plan, iep_period, enrollment_active).
    """
    return setup_active_part_d_enrollment(
        dob_iso=dob_iso, plan_year=plan_year,
        annual_deductible_cents=annual_deductible_cents,
        initial_coverage_limit_cents=initial_coverage_limit_cents,
        catastrophic_threshold_cents=catastrophic_threshold_cents,
    )


def setup_deceased_cascade_target(
) -> Dict[str, Any]:
    """Build a Beneficiary with one ACTIVE PART_C Enrollment, one
    ACTIVE PART_D Enrollment with an ADJUDICATED DrugClaim, and one
    ISSUED MedigapPolicy. Returns a dict with all rows for the
    depth-3 mark-deceased cascade test (instance
    deceased_triggers_depth3_cascade).
    """
    dob_iso = "1961-04-15"
    plan_year = 2026
    state_code = "CA"
    dob = date.fromisoformat(dob_iso)
    eligibility = first_of_month(add_months(dob, 65 * 12))
    iep_start = first_of_month(add_months(eligibility, -3))
    setup_clock_at(iep_start.year, iep_start.month, 15)
    beneficiary = create_beneficiary(
        date_of_birth=dob_iso, state_code=state_code,
    )
    beneficiary = re_get_beneficiary(beneficiary["id"])
    iep_period = get_iep_period(beneficiary["id"])

    # PART_C enrollment.
    part_c_plan = create_plan(
        plan_type="PART_C", plan_year=plan_year,
        monthly_premium_cents=12_000,
    )
    effective_iso = iso_date(eligibility)
    e_c_pending = create_enrollment(
        beneficiary=beneficiary, plan=part_c_plan,
        enrollment_period=iep_period, effective_date=effective_iso,
    )
    # Activation will consume the IEP period. Subsequent PART_D
    # enrollment will need a different period — create an SEP_MOVE
    # whose window covers the CURRENT clock day so its status is OPEN.
    e_c_active = activate_enrollment(e_c_pending["id"])

    # Build an SEP_MOVE period whose [window_start, window_end] is the
    # current month around the clock day (iep_start + 15 days). Per
    # PRD §3.2, the period auto-starts OPEN if the clock is inside the
    # window.
    sep_window_start = iso_day_start_utc(iep_start)
    sep_window_end_date = last_of_month(iep_start)
    sep_window_end = iso_day_end_utc(sep_window_end_date)
    sep_period = create_enrollment_period(
        beneficiary=beneficiary, period_type="SEP_MOVE",
        window_start=sep_window_start, window_end=sep_window_end,
    )
    # PART_D plan year must match year(effective_date). The SEP window
    # is in iep_start.year (the start of the IEP year).
    part_d_plan = create_part_d_plan(
        plan_year=iep_start.year,
        monthly_premium_cents=4_000,
        annual_deductible_cents=40_000,
        initial_coverage_limit_cents=400_000,
        catastrophic_threshold_cents=150_000,
    )
    # effective_date inside the SEP window AND in plan_year.
    partd_effective = iso_date(date(iep_start.year, iep_start.month, 20))
    e_d_pending = create_enrollment(
        beneficiary=beneficiary, plan=part_d_plan,
        enrollment_period=sep_period, effective_date=partd_effective,
    )
    e_d_active = activate_enrollment(e_d_pending["id"])

    # ADJUDICATED DrugClaim — fill_date must be on/after the PART_D
    # enrollment's effective_date and within the plan_year.
    claim_submitted = submit_drug_claim(
        beneficiary=beneficiary, enrollment=e_d_active,
        tier="TIER_3",
        fill_date=iso_date(date(iep_start.year, iep_start.month, 25)),
        gross_cost_cents=50_000,
    )
    claim_adjudicated = adjudicate_drug_claim(claim_submitted["id"])

    # MEDIGAP_GI period + ISSUED MedigapPolicy
    gi_period = create_enrollment_period(
        beneficiary=beneficiary, period_type="MEDIGAP_GI",
        window_start=sep_window_start, window_end=sep_window_end,
    )
    medigap_plan = create_medigap_plan(
        state_code=state_code, monthly_premium_cents=20_000,
    )
    medigap_policy = create_medigap_policy(
        beneficiary=beneficiary, plan=medigap_plan,
    )
    medigap_policy = evaluate_gi_medigap(medigap_policy["id"])
    medigap_policy = issue_medigap(medigap_policy["id"])

    return {
        "beneficiary": re_get_beneficiary(beneficiary["id"]),
        "iep_period": iep_period,
        "sep_period": sep_period,
        "part_c_plan": part_c_plan,
        "part_d_plan": part_d_plan,
        "medigap_plan": medigap_plan,
        "part_c_enrollment": re_get_enrollment(e_c_active["id"]),
        "part_d_enrollment": re_get_enrollment(e_d_active["id"]),
        "drug_claim": claim_adjudicated,
        "medigap_policy": re_get_medigap(medigap_policy["id"]),
    }


def setup_two_pending_enrollments_same_period(
    *,
    plan_type: str = "PART_B",
    plan_year: int = 2026,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any],
           Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Build two PENDING enrollments citing the SAME OPEN AEP period
    for the same beneficiary (different plans of the same type). Used
    by the period-consumption invariant test (instance
    enrollment_period_consumption_invariant).

    The AEP period stays OPEN (not consumed) until the first activate
    transition runs.

    Returns (beneficiary, plan_a, plan_b, aep_period, pending_a,
    pending_b).
    """
    advance_clock_to("2025-10-20T00:00:00.000Z")
    beneficiary = create_beneficiary(
        date_of_birth="1956-06-15", state_code="CA",
    )
    aep_period = create_enrollment_period(
        beneficiary=beneficiary, period_type="AEP",
        window_start="2025-10-15T00:00:00.000Z",
        window_end="2026-01-31T23:59:59.000Z",
    )
    plan_a = create_plan(
        plan_type=plan_type, plan_year=plan_year,
        monthly_premium_cents=18_000,
    )
    plan_b = create_plan(
        plan_type=plan_type, plan_year=plan_year,
        monthly_premium_cents=20_000,
    )
    pending_a = create_enrollment(
        beneficiary=beneficiary, plan=plan_a,
        enrollment_period=aep_period,
        effective_date="2026-01-01",
    )
    pending_b = create_enrollment(
        beneficiary=beneficiary, plan=plan_b,
        enrollment_period=aep_period,
        effective_date="2026-01-01",
    )
    return beneficiary, plan_a, plan_b, aep_period, pending_a, pending_b


__all__ = [
    # clock
    "advance_clock_to",
    "read_clock",
    "setup_clock_at",
    # beneficiary
    "create_beneficiary",
    "re_get_beneficiary",
    "mark_deceased",
    # plan
    "create_plan",
    "create_part_d_plan",
    "create_medigap_plan",
    "publish_star_rating",
    # period
    "create_enrollment_period",
    "list_enrollment_periods",
    "get_iep_period",
    # enrollment
    "create_enrollment",
    "activate_enrollment",
    "reject_enrollment",
    "terminate_enrollment",
    "transfer_enrollment",
    "re_get_enrollment",
    "get_cost_summary",
    # medigap
    "create_medigap_policy",
    "evaluate_gi_medigap",
    "begin_underwriting_medigap",
    "revise_medigap_application",
    "issue_medigap",
    "cancel_medigap",
    "deny_medigap",
    "re_get_medigap",
    # drug
    "submit_drug_claim",
    "adjudicate_drug_claim",
    "reverse_drug_claim",
    "re_get_drug_claim",
    "get_drug_phase_ledger",
    "get_drug_cost_estimate",
    # composite
    "setup_iep_open_beneficiary",
    "setup_iep_open_beneficiary_with_fresh_clock",
    "setup_active_part_b_enrollment",
    "setup_active_part_d_enrollment",
    "setup_pending_part_b_enrollment_via_aep",
    "setup_medigap_applied",
    "setup_medigap_with_open_gi_period",
    "setup_part_d_with_one_adjudicated_claim",
    "setup_part_d_with_empty_ledger",
    "setup_deceased_cascade_target",
    "setup_two_pending_enrollments_same_period",
]
