"""Public-facing serializers — produce JSON shapes for response envelopes."""

from __future__ import annotations


def _versioned_common(entity: dict) -> dict:
    return {
        "id": entity["id"],
        "created_at": entity["created_at"],
        "updated_at": entity.get("updated_at"),
        "version": entity.get("version"),
    }


def _immutable_common(entity: dict) -> dict:
    return {
        "id": entity["id"],
        "created_at": entity["created_at"],
    }


def serialize_carrier(c: dict) -> dict:
    return {
        **_versioned_common(c),
        "dot_number": c["dot_number"],
        "legal_name": c["legal_name"],
        "safety_contact_user_id": c["safety_contact_user_id"],
    }


def serialize_eld_device(d: dict) -> dict:
    return {
        **_versioned_common(d),
        "serial_number": d["serial_number"],
        "firmware_version": d["firmware_version"],
        "certified_for_fmcsa": d.get("certified_for_fmcsa", True),
    }


def serialize_vehicle(v: dict) -> dict:
    return {
        **_versioned_common(v),
        "vin": v["vin"],
        "carrier_id": v["carrier_id"],
        "eld_device_id": v["eld_device_id"],
        "current_driver_id": v.get("current_driver_id"),
        "odometer_miles": v.get("odometer_miles", 0),
    }


def serialize_driver(d: dict) -> dict:
    return {
        **_versioned_common(d),
        "cdl_number": d["cdl_number"],
        "full_name": d["full_name"],
        "carrier_id": d["carrier_id"],
        "cycle_type": d.get("cycle_type", "SEVENTY_HOUR_EIGHT_DAY"),
        "duty_status": d.get("duty_status", "OFF_DUTY"),
        "bound_vehicle_id": d.get("bound_vehicle_id"),
        "bound_eld_device_id": d.get("bound_eld_device_id"),
        "home_terminal_timezone": d.get("home_terminal_timezone", "America/New_York"),
        "last_34_hour_restart_completed_at": d.get("last_34_hour_restart_completed_at"),
    }


def serialize_duty_event(e: dict) -> dict:
    return {
        **_immutable_common(e),
        "driver_id": e["driver_id"],
        "vehicle_id": e.get("vehicle_id"),
        "new_status": e["new_status"],
        "event_time": e["event_time"],
        "latitude": e["latitude"],
        "longitude": e["longitude"],
        "odometer_miles": e.get("odometer_miles"),
        "annotation": e.get("annotation"),
        "edit_state": e.get("edit_state", "ACTIVE"),
        "superseded_by_event_id": e.get("superseded_by_event_id"),
        "daily_log_id": e.get("daily_log_id"),
        "adverse_conditions_exemption_id": e.get("adverse_conditions_exemption_id"),
    }


def serialize_daily_log(l: dict) -> dict:
    return {
        **_versioned_common(l),
        "driver_id": l["driver_id"],
        "log_date": l["log_date"],
        "status": l.get("status", "UNCERTIFIED"),
        "certified_at": l.get("certified_at"),
        "certification_count": l.get("certification_count", 0),
        "total_driving_minutes": l.get("total_driving_minutes", 0),
        "total_on_duty_minutes": l.get("total_on_duty_minutes", 0),
        "integrity_hash": l.get("integrity_hash"),
    }


def serialize_violation(v: dict) -> dict:
    return {
        **_versioned_common(v),
        "driver_id": v["driver_id"],
        "triggering_duty_event_id": v.get("triggering_duty_event_id"),
        "rule_code": v["rule_code"],
        "detected_at": v.get("detected_at"),
        "status": v.get("status", "OPEN"),
        "reported_to_fmcsa_at": v.get("reported_to_fmcsa_at"),
        "fmcsa_report_id": v.get("fmcsa_report_id"),
        "overage_minutes": v.get("overage_minutes", 0),
    }


def serialize_exemption(e: dict) -> dict:
    return {
        **_versioned_common(e),
        "driver_id": e["driver_id"],
        "declared_at": e["declared_at"],
        "reason": e["reason"],
        "status": e.get("status", "ACTIVE"),
        "extra_minutes_granted": e.get("extra_minutes_granted", 120),
        "applies_to_log_date": e.get("applies_to_log_date"),
    }
