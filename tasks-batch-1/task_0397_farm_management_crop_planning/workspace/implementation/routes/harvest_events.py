"""HarvestEvent + HarvestLot endpoints (PRD §3.5, §3.6).

HarvestEvent: RECORDED -> VOIDED.
HarvestLot: parallel axes quality_status x sale_status.
"""
from flask import Blueprint, request

import db
import lookups
import serializers
from errors import err
from helpers import (
    get_json_body,
    paginate,
    parse_pagination,
    require_enum,
    require_number,
    require_str,
    round2,
)
from middleware import require_roles
from response import array_response, object_response
from services import compute

bp = Blueprint("harvest_events", __name__)
READ_ROLES = ("FarmManager", "Agronomist", "SalesAgent")
QUALITY_GRADES = {"GRADE_A", "GRADE_B", "REJECTED"}


# ---------------- HarvestEvent ----------------
@bp.post("/harvest-events")
@require_roles("Agronomist")
def create_harvest_event():
    body = get_json_body()
    crop_plan_id = require_str(body, "crop_plan_id")
    acres_harvested = require_number(body, "acres_harvested")
    gross_quantity = require_number(body, "gross_quantity")
    moisture_pct = require_number(body, "moisture_pct")

    plan = lookups.crop_plan(crop_plan_id)

    if acres_harvested <= 0:
        raise err("ERR_INVALID_REQUEST", "acres_harvested must be > 0.")
    if gross_quantity < 0:
        raise err("ERR_INVALID_REQUEST", "gross_quantity must be >= 0.")
    if moisture_pct < 0 or moisture_pct > 100:
        raise err("ERR_INVALID_REQUEST", "moisture_pct must be between 0 and 100.")

    # A harvest is recorded against a plan that is in HARVESTING (PRD §3.5).
    if plan["status"] != "HARVESTING":
        raise err("ERR_INVALID_STATE", "Plan is not HARVESTING.")

    net_quantity = round2(gross_quantity * (1 - moisture_pct / 100))

    rec = db.new_entity(
        {
            "crop_plan_id": crop_plan_id,
            "acres_harvested": acres_harvested,
            "gross_quantity": gross_quantity,
            "moisture_pct": moisture_pct,
            "net_quantity": net_quantity,
            "status": "RECORDED",
        }
    )
    db.harvest_events[rec["id"]] = rec

    compute.recompute_harvested_acres(plan)
    db.touch(plan)

    return object_response(serializers.harvest_event(rec), 201)


@bp.get("/harvest-events/<hid>")
@require_roles(*READ_ROLES)
def get_harvest_event(hid):
    rec = lookups.harvest_event(hid)
    return object_response(serializers.harvest_event(rec))


@bp.get("/harvest-events")
@require_roles(*READ_ROLES)
def list_harvest_events():
    limit, offset = parse_pagination()
    records = list(db.harvest_events.values())
    for key in ("crop_plan_id", "status"):
        val = request.args.get(key)
        if val is not None:
            records = [r for r in records if r[key] == val]
    page, total = paginate(records, limit, offset)
    return array_response(
        [serializers.harvest_event(r) for r in page], limit, offset, total
    )


@bp.get("/harvest-events/<hid>/harvest-lots")
@require_roles(*READ_ROLES)
def list_event_lots(hid):
    lookups.harvest_event(hid)
    limit, offset = parse_pagination()
    records = [l for l in db.harvest_lots.values() if l["harvest_event_id"] == hid]
    page, total = paginate(records, limit, offset)
    return array_response(
        [serializers.harvest_lot(r) for r in page], limit, offset, total
    )


# ---------------- HarvestLot ----------------
@bp.post("/harvest-lots")
@require_roles("Agronomist")
def create_harvest_lot():
    body = get_json_body()
    harvest_event_id = require_str(body, "harvest_event_id")
    quantity = require_number(body, "quantity")

    event = lookups.harvest_event(harvest_event_id)

    if quantity <= 0:
        raise err("ERR_INVALID_REQUEST", "quantity must be > 0.")

    rec = db.new_entity(
        {
            "harvest_event_id": harvest_event_id,
            "crop_plan_id": event["crop_plan_id"],  # denormalized (PRD §3.6)
            "quantity": quantity,
            "quantity_committed": 0,
            "quality_status": "UNGRADED",
            "sale_status": "IN_INVENTORY",
            "committed_contract_id": None,
        }
    )
    db.harvest_lots[rec["id"]] = rec
    return object_response(serializers.harvest_lot(rec), 201)


@bp.get("/harvest-lots/<lid>")
@require_roles(*READ_ROLES)
def get_harvest_lot(lid):
    rec = lookups.harvest_lot(lid)
    return object_response(serializers.harvest_lot(rec))


@bp.get("/harvest-lots")
@require_roles(*READ_ROLES)
def list_harvest_lots():
    limit, offset = parse_pagination()
    records = list(db.harvest_lots.values())
    for key in ("crop_plan_id", "committed_contract_id", "quality_status", "sale_status"):
        val = request.args.get(key)
        if val is not None:
            records = [r for r in records if r[key] == val]
    page, total = paginate(records, limit, offset)
    return array_response(
        [serializers.harvest_lot(r) for r in page], limit, offset, total
    )


@bp.post("/harvest-lots/<lid>/grade")
@require_roles("Agronomist")
def grade_lot(lid):
    rec = lookups.harvest_lot(lid)
    body = get_json_body()
    grade = require_enum(body, "grade", QUALITY_GRADES)

    # Grading only permitted while UNGRADED (PRD §3.6).
    if rec["quality_status"] != "UNGRADED":
        raise err("ERR_LOT_ALREADY_GRADED", "Lot is already graded.")

    if grade == "REJECTED":
        # Strictest branch: requires IN_INVENTORY with quantity_committed == 0.
        if rec["sale_status"] != "IN_INVENTORY" or rec["quantity_committed"] != 0:
            raise err(
                "ERR_LOT_ALREADY_COMMITTED",
                "A committed lot cannot be rejected.",
            )

    rec["quality_status"] = grade
    db.touch(rec)
    return object_response(serializers.harvest_lot(rec))
