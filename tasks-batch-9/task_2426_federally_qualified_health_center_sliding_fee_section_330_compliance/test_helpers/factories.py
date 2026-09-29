"""Payload factories — one per resource, carrying client-supplied fields only.

Every factory takes `**overrides`, so a test can pin exactly the field it is
exercising and let the factory supply a valid value for everything else.
"""

import itertools

from .constants import TEST_DEFAULTS

_SEQ = itertools.count(1)


def next_sequence() -> int:
    """Monotonic counter for values the PRD requires to be unique."""
    return next(_SEQ)


# ---------------------------------------------------------------------------
# HealthCenter / PovertyGuideline
# ---------------------------------------------------------------------------


def create_health_center_payload(**overrides) -> dict:
    n = next_sequence()
    payload = {
        "legal_name": f"Riverbend Community Health {n}",
        "grant_number": f"H80CS{n:05d}",
        "pps_base_rate_cents": TEST_DEFAULTS["PPS_BASE_RATE_CENTS"],
        "medicare_upper_limit_cents": TEST_DEFAULTS["MEDICARE_UPPER_LIMIT_CENTS"],
        "nominal_fee_cap_cents": TEST_DEFAULTS["NOMINAL_FEE_CAP_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_poverty_guideline_payload(**overrides) -> dict:
    payload = {
        "guideline_year": TEST_DEFAULTS["FPG_YEAR"],
        "base_amount_cents": TEST_DEFAULTS["GUIDELINE_2026_BASE_CENTS"],
        "increment_cents": TEST_DEFAULTS["GUIDELINE_2026_INCREMENT_CENTS"],
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# BoardMember
# ---------------------------------------------------------------------------


def create_board_member_payload(**overrides) -> dict:
    payload = {
        "seat_number": 1,
        "seat_type": "NON_PATIENT",
        "expertise_category": "FINANCE",
        "term_start": "2026-01-01T00:00:00Z",
        "term_end": "2028-12-31T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_patient_seat_payload(patient_id: str, **overrides) -> dict:
    payload = {
        "seat_number": 2,
        "seat_type": "PATIENT",
        "patient_id": patient_id,
        "term_start": "2026-01-01T00:00:00Z",
        "term_end": "2028-12-31T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def resign_board_member_payload(**overrides) -> dict:
    payload = {"resignation_date": "2026-08-01T00:00:00Z"}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# ServiceSite / ServiceDefinition
# ---------------------------------------------------------------------------


def create_service_site_payload(**overrides) -> dict:
    payload = {
        "site_name": "Main Clinic",
        "site_type": "SERVICE_DELIVERY",
        "address_line": "12 River Rd",
        "weekly_service_hours": 40,
    }
    payload.update(overrides)
    return payload


def create_service_definition_payload(**overrides) -> dict:
    payload = {
        "service_code": "GEN_PRIMARY_CARE",
        "service_category": "REQUIRED_PRIMARY",
        "delivery_method": "COLUMN_I_DIRECT",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# ScopeChangeRequest
# ---------------------------------------------------------------------------


def create_scope_change_request_payload(**overrides) -> dict:
    payload = {
        "request_type": "ADD_SITE",
        "justification": "Expanding primary care access in the service area.",
    }
    payload.update(overrides)
    return payload


def decide_scope_change_request_payload(decision: str, **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# FeeSchedule / DiscountTier
# ---------------------------------------------------------------------------


def create_fee_schedule_payload(**overrides) -> dict:
    payload = {
        "fpg_year": TEST_DEFAULTS["FPG_YEAR"],
        "effective_start": TEST_DEFAULTS["EFFECTIVE_START"],
        "effective_end": TEST_DEFAULTS["EFFECTIVE_END"],
        "nominal_fee_cents": TEST_DEFAULTS["NOMINAL_FEE_CENTS"],
    }
    payload.update(overrides)
    return payload


def adopt_fee_schedule_payload(expected_health_center_version: int, **overrides) -> dict:
    payload = {"expected_health_center_version": expected_health_center_version}
    payload.update(overrides)
    return payload


def annual_review_payload(reviewed_against_guideline_year: int, **overrides) -> dict:
    payload = {"reviewed_against_guideline_year": reviewed_against_guideline_year}
    payload.update(overrides)
    return payload


def create_discount_tier_payload(**overrides) -> dict:
    payload = {
        "tier_label": "NOMINAL_FULL",
        "fpg_min_pct": 0,
        "fpg_max_pct": 100,
        "discount_kind": "NOMINAL",
        "sort_order": 1,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Patient / IncomeVerification
# ---------------------------------------------------------------------------


def create_patient_payload(**overrides) -> dict:
    n = next_sequence()
    payload = {
        "mrn": f"MRN-{n:04d}",
        "full_name": "Ada Rivera",
        "household_size": 2,
    }
    payload.update(overrides)
    return payload


def create_income_verification_payload(
    expected_patient_version: int, **overrides
) -> dict:
    payload = {
        "declared_annual_income_cents": 2190000,
        "household_size": 2,
        "documentation_type": "TAX_RETURN",
        "effective_date": "2026-02-01T00:00:00Z",
        "expected_patient_version": expected_patient_version,
    }
    payload.update(overrides)
    return payload


def verify_income_verification_payload(decision: str = "VERIFY", **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def resubmit_income_verification_payload(
    documentation_type: str = "PAY_STUBS", **overrides
) -> dict:
    payload = {"documentation_type": documentation_type}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Encounter and its actions
# ---------------------------------------------------------------------------


def create_encounter_payload(
    patient_id: str, service_site_id: str, service_definition_id: str, **overrides
) -> dict:
    payload = {
        "patient_id": patient_id,
        "service_site_id": service_site_id,
        "service_definition_id": service_definition_id,
        "encounter_date": "2026-03-01T00:00:00Z",
        "payer_type": "SELF_PAY",
        "gross_charge_cents": 12000,
    }
    payload.update(overrides)
    return payload


def bill_encounter_payload(claim_reference: str = "CLM-0001", **overrides) -> dict:
    payload = {"claim_reference": claim_reference}
    payload.update(overrides)
    return payload


def record_payment_payload(mco_paid_cents: int, **overrides) -> dict:
    payload = {"mco_paid_cents": mco_paid_cents}
    payload.update(overrides)
    return payload


def claim_wraparound_payload(**overrides) -> dict:
    payload: dict = {}
    payload.update(overrides)
    return payload


def void_encounter_payload(void_reason: str = "CODING_ERROR", **overrides) -> dict:
    payload = {"void_reason": void_reason}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# InabilityToPayWaiver
# ---------------------------------------------------------------------------


def create_waiver_payload(waiver_reason: str = "NO_INCOME", **overrides) -> dict:
    payload = {"waiver_reason": waiver_reason}
    payload.update(overrides)
    return payload


def decide_waiver_payload(decision: str, **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# UDSReport / QualityMeasureResult
# ---------------------------------------------------------------------------


def create_uds_report_payload(**overrides) -> dict:
    payload = {"reporting_year": 2026}
    payload.update(overrides)
    return payload


def create_quality_measure_result_payload(**overrides) -> dict:
    payload = {
        "measure_code": "DIABETES_A1C",
        "numerator": 7,
        "denominator": 9,
        "benchmark_pct": 77.8,
    }
    payload.update(overrides)
    return payload


def adjudicate_uds_report_payload(decision: str, **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# SiteVisitFinding / CorrectiveActionPlan
# ---------------------------------------------------------------------------


def create_site_visit_finding_payload(**overrides) -> dict:
    payload = {
        "requirement_code": "REQ_SLIDING_FEE_16",
        "severity": "CONDITION",
        "finding_summary": "Sliding fee discount schedule not applied consistently.",
        "cap_due_days": 30,
    }
    payload.update(overrides)
    return payload


def create_corrective_action_plan_payload(**overrides) -> dict:
    payload = {
        "narrative": "Retrain front desk staff and re-audit the discount ladder.",
        "milestone_count": 3,
        "target_completion_date": "2026-08-15T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def adjudicate_corrective_action_plan_payload(decision: str, **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------


def set_clock_payload(current_utc: str) -> dict:
    return {"current_utc": current_utc}
