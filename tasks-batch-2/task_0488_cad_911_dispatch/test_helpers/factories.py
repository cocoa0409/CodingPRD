"""Payload factories — one per entity, input fields only."""


def create_agency_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Agency",
        "discipline": "POLICE",
        "response_sla_seconds": 600,
    }
    defaults.update(overrides)
    return defaults


def create_station_payload(agency_id: str, **overrides) -> dict:
    defaults = {
        "agency_id": agency_id,
        "name": "Test Station",
        "grid_x": 10,
        "grid_y": 10,
    }
    defaults.update(overrides)
    return defaults


def create_unit_payload(agency_id: str, station_id: str, **overrides) -> dict:
    defaults = {
        "agency_id": agency_id,
        "station_id": station_id,
        "call_sign": "U1",
        "capability": "PATROL",
    }
    defaults.update(overrides)
    return defaults


def create_premise_alert_payload(**overrides) -> dict:
    defaults = {
        "grid_x": 10,
        "grid_y": 10,
        "hazard_class": "WEAPONS",
        "min_priority_floor": 3,
    }
    defaults.update(overrides)
    return defaults


def create_incident_payload(**overrides) -> dict:
    defaults = {
        "ani": "5125550000",
        "ali_grid_x": 10,
        "ali_grid_y": 10,
        "incident_type": "ASSAULT_IN_PROGRESS",
    }
    defaults.update(overrides)
    return defaults


def create_assignment_payload(expected_incident_version, **overrides) -> dict:
    defaults = {
        "expected_incident_version": expected_incident_version,
    }
    defaults.update(overrides)
    return defaults


def create_disposition_payload(**overrides) -> dict:
    defaults = {
        "disposition_code": "REPORT_TAKEN",
        "narrative": "Closing narrative",
    }
    defaults.update(overrides)
    return defaults


def create_report_payload(**overrides) -> dict:
    defaults = {
        "report_standard": "NENA",
    }
    defaults.update(overrides)
    return defaults
