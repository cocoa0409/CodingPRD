"""Payload factories — one per entity, input fields only (PRD §3, §4)."""

DEFAULTS = {
    "OPERATOR_LEGAL_NAME": "Test Transport Co",
    "OPERATOR_CONTACT_EMAIL": "test@transport.example",
    "VALID_FROM": "2026-01-01T00:00:00Z",
    "VALID_UNTIL": "2027-01-01T00:00:00Z",
    "FEE_PAID_CENTS": 10000,
    "LOT_CENTER_LAT": 40.64,
    "LOT_CENTER_LNG": -73.78,
    "LOT_RADIUS_M": 5000,
    "LOT_CAPACITY": 5,
}


def create_operator_payload(**overrides) -> dict:
    payload = {
        "legal_name": DEFAULTS["OPERATOR_LEGAL_NAME"],
        "operator_type": "TNC",
        "contact_email": DEFAULTS["OPERATOR_CONTACT_EMAIL"],
    }
    payload.update(overrides)
    return payload


def create_vehicle_payload(operator_id, **overrides) -> dict:
    payload = {"operator_id": operator_id, "plate": "PLATE-1"}
    payload.update(overrides)
    return payload


def create_permit_payload(vehicle_id, expected_vehicle_version, **overrides) -> dict:
    payload = {
        "vehicle_id": vehicle_id,
        "avi_tag_id": "AVI-DEFAULT",
        "valid_from": DEFAULTS["VALID_FROM"],
        "valid_until": DEFAULTS["VALID_UNTIL"],
        "fee_paid_cents": DEFAULTS["FEE_PAID_CENTS"],
        "expected_vehicle_version": expected_vehicle_version,
    }
    payload.update(overrides)
    return payload


def create_staging_lot_payload(**overrides) -> dict:
    payload = {
        "name": "Test Lot",
        "geofence_center_lat": DEFAULTS["LOT_CENTER_LAT"],
        "geofence_center_lng": DEFAULTS["LOT_CENTER_LNG"],
        "geofence_radius_m": DEFAULTS["LOT_RADIUS_M"],
        "capacity": DEFAULTS["LOT_CAPACITY"],
    }
    payload.update(overrides)
    return payload


def create_queue_entry_payload(staging_lot_id, vehicle_id, **overrides) -> dict:
    payload = {
        "staging_lot_id": staging_lot_id,
        "vehicle_id": vehicle_id,
        "lat": DEFAULTS["LOT_CENTER_LAT"],
        "lng": DEFAULTS["LOT_CENTER_LNG"],
    }
    payload.update(overrides)
    return payload


def create_curb_zone_payload(**overrides) -> dict:
    payload = {"name": "Test Zone", "terminal": "T1", "capacity": 1}
    payload.update(overrides)
    return payload


def create_curb_assignment_payload(curb_zone_id, trip_id, start_ts, end_ts, **overrides) -> dict:
    payload = {
        "curb_zone_id": curb_zone_id,
        "trip_id": trip_id,
        "start_ts": start_ts,
        "end_ts": end_ts,
    }
    payload.update(overrides)
    return payload


def create_trip_payload(vehicle_id, staging_lot_id, **overrides) -> dict:
    payload = {"vehicle_id": vehicle_id, "staging_lot_id": staging_lot_id}
    payload.update(overrides)
    return payload


def create_violation_payload(operator_id, violation_type, **overrides) -> dict:
    payload = {"operator_id": operator_id, "violation_type": violation_type}
    payload.update(overrides)
    return payload


def create_settlement_payload(operator_id, period_year, period_month, **overrides) -> dict:
    payload = {
        "operator_id": operator_id,
        "period_year": period_year,
        "period_month": period_month,
    }
    payload.update(overrides)
    return payload
