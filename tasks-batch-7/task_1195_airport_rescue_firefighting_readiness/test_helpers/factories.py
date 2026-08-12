"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "AIRPORT_CODE": "KDEMO",
    "CERTIFICATED_INDEX": "C",
    "AIRCRAFT_MODEL": "B737-900",
    "AIRCRAFT_LENGTH_FT": 138.2,
    "AIRCRAFT_DEPS": 6.0,
    "VEHICLE_CALL_SIGN": "RED-1",
    "VEHICLE_WATER_CAP": 2000,
    "VEHICLE_DRY_CHEM_CAP": 500,
    "EMPLOYEE_NO": "FF-101",
    "FULL_NAME": "Ann Lee",
    "RUNWAY": "09L",
    "LOCATION": "Runway 09L midfield",
    "PARTNER_CODE": "KCTY",
    "NARRATIVE": (
        "Aircraft N12345 experienced a hydraulic systems failure during "
        "landing rollout on runway 09L at 10:42Z. ARFF units RED-1 and "
        "RED-2 responded within three minutes, applied a foam blanket "
        "around the leaking left main gear, and escorted the airframe to "
        "the hardstand. No injuries."
    ),
}


def create_profile_payload(**overrides) -> dict:
    defaults = {
        "airport_code": DEFAULTS["AIRPORT_CODE"],
        "certificated_index": DEFAULTS["CERTIFICATED_INDEX"],
    }
    defaults.update(overrides)
    return defaults


def create_aircraft_payload(**overrides) -> dict:
    defaults = {
        "model_name": DEFAULTS["AIRCRAFT_MODEL"],
        "length_ft": DEFAULTS["AIRCRAFT_LENGTH_FT"],
        "avg_daily_departures": DEFAULTS["AIRCRAFT_DEPS"],
        "in_scheduled_service": True,
    }
    defaults.update(overrides)
    return defaults


def create_vehicle_payload(**overrides) -> dict:
    defaults = {
        "call_sign": DEFAULTS["VEHICLE_CALL_SIGN"],
        "water_capacity_gal": DEFAULTS["VEHICLE_WATER_CAP"],
        "dry_chem_capacity_lb": DEFAULTS["VEHICLE_DRY_CHEM_CAP"],
    }
    defaults.update(overrides)
    return defaults


def create_readiness_check_payload(vehicle_id, **overrides) -> dict:
    defaults = {
        "vehicle_id": vehicle_id,
        "water_available_gal": 2000,
        "dry_chem_available_lb": 500,
        "discharge_system_ok": True,
    }
    defaults.update(overrides)
    return defaults


def create_firefighter_payload(**overrides) -> dict:
    defaults = {
        "employee_no": DEFAULTS["EMPLOYEE_NO"],
        "full_name": DEFAULTS["FULL_NAME"],
    }
    defaults.update(overrides)
    return defaults


def create_training_record_payload(firefighter_id, **overrides) -> dict:
    defaults = {
        "firefighter_id": firefighter_id,
        "completed_on": "2026-04-15",
        "drill_type": "AIRCRAFT",
        "result": "PASS",
    }
    defaults.update(overrides)
    return defaults


def create_response_drill_payload(**overrides) -> dict:
    defaults = {
        "runway_designator": DEFAULTS["RUNWAY"],
        "scheduled_start": "2026-05-03T10:00:00Z",
        "scheduled_end": "2026-05-03T11:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def execute_drill_payload(**overrides) -> dict:
    defaults = {
        "first_vehicle_arrival_seconds": 120,
        "all_vehicles_arrival_seconds": 200,
    }
    defaults.update(overrides)
    return defaults


def create_incident_payload(**overrides) -> dict:
    defaults = {
        "alert_level": "ALERT_1",
        "location": DEFAULTS["LOCATION"],
    }
    defaults.update(overrides)
    return defaults


def create_mutual_aid_agreement_payload(**overrides) -> dict:
    defaults = {
        "partner_airport_code": DEFAULTS["PARTNER_CODE"],
        "max_alert_level": "ALERT_2",
        "start_date": "2026-01-01",
        "end_date": "2026-12-31",
    }
    defaults.update(overrides)
    return defaults


def create_mutual_aid_request_payload(agreement_id, **overrides) -> dict:
    defaults = {
        "agreement_id": agreement_id,
        "units_requested": 1,
    }
    defaults.update(overrides)
    return defaults


def create_out_of_service_event_payload(**overrides) -> dict:
    defaults = {"reason": "Foam pump failure"}
    defaults.update(overrides)
    return defaults


def create_incident_report_payload(**overrides) -> dict:
    defaults = {"narrative": DEFAULTS["NARRATIVE"]}
    defaults.update(overrides)
    return defaults


def create_post_incident_review_payload(**overrides) -> dict:
    defaults = {"findings": "Foam usage high", "corrective_actions_open": 0}
    defaults.update(overrides)
    return defaults


def create_faa_inspection_payload(**overrides) -> dict:
    defaults = {"inspection_year": 2026, "scheduled_on": "2026-05-03"}
    defaults.update(overrides)
    return defaults
