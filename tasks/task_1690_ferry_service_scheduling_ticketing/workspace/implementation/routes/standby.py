"""Standby queue endpoints (PRD §3.6)."""

from flask import Blueprint, request

from db import db, now_iso
from errors import (
    raise_error, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_SAILING_NOT_BOOKABLE,
    ERR_NOT_RESOURCE_OWNER, ERR_INVALID_PARTY_SPEC,
    ERR_VEHICLE_LENGTH_EXCEEDS, ERR_DUPLICATE,
)
from middleware import require_roles
from response import success_object
from services.calculations import touch
from services.serializers import serialize_standby_entry

bp = Blueprint("standby", __name__)


@bp.post("/ferry/sailings/<sailing_id>/standby-queue")
def join_standby(sailing_id):
    user_id, _role = require_roles("Customer")

    # Priority 3: path id
    sailing = db.sailings.get(sailing_id)
    if sailing is None:
        raise_error(ERR_NOT_FOUND, "Sailing not found")

    payload = request.get_json(silent=True) or {}

    # Priority 7: ownership
    customer_id = payload.get("customer_id")
    if customer_id != user_id:
        raise_error(ERR_NOT_RESOURCE_OWNER,
                    "customer_id must equal the acting customer's id")
    if db.customers.get(customer_id) is None:
        raise_error(ERR_NOT_FOUND, "Customer not found")

    # Priority 5: sailing posture
    if sailing["status"] != "OPEN_FOR_BOOKING":
        raise_error(ERR_SAILING_NOT_BOOKABLE,
                    "Sailing is not OPEN_FOR_BOOKING")

    # Priority 11: party spec (passenger_count >= 1 for standby entries)
    has_vehicle = bool(payload.get("has_vehicle"))
    passenger_count = payload.get("passenger_count")
    vehicle_length_feet = payload.get("vehicle_length_feet")
    if passenger_count is None or int(passenger_count) < 1:
        raise_error(ERR_INVALID_PARTY_SPEC,
                    "passenger_count must be at least 1 for standby entries")
    if has_vehicle:
        if vehicle_length_feet is None:
            raise_error(ERR_INVALID_PARTY_SPEC,
                        "vehicle_length_feet is required when has_vehicle is true")
        if int(vehicle_length_feet) < 1:
            raise_error(ERR_INVALID_PARTY_SPEC,
                        "vehicle_length_feet must be at least 1")

    # Priority 12: standby staging limit — over 60 ft rejected
    if has_vehicle and int(vehicle_length_feet) > 60:
        raise_error(ERR_VEHICLE_LENGTH_EXCEEDS,
                    "Standby vehicles longer than 60 feet cannot be staged")

    # Priority 16: one WAITING entry per customer per sailing
    for e in db.standby_entries.values():
        if (e["sailing_id"] == sailing_id and e["customer_id"] == customer_id
                and e["status"] == "WAITING"):
            raise_error(ERR_DUPLICATE,
                        "Customer already holds a WAITING standby entry for this sailing")

    ts = now_iso()
    entry = {
        "id": db.new_id(),
        "sailing_id": sailing_id,
        "customer_id": customer_id,
        "has_vehicle": has_vehicle,
        "vehicle_length_feet": int(vehicle_length_feet) if has_vehicle else None,
        "passenger_count": int(passenger_count),
        "priority_class": payload.get("priority_class"),
        "queued_at": ts,  # server-stamped join time; queue order key
        "status": "WAITING",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    db.standby_entries[entry["id"]] = entry
    return success_object(serialize_standby_entry(entry), status=201)


@bp.get("/ferry/standby-queue/<entry_id>")
def get_standby_entry(entry_id):
    require_roles("SchedulerAdmin", "TerminalAgent", "Customer")
    entry = db.standby_entries.get(entry_id)
    if entry is None:
        raise_error(ERR_NOT_FOUND, "Standby queue entry not found")
    return success_object(serialize_standby_entry(entry))


@bp.post("/ferry/standby-queue/<entry_id>/leave")
def leave_standby(entry_id):
    user_id, _role = require_roles("Customer")
    entry = db.standby_entries.get(entry_id)
    if entry is None:
        raise_error(ERR_NOT_FOUND, "Standby queue entry not found")

    # Priority 7: ownership
    if entry["customer_id"] != user_id:
        raise_error(ERR_NOT_RESOURCE_OWNER,
                    "Customer may only leave its own standby entries")

    # Priority 4: only WAITING may be left (§3.6)
    if entry["status"] != "WAITING":
        raise_error(ERR_INVALID_STATE,
                    f"Cannot leave a standby entry in status {entry['status']}")

    entry["status"] = "EXPIRED"
    touch(entry)
    return success_object(serialize_standby_entry(entry))
