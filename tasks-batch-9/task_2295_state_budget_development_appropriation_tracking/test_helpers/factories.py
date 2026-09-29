"""Payload factories — one per entity, carrying only client-supplied input fields."""

from .constants import TEST_DEFAULTS


def agency_payload(**overrides) -> dict:
    payload = {
        "agency_code": "DOH",
        "name": "Department of Health",
        "agency_type": "EXECUTIVE",
    }
    payload.update(overrides)
    return payload


def budget_cycle_payload(**overrides) -> dict:
    payload = {
        "fiscal_year": TEST_DEFAULTS["FISCAL_YEAR"],
        "fiscal_year_start_date": TEST_DEFAULTS["FISCAL_YEAR_START_DATE"],
        "reserve_balance_cents": TEST_DEFAULTS["RESERVE_BALANCE_CENTS"],
        "constitutional_reserve_pct": 0.05,
    }
    payload.update(overrides)
    return payload


def revenue_forecast_payload(budget_cycle_id, expected_budget_cycle_version, **overrides) -> dict:
    payload = {
        "budget_cycle_id": budget_cycle_id,
        "source_code": "SALES_TAX",
        "fund_type": "GENERAL",
        "forecast_round": "CONSENSUS_SPRING",
        "amount_cents": TEST_DEFAULTS["GENERAL_REVENUE_CENTS"],
        "effective_from": "2026-07-01T00:00:00Z",
        "effective_to": "2027-07-01T00:00:00Z",
        "expected_budget_cycle_version": expected_budget_cycle_version,
    }
    payload.update(overrides)
    return payload


def agency_request_payload(budget_cycle_id, agency_id, **overrides) -> dict:
    payload = {
        "budget_cycle_id": budget_cycle_id,
        "agency_id": agency_id,
        "base_budget_cents": TEST_DEFAULTS["BASE_BUDGET_CENTS"],
    }
    payload.update(overrides)
    return payload


def decision_package_payload(agency_request_id, **overrides) -> dict:
    payload = {
        "agency_request_id": agency_request_id,
        "package_type": "TECHNICAL",
        "priority_rank": 1,
        "amount_cents": 300_000_000,
    }
    payload.update(overrides)
    return payload


def performance_measure_payload(decision_package_id, **overrides) -> dict:
    payload = {
        "decision_package_id": decision_package_id,
        "measure_code": "M1",
        "unit": "COUNT",
        "baseline_value": 100,
        "target_value": 150,
    }
    payload.update(overrides)
    return payload


def executive_recommendation_payload(
    agency_request_id, expected_agency_request_version, **overrides
) -> dict:
    payload = {
        "agency_request_id": agency_request_id,
        "recommended_base_cents": TEST_DEFAULTS["BASE_BUDGET_CENTS"],
        "recommended_package_ids": [],
        "policy_priority": "HEALTH",
        "expected_agency_request_version": expected_agency_request_version,
    }
    payload.update(overrides)
    return payload


def reduction_scenario_payload(budget_cycle_id, **overrides) -> dict:
    payload = {"budget_cycle_id": budget_cycle_id, "target_reduction_pct": 0.10}
    payload.update(overrides)
    return payload


def appropriation_payload(budget_cycle_id, agency_id, **overrides) -> dict:
    payload = {
        "budget_cycle_id": budget_cycle_id,
        "agency_id": agency_id,
        "fund_type": "GENERAL",
        "program_code": "P100",
        "introduced_amount_cents": TEST_DEFAULTS["APPROPRIATION_CENTS"],
    }
    payload.update(overrides)
    return payload


def emergency_appropriation_payload(budget_cycle_id, agency_id, **overrides) -> dict:
    payload = {
        "budget_cycle_id": budget_cycle_id,
        "agency_id": agency_id,
        "program_code": "E900",
        "requested_amount_cents": 100_000_000,
        "justification": "wildfire response",
    }
    payload.update(overrides)
    return payload


def committee_action_payload(appropriation_id, **overrides) -> dict:
    payload = {
        "appropriation_id": appropriation_id,
        "chamber": "HOUSE",
        "committee_name": "Appropriations",
        "action_type": "INCREASE",
        "amount_cents": 100_000_000,
        "sequence_number": 1,
    }
    payload.update(overrides)
    return payload


def allotment_payload(appropriation_id, **overrides) -> dict:
    payload = {
        "appropriation_id": appropriation_id,
        "quarter": 1,
        "requested_cents": 440_000_000,
    }
    payload.update(overrides)
    return payload


def budget_transfer_payload(
    source_appropriation_id,
    target_appropriation_id,
    expected_source_appropriation_version,
    **overrides,
) -> dict:
    payload = {
        "source_appropriation_id": source_appropriation_id,
        "target_appropriation_id": target_appropriation_id,
        "amount_cents": 100_000_000,
        "transfer_type": "INTRA_AGENCY",
        "justification": "rebalance programs",
        "expected_source_appropriation_version": expected_source_appropriation_version,
    }
    payload.update(overrides)
    return payload


def expenditure_payload(appropriation_id, **overrides) -> dict:
    payload = {
        "appropriation_id": appropriation_id,
        "quarter": 1,
        "amount_cents": 100_000_000,
        "object_code": "OC100",
        "vendor_reference": "INV-1",
    }
    payload.update(overrides)
    return payload


def federal_grant_payload(agency_id, budget_cycle_id, **overrides) -> dict:
    payload = {
        "agency_id": agency_id,
        "budget_cycle_id": budget_cycle_id,
        "cfda_number": "93.778",
        "award_cents": 1_000_000_000,
        "period_start": "2026-07-01T00:00:00Z",
        "period_end": "2027-07-01T00:00:00Z",
        "moe_baseline_cents": 350_000_000,
    }
    payload.update(overrides)
    return payload


def match_commitment_payload(federal_grant_id, appropriation_id, **overrides) -> dict:
    payload = {
        "federal_grant_id": federal_grant_id,
        "appropriation_id": appropriation_id,
        "committed_match_cents": 250_000_000,
    }
    payload.update(overrides)
    return payload


def clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
