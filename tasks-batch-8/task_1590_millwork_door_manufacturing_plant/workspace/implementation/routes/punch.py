"""PunchItem endpoints (PRD §3.8): punch-list reporting, triage, rework, verification."""

from flask import Blueprint, request

import db
from errors import err
from middleware import (get_context, require_role, raw_body, validate_fields,
                        req_string, req_enum, require_existence)
from response import success, list_response, parse_pagination
from services import cascade

bp = Blueprint("punch", __name__)

CATEGORIES = ("FINISH_DEFECT", "HARDWARE_MISALIGNMENT", "TRANSIT_DAMAGE", "LABEL_MISSING")
SEVERITIES = ("MINOR", "MAJOR")
PUNCH_STATUSES = ("REPORTED", "TRIAGED", "REWORK_AUTHORIZED", "IN_REWORK",
                  "RESOLVED", "VERIFIED", "REJECTED_INVALID")

TARGET_ACTORS = {
    "TRIAGED": ("QAInspector",),
    "REJECTED_INVALID": ("QAInspector",),
    "VERIFIED": ("QAInspector",),
    "REWORK_AUTHORIZED": ("PlantManager",),
}
ALL_STATUS_ACTORS = ("QAInspector", "PlantManager")


def serialize(p):
    return {
        "id": p["id"],
        "opening_id": p["opening_id"],
        "category": p["category"],
        "severity": p["severity"],
        "description": p["description"],
        "reported_by": p["reported_by"],
        "rework_batch_id": p["rework_batch_id"],
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


@bp.post("/punch-items")
def create_punch():
    user_id, role = get_context()
    require_role(role, "QAInspector", "Architect")
    body = raw_body()
    # Rung 3: body FK existence.
    if body.get("opening_id") is not None:
        opening = require_existence(db.openings, body["opening_id"],
                                    "ERR_OPENING_NOT_FOUND", "Opening")
    else:
        opening = None
    # Rung 4: payload.
    validate_fields(body, required=("opening_id", "category", "severity", "description"))
    category = req_enum(body, "category", CATEGORIES)
    severity = req_enum(body, "severity", SEVERITIES)
    description = req_string(body, "description")
    # Rung 6: the opening must be delivered (or already punch-listed).
    if opening["ship_status"] not in ("DELIVERED", "PUNCH_LISTED"):
        raise err("ERR_OPENING_NOT_DELIVERED",
                  "Punch report requires opening ship DELIVERED or PUNCH_LISTED")
    rec = db.new_record()
    rec.update({
        "opening_id": opening["id"],
        "category": category,
        "severity": severity,
        "description": description,
        "reported_by": user_id,
        "rework_batch_id": None,
        "status": "REPORTED",
    })
    db.punch_items[rec["id"]] = rec
    # First report on a DELIVERED opening moves it to PUNCH_LISTED.
    if opening["ship_status"] == "DELIVERED":
        opening["ship_status"] = "PUNCH_LISTED"
        db.touch(opening)
    return success(serialize(rec), status=201)


@bp.get("/punch-items")
def list_punches():
    get_context()
    limit, offset = parse_pagination(request.args)
    opening_id = request.args.get("opening_id")
    rework_batch_id = request.args.get("rework_batch_id")
    status = request.args.get("status")
    items = [p for p in db.punch_items.values()
             if (opening_id is None or p["opening_id"] == opening_id)
             and (rework_batch_id is None or p["rework_batch_id"] == rework_batch_id)
             and (status is None or p["status"] == status)]
    return list_response(items, limit, offset, serialize)


@bp.get("/punch-items/<pid>")
def get_punch(pid):
    get_context()
    punch = require_existence(db.punch_items, pid, "ERR_PUNCH_NOT_FOUND", "PunchItem")
    return success(serialize(punch))


@bp.put("/punch-items/<pid>/status")
def transition_punch(pid):
    user_id, role = get_context()
    body = raw_body()
    # Peek at target_status for per-target authorization (rung 2) without
    # validating payload — existence (rung 3) must precede payload errors (rung 4).
    target = body.get("target_status")
    allowed = TARGET_ACTORS.get(target, ALL_STATUS_ACTORS)
    require_role(role, *allowed)
    punch = require_existence(db.punch_items, pid, "ERR_PUNCH_NOT_FOUND", "PunchItem")
    validate_fields(body, required=("target_status",))
    current = punch["status"]

    if target == "TRIAGED":
        if current != "REPORTED":
            raise err("ERR_INVALID_PUNCH_STATUS_TRANSITION",
                      "Punch item cannot transition from %s to TRIAGED" % current)
        punch["status"] = "TRIAGED"

    elif target == "REWORK_AUTHORIZED":
        if current != "TRIAGED":
            raise err("ERR_INVALID_PUNCH_STATUS_TRANSITION",
                      "Punch item cannot transition from %s to REWORK_AUTHORIZED" % current)
        if punch["severity"] != "MAJOR":
            raise err("ERR_PUNCH_NOT_MAJOR", "Rework authorization requires severity MAJOR")
        punch["status"] = "REWORK_AUTHORIZED"
        # Cascade: opening fab falls back to REWORK; applied labels are destroyed.
        opening = db.openings.get(punch["opening_id"])
        if opening is not None and opening["fab_status"] in ("FINISHED", "LABELED", "STAGED"):
            opening["fab_status"] = "REWORK"
            db.touch(opening)
        for allocation in db.label_allocations.values():
            if allocation["opening_id"] == punch["opening_id"] and allocation["status"] in ("APPLIED", "VERIFIED"):
                cascade.void_allocation(allocation)

    elif target == "VERIFIED":
        if current != "RESOLVED":
            raise err("ERR_INVALID_PUNCH_STATUS_TRANSITION",
                      "Punch item cannot transition from %s to VERIFIED" % current)
        # Rung 6 (state) before rung 7 (safety) per the §2.5 ladder.
        opening = db.openings.get(punch["opening_id"])
        if opening is None or opening["fab_status"] != "STAGED":
            raise err("ERR_OPENING_NOT_RESTAGED",
                      "Verify requires the opening re-staged (fab STAGED)")
        if user_id == punch["reported_by"]:
            raise err("ERR_SEGREGATION_OF_DUTIES_VIOLATION",
                      "Verifier must differ from the reporter")
        punch["status"] = "VERIFIED"

    elif target == "REJECTED_INVALID":
        if current != "TRIAGED":
            raise err("ERR_INVALID_PUNCH_STATUS_TRANSITION",
                      "Punch item cannot transition from %s to REJECTED_INVALID" % current)
        punch["status"] = "REJECTED_INVALID"

    elif target in PUNCH_STATUSES:
        raise err("ERR_INVALID_PUNCH_STATUS_TRANSITION",
                  "Punch item cannot transition from %s to %s" % (current, target))
    else:
        raise err("ERR_INVALID_PUNCH_STATUS_TRANSITION",
                  "Unknown punch status: %s" % target)

    db.touch(punch)
    return success(serialize(punch))


@bp.post("/punch-items/<pid>/begin-rework")
def begin_rework(pid):
    _, role = get_context()
    require_role(role, "ProductionLead")
    punch = require_existence(db.punch_items, pid, "ERR_PUNCH_NOT_FOUND", "PunchItem")
    body = raw_body()
    batch = None
    if body.get("rework_batch_id") is not None:
        batch = require_existence(db.finishing_batches, body["rework_batch_id"],
                                  "ERR_BATCH_NOT_FOUND", "FinishingBatch")
    validate_fields(body, optional=("rework_batch_id",))
    if punch["status"] != "REWORK_AUTHORIZED":
        raise err("ERR_INVALID_PUNCH_STATUS_TRANSITION",
                  "Begin-rework requires REWORK_AUTHORIZED, not %s" % punch["status"])
    # Fixed finer ordering (PRD §2.5): batch-order match before batch usability.
    if batch is not None:
        opening = db.openings.get(punch["opening_id"])
        opening_order_id = opening["order_id"] if opening is not None else None
        if batch["order_id"] != opening_order_id:
            raise err("ERR_REWORK_BATCH_ORDER_MISMATCH",
                      "Rework batch's order differs from the punch opening's order")
    if punch["category"] == "FINISH_DEFECT":
        if (batch is None or not batch["is_rework_batch"]
                or batch["status"] not in ("MIXED", "SPRAYED", "CURED")):
            raise err("ERR_REWORK_BATCH_NOT_USABLE",
                      "FINISH_DEFECT rework requires a usable rework batch")
    if batch is not None:
        punch["rework_batch_id"] = batch["id"]
    punch["status"] = "IN_REWORK"
    db.touch(punch)
    return success(serialize(punch))


@bp.post("/punch-items/<pid>/resolve")
def resolve_punch(pid):
    _, role = get_context()
    require_role(role, "ProductionLead")
    punch = require_existence(db.punch_items, pid, "ERR_PUNCH_NOT_FOUND", "PunchItem")
    body = raw_body()
    validate_fields(body)
    triaged_minor = punch["status"] == "TRIAGED" and punch["severity"] == "MINOR"
    in_rework_unlinked = punch["status"] == "IN_REWORK" and punch["rework_batch_id"] is None
    if not (triaged_minor or in_rework_unlinked):
        raise err("ERR_PUNCH_NOT_RESOLVABLE",
                  "Resolve requires a TRIAGED MINOR item or an IN_REWORK item with no linked batch")
    punch["status"] = "RESOLVED"
    db.touch(punch)
    return success(serialize(punch))
