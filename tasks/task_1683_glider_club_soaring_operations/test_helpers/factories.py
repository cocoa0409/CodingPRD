"""Payload factories — one per creatable resource, input fields only (PRD §3)."""
from .constants import DEFAULT_ANNUAL_DUE

DEFAULTS = {
    "TIER_CODE": "STANDARD",
    "FULL_NAME": "Test Member",
    "REGISTRATION": "N100G",
}


def tier_payload(**overrides) -> dict:
    defaults = {
        "tier_code": DEFAULTS["TIER_CODE"],
        "monthly_dues_cents": 0,
        "tow_fee_discount_pct": 0.0,
        "included_tows_per_month": 0,
        "student_tier": False,
    }
    defaults.update(overrides)
    return defaults


def member_payload(tier_id: str, **overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["FULL_NAME"],
        "tier_id": tier_id,
    }
    defaults.update(overrides)
    return defaults


def aircraft_payload(**overrides) -> dict:
    defaults = {
        "registration": DEFAULTS["REGISTRATION"],
        "kind": "GLIDER",
        "annual_due_date": DEFAULT_ANNUAL_DUE,
    }
    defaults.update(overrides)
    return defaults


def availability_payload(instructor_id: str, start_at: str, end_at: str) -> dict:
    return {"instructor_id": instructor_id, "start_at": start_at, "end_at": end_at}


def reservation_payload(
    aircraft_id: str,
    member_id: str,
    start_at: str,
    end_at: str,
    expected_aircraft_version: int,
    instructor_id: str = None,
) -> dict:
    payload = {
        "aircraft_id": aircraft_id,
        "member_id": member_id,
        "start_at": start_at,
        "end_at": end_at,
        "expected_aircraft_version": expected_aircraft_version,
    }
    if instructor_id is not None:
        payload["instructor_id"] = instructor_id
    return payload


def tow_slot_payload(
    tow_plane_id: str, tow_pilot_id: str, start_at: str, end_at: str, capacity: int
) -> dict:
    return {
        "tow_plane_id": tow_plane_id,
        "tow_pilot_id": tow_pilot_id,
        "start_at": start_at,
        "end_at": end_at,
        "capacity": capacity,
    }


def flight_payload(
    reservation_id: str,
    tow_slot_id: str,
    release_altitude_ft: int,
    takeoff_at: str,
    expected_tow_slot_version: int,
) -> dict:
    return {
        "reservation_id": reservation_id,
        "tow_slot_id": tow_slot_id,
        "release_altitude_ft": release_altitude_ft,
        "takeoff_at": takeoff_at,
        "expected_tow_slot_version": expected_tow_slot_version,
    }


def maintenance_payload(
    kind: str, performed_at: str, hobbs_hours_at_service: float, notes: str = None
) -> dict:
    payload = {
        "kind": kind,
        "performed_at": performed_at,
        "hobbs_hours_at_service": hobbs_hours_at_service,
    }
    if notes is not None:
        payload["notes"] = notes
    return payload


def duty_slot_payload(duty_date: str, member_id: str) -> dict:
    return {"duty_date": duty_date, "member_id": member_id}


def progress_payload(student_id: str, instructor_id: str, kind: str) -> dict:
    return {"student_id": student_id, "instructor_id": instructor_id, "kind": kind}


def retrieve_payload(flight_id: str, distance_km: float) -> dict:
    return {"flight_id": flight_id, "distance_km": distance_km}


def clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}


def payment_payload(amount_cents: int) -> dict:
    return {"amount_cents": amount_cents}


def land_payload(landed_at: str) -> dict:
    return {"landed_at": landed_at}


def tier_change_payload(tier_id: str) -> dict:
    return {"tier_id": tier_id}


def swap_payload(swap_with_slot_id: str) -> dict:
    return {"swap_with_slot_id": swap_with_slot_id}


def crew_payload(crew_member_id: str) -> dict:
    return {"crew_member_id": crew_member_id}
