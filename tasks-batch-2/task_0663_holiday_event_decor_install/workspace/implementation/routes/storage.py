"""StorageBay + StorageLot endpoints."""
from flask import Blueprint, request

import errors
from db import db, base_fields, public, touch
from middleware import get_identity, require_role
from response import success, list_success
from validation import (get_json_body, require_str, require_int,
                        require_datetime, parse_pagination, paginate, parse_iso)

bp = Blueprint("storage", __name__)


def _get_bay_or_404(bay_id):
    rec = db.storage_bays.get(bay_id)
    if rec is None:
        raise errors.not_found("Storage bay not found")
    return rec


def _get_lot_or_404(lot_id):
    rec = db.storage_lots.get(lot_id)
    if rec is None:
        raise errors.not_found("Storage lot not found")
    return rec


# ---------------------------------------------------------------------------
# Storage bays
# ---------------------------------------------------------------------------
@bp.post("/storage-bays")
def create_bay():
    _, role = get_identity()
    require_role(role, ["FieldSupervisor"])
    body = get_json_body()
    bay_code = require_str(body, "bay_code")
    capacity_units = require_int(body, "capacity_units", minimum=1)
    # bay_code uniqueness (priority 16)
    if any(b["bay_code"] == bay_code for b in db.storage_bays.values()):
        raise errors.duplicate_code("bay_code already exists")

    rec = base_fields()
    rec.update({
        "bay_code": bay_code,
        "capacity_units": capacity_units,
    })
    db.storage_bays[rec["id"]] = rec
    return success(public(rec), status=201)


@bp.get("/storage-bays/<id>")
def get_bay(id):
    _, role = get_identity()
    require_role(role, ["FieldSupervisor", "AccountManager", "PlatformAdmin"])
    rec = _get_bay_or_404(id)
    return success(public(rec))


# ---------------------------------------------------------------------------
# Storage lots
# ---------------------------------------------------------------------------
def _intervals_overlap(a_start, a_end, b_start, b_end):
    """Half-open [start, end) overlap test."""
    return a_start < b_end and b_start < a_end


def _capacity_exceeded(bay, new_start, new_end, new_units, exclude_lot_id=None):
    """A reservation must not push overlapping aggregate unit_count above the
    bay's capacity over the half-open [stored_from, released_on) interval.

    We check capacity at every interval boundary among overlapping active lots.
    Lots in RELEASED do not occupy the bay."""
    active = []
    for lot in db.storage_lots.values():
        if lot["id"] == exclude_lot_id:
            continue
        if lot["storage_bay_id"] != bay["id"]:
            continue
        if lot["status"] == "RELEASED":
            continue
        ls = parse_iso(lot["stored_from"])
        le = parse_iso(lot["released_on"])
        if ls is None or le is None:
            continue
        if _intervals_overlap(new_start, new_end, ls, le):
            active.append((ls, le, lot["unit_count"]))

    # candidate sample points: new_start and every overlapping lot's start that
    # falls within the new interval.
    points = {new_start}
    for ls, le, _ in active:
        if new_start <= ls < new_end:
            points.add(ls)
    for p in points:
        total = new_units
        for ls, le, units in active:
            if ls <= p < le:
                total += units
        if total > bay["capacity_units"]:
            return True
    return False


@bp.post("/storage-lots")
def create_lot():
    _, role = get_identity()
    require_role(role, ["FieldSupervisor"])
    body = get_json_body()
    contract_id = require_str(body, "contract_id")
    storage_bay_id = require_str(body, "storage_bay_id")
    unit_count = require_int(body, "unit_count", minimum=1)
    stored_from = require_datetime(body, "stored_from")
    released_on = require_datetime(body, "released_on")

    # body FK existence (priority 5) — before structural interval check (6)
    if contract_id not in db.contracts:
        raise errors.reference_not_found("contract_id does not exist")
    if storage_bay_id not in db.storage_bays:
        raise errors.reference_not_found("storage_bay_id does not exist")

    sf = parse_iso(stored_from)
    ro = parse_iso(released_on)
    # released_on must be strictly after stored_from (priority 6)
    if ro <= sf:
        raise errors.invalid_request("released_on must be strictly after stored_from")

    # aggregate capacity over interval (priority 13)
    bay = db.storage_bays[storage_bay_id]
    if _capacity_exceeded(bay, sf, ro, unit_count):
        raise errors.bay_capacity_exceeded()

    rec = base_fields()
    rec.update({
        "contract_id": contract_id,
        "storage_bay_id": storage_bay_id,
        "unit_count": unit_count,
        "stored_from": stored_from,
        "released_on": released_on,
        "status": "RESERVED",
    })
    db.storage_lots[rec["id"]] = rec
    return success(public(rec), status=201)


@bp.get("/storage-lots/<id>")
def get_lot(id):
    _, role = get_identity()
    require_role(role, ["FieldSupervisor", "AccountManager", "PlatformAdmin"])
    rec = _get_lot_or_404(id)
    return success(public(rec))


@bp.get("/storage-lots")
def list_lots():
    _, role = get_identity()
    require_role(role, ["FieldSupervisor", "AccountManager", "PlatformAdmin"])
    limit, offset = parse_pagination()
    contract_id = request.args.get("contract_id")
    storage_bay_id = request.args.get("storage_bay_id")
    status = request.args.get("status")
    records = list(db.storage_lots.values())
    if contract_id is not None:
        records = [r for r in records if r["contract_id"] == contract_id]
    if storage_bay_id is not None:
        records = [r for r in records if r["storage_bay_id"] == storage_bay_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, total = paginate(records, limit, offset)
    return list_success([public(r) for r in page], limit, offset, total)


@bp.post("/storage-lots/<id>/check-in")
def check_in_lot(id):
    _, role = get_identity()
    require_role(role, ["FieldSupervisor"])
    lot = _get_lot_or_404(id)
    if lot["status"] != "RESERVED":
        raise errors.invalid_state()
    contract = db.contracts.get(lot["contract_id"])
    if contract is None or contract["status"] not in ("SIGNED", "ACTIVE"):
        raise errors.invalid_state("Owning contract not SIGNED or ACTIVE")
    lot["status"] = "STORED"
    touch(lot)
    return success(public(lot))


@bp.post("/storage-lots/<id>/release")
def release_lot(id):
    _, role = get_identity()
    require_role(role, ["FieldSupervisor"])
    lot = _get_lot_or_404(id)
    if lot["status"] != "STORED":
        raise errors.invalid_state()
    lot["status"] = "RELEASED"
    touch(lot)
    return success(public(lot))
