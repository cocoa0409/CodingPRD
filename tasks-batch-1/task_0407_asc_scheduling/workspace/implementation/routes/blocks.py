"""SurgeonBlock routes: create / confirm / release / book-case (PRD §3.4).

Booking is the OCC-guarded operation and runs the full validation precedence
of PRD §2.6 / §3.4-§3.7.
"""
from flask import Blueprint

from db import db, stamp_common, touch
from errors import err
from middleware import get_user_context, require_role
from response import success, list_response
from services.helpers import (
    lookup, get_body, require_str, require_int, require_positive_int,
    optional_bool, paginate, sorted_by_created, ser_default,
)
from services.calculations import estimated_case_cost, recompute_day
from services.case_ops import cancel_case_effects

bp = Blueprint("blocks", __name__)

ALL_ROLES = {"Scheduler", "PreOpNurse", "ORManager", "BillingAnalyst"}
ACTIVE_CASE_STATES = {"IN_OR", "IN_RECOVERY", "COMPLETED"}


def _block_cases(block_id):
    return [c for c in db.surgical_cases.values() if c["surgeon_block_id"] == block_id]


# ---------------------------------------------------------------- create block
@bp.route("/asc/surgeon-blocks", methods=["POST"])
def create_block():
    _, role = get_user_context()
    require_role(role, {"Scheduler"})
    body = get_body()
    day_id = require_str(body, "surgical_day_id")
    surgeon_id = require_str(body, "surgeon_id")
    or_id = require_str(body, "operating_room_id")
    day = lookup("surgical_days", day_id)
    surgeon = lookup("surgeons", surgeon_id)
    room = lookup("operating_rooms", or_id)

    start_min = require_int(body, "start_min")
    end_min = require_int(body, "end_min")
    if end_min <= start_min:
        raise err("ERR_INVALID_REQUEST", "end_min must be > start_min.")
    release_threshold = body.get("release_threshold_hours", 48)
    if isinstance(release_threshold, bool) or not isinstance(release_threshold, int):
        raise err("ERR_INVALID_REQUEST", "release_threshold_hours must be an integer.")

    rec = stamp_common({
        "facility_id": day["facility_id"],
        "surgical_day_id": day_id,
        "surgeon_id": surgeon_id,
        "operating_room_id": or_id,
        "start_min": start_min,
        "end_min": end_min,
        "allocated_minutes": end_min - start_min,
        "committed_minutes": 0,
        "release_threshold_hours": release_threshold,
        "status": "HELD",
    })
    db.surgeon_blocks[rec["id"]] = rec
    return success(ser_default(rec), status=201)


@bp.route("/asc/surgeon-blocks", methods=["GET"])
def list_blocks():
    _, role = get_user_context()
    require_role(role, ALL_ROLES)
    items = list(db.surgeon_blocks.values())
    for field in ("surgical_day_id", "surgeon_id", "operating_room_id", "facility_id"):
        v = _arg(field)
        if v is not None:
            items = [r for r in items if r.get(field) == v]
    items = sorted_by_created(items)
    page, limit, offset, total = paginate(items)
    return list_response([ser_default(r) for r in page], limit, offset, total)


@bp.route("/asc/surgeon-blocks/<block_id>", methods=["GET"])
def get_block(block_id):
    _, role = get_user_context()
    require_role(role, ALL_ROLES)
    return success(ser_default(lookup("surgeon_blocks", block_id)))


# --------------------------------------------------------------- confirm block
@bp.route("/asc/surgeon-blocks/<block_id>/confirm", methods=["POST"])
def confirm_block(block_id):
    _, role = get_user_context()
    require_role(role, {"Scheduler"})
    block = lookup("surgeon_blocks", block_id)
    if block["status"] != "HELD":
        raise err("ERR_BLOCK_NOT_HELD", "Block must be HELD to confirm.")
    surgeon = db.surgeons[block["surgeon_id"]]
    if not surgeon["active"]:
        raise err("ERR_SURGEON_INACTIVE", "Owning surgeon is inactive.")
    day = db.surgical_days[block["surgical_day_id"]]
    if day["posture"] == "CLOSED":
        raise err("ERR_DAY_CLOSED", "Owning day is CLOSED.")
    block["status"] = "CONFIRMED"
    touch(block)  # increments version by 1
    return success(ser_default(block))


# --------------------------------------------------------------- release block
@bp.route("/asc/surgeon-blocks/<block_id>/release", methods=["POST"])
def release_block(block_id):
    _, role = get_user_context()
    require_role(role, {"Scheduler"})
    block = lookup("surgeon_blocks", block_id)
    if block["status"] not in ("HELD", "CONFIRMED"):
        raise err("ERR_BLOCK_NOT_RELEASABLE", "Block must be HELD or CONFIRMED to release.")
    day = db.surgical_days[block["surgical_day_id"]]
    if day["posture"] == "CLOSED":
        raise err("ERR_DAY_CLOSED", "Owning day is CLOSED.")
    # Refuse if any case is already IN_OR/IN_RECOVERY/COMPLETED.
    cases = _block_cases(block_id)
    if any(c["case_status"] in ACTIVE_CASE_STATES for c in cases):
        raise err("ERR_BLOCK_HAS_ACTIVE_CASES",
                  "Block has a case IN_OR/IN_RECOVERY/COMPLETED.")

    block["status"] = "RELEASED"
    # Cascade depth-1: force-cancel every SCHEDULED case, ascending (start_min, created_at).
    scheduled = [c for c in cases if c["case_status"] == "SCHEDULED"]
    scheduled.sort(key=lambda c: (c["start_min"], c["_seq"]))
    for case in scheduled:
        cancel_case_effects(case)
    touch(block)  # increments version by 1
    return success(ser_default(block))


# --------------------------------------------------------------- book a case
@bp.route("/asc/surgeon-blocks/<block_id>/cases", methods=["POST"])
def book_case(block_id):
    _, role = get_user_context()
    require_role(role, {"Scheduler"})
    block = lookup("surgeon_blocks", block_id)
    body = get_body()

    # ---- Priority 4: body FK existence (same facility) ----
    patient_id = require_str(body, "patient_id")
    procedure_id = require_str(body, "procedure_id")
    patient = lookup("patients", patient_id)
    procedure = lookup("procedures", procedure_id)
    if patient["facility_id"] != block["facility_id"]:
        raise err("ERR_PATIENT_NOT_FOUND", "Patient not in block's facility.")
    if procedure["facility_id"] != block["facility_id"]:
        raise err("ERR_PROCEDURE_NOT_FOUND", "Procedure not in block's facility.")

    anesth_id = body.get("anesthesiologist_id")
    anesth = None
    if anesth_id is not None:
        anesth = lookup("anesthesiologists", anesth_id)
        if anesth["facility_id"] != block["facility_id"]:
            raise err("ERR_ANESTHESIOLOGIST_NOT_FOUND", "Anesthesiologist not in facility.")
    bay_id = body.get("recovery_bay_id")
    bay = None
    if bay_id is not None:
        bay = lookup("recovery_bays", bay_id)
        if bay["facility_id"] != block["facility_id"]:
            raise err("ERR_RECOVERY_BAY_NOT_FOUND", "Recovery bay not in facility.")

    # ---- Priority 5: body well-formed ----
    if body.get("expected_block_version") is None:
        raise err("ERR_INVALID_REQUEST", "expected_block_version is required.")
    expected_version = require_int(body, "expected_block_version")
    start_min = require_int(body, "start_min")
    is_add_on = optional_bool(body, "is_add_on", False)

    # ---- Priority 7: OCC (after existence, before state/business) ----
    if expected_version != block["version"]:
        raise err("ERR_STALE_BLOCK_VERSION",
                  "expected_block_version does not match current block version.")

    # ---- Priority 8: block state — released block cannot accept bookings ----
    if block["status"] == "RELEASED":
        raise err("ERR_BLOCK_RELEASED", "Block is RELEASED and cannot accept bookings.")

    day = db.surgical_days[block["surgical_day_id"]]

    scheduled_minutes = procedure["scheduled_minutes"]
    end_min = start_min + scheduled_minutes

    # ---- Priority 9: procedure not EXCLUDED ----
    if procedure["cms_payment_indicator"] == "EXCLUDED":
        raise err("ERR_PROCEDURE_EXCLUDED", "EXCLUDED procedures cannot be booked.")

    # ---- Priority 10: surgeon active ----
    surgeon = db.surgeons[block["surgeon_id"]]
    if not surgeon["active"]:
        raise err("ERR_SURGEON_INACTIVE", "Block surgeon is inactive.")

    # ---- Priority 11: non-add-on case footprint within block window ----
    if not is_add_on:
        if not (start_min >= block["start_min"] and end_min <= block["end_min"]):
            raise err("ERR_CASE_OUTSIDE_BLOCK_WINDOW",
                      "Case footprint must lie within the block window.")

    # ---- Priority 12: OR turnover conflict ----
    _check_or_conflict(day, block["operating_room_id"], start_min, end_min, exclude_case_id=None)

    # ---- Priority 13: anesthesia overlap conflict ----
    if anesth_id is not None:
        _check_anesthesia_conflict(day, anesth_id, start_min, end_min, exclude_case_id=None)

    # ---- Priority 14: CRNA cannot solo-cover GENERAL ----
    if anesth is not None:
        if anesth["credential"] == "CRNA" and procedure["anesthesia_class"] == "GENERAL":
            raise err("ERR_CRNA_CANNOT_COVER_GENERAL",
                      "CRNA may not solo-cover a GENERAL anesthesia case.")

    # ---- Priority 15: Phase II recovery requirement ----
    if bay is not None:
        if procedure["requires_phase2"] and not bay["phase2_capable"]:
            raise err("ERR_RECOVERY_PHASE2_REQUIRED",
                      "Procedure requires a Phase II-capable recovery bay.")

    # ---- Priority 18: block-minute capacity (non-add-on only) ----
    if not is_add_on:
        if block["committed_minutes"] + scheduled_minutes > block["allocated_minutes"]:
            raise err("ERR_BLOCK_CAPACITY_EXCEEDED",
                      "Booking would exceed the block's allocated minutes.")

    # ---- Priority 19: day-posture booking rule ----
    if is_add_on:
        if day["posture"] != "LOCKED":
            raise err("ERR_DAY_LOCKED", "Add-on bookings require the day to be LOCKED.")
    else:
        if day["posture"] in ("LOCKED", "CLOSED"):
            raise err("ERR_DAY_LOCKED", "Non-add-on booking rejected: day is LOCKED/CLOSED.")

    # ---- All guards pass: create the case ----
    case = stamp_common({
        "facility_id": block["facility_id"],
        "surgical_day_id": block["surgical_day_id"],
        "surgeon_block_id": block_id,
        "patient_id": patient_id,
        "procedure_id": procedure_id,
        "operating_room_id": block["operating_room_id"],
        "anesthesiologist_id": anesth_id,
        "recovery_bay_id": bay_id,
        "start_min": start_min,
        "scheduled_minutes": scheduled_minutes,
        "end_min": end_min,
        "is_add_on": is_add_on,
        "actual_minutes": None,
        "estimated_cost_cents": 0,
        "actual_cost_cents": None,
        "cms_payment_cents": None,
        "clearance_status": "PENDING_CLEARANCE",
        "hp_signed_at": None,
        "case_status": "SCHEDULED",
    })
    case["estimated_cost_cents"] = estimated_case_cost(case, procedure)
    db.surgical_cases[case["id"]] = case

    # Side effects: block committed_minutes += scheduled; recompute day; bump block version.
    block["committed_minutes"] += scheduled_minutes
    touch(block)  # increments version by 1
    recompute_day(day)
    touch(day)

    return success(ser_default(case), status=201)


# ---- conflict helpers (PRD §3.5) ----
def _check_or_conflict(day, or_id, start_min, end_min, exclude_case_id):
    """OR turnover conflict: next.start_min >= prev.end_min + turnover_minutes.

    Compatible iff a buffer of turnover_minutes separates the two footprints.
    """
    facility = db.facilities[day["facility_id"]]
    turnover = facility["turnover_minutes"]
    for c in db.surgical_cases.values():
        if c["surgical_day_id"] != day["id"]:
            continue
        if c["operating_room_id"] != or_id:
            continue
        if c["case_status"] == "CANCELLED":
            continue
        if exclude_case_id is not None and c["id"] == exclude_case_id:
            continue
        # Two cases compatible iff later.start >= earlier.end + turnover.
        if start_min >= c["end_min"] + turnover:
            continue
        if c["start_min"] >= end_min + turnover:
            continue
        raise err("ERR_OR_TIME_CONFLICT",
                  "Case overlaps another case (incl. turnover) in the same OR.")


def _check_anesthesia_conflict(day, anesth_id, start_min, end_min, exclude_case_id):
    """Anesthesia overlap (no buffer): conflict iff [start,end) intervals overlap."""
    for c in db.surgical_cases.values():
        if c["surgical_day_id"] != day["id"]:
            continue
        if c.get("anesthesiologist_id") != anesth_id:
            continue
        if c["case_status"] == "CANCELLED":
            continue
        if exclude_case_id is not None and c["id"] == exclude_case_id:
            continue
        if start_min < c["end_min"] and c["start_min"] < end_min:
            raise err("ERR_ANESTHESIA_TIME_CONFLICT",
                      "Case overlaps another case for the same anesthesiologist.")


def _arg(name):
    from flask import request
    return request.args.get(name)
