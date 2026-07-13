"""Payload factories — one per entity, input fields only."""
from .constants import COVERING_SHIFT_START, COVERING_SHIFT_END


def create_incident_payload(**overrides) -> dict:
    payload = {
        "name": "Ridge Fire",
        "jurisdiction": "Butte County",
        "hazard_type": "WILDFIRE",
    }
    payload.update(overrides)
    return payload


def create_zone_payload(incident_id, **overrides) -> dict:
    payload = {
        "incident_id": incident_id,
        "name": "Zone-1",
        "geofence_wkt": "POLYGON((0 0,0 1,1 1,1 0,0 0))",
        "residential_population": 100,
    }
    payload.update(overrides)
    return payload


def create_shelter_payload(incident_id, **overrides) -> dict:
    payload = {
        "incident_id": incident_id,
        "name": "North HS",
        "physical_capacity": 10,
        "power_backup": True,
    }
    payload.update(overrides)
    return payload


def create_staff_shift_payload(shelter_id, **overrides) -> dict:
    payload = {
        "shelter_id": shelter_id,
        "role_label": "GENERAL",
        "staffed_beds": 20,
        "start_utc": COVERING_SHIFT_START,
        "end_utc": COVERING_SHIFT_END,
    }
    payload.update(overrides)
    return payload


def create_route_payload(incident_id, **overrides) -> dict:
    payload = {
        "incident_id": incident_id,
        "name": "US-101 N",
        "corridor_label": "US-101",
        "throughput_vph": 1200,
    }
    payload.update(overrides)
    return payload


def create_contraflow_payload(route_id, **overrides) -> dict:
    payload = {
        "route_id": route_id,
        "segment_key": "SEG-A",
        "direction": "INBOUND_REVERSED",
        "window_start_utc": "2026-03-01T10:00:00Z",
        "window_end_utc": "2026-03-01T12:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_registrant_payload(zone_id, **overrides) -> dict:
    payload = {
        "zone_id": zone_id,
        "household_name": "Alvarez",
        "party_size": 2,
    }
    payload.update(overrides)
    return payload


def create_shelter_assignment_payload(registrant_id, shelter_id, expected_registrant_version, **overrides) -> dict:
    payload = {
        "registrant_id": registrant_id,
        "shelter_id": shelter_id,
        "expected_registrant_version": expected_registrant_version,
    }
    payload.update(overrides)
    return payload


def create_access_credential_payload(zone_id, registrant_id, **overrides) -> dict:
    payload = {
        "zone_id": zone_id,
        "registrant_id": registrant_id,
        "credential_type": "RESIDENT",
        "valid_from_utc": "2026-02-01T00:00:00Z",
        "valid_until_utc": "2026-12-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_alert_payload(zone_id, **overrides) -> dict:
    payload = {
        "zone_id": zone_id,
        "message": "Evacuate now",
        "severity": "WARNING",
        "channels": ["WEA"],
    }
    payload.update(overrides)
    return payload
