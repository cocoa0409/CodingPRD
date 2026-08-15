"""Payload factories — one per entity, input fields only."""
from .constants import TEST_DEFAULTS as D


def create_contract_payload(**overrides) -> dict:
    defaults = {
        "contract_number": D["CONTRACT_NUMBER"],
        "agency": D["AGENCY"],
        "contract_type": D["CONTRACT_TYPE"],
        "daily_availability_rate_cents": D["DAILY_AVAILABILITY_RATE_CENTS"],
        "flight_hour_rate_cents": D["FLIGHT_HOUR_RATE_CENTS"],
        "season_start_date": D["SEASON_START_DATE"],
        "season_end_date": D["SEASON_END_DATE"],
        "season_flight_hour_cap_tenths": D["SEASON_FLIGHT_HOUR_CAP_TENTHS"],
        "acceptance_window_minutes": D["ACCEPTANCE_WINDOW_MINUTES"],
    }
    defaults.update(overrides)
    return defaults


def create_aircraft_payload(contract_id, **overrides) -> dict:
    defaults = {
        "tail_number": D["TAIL_NUMBER"],
        "model": D["AIRCRAFT_MODEL"],
        "tank_capacity_gallons": D["TANK_CAPACITY_GALLONS"],
        "contract_id": contract_id,
    }
    defaults.update(overrides)
    return defaults


def create_crew_member_payload(contract_id, **overrides) -> dict:
    defaults = {
        "full_name": D["PILOT_NAME"],
        "crew_role": "PIC",
        "contract_id": contract_id,
        "qualified_aircraft_models": [D["AIRCRAFT_MODEL"]],
    }
    defaults.update(overrides)
    return defaults


def create_carding_inspection_payload(subject_aircraft_id=None,
                                      subject_crew_member_id=None,
                                      **overrides) -> dict:
    defaults = {
        "scheduled_for": D["INSPECTION_SCHEDULED_FOR"],
        "valid_days": D["VALID_DAYS"],
    }
    if subject_aircraft_id is not None:
        defaults["subject_aircraft_id"] = subject_aircraft_id
    if subject_crew_member_id is not None:
        defaults["subject_crew_member_id"] = subject_crew_member_id
    defaults.update(overrides)
    return defaults


def complete_inspection_payload(result="PASSED", completed_at=None, **overrides) -> dict:
    defaults = {
        "result": result,
        "completed_at": completed_at or D["INSPECTION_COMPLETED_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_availability_period_payload(aircraft_id, service_date="2026-08-03",
                                       available_start="2026-08-03T07:00:00Z",
                                       available_end="2026-08-03T16:30:00Z",
                                       **overrides) -> dict:
    defaults = {
        "aircraft_id": aircraft_id,
        "service_date": service_date,
        "available_start": available_start,
        "available_end": available_end,
    }
    defaults.update(overrides)
    return defaults


def create_incident_payload(**overrides) -> dict:
    defaults = {
        "incident_number": D["INCIDENT_NUMBER"],
        "name": D["INCIDENT_NAME"],
        "location": D["INCIDENT_LOCATION"],
        "agency": D["AGENCY"],
        "priority": "EXTENDED_ATTACK",
    }
    defaults.update(overrides)
    return defaults


def create_dispatch_order_payload(contract_id, incident_id, **overrides) -> dict:
    defaults = {
        "order_number": D["ORDER_NUMBER"],
        "contract_id": contract_id,
        "incident_id": incident_id,
        "aircraft_quantity": 1,
    }
    defaults.update(overrides)
    return defaults


def create_assignment_payload(aircraft_id, pilot_id, planned_start, planned_end,
                              expected_dispatch_order_version, **overrides) -> dict:
    defaults = {
        "aircraft_id": aircraft_id,
        "pilot_id": pilot_id,
        "planned_start": planned_start,
        "planned_end": planned_end,
        "expected_dispatch_order_version": expected_dispatch_order_version,
    }
    defaults.update(overrides)
    return defaults


def create_flight_log_payload(logged_date, hobbs_start, hobbs_stop, **overrides) -> dict:
    defaults = {
        "logged_date": logged_date,
        "hobbs_start": hobbs_start,
        "hobbs_stop": hobbs_stop,
    }
    defaults.update(overrides)
    return defaults


def create_retardant_load_payload(gallons=700, requested_at=None, **overrides) -> dict:
    defaults = {"gallons": gallons}
    if requested_at is not None:
        defaults["requested_at"] = requested_at
    defaults.update(overrides)
    return defaults


def create_invoice_payload(period_start, period_end, expected_contract_version,
                           **overrides) -> dict:
    defaults = {
        "period_start": period_start,
        "period_end": period_end,
        "expected_contract_version": expected_contract_version,
    }
    defaults.update(overrides)
    return defaults


def create_agency_record_payload(contract_id, assignment_id, record_date,
                                 agency_flight_hours_tenths, **overrides) -> dict:
    defaults = {
        "contract_id": contract_id,
        "assignment_id": assignment_id,
        "record_date": record_date,
        "agency_flight_hours_tenths": agency_flight_hours_tenths,
    }
    defaults.update(overrides)
    return defaults
