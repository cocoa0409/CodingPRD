"""Payload factories — one per entity, request-input fields only."""

DEFAULTS = {
    "JURISDICTION_NAME": "City of Brentwood",
    "CODE_EDITION_YEAR": 2019,
    "BUILDING_NAME": "Brentwood Tower",
    "CONTRACT_VALUE_CENTS": 60_000_000,
    "STAGING_AREA_SQFT": 1200,
    "MAX_CONCURRENT_OUTAGES": 2,
    "GROUP_LABEL": "BANK-A",
    "CAR_DESIGNATION": "CAR-1",
    "RATED_LOAD_LBS": 3500,
    "MONTHLY_BASE_CENTS": 45_000,
}


def create_jurisdiction_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["JURISDICTION_NAME"],
        "code_edition_year": DEFAULTS["CODE_EDITION_YEAR"],
        "fire_service_required": False,
        "seismic_zone": 0,
        "door_protection_required": False,
    }
    payload.update(overrides)
    return payload


def create_project_payload(jurisdiction_id: str, **overrides) -> dict:
    payload = {
        "jurisdiction_id": jurisdiction_id,
        "building_name": DEFAULTS["BUILDING_NAME"],
        "occupancy_type": "OCCUPIED",
        "contract_value_cents": DEFAULTS["CONTRACT_VALUE_CENTS"],
        "staging_area_sqft": DEFAULTS["STAGING_AREA_SQFT"],
        "max_concurrent_outages": DEFAULTS["MAX_CONCURRENT_OUTAGES"],
    }
    payload.update(overrides)
    return payload


def create_elevator_group_payload(project_id: str, **overrides) -> dict:
    payload = {
        "project_id": project_id,
        "group_label": DEFAULTS["GROUP_LABEL"],
        "min_cars_in_service": 0,
    }
    payload.update(overrides)
    return payload


def create_elevator_car_payload(project_id: str, group_id: str, **overrides) -> dict:
    payload = {
        "project_id": project_id,
        "group_id": group_id,
        "car_designation": DEFAULTS["CAR_DESIGNATION"],
        "rated_load_lbs": DEFAULTS["RATED_LOAD_LBS"],
        "controller_type_legacy": "RELAY",
        "machine_type": "GEARLESS",
        "duty_rank": 1,
    }
    payload.update(overrides)
    return payload


def create_equipment_survey_payload(car_id: str, **overrides) -> dict:
    payload = {
        "car_id": car_id,
        "controller_condition": "GOOD",
        "machine_condition": "GOOD",
        "door_equipment_condition": "EXCELLENT",
    }
    payload.update(overrides)
    return payload


def create_scope_option_payload(
    car_id: str, expected_project_version: int, **overrides
) -> dict:
    payload = {
        "car_id": car_id,
        "tier": "CONTROLLER_ONLY",
        "base_price_cents": 5_000_000,
        "expected_project_version": expected_project_version,
    }
    payload.update(overrides)
    return payload


def create_procurement_order_payload(scope_option_id: str, **overrides) -> dict:
    payload = {
        "scope_option_id": scope_option_id,
        "item_type": "CONTROLLER",
        "lead_time_days": 30,
        "required_staging_sqft": 400,
    }
    payload.update(overrides)
    return payload


def create_staging_reservation_payload(
    procurement_order_id: str, expected_project_version: int, **overrides
) -> dict:
    payload = {
        "procurement_order_id": procurement_order_id,
        "sqft": 400,
        "hold_start": "2026-08-05T00:00:00Z",
        "hold_end": "2026-08-20T00:00:00Z",
        "expected_project_version": expected_project_version,
    }
    payload.update(overrides)
    return payload


def create_outage_window_payload(car_id: str, **overrides) -> dict:
    payload = {
        "car_id": car_id,
        "start_at": "2026-08-10T08:00:00Z",
        "end_at": "2026-08-12T18:00:00Z",
        "temporary_service_plan": "ADJACENT_CAR",
    }
    payload.update(overrides)
    return payload


def create_inspection_appointment_payload(car_id: str, **overrides) -> dict:
    payload = {
        "car_id": car_id,
        "requested_date": "2026-08-25",
    }
    payload.update(overrides)
    return payload


def create_warranty_transition_payload(car_id: str, **overrides) -> dict:
    payload = {
        "car_id": car_id,
        "warranty_months": 24,
    }
    payload.update(overrides)
    return payload


def create_maintenance_contract_payload(project_id: str, **overrides) -> dict:
    payload = {
        "project_id": project_id,
        "monthly_base_cents": DEFAULTS["MONTHLY_BASE_CENTS"],
        "coverage_start": "2027-03-15",
    }
    payload.update(overrides)
    return payload


def set_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
