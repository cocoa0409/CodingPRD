"""Emission repair orders: read and the attempt / delay / close action set."""

from flask import Blueprint

import schema
from db import db, now
from errors import fail
from middleware import endpoint
from response import ok
from routes.common import by_created_at, load, respond_list
from services import calc, cascade, derive
from services.tracking import touch
from util import D, add_days

bp = Blueprint("repair_orders", __name__)

READERS = ["PlatformAdmin", "ComplianceManager", "TreatmentOperator", "RegulatoryInspector"]

ACTION_SPEC = {
    "action": {"type": "string", "required": True,
               "enum": ["FIRST_ATTEMPT", "REPAIR_ATTEMPT", "DELAY", "CLOSE"]},
    "monitored_ppm": {"type": "number", "ge": 0},
    "justification_code": {"type": "string"},
    "delayed_due_at": {"type": "datetime"},
}


@bp.get("/tsdf/emission-repair-orders/<oid>")
@endpoint(roles=READERS)
def get_order(oid):
    return ok(derive.project_repair_order(load("repair_orders", oid)))


@bp.get("/tsdf/emission-repair-orders")
@endpoint(roles=READERS)
def list_orders():
    filters, limit, offset = schema.listing(
        filters=["storage_unit_id", "container_id", "source_inspection_event_id", "status"],
        enums={"status": calc.REPAIR_STATUSES})
    rows = by_created_at(list(db.repair_orders.values()))
    for key in ("storage_unit_id", "container_id", "source_inspection_event_id", "status"):
        if key in filters:
            rows = [o for o in rows if o[key] == filters[key]]
    return respond_list(rows, derive.project_repair_order, limit, offset)


@bp.post("/tsdf/emission-repair-orders/<oid>/actions")
@endpoint(roles=["ComplianceManager", "TreatmentOperator"], mutating=True)
def act_on_order(oid):
    body = schema.body(ACTION_SPEC)
    action = body["action"]
    if action == "CLOSE" and body["monitored_ppm"] is None:
        fail("ERR_INVALID_REQUEST", "monitored_ppm is required to close a repair order")
    if action == "DELAY" and body["delayed_due_at"] is None:
        fail("ERR_INVALID_REQUEST", "delayed_due_at is required to delay a repair")

    o = load("repair_orders", oid)
    status = o["status"]

    if action == "FIRST_ATTEMPT":
        if status != "OPEN":
            fail("ERR_INVALID_STATE", "A first attempt is only recorded against an open order")
        if now() > o["first_attempt_due_at"]:
            fail("ERR_REPAIR_ATTEMPT_LATE")
        o["attempt_count"] = int(o["attempt_count"]) + 1
        o["last_monitored_ppm"] = body["monitored_ppm"]
        o["status"] = "FIRST_ATTEMPTED"

    elif action == "REPAIR_ATTEMPT":
        if status != "FIRST_ATTEMPTED":
            fail("ERR_INVALID_STATE", "A further attempt requires a first attempt on record")
        if derive.repair_order_overdue(o):
            fail("ERR_REPAIR_ATTEMPT_LATE")
        o["attempt_count"] = int(o["attempt_count"]) + 1
        o["last_monitored_ppm"] = body["monitored_ppm"]

    elif action == "DELAY":
        if status not in ("OPEN", "FIRST_ATTEMPTED"):
            fail("ERR_INVALID_STATE", "The order cannot be delayed from its current status")
        if body["justification_code"] not in calc.ALLOWED_DELAY_JUSTIFICATIONS:
            fail("ERR_DELAY_JUSTIFICATION_INVALID")
        if body["delayed_due_at"] > add_days(o["detected_at"], calc.MAX_DELAY_DAYS):
            fail("ERR_DELAY_JUSTIFICATION_INVALID")
        o["delayed_due_at"] = body["delayed_due_at"]
        o["justification_code"] = body["justification_code"]
        o["status"] = "DELAYED"

    else:
        if status not in ("OPEN", "FIRST_ATTEMPTED", "DELAYED"):
            fail("ERR_INVALID_STATE", "The order is already repaired")
        if status == "OPEN" and int(o["attempt_count"]) < 1:
            fail("ERR_INVALID_STATE", "No repair attempt has been recorded yet")
        # Closure is strict: a reading exactly at the leak definition still leaks.
        if D(body["monitored_ppm"]) >= D(o["leak_definition_ppm"]):
            fail("ERR_LEAK_PERSISTS")
        o["last_monitored_ppm"] = body["monitored_ppm"]
        o["status"] = "REPAIRED"

    u = derive.unit(o["storage_unit_id"])
    if u is not None:
        cascade.reconcile_unit(u)
    touch("repair_orders", o)
    return ok(derive.project_repair_order(o))
