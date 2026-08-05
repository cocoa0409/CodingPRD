"""Payload factories - one per write endpoint, input fields only."""

from .constants import TEST_DEFAULTS


def create_employer_payload(**overrides):
    payload = {
        "legal_name": "Northwind Manufacturing",
        "employer_code": "NWM",
        "annual_total_cost_of_coverage_cents": TEST_DEFAULTS[
            "ANNUAL_TOTAL_COST_OF_COVERAGE_CENTS"
        ],
        "wellness_budget_cents": TEST_DEFAULTS["WELLNESS_BUDGET_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_site_payload(**overrides):
    payload = {
        "site_name": "Northwind On-Site Clinic",
        "site_type": "ON_SITE",
        "open_time_utc": TEST_DEFAULTS["OPEN_TIME_UTC"],
        "close_time_utc": TEST_DEFAULTS["CLOSE_TIME_UTC"],
        "operating_weekdays": list(TEST_DEFAULTS["OPERATING_WEEKDAYS"]),
        "daily_slot_capacity": TEST_DEFAULTS["DAILY_SLOT_CAPACITY"],
    }
    payload.update(overrides)
    return payload


def create_vendor_contract_payload(site_id, employer_id, **overrides):
    payload = {
        "site_id": site_id,
        "employer_id": employer_id,
        "vendor_name": "CareOnSite LLC",
        "fee_model": "PER_VISIT",
        "per_visit_fee_cents": TEST_DEFAULTS["PER_VISIT_FEE_CENTS"],
        "fte_hourly_rate_cents": TEST_DEFAULTS["FTE_HOURLY_RATE_CENTS"],
        "minimum_guarantee_cents": TEST_DEFAULTS["MINIMUM_GUARANTEE_CENTS"],
        "quota_visits_total": TEST_DEFAULTS["QUOTA_VISITS_TOTAL"],
    }
    payload.update(overrides)
    return payload


def create_provider_payload(site_id, **overrides):
    payload = {
        "site_id": site_id,
        "full_name": "Dr Rivera",
        "provider_function": "CLINICIAN",
        "license_expiry_date": TEST_DEFAULTS["LICENSE_EXPIRY_DATE"],
    }
    payload.update(overrides)
    return payload


def create_staffing_shift_payload(site_id, provider_id, **overrides):
    payload = {
        "site_id": site_id,
        "provider_id": provider_id,
        "shift_start": TEST_DEFAULTS["SHIFT_START"],
        "shift_end": TEST_DEFAULTS["SHIFT_END"],
        "coverage_role": "PRIMARY_CARE",
    }
    payload.update(overrides)
    return payload


def create_eligibility_record_payload(employer_id, **overrides):
    payload = {
        "employer_id": employer_id,
        "subscriber_external_id": "S-1001",
        "member_external_id": "M-1001",
        "tier": "EMPLOYEE",
        "effective_date": "2026-01-01",
    }
    payload.update(overrides)
    return payload


def create_participant_payload(employer_id, eligibility_record_id, **overrides):
    payload = {
        "employer_id": employer_id,
        "eligibility_record_id": eligibility_record_id,
        "display_name": "Ana Silva",
    }
    payload.update(overrides)
    return payload


def create_appointment_payload(
    participant_id, site_id, provider_id, scheduled_start, expected_site_version, **overrides
):
    payload = {
        "participant_id": participant_id,
        "site_id": site_id,
        "provider_id": provider_id,
        "visit_type": "PRIMARY_CARE",
        "scheduled_start": scheduled_start,
        "expected_site_version": expected_site_version,
    }
    payload.update(overrides)
    return payload


def create_health_assessment_payload(participant_id, **overrides):
    """Defaults to a clinic-measured row carrying all six numeric metrics."""
    payload = {
        "participant_id": participant_id,
        "source_type": "CLINIC_MEASURED",
        "measurement_date": TEST_DEFAULTS["SERVICE_DAY"],
        "systolic_mmhg": 118,
        "diastolic_mmhg": 76,
        "bmi": 24.9,
        "a1c_pct": 5.4,
        "ldl_mg_dl": 99,
        "cotinine_ng_ml": 1.0,
    }
    payload.update(overrides)
    return payload


def self_attested_assessment_payload(participant_id, **overrides):
    payload = {
        "participant_id": participant_id,
        "source_type": "SELF_ATTESTED",
        "measurement_date": TEST_DEFAULTS["SERVICE_DAY"],
        "bmi": 24.0,
        "self_reported_tobacco": False,
    }
    payload.update(overrides)
    return payload


def create_referral_payload(participant_id, visit_id, **overrides):
    payload = {
        "participant_id": participant_id,
        "visit_id": visit_id,
        "specialty": "ORTHOPEDICS",
        "steerage_tier": "STANDARD",
        "urgency": "ROUTINE",
    }
    payload.update(overrides)
    return payload


def redirect_referral_payload(**overrides):
    payload = {
        "specialty": "ORTHOPEDICS",
        "steerage_tier": "PREFERRED",
        "urgency": "ROUTINE",
    }
    payload.update(overrides)
    return payload


def create_alternative_standard_payload(participant_id, health_assessment_id, **overrides):
    payload = {
        "participant_id": participant_id,
        "health_assessment_id": health_assessment_id,
        "requested_reason": "Outcome standard is medically inadvisable",
    }
    payload.update(overrides)
    return payload


def create_incentive_award_payload(
    participant_id, reporting_period_id, expected_participant_version, **overrides
):
    payload = {
        "participant_id": participant_id,
        "reporting_period_id": reporting_period_id,
        "award_type": "PARTICIPATORY",
        "expected_participant_version": expected_participant_version,
    }
    payload.update(overrides)
    return payload


def create_reporting_period_payload(employer_id, **overrides):
    payload = {
        "employer_id": employer_id,
        "period_start": "2026-06-01",
        "period_end": "2026-06-30",
    }
    payload.update(overrides)
    return payload


# --- Metric bundles used by the health-risk scoring tests -------------------
def clinic_metrics(systolic, diastolic, bmi, a1c, ldl, cotinine):
    """The six mandatory CLINIC_MEASURED metrics as a payload fragment."""
    return {
        "systolic_mmhg": systolic,
        "diastolic_mmhg": diastolic,
        "bmi": bmi,
        "a1c_pct": a1c,
        "ldl_mg_dl": ldl,
        "cotinine_ng_ml": cotinine,
    }


HIGH_RISK_CLINIC_METRICS = clinic_metrics(145, 92, 36.0, 6.6, 165, 12.0)
BORDERLINE_CLINIC_METRICS = clinic_metrics(132, 78, 27.4, 5.7, 118, 2.0)
ZERO_BAND_CLINIC_METRICS = clinic_metrics(118, 76, 24.9, 5.4, 99, 1.0)
