"""Payload factories — one per resource, input fields only."""

from .constants import TEST_DEFAULTS


def branch_payload(**overrides) -> dict:
    payload = {
        "code": "WST-01",
        "name": "West Yard",
        "region": "WEST",
        "yard_capacity": TEST_DEFAULTS["BRANCH_CAPACITY"],
        "peak_season_start_date": TEST_DEFAULTS["PEAK_START"],
        "peak_season_end_date": TEST_DEFAULTS["PEAK_END"],
        "lease_reserve_pct": 0.00,
    }
    payload.update(overrides)
    return payload


def east_branch_payload(**overrides) -> dict:
    payload = {
        "code": "EST-01",
        "name": "East Yard",
        "region": "EAST",
        "yard_capacity": 8,
        "peak_season_start_date": "2026-06-01",
        "peak_season_end_date": "2026-08-31",
        "lease_reserve_pct": 0.00,
    }
    payload.update(overrides)
    return payload


def trailer_type_payload(**overrides) -> dict:
    payload = {
        "code": "DRY_VAN_53",
        "description": "53ft dry van",
        "base_daily_rate_cents": 4500,
        "base_monthly_rate_cents": 95000,
        "residual_floor_cents": TEST_DEFAULTS["RESIDUAL_FLOOR_CENTS"],
        "required_physical_damage_limit_cents":
            TEST_DEFAULTS["REQUIRED_PHYSICAL_DAMAGE_LIMIT_CENTS"],
        "dot_inspection_interval_days": TEST_DEFAULTS["DOT_INSPECTION_INTERVAL_DAYS"],
        "pm_interval_miles": TEST_DEFAULTS["PM_INTERVAL_MILES"],
    }
    payload.update(overrides)
    return payload


def trailer_payload(trailer_type_id: str, home_branch_id: str, **overrides) -> dict:
    payload = {
        "unit_number": "T-1001",
        "trailer_type_id": trailer_type_id,
        "home_branch_id": home_branch_id,
        "acquisition_cost_cents": TEST_DEFAULTS["ACQUISITION_COST_CENTS"],
        "in_service_date": "2022-08-01",
        "last_dot_inspection_date": "2026-01-01",
        "hub_miles": TEST_DEFAULTS["TRAILER_HUB_MILES"],
    }
    payload.update(overrides)
    return payload


def customer_payload(**overrides) -> dict:
    payload = {
        "legal_name": "Ridge Haul LLC",
        "dot_number": "DOT-771",
        "credit_tier": "B",
        "credit_limit_cents": TEST_DEFAULTS["CREDIT_LIMIT_CENTS"],
    }
    payload.update(overrides)
    return payload


def insurance_certificate_payload(customer_id: str, **overrides) -> dict:
    payload = {
        "customer_id": customer_id,
        "carrier_name": "Great West Casualty",
        "policy_number": "P-1",
        "physical_damage_limit_cents": 3_000_000,
        "liability_limit_cents": 100_000_000,
        "effective_date": "2024-01-01",
        "expiry_date": "2027-01-01",
    }
    payload.update(overrides)
    return payload


def rate_card_payload(branch_id: str, trailer_type_id: str,
                      expected_branch_version: int, **overrides) -> dict:
    payload = {
        "branch_id": branch_id,
        "trailer_type_id": trailer_type_id,
        "product": "SHORT_TERM_RENTAL",
        "daily_rate_cents": TEST_DEFAULTS["DAILY_RATE_CENTS"],
        "monthly_rate_cents": 110000,
        "peak_uplift_pct": TEST_DEFAULTS["PEAK_UPLIFT_PCT"],
        "mileage_included_per_month": TEST_DEFAULTS["MILEAGE_INCLUDED_PER_MONTH"],
        "excess_mileage_rate_cents_per_mile":
            TEST_DEFAULTS["EXCESS_MILEAGE_RATE_CENTS_PER_MILE"],
        "effective_date": "2026-07-01",
        "expected_branch_version": expected_branch_version,
    }
    payload.update(overrides)
    return payload


def lease_rate_card_payload(branch_id: str, trailer_type_id: str,
                            expected_branch_version: int, **overrides) -> dict:
    payload = {
        "branch_id": branch_id,
        "trailer_type_id": trailer_type_id,
        "product": "FULL_SERVICE_LEASE",
        "daily_rate_cents": 3800,
        "monthly_rate_cents": 82000,
        "peak_uplift_pct": 0.10,
        "mileage_included_per_month": 5000,
        "excess_mileage_rate_cents_per_mile": 15,
        "effective_date": "2024-01-01",
        "expected_branch_version": expected_branch_version,
    }
    payload.update(overrides)
    return payload


def agreement_payload(customer_id: str, branch_id: str, trailer_type_id: str,
                      **overrides) -> dict:
    payload = {
        "customer_id": customer_id,
        "branch_id": branch_id,
        "product": "SHORT_TERM_RENTAL",
        "trailer_type_id": trailer_type_id,
        "unit_count": 1,
        "start_date": TEST_DEFAULTS["AGREEMENT_START_DATE"],
        "end_date": TEST_DEFAULTS["AGREEMENT_END_DATE"],
    }
    payload.update(overrides)
    return payload


def lease_agreement_payload(customer_id: str, branch_id: str, trailer_type_id: str,
                            **overrides) -> dict:
    payload = {
        "customer_id": customer_id,
        "branch_id": branch_id,
        "product": "FULL_SERVICE_LEASE",
        "trailer_type_id": trailer_type_id,
        "unit_count": 1,
        "start_date": "2024-09-01",
        "end_date": "2026-09-01",
        "term_months": 24,
    }
    payload.update(overrides)
    return payload


def return_payload(return_branch_id: str, **overrides) -> dict:
    payload = {
        "return_branch_id": return_branch_id,
        "return_hub_miles": TEST_DEFAULTS["RETURN_HUB_MILES"],
        "return_date": TEST_DEFAULTS["RETURN_DATE"],
    }
    payload.update(overrides)
    return payload


def damage_line_item(severity: str = "MODERATE", quantity: int = 2,
                     unit_cost_cents: int = 40000,
                     description: str = "sidewall scuff") -> dict:
    return {
        "severity": severity,
        "quantity": quantity,
        "unit_cost_cents": unit_cost_cents,
        "description": description,
    }


def damage_assessment_payload(expected_agreement_unit_version: int,
                              line_items=None, **overrides) -> dict:
    payload = {
        "line_items": line_items if line_items is not None else [damage_line_item()],
        "expected_agreement_unit_version": expected_agreement_unit_version,
    }
    payload.update(overrides)
    return payload


def maintenance_event_payload(trailer_id: str, event_type: str = "PM_SERVICE",
                              **overrides) -> dict:
    payload = {
        "trailer_id": trailer_id,
        "event_type": event_type,
        "performed_on": "2026-08-02",
        "hub_miles_at_event": TEST_DEFAULTS["TRAILER_HUB_MILES"],
        "cost_cents": 42000,
    }
    if event_type == "DOT_INSPECTION":
        payload["passed"] = True
    payload.update(overrides)
    return payload


def relocation_order_payload(trailer_id: str, destination_branch_id: str,
                             **overrides) -> dict:
    payload = {
        "trailer_id": trailer_id,
        "destination_branch_id": destination_branch_id,
        "planned_depart_date": "2026-09-10",
        "planned_arrive_date": "2026-09-12",
        "planned_miles": 430,
    }
    payload.update(overrides)
    return payload
