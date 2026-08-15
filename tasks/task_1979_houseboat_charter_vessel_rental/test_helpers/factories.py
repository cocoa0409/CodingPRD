"""Payload factories — one per entity, input fields only."""
from .constants import TEST_DEFAULTS


def create_vessel_payload(**overrides) -> dict:
    defaults = {
        "name": TEST_DEFAULTS["VESSEL_NAME"],
        "size_class": "COMPACT_36",
        "berth_count": TEST_DEFAULTS["BERTH_COMPACT"],
        "home_marina": TEST_DEFAULTS["HOME_MARINA"],
        "fuel_tank_capacity_gallons": TEST_DEFAULTS["TANK_COMPACT"],
    }
    defaults.update(overrides)
    return defaults


def create_season_rate_payload(**overrides) -> dict:
    defaults = {
        "size_class": "COMPACT_36",
        "season": "PEAK",
        "start_date": "2026-06-01",
        "end_date": "2026-08-31",
        "nightly_rate_cents": TEST_DEFAULTS["RATE_COMPACT_PEAK"],
        "weekly_discount_pct": TEST_DEFAULTS["WEEKLY_DISCOUNT_PCT"],
    }
    defaults.update(overrides)
    return defaults


def create_geo_zone_payload(**overrides) -> dict:
    defaults = {
        "zone_code": "ZP-TEST",
        "name": "Test Zone",
        "max_vessels_per_night": 5,
        "allowed_size_classes": ["COMPACT_36", "STANDARD_44", "LUXE_56"],
    }
    defaults.update(overrides)
    return defaults


def create_maintenance_window_payload(**overrides) -> dict:
    defaults = {
        "start_date": "2026-09-10",
        "end_date": "2026-09-12",
        "reason": "Scheduled service",
    }
    defaults.update(overrides)
    return defaults


def create_weather_advisory_payload(**overrides) -> dict:
    defaults = {
        "severity": "STORM",
        "zone_ids": [],
        "window_start": "2026-08-09T00:00:00Z",
        "window_end": "2026-08-15T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_renter_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Renter",
        "email": "renter@example.com",
        "date_of_birth": "1990-01-01",
    }
    defaults.update(overrides)
    return defaults


def create_certificate_payload(**overrides) -> dict:
    defaults = {
        "cert_number": "CERT-0001",
        "issuing_authority": "NASBLA",
        "issued_on": "2026-01-15",
        "expires_on": "2027-06-30",
    }
    defaults.update(overrides)
    return defaults


def create_booking_payload(vessel_id, renter_id, **overrides) -> dict:
    defaults = {
        "vessel_id": vessel_id,
        "renter_id": renter_id,
        "start_date": "2026-08-20",
        "end_date": "2026-08-22",
        "party_size": 2,
    }
    defaults.update(overrides)
    return defaults


def itinerary_payload(waypoints) -> dict:
    return {"waypoints": waypoints}


def waypoint(zone_id, night_date) -> dict:
    return {"zone_id": zone_id, "night_date": night_date}


def sign_item_payload(item_code) -> dict:
    return {"item_code": item_code}


def countersign_payload(approved=True, item_code=None) -> dict:
    payload = {"approved": approved}
    if item_code is not None:
        payload["item_code"] = item_code
    return payload


def checkout_payload(fuel_gauge_percent=100, pump_out_done=True) -> dict:
    return {
        "fuel_gauge_percent": fuel_gauge_percent,
        "pump_out_done": pump_out_done,
    }


def return_payload(actual_return_at, fuel_gauge_percent=100, pump_out_done=True) -> dict:
    return {
        "fuel_gauge_percent": fuel_gauge_percent,
        "pump_out_done": pump_out_done,
        "actual_return_at": actual_return_at,
    }


def modify_booking_payload(expected_booking_version, start_date, end_date) -> dict:
    return {
        "expected_booking_version": expected_booking_version,
        "start_date": start_date,
        "end_date": end_date,
    }


def cancel_booking_payload(expected_booking_version, reason=None) -> dict:
    payload = {"expected_booking_version": expected_booking_version}
    if reason is not None:
        payload["reason"] = reason
    return payload


def report_incident_payload(incident_type, occurred_at, description=None) -> dict:
    payload = {"incident_type": incident_type, "occurred_at": occurred_at}
    if description is not None:
        payload["description"] = description
    return payload


def resolve_incident_payload(resolution, severity=None, downtime_days=None,
                             assessed_damage_cents=None) -> dict:
    payload = {"resolution": resolution}
    if severity is not None:
        payload["severity"] = severity
    if downtime_days is not None:
        payload["downtime_days"] = downtime_days
    if assessed_damage_cents is not None:
        payload["assessed_damage_cents"] = assessed_damage_cents
    return payload
