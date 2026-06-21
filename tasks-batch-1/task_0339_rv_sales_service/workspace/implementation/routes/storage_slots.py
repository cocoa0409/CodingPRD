"""Storage slot routes: booking (OCC), activation, release billing (PRD 3.10)."""

from flask import Blueprint, request

import db
import errors
import calculations as calc
from common import (body, new_entity, touch, require_int, require_bool, paginate,
                    get_or_404, find_dealership, parse_iso, invalid)
from middleware import get_auth, require_role
from response import ok, created, ok_list

bp = Blueprint("storage_slots", __name__)


def _overlaps(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


@bp.post("/storage-slots")
def book_slot():
    _, role = get_auth()
    require_role(role, {"ServiceAdvisor", "DealerManager"})
    data = body()
    did = data.get("dealership_id")
    find_dealership(did)
    unit = get_or_404("units", data.get("unit_id"))
    customer = get_or_404("customers", data.get("customer_id"))

    # OCC on Unit.version (priority 4) — before business rules.
    if "expected_unit_version" not in data or data.get("expected_unit_version") is None:
        invalid("expected_unit_version is required.")
    expected = data.get("expected_unit_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        invalid("expected_unit_version must be an integer.")
    if expected != unit["version"]:
        errors.err("ERR_STALE_UNIT_VERSION", "Unit version is stale.")

    daily_rate = require_int(data, "daily_rate_cents", minimum=0)
    winterized = require_bool(data, "winterized", default=False)
    start_dt = parse_iso(data.get("start_utc"), "start_utc")
    end_dt = parse_iso(data.get("end_utc"), "end_utc")
    if end_dt <= start_dt:
        errors.err("ERR_INVALID_INTERVAL", "end_utc must be strictly after start_utc.")

    # Storage overlap on the same unit, half-open, no buffer (priority 9).
    for slot in db.store["storage_slots"].values():
        if slot["unit_id"] != unit["id"] or slot["status"] == "CANCELLED":
            continue
        ex_start = parse_iso(slot["start_utc"], "start_utc")
        ex_end = parse_iso(slot["end_utc"], "end_utc")
        if _overlaps(start_dt, end_dt, ex_start, ex_end):
            errors.err("ERR_STORAGE_OVERLAP", "Storage interval overlaps an existing slot.")

    rec = new_entity({
        "dealership_id": did,
        "unit_id": unit["id"],
        "customer_id": customer["id"],
        "winterized": winterized,
        "daily_rate_cents": daily_rate,
        "start_utc": data["start_utc"],
        "end_utc": data["end_utc"],
        "billed_cents": None,
        "status": "BOOKED",
    })
    db.store["storage_slots"][rec["id"]] = rec
    # OCC-guarded write bumps the unit's version (PRD 3.10).
    touch(unit)
    return created(rec)


@bp.get("/storage-slots")
def list_slots():
    _, role = get_auth()
    require_role(role, {"DealerManager", "ServiceAdvisor"})
    items = list(db.store["storage_slots"].values())
    a = request.args
    for field in ("dealership_id", "unit_id", "customer_id", "status"):
        val = a.get(field)
        if val is not None:
            items = [s for s in items if s.get(field) == val]
    page, limit, offset, total = paginate(items)
    return ok_list(page, limit, offset, total)


@bp.get("/storage-slots/<slot_id>")
def get_slot(slot_id):
    user_id, role = get_auth()
    require_role(role, {"DealerManager", "ServiceAdvisor", "Customer"})
    rec = get_or_404("storage_slots", slot_id)
    if role == "Customer" and rec["customer_id"] != user_id:
        errors.err("ERR_STORAGE_SLOT_NOT_FOUND", "Storage slot not found.")
    return ok(rec)


@bp.post("/storage-slots/<slot_id>/activate")
def activate_slot(slot_id):
    _, role = get_auth()
    require_role(role, {"ServiceAdvisor"})
    slot = get_or_404("storage_slots", slot_id)
    if slot["status"] != "BOOKED":
        errors.err("ERR_STORAGE_BAD_STATE", "Storage slot is not BOOKED.")
    slot["status"] = "ACTIVE"
    touch(slot)
    return ok(slot)


@bp.post("/storage-slots/<slot_id>/release")
def release_slot(slot_id):
    _, role = get_auth()
    require_role(role, {"ServiceAdvisor", "DealerManager"})
    slot = get_or_404("storage_slots", slot_id)
    data = body()

    # State legality (priority 5) before field validation (priority 13).
    if slot["status"] != "ACTIVE":
        errors.err("ERR_STORAGE_BAD_STATE", "Storage slot is not ACTIVE.")

    released_dt = parse_iso(data.get("released_on_utc"), "released_on_utc")
    start_dt = parse_iso(slot["start_utc"], "start_utc")
    if released_dt < start_dt:
        errors.err("ERR_INVALID_RELEASE_TIME", "released_on_utc is before start_utc.")

    slot["billed_cents"] = calc.storage_charge(
        start_dt, released_dt, slot["daily_rate_cents"], slot["winterized"])
    slot["status"] = "RELEASED"
    touch(slot)
    return ok(slot)


@bp.post("/storage-slots/<slot_id>/cancel")
def cancel_slot(slot_id):
    _, role = get_auth()
    require_role(role, {"ServiceAdvisor", "DealerManager"})
    slot = get_or_404("storage_slots", slot_id)
    if slot["status"] != "BOOKED":
        errors.err("ERR_STORAGE_BAD_STATE", "Storage slot is not BOOKED.")
    slot["status"] = "CANCELLED"
    touch(slot)
    return ok(slot)
