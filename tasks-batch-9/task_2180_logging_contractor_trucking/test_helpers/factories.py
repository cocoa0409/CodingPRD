"""Payload factories — one per entity, client-supplied input fields only."""
from .constants import TEST_DEFAULTS


def create_mill_payload(**overrides) -> dict:
    payload = {
        "name": TEST_DEFAULTS["MILL_NAME"],
        "state_code": TEST_DEFAULTS["MILL_STATE_CODE"],
        "receiving_status": "OPEN",
    }
    payload.update(overrides)
    return payload


def create_mill_contract_payload(mill_id, **overrides) -> dict:
    payload = {
        "mill_id": mill_id,
        "species": "DOUGLAS_FIR",
        "grade": "SAWLOG_1",
        "quota_tons": TEST_DEFAULTS["QUOTA_TONS"],
        "base_rate_cents_per_ton": TEST_DEFAULTS["BASE_RATE_CENTS_PER_TON"],
        "period_start": TEST_DEFAULTS["PERIOD_START"],
        "period_end": TEST_DEFAULTS["PERIOD_END"],
        "overrun_tolerance_pct": TEST_DEFAULTS["OVERRUN_TOLERANCE_PCT"],
    }
    payload.update(overrides)
    return payload


def create_haul_contractor_payload(**overrides) -> dict:
    payload = {
        "name": TEST_DEFAULTS["CARRIER_NAME"],
        "dot_number": TEST_DEFAULTS["CARRIER_DOT_NUMBER"],
        "base_state_code": TEST_DEFAULTS["CARRIER_STATE_CODE"],
    }
    payload.update(overrides)
    return payload


def create_insurance_certificate_payload(coverage_type, **overrides) -> dict:
    payload = {
        "coverage_type": coverage_type,
        "effective_on": TEST_DEFAULTS["INSURANCE_EFFECTIVE_ON"],
        "expires_on": TEST_DEFAULTS["INSURANCE_EXPIRES_ON"],
        "limit_cents": TEST_DEFAULTS["INSURANCE_LIMIT_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_truck_payload(**overrides) -> dict:
    payload = {
        "unit_number": TEST_DEFAULTS["TRUCK_UNIT_NUMBER"],
        "axle_config": "SIX_AXLE",
        "tare_weight_lbs": TEST_DEFAULTS["TRUCK_TARE_WEIGHT_LBS"],
        "permit_class": "STANDARD",
    }
    payload.update(overrides)
    return payload


def create_safety_finding_payload(**overrides) -> dict:
    payload = {
        "severity": "MINOR",
        "points": 5,
        "occurred_on": "2026-07-30",
    }
    payload.update(overrides)
    return payload


def create_crew_payload(**overrides) -> dict:
    payload = {
        "name": TEST_DEFAULTS["CREW_NAME"],
        "crew_type": "MECHANIZED_GROUND",
        "equipment_pieces": TEST_DEFAULTS["CREW_EQUIPMENT_PIECES"],
        "daily_rate_cents": TEST_DEFAULTS["CREW_DAILY_RATE_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_tract_payload(**overrides) -> dict:
    payload = {
        "name": TEST_DEFAULTS["TRACT_NAME"],
        "legal_description": TEST_DEFAULTS["TRACT_LEGAL_DESCRIPTION"],
        "gross_acres": TEST_DEFAULTS["TRACT_GROSS_ACRES"],
        "planned_volume_tons": TEST_DEFAULTS["TRACT_PLANNED_VOLUME_TONS"],
        "access_class": "ALL_SEASON",
    }
    payload.update(overrides)
    return payload


def create_production_plan_payload(expected_tract_version, **overrides) -> dict:
    payload = {
        "target_tons_per_week": 600,
        "plan_horizon_weeks": 8,
        "expected_tract_version": expected_tract_version,
    }
    payload.update(overrides)
    return payload


def create_crew_assignment_payload(crew_id, **overrides) -> dict:
    payload = {
        "crew_id": crew_id,
        "move_in_miles": TEST_DEFAULTS["MOVE_IN_MILES"],
        "window_start": TEST_DEFAULTS["WINDOW_START"],
        "window_end": TEST_DEFAULTS["WINDOW_END"],
    }
    payload.update(overrides)
    return payload


def create_haul_route_payload(tract_id, mill_id, **overrides) -> dict:
    payload = {
        "tract_id": tract_id,
        "mill_id": mill_id,
        "distance_miles": TEST_DEFAULTS["ROUTE_DISTANCE_MILES"],
        "legal_gross_weight_lbs": TEST_DEFAULTS["ROUTE_LEGAL_GROSS_WEIGHT_LBS"],
        "permit_class_required": "STANDARD",
        "status": "OPEN",
    }
    payload.update(overrides)
    return payload


def create_shutdown_order_payload(**overrides) -> dict:
    payload = {"reason": "WET_WEATHER", "soil_moisture_index": 85}
    payload.update(overrides)
    return payload


def create_load_payload(
    tract_id, mill_contract_id, haul_route_id, truck_id, **overrides
) -> dict:
    payload = {
        "tract_id": tract_id,
        "mill_contract_id": mill_contract_id,
        "haul_route_id": haul_route_id,
        "truck_id": truck_id,
        "declared_species": "DOUGLAS_FIR",
        "declared_grade": "SAWLOG_1",
        "estimated_net_tons": 26.5,
        "scheduled_depart_at": "2026-08-03T08:00:00Z",
        "scheduled_arrive_at": "2026-08-03T10:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_delivery_ticket_payload(**overrides) -> dict:
    payload = {
        "gross_weight_lbs": 90000,
        "defect_deduction_pct": 0.04,
        "scaled_species": "DOUGLAS_FIR",
        "scaled_grade": "SAWLOG_1",
    }
    payload.update(overrides)
    return payload


def create_settlement_statement_payload(
    haul_contractor_id, expected_haul_contractor_version, **overrides
) -> dict:
    payload = {
        "haul_contractor_id": haul_contractor_id,
        "period_start": "2026-08-01",
        "period_end": "2026-08-31",
        "expected_haul_contractor_version": expected_haul_contractor_version,
    }
    payload.update(overrides)
    return payload
