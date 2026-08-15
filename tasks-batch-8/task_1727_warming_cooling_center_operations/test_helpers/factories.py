"""Payload factories — one per entity, input fields only (PRD §4)."""
from .constants import (
    DEFAULT_COOLING_THRESHOLD_F,
    DEFAULT_SCHEDULED_END,
    DEFAULT_SITE,
    DEFAULT_SUSTAINED_HOURS,
    DEFAULT_TURNAROUND_MINUTES,
)


def create_episode_payload(mode="COOLING", threshold_f=DEFAULT_COOLING_THRESHOLD_F,
                           sustained_hours_required=DEFAULT_SUSTAINED_HOURS,
                           scheduled_end_at=DEFAULT_SCHEDULED_END, **overrides):
    payload = {
        "mode": mode,
        "threshold_f": threshold_f,
        "sustained_hours_required": sustained_hours_required,
        "scheduled_end_at": scheduled_end_at,
    }
    payload.update(overrides)
    return payload


def weather_reading_payload(observed_at, temp_f=95.0, heat_index_f=101.0, source=None):
    payload = {
        "observed_at": observed_at,
        "temp_f": temp_f,
        "heat_index_f": heat_index_f,
    }
    if source is not None:
        payload["source"] = source
    return payload


def create_site_payload(name=DEFAULT_SITE["name"], address=DEFAULT_SITE["address"],
                        bed_capacity=DEFAULT_SITE["bed_capacity"],
                        pet_capacity=DEFAULT_SITE["pet_capacity"],
                        locker_capacity=DEFAULT_SITE["locker_capacity"], **overrides):
    payload = {
        "name": name,
        "address": address,
        "bed_capacity": bed_capacity,
        "pet_capacity": pet_capacity,
        "locker_capacity": locker_capacity,
    }
    payload.update(overrides)
    return payload


def site_patch_payload(expected_site_version, **fields):
    payload = {"expected_site_version": expected_site_version}
    payload.update(fields)
    return payload


def create_site_activation_payload(site_id, capacity_override=None):
    payload = {"site_id": site_id}
    if capacity_override is not None:
        payload["capacity_override"] = capacity_override
    return payload


def create_staff_member_payload(full_name, skills, active=None):
    payload = {"full_name": full_name, "skills": list(skills)}
    if active is not None:
        payload["active"] = active
    return payload


def create_shift_payload(staff_member_id, role_on_shift, start_at, end_at):
    return {
        "staff_member_id": staff_member_id,
        "role_on_shift": role_on_shift,
        "start_at": start_at,
        "end_at": end_at,
    }


def create_guest_payload(alias, has_pets=None, pet_count=None, bag_count=None,
                         medical_flag=None):
    payload = {"alias": alias}
    if has_pets is not None:
        payload["has_pets"] = has_pets
    if pet_count is not None:
        payload["pet_count"] = pet_count
    if bag_count is not None:
        payload["bag_count"] = bag_count
    if medical_flag is not None:
        payload["medical_flag"] = medical_flag
    return payload


def create_stay_payload(guest_id):
    return {"guest_id": guest_id}


def transfer_stay_payload(target_site_activation_id):
    return {"target_site_activation_id": target_site_activation_id}


def create_vehicle_payload(label="van-1", seats=4,
                           turnaround_minutes=DEFAULT_TURNAROUND_MINUTES):
    return {
        "label": label,
        "seats": seats,
        "turnaround_minutes": turnaround_minutes,
    }


def create_dispatch_payload(site_activation_id, guest_ids, pickup_window_start,
                            pickup_window_end, has_pets=None):
    payload = {
        "site_activation_id": site_activation_id,
        "guest_ids": list(guest_ids),
        "pickup_window_start": pickup_window_start,
        "pickup_window_end": pickup_window_end,
    }
    if has_pets is not None:
        payload["has_pets"] = has_pets
    return payload


def assign_dispatch_payload(vehicle_id):
    return {"vehicle_id": vehicle_id}


def create_donation_payload(partner_name="FoodBank", category="MEAL", quantity=10):
    return {
        "partner_name": partner_name,
        "category": category,
        "quantity": quantity,
    }


def create_meal_service_payload(service_date, meal_period):
    return {"service_date": service_date, "meal_period": meal_period}


def serve_meal_payload(served_count):
    return {"served_count": served_count}


def create_incident_payload(site_activation_id, kind, severity, guest_id=None):
    payload = {
        "site_activation_id": site_activation_id,
        "kind": kind,
        "severity": severity,
    }
    if guest_id is not None:
        payload["guest_id"] = guest_id
    return payload


def resolve_incident_payload(resolution_note):
    return {"resolution_note": resolution_note}


def extension_payload(new_scheduled_end_at, expected_episode_version):
    return {
        "new_scheduled_end_at": new_scheduled_end_at,
        "expected_episode_version": expected_episode_version,
    }
