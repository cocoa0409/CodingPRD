"""Payload factories — one per write endpoint body, input fields only."""

import itertools

from .constants import TEST_DEFAULTS

_EIN_COUNTER = itertools.count(1)


def next_ein() -> str:
    """A fresh nine-digit employer identification number.

    Registration numbers are unique across institutions, so every institution
    created inside one test needs its own.
    """
    return "9{:08d}".format(next(_EIN_COUNTER))


def institution_payload(**overrides) -> dict:
    payload = {
        "legal_name": "Delta Community Capital Fund",
        "ein": next_ein(),
        "entity_type": "LOAN_FUND",
        "primary_mission_statement": TEST_DEFAULTS["MISSION_STATEMENT"],
        "asset_size_cents": TEST_DEFAULTS["ASSET_SIZE_CENTS"],
        "reserve_method": "MIGRATION_ANALYSIS",
        "loss_reserve_balance_cents": 0,
    }
    payload.update(overrides)
    return payload


def target_market_payload(**overrides) -> dict:
    payload = {
        "market_type": "INVESTMENT_AREA",
        "name": "South Bronx Investment Area",
        "census_tract_codes": [TEST_DEFAULTS["CENSUS_TRACT"]],
    }
    payload.update(overrides)
    return payload


def low_income_market_payload(**overrides) -> dict:
    payload = {
        "market_type": "LOW_INCOME_TARGETED_POPULATION",
        "name": "Households at or below 80 percent AMI",
        "ami_threshold_pct": 80.00,
    }
    payload.update(overrides)
    return payload


def other_population_market_payload(**overrides) -> dict:
    payload = {
        "market_type": "OTHER_TARGETED_POPULATION",
        "name": "Credit invisible households",
    }
    payload.update(overrides)
    return payload


def board_seat_payload(**overrides) -> dict:
    payload = {
        "structure": "GOVERNING_BOARD",
        "holder_name": "R. Alvarez",
        "represents_target_market": False,
    }
    payload.update(overrides)
    return payload


def certification_application_payload(expected_institution_version, **overrides) -> dict:
    payload = {
        "expected_institution_version": expected_institution_version,
        "primary_mission_statement": TEST_DEFAULTS["MISSION_STATEMENT"],
        "financing_activity_pct_claimed": 72.50,
        "development_services_description": TEST_DEFAULTS["DEVELOPMENT_SERVICES"],
    }
    payload.update(overrides)
    return payload


def evaluate_test_payload(test_code, verdict="PASSED", **overrides) -> dict:
    payload = {"test_code": test_code, "verdict": verdict}
    payload.update(overrides)
    return payload


def borrower_payload(**overrides) -> dict:
    payload = {
        "full_name": "Maria Ortiz",
        "street_address": TEST_DEFAULTS["STREET_ADDRESS"],
        "postal_code": TEST_DEFAULTS["POSTAL_CODE"],
        "household_income_cents": 4_200_000,
        "area_median_income_cents": 7_000_000,
        "credit_score": 740,
    }
    payload.update(overrides)
    return payload


def geocode_payload(outcome="MATCHED", **overrides) -> dict:
    payload = {"outcome": outcome}
    if outcome == "MATCHED":
        payload["census_tract_code"] = TEST_DEFAULTS["CENSUS_TRACT"]
    payload.update(overrides)
    return payload


def loan_product_payload(**overrides) -> dict:
    payload = {
        "name": "Flexible Small Business Loan",
        "base_rate_bps": TEST_DEFAULTS["BASE_RATE_BPS"],
        "term_months": TEST_DEFAULTS["TERM_MONTHS"],
        "max_dti_pct": 50.00,
        "min_credit_score": 580,
        "allow_no_credit_score": True,
        "credit_building_features": ["REPORTS_TO_BUREAUS"],
        "requires_ta_completion": False,
        "product_cap_cents": TEST_DEFAULTS["PRODUCT_CAP_CENTS"],
    }
    payload.update(overrides)
    return payload


def loan_payload(institution_id, borrower_id, product_id,
                 requested_principal_cents=1_000_000, **overrides) -> dict:
    payload = {
        "institution_id": institution_id,
        "borrower_id": borrower_id,
        "product_id": product_id,
        "requested_principal_cents": requested_principal_cents,
    }
    payload.update(overrides)
    return payload


def underwrite_payload(verified_monthly_income_cents=1_000_000,
                       existing_monthly_debt_cents=100_000,
                       credit_score_at_underwriting=740, **overrides) -> dict:
    payload = {
        "verified_monthly_income_cents": verified_monthly_income_cents,
        "existing_monthly_debt_cents": existing_monthly_debt_cents,
    }
    if credit_score_at_underwriting is not None:
        payload["credit_score_at_underwriting"] = credit_score_at_underwriting
    payload.update(overrides)
    return payload


def loan_decision_payload(decision="APPROVE", **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def ta_engagement_payload(borrower_id, scheduled_start_at, scheduled_end_at,
                          planned_hours, topic="CREDIT_BUILDING", **overrides) -> dict:
    payload = {
        "borrower_id": borrower_id,
        "topic": topic,
        "scheduled_start_at": scheduled_start_at,
        "scheduled_end_at": scheduled_end_at,
        "planned_hours": planned_hours,
    }
    payload.update(overrides)
    return payload


def ta_close_payload(outcome="COMPLETED", actual_hours=None,
                     competency_verified=None, **overrides) -> dict:
    payload = {"outcome": outcome}
    if actual_hours is not None:
        payload["actual_hours"] = actual_hours
    if competency_verified is not None:
        payload["competency_verified"] = competency_verified
    payload.update(overrides)
    return payload


def impact_report_payload(expected_loan_version, reporting_period_end,
                          jobs_created=0, jobs_retained=0, housing_units=0,
                          businesses_financed=0, **overrides) -> dict:
    payload = {
        "expected_loan_version": expected_loan_version,
        "reporting_period_end": reporting_period_end,
        "jobs_created": jobs_created,
        "jobs_retained": jobs_retained,
        "housing_units": housing_units,
        "businesses_financed": businesses_financed,
    }
    payload.update(overrides)
    return payload


def impact_resubmit_payload(jobs_created=0, jobs_retained=0, housing_units=0,
                            businesses_financed=0, **overrides) -> dict:
    payload = {
        "jobs_created": jobs_created,
        "jobs_retained": jobs_retained,
        "housing_units": housing_units,
        "businesses_financed": businesses_financed,
    }
    payload.update(overrides)
    return payload


def compliance_measurement_payload(period_start, period_end,
                                   weighting_basis="DOLLAR_WEIGHTED",
                                   **overrides) -> dict:
    payload = {
        "period_start": period_start,
        "period_end": period_end,
        "weighting_basis": weighting_basis,
    }
    payload.update(overrides)
    return payload


def award_application_payload(requested_amount_cents=4_000_000,
                              match_ratio_pct=25.00,
                              performance_goal_jobs=40,
                              performance_goal_housing_units=10,
                              period_start="2026-10-01T00:00:00Z",
                              period_end="2027-10-01T00:00:00Z",
                              program="CDFI_PROGRAM_FA", **overrides) -> dict:
    payload = {
        "program": program,
        "requested_amount_cents": requested_amount_cents,
        "match_ratio_pct": match_ratio_pct,
        "performance_goal_jobs": performance_goal_jobs,
        "performance_goal_housing_units": performance_goal_housing_units,
        "period_start": period_start,
        "period_end": period_end,
    }
    payload.update(overrides)
    return payload


def matching_fund_commitment_payload(source_type="CASH_PRIVATE",
                                     amount_cents=1_000_000,
                                     source_name="Kellerman Family Foundation",
                                     committed_on="2026-08-15T00:00:00Z",
                                     **overrides) -> dict:
    payload = {
        "source_name": source_name,
        "source_type": source_type,
        "amount_cents": amount_cents,
        "committed_on": committed_on,
    }
    payload.update(overrides)
    return payload
