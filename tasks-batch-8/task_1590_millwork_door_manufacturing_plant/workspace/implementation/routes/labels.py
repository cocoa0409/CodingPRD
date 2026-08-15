"""LabelAllocation endpoints (PRD §3.6): serialized fire-label issuance and accounting."""

from flask import Blueprint, request

import db
from errors import err
from middleware import (get_context, require_role, raw_body, validate_fields,
                        req_string, req_int, require_existence)
from response import success, list_response, parse_pagination
from services import cascade

bp = Blueprint("labels", __name__)

ALLOCATION_STATUSES = ("ISSUED", "APPLIED", "VERIFIED", "VOIDED")
RATING_TO_SERIES = {"MIN_20": "UL_20MIN", "MIN_45": "UL_45MIN", "MIN_90": "UL_90MIN"}

TARGET_ACTORS = {
    "APPLIED": ("ProductionLead",),
    "VERIFIED": ("QAInspector",),
    "VOIDED": ("LabelAuthority",),
}
ALL_STATUS_ACTORS = ("ProductionLead", "QAInspector", "LabelAuthority")


def serialize(a):
    return {
        "id": a["id"],
        "opening_id": a["opening_id"],
        "roll_id": a["roll_id"],
        "serial_count": a["serial_count"],
        "issued_by": a["issued_by"],
        "applied_by": a["applied_by"],
        "verified_by": a["verified_by"],
        "status": a["status"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


@bp.post("/label-allocations")
def create_allocation():
    user_id, role = get_context()
    require_role(role, "LabelAuthority")
    body = raw_body()
    # Rung 3: body FK existence in declared input order.
    if body.get("opening_id") is not None:
        opening = require_existence(db.openings, body["opening_id"],
                                    "ERR_OPENING_NOT_FOUND", "Opening")
    else:
        opening = None
    if body.get("roll_id") is not None:
        roll = require_existence(db.fire_label_rolls, body["roll_id"],
                                 "ERR_ROLL_NOT_FOUND", "FireLabelRoll")
    else:
        roll = None
    # Rung 4: payload.
    validate_fields(body, required=("opening_id", "roll_id", "expected_roll_version"))
    expected = req_int(body, "expected_roll_version")
    # Rung 5 (OCC): expected_roll_version must equal the roll's current version.
    if expected != roll["version"]:
        raise err("ERR_STALE_ROLL_VERSION",
                  "expected_roll_version differs from the roll's current version")
    # Rung 6 (state gates, fixed order per PRD §2.5): rated before finish-passed.
    if opening["fire_rating"] == "NONE":
        raise err("ERR_OPENING_NOT_RATED", "Label issuance requires a rated opening")
    if opening["fab_status"] != "FINISHED":
        raise err("ERR_OPENING_NOT_FINISH_PASSED",
                  "Label issuance requires opening fab FINISHED")
    if roll["status"] != "ACTIVE":
        raise err("ERR_ROLL_NOT_ACTIVE", "Label issuance requires roll ACTIVE")
    # Rung 7 (safety): roll series must correspond to the opening's rating.
    if roll["label_series"] != RATING_TO_SERIES[opening["fire_rating"]]:
        raise err("ERR_LABEL_SERIES_MISMATCH",
                  "Roll label_series does not match the opening's fire rating")
    # Rung 8: single active allocation per opening.
    for existing in db.label_allocations.values():
        if existing["opening_id"] == opening["id"] and existing["status"] in ("ISSUED", "APPLIED", "VERIFIED"):
            raise err("ERR_ACTIVE_ALLOCATION_EXISTS",
                      "Opening already holds an active allocation")
    # Rung 11 (fiscal): the roll must have enough serials for one label per leaf.
    if roll["serials_available"] < opening["leaf_count"]:
        raise err("ERR_INSUFFICIENT_LABEL_SERIALS",
                  "Roll has insufficient available serials")
    rec = db.new_record()
    rec.update({
        "opening_id": opening["id"],
        "roll_id": roll["id"],
        "serial_count": opening["leaf_count"],
        "issued_by": user_id,
        "applied_by": None,
        "verified_by": None,
        "status": "ISSUED",
    })
    db.label_allocations[rec["id"]] = rec
    roll["serials_issued"] += rec["serial_count"]
    cascade.refresh_roll_counters(roll)
    return success(serialize(rec), status=201)


@bp.get("/label-allocations")
def list_allocations():
    get_context()
    limit, offset = parse_pagination(request.args)
    opening_id = request.args.get("opening_id")
    roll_id = request.args.get("roll_id")
    status = request.args.get("status")
    items = [a for a in db.label_allocations.values()
             if (opening_id is None or a["opening_id"] == opening_id)
             and (roll_id is None or a["roll_id"] == roll_id)
             and (status is None or a["status"] == status)]
    return list_response(items, limit, offset, serialize)


@bp.get("/label-allocations/<aid>")
def get_allocation(aid):
    get_context()
    allocation = require_existence(db.label_allocations, aid, "ERR_ALLOCATION_NOT_FOUND", "LabelAllocation")
    return success(serialize(allocation))


@bp.put("/label-allocations/<aid>/status")
def transition_allocation(aid):
    user_id, role = get_context()
    body = raw_body()
    # Peek at target_status for per-target authorization (rung 2) without
    # validating payload — existence (rung 3) must precede payload errors (rung 4).
    target = body.get("target_status")
    allowed = TARGET_ACTORS.get(target, ALL_STATUS_ACTORS)
    require_role(role, *allowed)
    allocation = require_existence(db.label_allocations, aid,
                                   "ERR_ALLOCATION_NOT_FOUND", "LabelAllocation")
    validate_fields(body, required=("target_status",))
    current = allocation["status"]

    if target == "APPLIED":
        if current != "ISSUED":
            raise err("ERR_INVALID_ALLOCATION_STATUS_TRANSITION",
                      "Allocation cannot transition from %s to APPLIED" % current)
        opening = db.openings.get(allocation["opening_id"])
        if opening is None or opening["fab_status"] != "FINISHED":
            raise err("ERR_OPENING_NOT_FINISH_PASSED",
                      "Application requires opening fab FINISHED")
        roll = db.fire_label_rolls.get(allocation["roll_id"])
        if roll is None or roll["status"] != "ACTIVE":
            raise err("ERR_ROLL_NOT_ACTIVE", "Application requires roll ACTIVE")
        allocation["applied_by"] = user_id
        allocation["status"] = "APPLIED"
        # Cascade: opening fab FINISHED -> LABELED; serials shift issued -> applied.
        opening["fab_status"] = "LABELED"
        db.touch(opening)
        roll["serials_issued"] -= allocation["serial_count"]
        roll["serials_applied"] += allocation["serial_count"]
        cascade.refresh_roll_counters(roll)

    elif target == "VERIFIED":
        if current != "APPLIED":
            raise err("ERR_INVALID_ALLOCATION_STATUS_TRANSITION",
                      "Allocation cannot transition from %s to VERIFIED" % current)
        if user_id == allocation["issued_by"] or user_id == allocation["applied_by"]:
            raise err("ERR_SEGREGATION_OF_DUTIES_VIOLATION",
                      "Verifier must differ from issuer and applier")
        allocation["verified_by"] = user_id
        allocation["status"] = "VERIFIED"

    elif target == "VOIDED":
        if current != "ISSUED":
            raise err("ERR_INVALID_ALLOCATION_STATUS_TRANSITION",
                      "Allocation cannot transition from %s to VOIDED" % current)
        cascade.void_allocation(allocation)

    elif target in ALLOCATION_STATUSES:
        raise err("ERR_INVALID_ALLOCATION_STATUS_TRANSITION",
                  "Allocation cannot transition from %s to %s" % (current, target))
    else:
        raise err("ERR_INVALID_ALLOCATION_STATUS_TRANSITION",
                  "Unknown allocation status: %s" % target)

    db.touch(allocation)
    return success(serialize(allocation))
