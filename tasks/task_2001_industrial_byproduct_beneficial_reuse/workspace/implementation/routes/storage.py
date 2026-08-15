"""Storage facilities and reservations."""
from datetime import timedelta

from flask import Blueprint, request

from common import (ApiError, actor, as_date, as_dec, as_int, as_str,
                    bad_request, body_dict, created, fk_not_found,
                    invalid_state, not_found, ok, ok_list, paginate, ser)
from logic import D0, MATERIALS, current_date, new_record, sorted_items, touch
from store import db

bp = Blueprint("storage", __name__)


def as_material_list(body, name):
    if name not in body or body[name] is None:
        bad_request(f"Missing required field: {name}")
    v = body[name]
    if not isinstance(v, list) or not all(
            isinstance(x, str) and x in MATERIALS for x in v):
        bad_request(f"Field {name} must be an array of material types")
    return v


@bp.post("/api/storage-facilities")
def create_facility():
    actor({"BrokerOps"})
    body = body_dict()
    state_code = as_str(body, "state_code")
    materials = as_material_list(body, "material_types_allowed")
    capacity = as_int(body, "capacity_tons")
    if capacity <= 0:
        bad_request("capacity_tons must be positive")
    rec = new_record()
    rec.update(state_code=state_code, material_types_allowed=materials,
               capacity_tons=capacity, current_inventory_tons=D0)
    db.facilities[rec["id"]] = rec
    return created(ser(rec))


@bp.get("/api/storage-facilities/<fid>")
def get_facility(fid):
    actor()
    rec = db.facilities.get(fid)
    if rec is None:
        not_found("Storage facility not found")
    return ok(ser(rec))


# ---------------------------------------------------------------------------
# Reservations
# ---------------------------------------------------------------------------

def _capacity_ok(facility, start, end, tons):
    """storage_overlap_capacity: per-day half-open aggregate, equality allowed."""
    daily = {}
    for r in db.reservations.values():
        if r["facility_id"] != facility["id"]:
            continue
        if r["status"] not in ("RESERVED", "CHECKED_IN"):
            continue
        lo = max(r["start_date"], start)
        hi = min(r["end_date"], end)
        day = lo
        while day < hi:
            daily[day] = daily.get(day, D0) + r["tons"]
            day += timedelta(days=1)
    for total in daily.values():
        if total + tons > facility["capacity_tons"]:
            return False
    return True


@bp.post("/api/storage-reservations")
def create_reservation():
    actor({"BrokerOps"})
    body = body_dict()
    facility_id = as_str(body, "facility_id")
    stream_id = as_str(body, "stream_id")
    start = as_date(body, "start_date")
    end = as_date(body, "end_date")
    tons = as_dec(body, "tons")
    if tons <= D0:
        bad_request("tons must be > 0")
    facility = db.facilities.get(facility_id)
    if facility is None:
        fk_not_found("facility_id does not resolve to a StorageFacility")
    stream = db.streams.get(stream_id)
    if stream is None:
        fk_not_found("stream_id does not resolve to a ByproductStream")
    # stage 10 temporal
    if end <= start:
        raise ApiError("ERR_RESERVATION_WINDOW_INVALID", 422,
                       "end_date must be after start_date")
    # stage 11 constraints: material then capacity
    if stream["material_type"] not in facility["material_types_allowed"]:
        raise ApiError("ERR_MATERIAL_NOT_ACCEPTED", 422,
                       "Facility does not accept this material type")
    if not _capacity_ok(facility, start, end, tons):
        raise ApiError("ERR_STORAGE_CAPACITY_EXCEEDED", 422,
                       "Per-day aggregate would exceed facility capacity")
    rec = new_record()
    rec.update(facility_id=facility_id, stream_id=stream_id,
               start_date=start, end_date=end, tons=tons, status="RESERVED")
    db.reservations[rec["id"]] = rec
    return created(ser(rec))


@bp.get("/api/storage-reservations")
def list_reservations():
    actor()
    items = sorted_items(db.reservations.values())
    fid = request.args.get("facility_id")
    sid = request.args.get("stream_id")
    st = request.args.get("status")
    if fid is not None:
        items = [r for r in items if r["facility_id"] == fid]
    if sid is not None:
        items = [r for r in items if r["stream_id"] == sid]
    if st is not None:
        items = [r for r in items if r["status"] == st]
    page, meta = paginate(items)
    return ok_list([ser(r) for r in page], meta)


@bp.get("/api/storage-reservations/<rid>")
def get_reservation(rid):
    actor()
    rec = db.reservations.get(rid)
    if rec is None:
        not_found("Storage reservation not found")
    return ok(ser(rec))


def _load_reservation(rid):
    rec = db.reservations.get(rid)
    if rec is None:
        not_found("Storage reservation not found")
    return rec


@bp.post("/api/storage-reservations/<rid>/check-in")
def check_in_reservation(rid):
    actor({"BrokerOps"})
    rec = _load_reservation(rid)
    if rec["status"] != "RESERVED":
        invalid_state()
    today = current_date()
    if not (rec["start_date"] <= today < rec["end_date"]):
        raise ApiError("ERR_RESERVATION_WINDOW_INVALID", 422,
                       "Check-in outside the reservation window")
    rec["status"] = "CHECKED_IN"
    touch(rec)
    facility = db.facilities.get(rec["facility_id"])
    if facility is not None:
        facility["current_inventory_tons"] += rec["tons"]
        touch(facility)
    return ok(ser(rec))


@bp.post("/api/storage-reservations/<rid>/release")
def release_reservation(rid):
    actor({"BrokerOps"})
    rec = _load_reservation(rid)
    if rec["status"] != "CHECKED_IN":
        invalid_state()
    rec["status"] = "RELEASED"
    touch(rec)
    facility = db.facilities.get(rec["facility_id"])
    if facility is not None:
        facility["current_inventory_tons"] -= rec["tons"]
        touch(facility)
    return ok(ser(rec))


@bp.post("/api/storage-reservations/<rid>/cancel")
def cancel_reservation(rid):
    actor({"BrokerOps"})
    rec = _load_reservation(rid)
    if rec["status"] != "RESERVED":
        invalid_state()
    rec["status"] = "CANCELLED"
    touch(rec)
    return ok(ser(rec))
