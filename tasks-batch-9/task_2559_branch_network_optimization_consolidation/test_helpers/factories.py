"""Payload factories — one per entity, carrying only client-supplied input fields."""

HARBOR_METRO = {
    "name": "Harbor Metro",
    "region_code": "MD-01",
    "population": 240000,
    "median_household_income_cents": 7200000,
    "deposit_market_total_cents": 900000000000,
    "competitor_branch_count": 60,
    "household_growth_pct_bps": 180,
    "digital_penetration_bps": 5200,
}


def market_area_payload(**overrides) -> dict:
    payload = dict(HARBOR_METRO)
    payload.update(overrides)
    return payload


def branch_payload(market_area_id: str, **overrides) -> dict:
    """Default is the RB-101 closing-candidate profile used across the suite."""
    payload = {
        "market_area_id": market_area_id,
        "branch_code": "RB-101",
        "branch_type": "FULL_SERVICE",
        "tenure_class": "LEASED",
        "deposit_balance_cents": 4800000000,
        "monthly_transaction_count": 5400,
        "digital_adoption_bps": 5400,
        "annual_noninterest_expense_cents": 38000000,
        "annual_revenue_cents": 40000000,
        "fte_count": 9,
        "atm_count": 2,
        "opened_on": "2005-03-01",
    }
    payload.update(overrides)
    return payload


def receiving_branch_payload(market_area_id: str, **overrides) -> dict:
    """Default is the RB-102 survivor profile used across the suite."""
    payload = {
        "market_area_id": market_area_id,
        "branch_code": "RB-102",
        "branch_type": "FULL_SERVICE",
        "tenure_class": "OWNED",
        "deposit_balance_cents": 9600000000,
        "monthly_transaction_count": 8100,
        "digital_adoption_bps": 6100,
        "annual_noninterest_expense_cents": 52000000,
        "annual_revenue_cents": 96000000,
        "fte_count": 14,
        "atm_count": 3,
        "opened_on": "1998-07-15",
    }
    payload.update(overrides)
    return payload


def performance_snapshot_payload(**overrides) -> dict:
    payload = {
        "period_label": "2026-Q1",
        "period_end_date": "2026-03-31",
        "deposits_cents": 4800000000,
        "transaction_count": 5400,
        "digital_active_bps": 5400,
        "revenue_cents": 40000000,
        "noninterest_expense_cents": 30000000,
    }
    payload.update(overrides)
    return payload


def consolidation_case_payload(closing_branch_id: str, expected_branch_version: int,
                               **overrides) -> dict:
    payload = {
        "closing_branch_id": closing_branch_id,
        "rationale_code": "LOW_PERFORMANCE",
        "planned_closure_date": "2026-12-01",
        "expected_branch_version": expected_branch_version,
    }
    payload.update(overrides)
    return payload


def retention_forecast_payload(consolidation_case_id: str, expected_case_version: int,
                               **overrides) -> dict:
    payload = {
        "consolidation_case_id": consolidation_case_id,
        "expected_case_version": expected_case_version,
        "model_variant": "DISTANCE_DECAY",
        "distance_miles": 3.0,
        "retail_share_bps": 8000,
        "small_business_share_bps": 1500,
        "wealth_share_bps": 500,
    }
    payload.update(overrides)
    return payload


def impact_assessment_payload(**overrides) -> dict:
    payload = {
        "lmi_tract": False,
        "distance_to_nearest_remaining_miles": 2.0,
        "alternative_access_count": 3,
        "senior_household_pct_bps": 4000,
        "public_transit_access": True,
    }
    payload.update(overrides)
    return payload


def closure_notice_payload(consolidation_case_id: str, **overrides) -> dict:
    payload = {
        "consolidation_case_id": consolidation_case_id,
        "notice_type": "REGULATOR",
        "effective_closure_date": "2026-11-01",
    }
    payload.update(overrides)
    return payload


def staff_disposition_payload(consolidation_case_id: str, **overrides) -> dict:
    payload = {
        "consolidation_case_id": consolidation_case_id,
        "employee_ref": "EMP-001",
        "role_title": "Teller",
        "tenure_months": 150,
        "annual_salary_cents": 7800050,
        "proposed_disposition": "SEVERANCE",
    }
    payload.update(overrides)
    return payload


def leased_property_disposition_payload(branch_id: str, consolidation_case_id: str,
                                        **overrides) -> dict:
    payload = {
        "branch_id": branch_id,
        "consolidation_case_id": consolidation_case_id,
        "atm_disposition": "RETAIN_OFFSITE",
        "atm_monthly_cost_cents": 30000,
        "atm_monthly_surcharge_revenue_cents": 80000,
        "monthly_rent_cents": 250000,
        "lease_end_date": "2027-06-30",
        "buyout_offer_cents": 3000000,
    }
    payload.update(overrides)
    return payload


def owned_property_disposition_payload(branch_id: str, consolidation_case_id: str,
                                       **overrides) -> dict:
    payload = {
        "branch_id": branch_id,
        "consolidation_case_id": consolidation_case_id,
        "atm_disposition": "RETAIN_OFFSITE",
        "atm_monthly_cost_cents": 30000,
        "atm_monthly_surcharge_revenue_cents": 80000,
        "book_value_cents": 40000000,
        "list_price_cents": 52000000,
    }
    payload.update(overrides)
    return payload


def transition_campaign_payload(consolidation_case_id: str, **overrides) -> dict:
    payload = {
        "consolidation_case_id": consolidation_case_id,
        "wave_start_date": "2026-09-01",
        "wave_end_date": "2026-10-01",
        "inbound_household_count": 600,
        "channel_mix": "LETTER_EMAIL",
    }
    payload.update(overrides)
    return payload


def de_novo_plan_payload(market_area_id: str, **overrides) -> dict:
    payload = {
        "market_area_id": market_area_id,
        "site_label": "Harbor North Gateway",
        "proposed_branch_code": "HN-301",
        "target_year1_deposits_cents": 6000000000,
        "capex_budget_cents": 320000000,
    }
    payload.update(overrides)
    return payload


def case_observation_payload(consolidation_case_id: str, month_index: int,
                             observed_deposits_cents: int, **overrides) -> dict:
    payload = {
        "subject_type": "CONSOLIDATION_CASE",
        "consolidation_case_id": consolidation_case_id,
        "month_index": month_index,
        "observed_deposits_cents": observed_deposits_cents,
    }
    payload.update(overrides)
    return payload


def plan_observation_payload(de_novo_plan_id: str, month_index: int,
                             observed_deposits_cents: int, **overrides) -> dict:
    payload = {
        "subject_type": "DE_NOVO_PLAN",
        "de_novo_plan_id": de_novo_plan_id,
        "month_index": month_index,
        "observed_deposits_cents": observed_deposits_cents,
    }
    payload.update(overrides)
    return payload


def clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
