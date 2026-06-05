"""Payload factories — one per create endpoint, input fields only."""

DEFAULTS = {
    "FULL_NAME": "Test Beneficiary",
    "DOB": "2024-08-15T00:00:00.000Z",
    "PLAN_NAME": "Test Plan",
    "PREMIUM_CENTS": 2000,
    "STAR_RATING": 3.0,
}


def create_beneficiary_payload(**overrides) -> dict:
    """POST /beneficiaries. part_d_creditable_since is optional and omitted by default."""
    defaults = {
        "full_name": DEFAULTS["FULL_NAME"],
        "date_of_birth": DEFAULTS["DOB"],
    }
    defaults.update(overrides)
    return defaults


def create_plan_payload(**overrides) -> dict:
    """POST /plans."""
    defaults = {
        "name": DEFAULTS["PLAN_NAME"],
        "part_type": "PART_C",
        "monthly_premium_cents": DEFAULTS["PREMIUM_CENTS"],
        "star_rating": DEFAULTS["STAR_RATING"],
        "includes_drug_coverage": False,
    }
    defaults.update(overrides)
    return defaults


def create_enrollment_period_payload(period_type, **overrides) -> dict:
    """POST /beneficiaries/{id}/enrollment-periods.
    Pass aep_year for AEP/SEP_5STAR; source_event_date for GI_MEDIGAP."""
    defaults = {"period_type": period_type}
    defaults.update(overrides)
    return defaults


def create_part_b_enrollment_payload(beneficiary_id, enrollment_period_id, **overrides) -> dict:
    defaults = {
        "beneficiary_id": beneficiary_id,
        "enrollment_period_id": enrollment_period_id,
    }
    defaults.update(overrides)
    return defaults


def create_part_c_enrollment_payload(beneficiary_id, plan_id, enrollment_period_id, **overrides) -> dict:
    defaults = {
        "beneficiary_id": beneficiary_id,
        "plan_id": plan_id,
        "enrollment_period_id": enrollment_period_id,
    }
    defaults.update(overrides)
    return defaults


def confirm_part_c_payload(expected_beneficiary_version, **overrides) -> dict:
    """POST /part-c-enrollments/{id}/confirm — expected_beneficiary_version is required."""
    defaults = {"expected_beneficiary_version": expected_beneficiary_version}
    defaults.update(overrides)
    return defaults


def create_part_d_enrollment_payload(beneficiary_id, plan_id, enrollment_period_id, **overrides) -> dict:
    defaults = {
        "beneficiary_id": beneficiary_id,
        "plan_id": plan_id,
        "enrollment_period_id": enrollment_period_id,
    }
    defaults.update(overrides)
    return defaults


def create_drug_claim_payload(list_price_cents, incurred_at, **overrides) -> dict:
    defaults = {
        "list_price_cents": list_price_cents,
        "incurred_at": incurred_at,
    }
    defaults.update(overrides)
    return defaults


def create_medigap_policy_payload(beneficiary_id, enrollment_period_id,
                                  coverage_start, coverage_end, **overrides) -> dict:
    defaults = {
        "beneficiary_id": beneficiary_id,
        "enrollment_period_id": enrollment_period_id,
        "coverage_start": coverage_start,
        "coverage_end": coverage_end,
    }
    defaults.update(overrides)
    return defaults


def create_penalty_assessment_payload(beneficiary_id, penalty_type, uncovered_months, **overrides) -> dict:
    defaults = {
        "beneficiary_id": beneficiary_id,
        "penalty_type": penalty_type,
        "uncovered_months": uncovered_months,
    }
    defaults.update(overrides)
    return defaults
