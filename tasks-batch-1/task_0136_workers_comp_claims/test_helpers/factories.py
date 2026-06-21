"""Payload factories — one per entity, input fields only.

Field names match the PRD's request bodies exactly.
"""

DEFAULTS = {
    "EMPLOYER_NAME": "Test Employer",
    "STATE_CODE": "CA",
    "POLICY_NUMBER": "P-TEST",
    "MANUAL_PREMIUM_CENTS": 5_000_000,
    "EFFECTIVE_DATE": "2026-01-01T00:00:00Z",
    "EXPIRATION_DATE": "2027-01-01T00:00:00Z",
    "WORKER_NAME": "Worker A",
    "GROSS_WAGES_CENTS": 7_800_000,   # /52 -> AWW 150000
    "WEEKS_WORKED": 52,
    "DATE_OF_INJURY": "2026-02-01T00:00:00Z",
    "AWW_CENTS": 150_000,
    "EXAMINER_NAME": "Dr Example",
}


def create_employer_payload(**overrides) -> dict:
    payload = {
        "legal_name": DEFAULTS["EMPLOYER_NAME"],
        "state_code": DEFAULTS["STATE_CODE"],
    }
    payload.update(overrides)
    return payload


def create_policy_payload(employer_id, **overrides) -> dict:
    payload = {
        "employer_id": employer_id,
        "policy_number": DEFAULTS["POLICY_NUMBER"],
        "manual_premium_cents": DEFAULTS["MANUAL_PREMIUM_CENTS"],
        "effective_date": DEFAULTS["EFFECTIVE_DATE"],
        "expiration_date": DEFAULTS["EXPIRATION_DATE"],
    }
    payload.update(overrides)
    return payload


def create_worker_payload(employer_id, **overrides) -> dict:
    payload = {
        "employer_id": employer_id,
        "full_name": DEFAULTS["WORKER_NAME"],
        "gross_wages_cents": DEFAULTS["GROSS_WAGES_CENTS"],
        "weeks_worked": DEFAULTS["WEEKS_WORKED"],
    }
    payload.update(overrides)
    return payload


def create_claim_payload(policy_id, worker_id, **overrides) -> dict:
    payload = {
        "policy_id": policy_id,
        "worker_id": worker_id,
        "date_of_injury": DEFAULTS["DATE_OF_INJURY"],
    }
    payload.update(overrides)
    return payload


def create_injury_report_payload(claim_id, report_kind="FROI", maintenance_type_code="00", **overrides) -> dict:
    payload = {
        "claim_id": claim_id,
        "report_kind": report_kind,
        "maintenance_type_code": maintenance_type_code,
    }
    payload.update(overrides)
    return payload


def create_wage_statement_payload(claim_id, expected_claim_version, average_weekly_wage_cents=None, **overrides) -> dict:
    payload = {
        "claim_id": claim_id,
        "average_weekly_wage_cents": average_weekly_wage_cents
        if average_weekly_wage_cents is not None
        else DEFAULTS["AWW_CENTS"],
        "expected_claim_version": expected_claim_version,
    }
    payload.update(overrides)
    return payload


def create_reserve_payload(claim_id, severity_tier="MODERATE", projected_weeks=12, **overrides) -> dict:
    payload = {
        "claim_id": claim_id,
        "severity_tier": severity_tier,
        "projected_weeks": projected_weeks,
    }
    payload.update(overrides)
    return payload


def create_benefit_payment_payload(claim_id, benefit_type, **overrides) -> dict:
    payload = {
        "claim_id": claim_id,
        "benefit_type": benefit_type,
    }
    payload.update(overrides)
    return payload


def create_impairment_rating_payload(claim_id, whole_body_pct, rater_role, **overrides) -> dict:
    payload = {
        "claim_id": claim_id,
        "whole_body_pct": whole_body_pct,
        "rater_role": rater_role,
    }
    payload.update(overrides)
    return payload


def create_rtw_offer_payload(claim_id, light_duty_weekly_cents, start_date, end_date, **overrides) -> dict:
    payload = {
        "claim_id": claim_id,
        "light_duty_weekly_cents": light_duty_weekly_cents,
        "start_date": start_date,
        "end_date": end_date,
    }
    payload.update(overrides)
    return payload


def create_ime_order_payload(claim_id, scheduled_start, scheduled_end, examiner_name=None, **overrides) -> dict:
    payload = {
        "claim_id": claim_id,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "examiner_name": examiner_name if examiner_name is not None else DEFAULTS["EXAMINER_NAME"],
    }
    payload.update(overrides)
    return payload


def create_experience_mod_payload(employer_id, rating_year, weighting_factor, ballast_cents,
                                  expected_primary_cents, expected_excess_cents, **overrides) -> dict:
    payload = {
        "employer_id": employer_id,
        "rating_year": rating_year,
        "weighting_factor": weighting_factor,
        "ballast_cents": ballast_cents,
        "expected_primary_cents": expected_primary_cents,
        "expected_excess_cents": expected_excess_cents,
    }
    payload.update(overrides)
    return payload


def create_medical_payment_payload(amount_cents, **overrides) -> dict:
    payload = {"amount_cents": amount_cents}
    payload.update(overrides)
    return payload
