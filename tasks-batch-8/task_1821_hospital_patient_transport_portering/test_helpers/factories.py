"""Payload factories — one per entity, client-supplied (input) fields only.

Optional fields are omitted from the payload when left as None so the server
applies its documented defaults (PRD §3.2, §3.3).
"""


def create_location_payload(code, name, location_type, zone_code, **overrides):
    payload = {
        "code": code,
        "name": name,
        "location_type": location_type,
        "zone_code": zone_code,
    }
    payload.update(overrides)
    return payload


def create_travel_edge_payload(from_location_id, to_location_id, base_minutes,
                               airborne_minutes, **overrides):
    payload = {
        "from_location_id": from_location_id,
        "to_location_id": to_location_id,
        "base_minutes": base_minutes,
        "airborne_minutes": airborne_minutes,
    }
    payload.update(overrides)
    return payload


def create_transporter_payload(name, home_location_id, certified_equipment=None,
                               oxygen_certified=None, isolation_certified=None,
                               **overrides):
    payload = {"name": name, "home_location_id": home_location_id}
    if certified_equipment is not None:
        payload["certified_equipment"] = certified_equipment
    if oxygen_certified is not None:
        payload["oxygen_certified"] = oxygen_certified
    if isolation_certified is not None:
        payload["isolation_certified"] = isolation_certified
    payload.update(overrides)
    return payload


def create_equipment_asset_payload(asset_tag, equipment_type, current_location_id,
                                   **overrides):
    payload = {
        "asset_tag": asset_tag,
        "equipment_type": equipment_type,
        "current_location_id": current_location_id,
    }
    payload.update(overrides)
    return payload


def create_request_payload(patient_ref, origin_location_id, destination_location_id,
                           priority, required_equipment, oxygen_required=None,
                           isolation_precaution=None, scheduled_pickup_time=None,
                           appointment_deadline=None, **overrides):
    payload = {
        "patient_ref": patient_ref,
        "origin_location_id": origin_location_id,
        "destination_location_id": destination_location_id,
        "priority": priority,
        "required_equipment": required_equipment,
    }
    if oxygen_required is not None:
        payload["oxygen_required"] = oxygen_required
    if isolation_precaution is not None:
        payload["isolation_precaution"] = isolation_precaution
    if scheduled_pickup_time is not None:
        payload["scheduled_pickup_time"] = scheduled_pickup_time
    if appointment_deadline is not None:
        payload["appointment_deadline"] = appointment_deadline
    payload.update(overrides)
    return payload


def create_offer_payload(expected_request_version, transporter_id=None, **overrides):
    payload = {"expected_request_version": expected_request_version}
    if transporter_id is not None:
        payload["transporter_id"] = transporter_id
    payload.update(overrides)
    return payload


def create_close_payload(action, reason=None, duplicate_of_id=None, **overrides):
    payload = {"action": action}
    if reason is not None:
        payload["reason"] = reason
    if duplicate_of_id is not None:
        payload["duplicate_of_id"] = duplicate_of_id
    payload.update(overrides)
    return payload


def create_trip_event_payload(event, cause_code=None, **overrides):
    payload = {"event": event}
    if cause_code is not None:
        payload["cause_code"] = cause_code
    payload.update(overrides)
    return payload


def create_cleaning_advance_payload(to_state, note=None, **overrides):
    payload = {"to_state": to_state}
    if note is not None:
        payload["note"] = note
    payload.update(overrides)
    return payload


def create_shift_payload(transporter_id, shift_start, shift_end, **overrides):
    payload = {
        "transporter_id": transporter_id,
        "shift_start": shift_start,
        "shift_end": shift_end,
    }
    payload.update(overrides)
    return payload


def create_demand_curve_payload(day_type, hour_block, priority, expected_requests,
                                mean_service_minutes, **overrides):
    payload = {
        "day_type": day_type,
        "hour_block": hour_block,
        "priority": priority,
        "expected_requests": expected_requests,
        "mean_service_minutes": mean_service_minutes,
    }
    payload.update(overrides)
    return payload
