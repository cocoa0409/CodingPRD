"""Unit + Bed endpoints, including the Bed turnover state machine."""

from flask import Blueprint

import errors
from errors import err
from db import store
from middleware import authenticate, authorize, get_json_body, parse_pagination
from response import success, list_success
from services import common, placement
from services.listing import paginate

bp = Blueprint("units", __name__)

UNIT_TYPES = {"MEDSURG", "TELEMETRY", "ICU", "ED"}
ROOM_TYPES = {"PRIVATE", "SEMIPRIVATE"}
BLOCKED_REASONS = {"MAINTENANCE", "STAFFING", "INFECTION_CONTROL"}
BED_STATUSES = {"CLEAN", "DIRTY", "OCCUPIED", "BLOCKED", "RETIRED"}

ALL_ROLES = {"FlowAdmin", "BedControlCoordinator", "ChargeNurse",
             "TransferCenterAgent", "CaseManager", "EvsTech"}


def _get_unit_or_404(unit_id):
    unit = store.units.get(unit_id)
    if unit is None:
        raise err(errors.ERR_NOT_FOUND, "Unit not found")
    return unit


def _get_bed_or_404(unit_id, bed_id):
    _get_unit_or_404(unit_id)
    bed = store.beds.get(bed_id)
    if bed is None or bed["unit_id"] != unit_id:
        raise err(errors.ERR_NOT_FOUND, "Bed not found")
    return bed


# ---------------------------------------------------------------------------
# Units
# ---------------------------------------------------------------------------
@bp.route("/units", methods=["POST"])
def create_unit():
    _, role = authenticate()
    authorize(role, {"FlowAdmin"})
    body = get_json_body()

    name = body.get("name")
    unit_type = body.get("unit_type")
    if not isinstance(name, str) or not name:
        raise err(errors.ERR_INVALID_REQUEST, "name is required")
    if unit_type not in UNIT_TYPES:
        raise err(errors.ERR_INVALID_REQUEST, "unit_type must be one of MEDSURG, TELEMETRY, ICU, ED")

    gmlos = body.get("gmlos_days", 3)
    if gmlos is None:
        gmlos = 3
    if not isinstance(gmlos, int) or isinstance(gmlos, bool):
        raise err(errors.ERR_INVALID_REQUEST, "gmlos_days must be an integer")

    unit = {
        "name": name,
        "unit_type": unit_type,
        "gmlos_days": gmlos,
        "total_bed_count": 0,
        "staffed_bed_count": 0,
        "occupied_bed_count": 0,
        "clean_available_count": 0,
        "occupancy_pct": 0.00,
        "derived_posture": "CLOSED",
        "declared_surge_level": "GREEN",
        "effective_posture": "CLOSED",
    }
    common.stamp_new(unit)
    common.recompute_unit(unit)
    store.units[unit["id"]] = unit
    return success(common.serialize_unit(unit), status=201)


@bp.route("/units/<unit_id>", methods=["GET"])
def get_unit(unit_id):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    unit = _get_unit_or_404(unit_id)
    return success(common.serialize_unit(unit))


@bp.route("/units", methods=["GET"])
def list_units():
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    limit, offset = parse_pagination()
    page, total = paginate(list(store.units.values()), limit, offset)
    return list_success([common.serialize_unit(u) for u in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Beds
# ---------------------------------------------------------------------------
@bp.route("/units/<unit_id>/beds", methods=["POST"])
def create_bed(unit_id):
    _, role = authenticate()
    authorize(role, {"FlowAdmin", "ChargeNurse"})
    unit = _get_unit_or_404(unit_id)
    body = get_json_body()

    # body FK existence: unit_id (when supplied) must resolve
    body_unit_id = body.get("unit_id")
    if body_unit_id is not None and body_unit_id not in store.units:
        raise err(errors.ERR_REFERENCE_NOT_FOUND, "unit_id does not resolve")

    label = body.get("label")
    if not isinstance(label, str) or not label:
        raise err(errors.ERR_INVALID_REQUEST, "label is required")

    room_type = body.get("room_type", "SEMIPRIVATE")
    if room_type is None:
        room_type = "SEMIPRIVATE"
    if room_type not in ROOM_TYPES:
        raise err(errors.ERR_INVALID_REQUEST, "room_type must be PRIVATE or SEMIPRIVATE")

    iso_cap = body.get("isolation_capable", False)
    tele_cap = body.get("telemetry_capable", False)
    if iso_cap is None:
        iso_cap = False
    if tele_cap is None:
        tele_cap = False
    if not isinstance(iso_cap, bool):
        raise err(errors.ERR_INVALID_REQUEST, "isolation_capable must be boolean")
    if not isinstance(tele_cap, bool):
        raise err(errors.ERR_INVALID_REQUEST, "telemetry_capable must be boolean")

    bed = {
        "unit_id": unit_id,
        "label": label,
        "room_type": room_type,
        "isolation_capable": iso_cap,
        "telemetry_capable": tele_cap,
        "status": "DIRTY",
        "sex_cohort": "NONE",
        "current_encounter_id": None,
        "blocked_reason": None,
    }
    common.stamp_new(bed)
    store.beds[bed["id"]] = bed
    common.recompute_unit(unit)
    return success(common.serialize_bed(bed), status=201)


@bp.route("/units/<unit_id>/beds/<bed_id>", methods=["GET"])
def get_bed(unit_id, bed_id):
    _, role = authenticate()
    authorize(role, {"FlowAdmin", "BedControlCoordinator", "ChargeNurse",
                     "TransferCenterAgent", "EvsTech"})
    bed = _get_bed_or_404(unit_id, bed_id)
    return success(common.serialize_bed(bed))


@bp.route("/units/<unit_id>/beds", methods=["GET"])
def list_beds(unit_id):
    from flask import request
    _, role = authenticate()
    authorize(role, {"FlowAdmin", "BedControlCoordinator", "ChargeNurse",
                     "TransferCenterAgent", "EvsTech"})
    _get_unit_or_404(unit_id)
    limit, offset = parse_pagination()
    status_filter = request.args.get("status")
    if status_filter is not None and status_filter not in BED_STATUSES:
        raise err(errors.ERR_INVALID_REQUEST, "invalid status filter")
    beds = [b for b in store.beds.values() if b["unit_id"] == unit_id]
    if status_filter is not None:
        beds = [b for b in beds if b["status"] == status_filter]
    page, total = paginate(beds, limit, offset)
    return list_success([common.serialize_bed(b) for b in page], limit, offset, total)


@bp.route("/units/<unit_id>/beds/<bed_id>/mark-clean", methods=["POST"])
def mark_clean(unit_id, bed_id):
    _, role = authenticate()
    authorize(role, {"ChargeNurse", "EvsTech"})
    bed = _get_bed_or_404(unit_id, bed_id)
    if bed["status"] != "DIRTY":
        raise err(errors.ERR_INVALID_STATE, "Bed is not DIRTY")
    # DIRTY -> CLEAN: cohort preserved; cancel any open EvsTask for this bed.
    bed["status"] = "CLEAN"
    common.touch(bed)
    placement.cancel_open_evs_tasks_for_bed(bed_id)
    common.recompute_unit(store.units[unit_id])
    return success(common.serialize_bed(bed))


@bp.route("/units/<unit_id>/beds/<bed_id>/block", methods=["POST"])
def block_bed(unit_id, bed_id):
    _, role = authenticate()
    authorize(role, {"ChargeNurse", "FlowAdmin"})
    bed = _get_bed_or_404(unit_id, bed_id)
    body = get_json_body()

    # State legality first (must be CLEAN or DIRTY for the block transition).
    if bed["status"] not in ("CLEAN", "DIRTY"):
        # An OCCUPIED bed gets the dedicated ERR_BED_OCCUPIED; other states are invalid-state.
        if bed["status"] == "OCCUPIED":
            raise err(errors.ERR_BED_OCCUPIED, "Cannot block an OCCUPIED bed")
        raise err(errors.ERR_INVALID_STATE, "Bed cannot be blocked from this state")

    reason = body.get("blocked_reason")
    if reason is None:
        raise err(errors.ERR_BED_OCCUPIED, "blocked_reason is required")
    if reason not in BLOCKED_REASONS:
        raise err(errors.ERR_INVALID_REQUEST,
                  "blocked_reason must be one of MAINTENANCE, STAFFING, INFECTION_CONTROL")

    was_dirty = bed["status"] == "DIRTY"
    bed["status"] = "BLOCKED"
    bed["blocked_reason"] = reason
    common.touch(bed)
    if was_dirty:
        placement.cancel_open_evs_tasks_for_bed(bed_id)
    common.recompute_unit(store.units[unit_id])
    return success(common.serialize_bed(bed))


@bp.route("/units/<unit_id>/beds/<bed_id>/unblock", methods=["POST"])
def unblock_bed(unit_id, bed_id):
    _, role = authenticate()
    authorize(role, {"ChargeNurse", "FlowAdmin"})
    bed = _get_bed_or_404(unit_id, bed_id)
    if bed["status"] != "BLOCKED":
        raise err(errors.ERR_INVALID_STATE, "Bed is not BLOCKED")
    bed["status"] = "DIRTY"
    bed["blocked_reason"] = None
    bed["sex_cohort"] = "NONE"  # deep room turnover clears cohort
    common.touch(bed)
    common.recompute_unit(store.units[unit_id])
    return success(common.serialize_bed(bed))


@bp.route("/units/<unit_id>/beds/<bed_id>/retire", methods=["POST"])
def retire_bed(unit_id, bed_id):
    _, role = authenticate()
    authorize(role, {"FlowAdmin"})
    bed = _get_bed_or_404(unit_id, bed_id)
    if bed["status"] != "BLOCKED":
        raise err(errors.ERR_INVALID_STATE, "Bed is not BLOCKED")
    bed["status"] = "RETIRED"
    common.touch(bed)
    common.recompute_unit(store.units[unit_id])
    return success(common.serialize_bed(bed))
