"""Public serialization of entities — only declared fields, in scaffold order."""


def driver_view(r):
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
        "license_number": r["license_number"],
        "full_name": r["full_name"],
        "home_terminal_tz_offset_minutes": r["home_terminal_tz_offset_minutes"],
        "cycle_rule": r["cycle_rule"],
        "status": r["status"],
        "pc_authorized": r["pc_authorized"],
        "current_duty_status": r["current_duty_status"],
        "cycle_on_duty_minutes": r["cycle_on_duty_minutes"],
    }


def vehicle_view(r):
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
        "unit_number": r["unit_number"],
        "vin": r["vin"],
        "status": r["status"],
    }


def device_view(r):
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
        "serial_number": r["serial_number"],
        "vehicle_id": r["vehicle_id"],
        "bound_driver_id": r["bound_driver_id"],
        "status": r["status"],
    }


def event_view(r):
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
        "driver_id": r["driver_id"],
        "device_id": r["device_id"],
        "vehicle_id": r["vehicle_id"],
        "duty_status": r["duty_status"],
        "special_driving_category": r["special_driving_category"],
        "event_time": r["event_time"],
        "duration_minutes": r["duration_minutes"],
        "record_status": r["record_status"],
        "compliance_disposition": r["compliance_disposition"],
        "edited_from_event_id": r["edited_from_event_id"],
        "annotation": r["annotation"],
    }


def daily_log_view(r):
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
        "driver_id": r["driver_id"],
        "log_date": r["log_date"],
        "total_driving_minutes": r["total_driving_minutes"],
        "total_on_duty_minutes": r["total_on_duty_minutes"],
        "total_off_duty_minutes": r["total_off_duty_minutes"],
        "certification_status": r["certification_status"],
        "certified_at": r["certified_at"],
    }


def violation_view(r):
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
        "driver_id": r["driver_id"],
        "trigger_event_id": r["trigger_event_id"],
        "violation_type": r["violation_type"],
        "overage_minutes": r["overage_minutes"],
        "status": r["status"],
        "resolution_note": r["resolution_note"],
    }


def adverse_claim_view(r):
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
        "driver_id": r["driver_id"],
        "log_date": r["log_date"],
        "reason": r["reason"],
        "narrative": r["narrative"],
        "status": r["status"],
    }


def pc_segment_view(r):
    # PersonalConveyanceSegment carries only id + created_at (no updated_at/version)
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "driver_id": r["driver_id"],
        "event_id": r["event_id"],
        "minutes_excluded": r["minutes_excluded"],
    }
