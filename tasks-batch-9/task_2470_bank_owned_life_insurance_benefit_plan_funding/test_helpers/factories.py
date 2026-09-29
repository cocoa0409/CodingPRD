"""Payload factories — one per entity, client-supplied input fields only."""
from .constants import TEST_DEFAULTS


def capital_position_payload(**overrides) -> dict:
    payload = {
        "as_of_date": TEST_DEFAULTS["CAPITAL_AS_OF_DATE"],
        "tier1_capital_usd": TEST_DEFAULTS["TIER1_CAPITAL_USD"],
        "total_assets_usd": TEST_DEFAULTS["TOTAL_ASSETS_USD"],
    }
    payload.update(overrides)
    return payload


def carrier_payload(**overrides) -> dict:
    payload = {
        "legal_name": "Northbridge Life Assurance",
        "naic_code": "61111",
        "am_best_rating": TEST_DEFAULTS["AM_BEST_RATING"],
        "statutory_surplus_usd": TEST_DEFAULTS["STATUTORY_SURPLUS_USD"],
        "domicile_state": "NY",
    }
    payload.update(overrides)
    return payload


def product_type_payload(carrier_id: str, **overrides) -> dict:
    payload = {
        "carrier_id": carrier_id,
        "product_name": "General Account BOLI",
        "account_type": "GENERAL",
        "mec_status": "NON_MEC",
        "disclosed_me_charge_bps": TEST_DEFAULTS["DISCLOSED_ME_CHARGE_BPS"],
        "guaranteed_min_crediting_bps": TEST_DEFAULTS["GUARANTEED_MIN_CREDITING_BPS"],
    }
    payload.update(overrides)
    return payload


def diligence_review_payload(carrier_id: str, **overrides) -> dict:
    payload = {"carrier_id": carrier_id, "review_year": TEST_DEFAULTS["REVIEW_YEAR"]}
    payload.update(overrides)
    return payload


def employee_payload(**overrides) -> dict:
    payload = {
        "full_name": "Dana Reyes",
        "employee_number": "E-1001",
        "annual_salary_usd": 2_000_000.00,
        "officer_flag": True,
    }
    payload.update(overrides)
    return payload


def consent_record_payload(employee_id: str, **overrides) -> dict:
    payload = {
        "employee_id": employee_id,
        "coverage_start_date": TEST_DEFAULTS["COVERAGE_START_DATE"],
        "coverage_end_date": TEST_DEFAULTS["COVERAGE_END_DATE"],
        "consent_form_reference": "CF-1001",
        "notice_and_consent_version": TEST_DEFAULTS["NOTICE_AND_CONSENT_VERSION"],
    }
    payload.update(overrides)
    return payload


def purchase_request_payload(
    carrier_id: str, product_type_id: str, employee_id: str, **overrides
) -> dict:
    payload = {
        "carrier_id": carrier_id,
        "product_type_id": product_type_id,
        "employee_id": employee_id,
        "single_premium_usd": 1_000_000.00,
        "face_amount_usd": 5_000_000.00,
        "requested_effective_date": TEST_DEFAULTS["REQUESTED_EFFECTIVE_DATE"],
    }
    payload.update(overrides)
    return payload


def policy_payload(purchase_request_id: str, **overrides) -> dict:
    payload = {
        "purchase_request_id": purchase_request_id,
        "policy_number": "PN-0001",
        "issue_date": TEST_DEFAULTS["ISSUE_DATE"],
    }
    payload.update(overrides)
    return payload


def policy_valuation_payload(policy_id: str, **overrides) -> dict:
    payload = {
        "policy_id": policy_id,
        "period_start_date": "2026-08-15T00:00:00Z",
        "as_of_date": "2026-09-30T00:00:00Z",
        "credited_interest_usd": 20_000.00,
        "mortality_expense_charge_usd": 2_000.00,
        "gross_crediting_rate_bps": 200,
    }
    payload.update(overrides)
    return payload


def nqdc_plan_payload(**overrides) -> dict:
    payload = {
        "plan_name": "Executive SERP 2026",
        "plan_type": "SERP",
        "discount_rate_bps": 500,
    }
    payload.update(overrides)
    return payload


def nqdc_liability_payload(nqdc_plan_id: str, employee_id: str, **overrides) -> dict:
    payload = {
        "nqdc_plan_id": nqdc_plan_id,
        "employee_id": employee_id,
        "accrued_to_date_usd": 600_000.00,
        "projected_benefit_usd": 2_000_000.00,
        "years_to_payout": 10,
    }
    payload.update(overrides)
    return payload


def death_claim_payload(policy_id: str, **overrides) -> dict:
    payload = {
        "policy_id": policy_id,
        "date_of_death": "2026-11-10T00:00:00Z",
        "terminal_dividend_usd": 0.00,
        "proof_reference": "DC-0001",
    }
    payload.update(overrides)
    return payload


def beneficiary_allocation_payload(claim_id: str, **overrides) -> dict:
    payload = {
        "claim_id": claim_id,
        "beneficiary_name": "Family Beneficiary",
        "relationship": "SPOUSE",
        "allocation_pct_bps": 10000,
    }
    payload.update(overrides)
    return payload


def exchange_analysis_payload(
    policy_id: str, expected_policy_version: int, **overrides
) -> dict:
    payload = {
        "policy_id": policy_id,
        "disposition_type": "FULL_SURRENDER",
        "expected_policy_version": expected_policy_version,
    }
    payload.update(overrides)
    return payload


def risk_assessment_payload(capital_position_id: str, **overrides) -> dict:
    payload = {"capital_position_id": capital_position_id, "assessment_year": 2026}
    payload.update(overrides)
    return payload
