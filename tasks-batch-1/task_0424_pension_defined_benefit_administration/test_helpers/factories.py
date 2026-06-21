"""Payload factories — one per entity, input fields only.

Field names mirror the PRD exactly. EIN/SSN values are randomized so each
test's create calls never collide with another test under the global ein_psn
uniqueness rule.
"""
import random


def _rand_ein() -> str:
    """Globally-unique-ish ein_psn: '<2 digits>-<7 digits>-<3 digits>'."""
    return f"{random.randint(10, 99)}-{random.randint(1000000, 9999999)}-{random.randint(100, 999)}"


def _rand_ssn4() -> str:
    return f"{random.randint(1000, 9999)}"


def create_plan_payload(**overrides) -> dict:
    """POST /plans. benefit_formula_type is required; rate fields are variant-specific."""
    defaults = {
        "plan_name": "Test Pension Plan",
        "ein_psn": _rand_ein(),
        "benefit_formula_type": "FINAL_AVERAGE_PAY",
        "normal_retirement_age": 65,
        "cola_pct": 0.0,
        "fap_accrual_rate": 0.015,
        "cb_pay_credit_rate": 0.0,
        "cb_interest_crediting_rate": 0.0,
    }
    defaults.update(overrides)
    return defaults


def create_participant_payload(plan_id, **overrides) -> dict:
    """POST /plans/participants."""
    defaults = {
        "plan_id": plan_id,
        "ssn_last4": _rand_ssn4(),
        "date_of_birth": "1962-01-01",
        "hire_date": "2000-01-01",
    }
    defaults.update(overrides)
    return defaults


def create_compensation_payload(participant_id, plan_year, gross_comp_cents, **overrides) -> dict:
    """POST /plans/compensation."""
    defaults = {
        "participant_id": participant_id,
        "plan_year": plan_year,
        "gross_comp_cents": gross_comp_cents,
    }
    defaults.update(overrides)
    return defaults


def create_service_adjustment_payload(participant_id, adjustment_kind, delta_service_years, **overrides) -> dict:
    """POST /plans/service-adjustments."""
    defaults = {
        "participant_id": participant_id,
        "adjustment_kind": adjustment_kind,
        "delta_service_years": delta_service_years,
    }
    defaults.update(overrides)
    return defaults


def create_filing_payload(plan_id, plan_year, plan_assets_cents, funding_target_cents, **overrides) -> dict:
    """POST /plans/filings."""
    defaults = {
        "plan_id": plan_id,
        "plan_year": plan_year,
        "plan_assets_cents": plan_assets_cents,
        "funding_target_cents": funding_target_cents,
    }
    defaults.update(overrides)
    return defaults


def create_premium_payload(plan_id, premium_year, participant_count, unfunded_vested_benefits_cents, **overrides) -> dict:
    """POST /plans/premiums."""
    defaults = {
        "plan_id": plan_id,
        "premium_year": premium_year,
        "participant_count": participant_count,
        "unfunded_vested_benefits_cents": unfunded_vested_benefits_cents,
    }
    defaults.update(overrides)
    return defaults


def create_election_payload(participant_id, payment_form, annuity_start_date, **overrides) -> dict:
    """POST /plans/elections. js_survivor_pct & spouse_date_of_birth required only for J&S."""
    defaults = {
        "participant_id": participant_id,
        "payment_form": payment_form,
        "annuity_start_date": annuity_start_date,
    }
    defaults.update(overrides)
    return defaults


def create_qdro_payload(participant_id, alternate_payee_kind, split_method, **overrides) -> dict:
    """POST /plans/qdros. award_pct for PERCENTAGE, award_fixed_monthly_cents for SHARED_INTEREST."""
    defaults = {
        "participant_id": participant_id,
        "alternate_payee_kind": alternate_payee_kind,
        "split_method": split_method,
    }
    defaults.update(overrides)
    return defaults


def create_spousal_consent_payload(consenting_spouse_dob, notary_reference, waives_qjsa, **overrides) -> dict:
    """POST /plans/elections/{id}/spousal-consent."""
    defaults = {
        "consenting_spouse_dob": consenting_spouse_dob,
        "notary_reference": notary_reference,
        "waives_qjsa": waives_qjsa,
    }
    defaults.update(overrides)
    return defaults


def certify_payload(expected_plan_version, **overrides) -> dict:
    """POST /plans/filings/{id}/certify."""
    defaults = {"expected_plan_version": expected_plan_version}
    defaults.update(overrides)
    return defaults
