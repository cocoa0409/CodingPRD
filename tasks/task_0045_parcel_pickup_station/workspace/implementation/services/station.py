"""Station + Staff service."""
import re
from db import store, GLOBAL_LOCK
from errors import E, raise_error
from services.common import stamp_create, bump, check_version_occ


HHMM_RE = re.compile(r"^[0-2][0-9]:[0-5][0-9]$")


def _hhmm_to_minutes(s: str) -> int:
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def _validate_hhmm(label, value):
    if not isinstance(value, str) or not HHMM_RE.match(value):
        raise_error(E.VALIDATION, f"{label} must be HH:MM 24h")


def create_station(body: dict):
    name = body.get("name")
    address = body.get("address")
    open_t = body.get("business_hours_open")
    close_t = body.get("business_hours_close")
    capacity = body.get("storage_capacity")
    fsh = body.get("free_storage_hours", 72)

    if not isinstance(name, str) or not (1 <= len(name) <= 100):
        raise_error(E.VALIDATION, "name length 1..100")
    if not isinstance(address, str) or address == "":
        raise_error(E.VALIDATION, "address required")
    _validate_hhmm("business_hours_open", open_t)
    _validate_hhmm("business_hours_close", close_t)
    if _hhmm_to_minutes(close_t) <= _hhmm_to_minutes(open_t):
        raise_error(E.VALIDATION, "business_hours_close must be > open")
    if not isinstance(capacity, int) or capacity < 1:
        raise_error(E.VALIDATION, "storage_capacity must be int >= 1")
    if fsh is None:
        fsh = 72
    if not isinstance(fsh, int) or fsh < 1:
        raise_error(E.VALIDATION, "free_storage_hours must be int >= 1")

    with GLOBAL_LOCK:
        row = stamp_create({
            "name": name,
            "address": address,
            "business_hours_open": open_t,
            "business_hours_close": close_t,
            "storage_capacity": capacity,
            "free_storage_hours": fsh,
            "status": "ACTIVE",
            "current_occupancy": 0,
            "quality_score": None,
        })
        store.stations[row["id"]] = row
        return row


def get_station(station_id, allow_not_found=False):
    s = store.stations.get(station_id)
    if s is None and not allow_not_found:
        raise_error(E.RESOURCE_NOT_FOUND, "Station not found")
    return s


def update_station(station_id, body):
    station = get_station(station_id, allow_not_found=False)
    with GLOBAL_LOCK:
        check_version_occ(station, body)

        if "name" in body and body["name"] is not None:
            if not isinstance(body["name"], str) or not (1 <= len(body["name"]) <= 100):
                raise_error(E.VALIDATION, "name length 1..100")
            station["name"] = body["name"]
        if "address" in body and body["address"] is not None:
            if not isinstance(body["address"], str):
                raise_error(E.VALIDATION, "address must be string")
            station["address"] = body["address"]
        new_open = body.get("business_hours_open", station["business_hours_open"])
        new_close = body.get("business_hours_close", station["business_hours_close"])
        if "business_hours_open" in body and body["business_hours_open"] is not None:
            _validate_hhmm("business_hours_open", new_open)
        if "business_hours_close" in body and body["business_hours_close"] is not None:
            _validate_hhmm("business_hours_close", new_close)
        if _hhmm_to_minutes(new_close) <= _hhmm_to_minutes(new_open):
            raise_error(E.VALIDATION, "close must be > open")
        station["business_hours_open"] = new_open
        station["business_hours_close"] = new_close

        if "storage_capacity" in body and body["storage_capacity"] is not None:
            cap = body["storage_capacity"]
            if not isinstance(cap, int) or cap < 1:
                raise_error(E.VALIDATION, "storage_capacity must be int >= 1")
            station["storage_capacity"] = cap
        if "free_storage_hours" in body and body["free_storage_hours"] is not None:
            fsh = body["free_storage_hours"]
            if not isinstance(fsh, int) or fsh < 1:
                raise_error(E.VALIDATION, "free_storage_hours must be int >= 1")
            station["free_storage_hours"] = fsh
        if "status" in body and body["status"] is not None:
            if body["status"] not in ("ACTIVE", "SUSPENDED", "CLOSED"):
                raise_error(E.VALIDATION, "status invalid")
            station["status"] = body["status"]

        bump(station)
        return station


# ---------- Staff ----------
def create_staff(station_id, body):
    get_station(station_id, allow_not_found=False)
    full_name = body.get("full_name")
    phone = body.get("phone")
    role_kind = body.get("role_kind")
    if not isinstance(full_name, str) or not full_name:
        raise_error(E.VALIDATION, "full_name required")
    if not isinstance(phone, str) or not phone.isdigit() or not (6 <= len(phone) <= 15):
        raise_error(E.VALIDATION, "phone must be 6..15 digits")
    if role_kind not in ("CLERK", "MANAGER"):
        raise_error(E.VALIDATION, "role_kind invalid")
    with GLOBAL_LOCK:
        row = stamp_create({
            "station_id": station_id,
            "full_name": full_name,
            "phone": phone,
            "role_kind": role_kind,
            "status": "ACTIVE",
        })
        store.staff[row["id"]] = row
        return row


def get_staff(staff_id, allow_not_found=False):
    s = store.staff.get(staff_id)
    if s is None and not allow_not_found:
        raise_error(E.RESOURCE_NOT_FOUND, "Staff not found")
    return s


def update_staff(staff_id, body):
    staff = get_staff(staff_id, allow_not_found=False)
    with GLOBAL_LOCK:
        check_version_occ(staff, body)
        if "status" in body and body["status"] is not None:
            if body["status"] not in ("ACTIVE", "OFF_DUTY", "TERMINATED"):
                raise_error(E.VALIDATION, "status invalid")
            staff["status"] = body["status"]
        if "role_kind" in body and body["role_kind"] is not None:
            if body["role_kind"] not in ("CLERK", "MANAGER"):
                raise_error(E.VALIDATION, "role_kind invalid")
            staff["role_kind"] = body["role_kind"]
        bump(staff)
        return staff
