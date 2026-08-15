"""Part and WorkOrderPartLine routes."""
from datetime import timedelta

from flask import Blueprint, request

from errors import err
from httpkit import (require_roles, body, req_str, req_enum, req_int, opt_int,
                     req_bool, paginate, sort_default, success)
from store import db, init_common, mark_dirty, fmt_date, clock_date
from services import domain as dom
from services import serializers as ser
from routes.buses import ALL
from routes.workorders import get_wo_or_404

bp = Blueprint("parts", __name__)

PART_CLASSES = {"CONSUMABLE", "REBUILDABLE_CORE", "EXPENDABLE"}


def get_part_or_404(part_id):
    part = db["parts"].get(part_id)
    if part is None:
        raise err("ERR_NOT_FOUND", f"Part {part_id} not found")
    return part


def get_line_or_404(line_id):
    line = db["part_lines"].get(line_id)
    if line is None:
        raise err("ERR_NOT_FOUND", f"WorkOrderPartLine {line_id} not found")
    return line


# ---------------------------------------------------------------------------
# Parts
# ---------------------------------------------------------------------------
@bp.post("/fleet/parts")
def create_part():
    require_roles("PartsClerk")
    data = body()
    sku = req_str(data, "sku")
    description = req_str(data, "description")
    part_class = req_enum(data, "part_class", PART_CLASSES)
    unit_cost = req_int(data, "unit_cost_cents")
    reorder_point = req_int(data, "reorder_point")
    initial_on_hand = req_int(data, "initial_on_hand")
    warranty_eligible = req_bool(data, "warranty_eligible")
    core_charge = opt_int(data, "core_charge_cents")
    if part_class == "REBUILDABLE_CORE" and core_charge is None:
        raise err("ERR_VALIDATION",
                  "core_charge_cents is required for REBUILDABLE_CORE parts")
    if initial_on_hand < 0:
        raise err("ERR_VALIDATION", "initial_on_hand must be >= 0")
    part = init_common({
        "sku": sku,
        "description": description,
        "part_class": part_class,
        "unit_cost_cents": unit_cost,
        "reorder_point": reorder_point,
        "quantity_on_hand": initial_on_hand,
        "quantity_reserved": 0,
        "core_charge_cents": core_charge,
        "warranty_eligible": warranty_eligible,
        "superseded_by_id": None,
        "stock_status": "NORMAL",
    })
    part["stock_status"] = dom.derive_stock_status(part)
    db["parts"][part["id"]] = part
    return success(ser.part(part), code=201)


@bp.get("/fleet/parts/<part_id>")
def get_part(part_id):
    require_roles(*ALL)
    return success(ser.part(get_part_or_404(part_id)))


@bp.get("/fleet/parts")
def list_parts():
    require_roles(*ALL)
    items = list(db["parts"].values())
    ss = request.args.get("stock_status")
    if ss is not None:
        items = [p for p in items if p["stock_status"] == ss]
    sb = request.args.get("superseded_by_id")
    if sb is not None:
        items = [p for p in items if p.get("superseded_by_id") == sb]
    items = sort_default(items)
    page, meta_p = paginate(items)
    return success([ser.part(p) for p in page], response_type="array",
                   pagination=meta_p)


@bp.post("/fleet/parts/<part_id>/stock-adjustments")
def stock_adjust(part_id):
    require_roles("PartsClerk")
    part = get_part_or_404(part_id)
    data = body()
    delta = req_int(data, "delta")
    reason = data.get("reason")
    if reason is None or not isinstance(reason, str):
        raise err("ERR_VALIDATION", "Field reason must be a string")
    new_on_hand = part["quantity_on_hand"] + delta
    if new_on_hand < 0:
        raise err("ERR_VALIDATION",
                  "Stock adjustment may not drop quantity_on_hand below zero")
    part["quantity_on_hand"] = new_on_hand
    mark_dirty("parts", part["id"])
    dom.recompute_stock_status(part)
    return success(ser.part(part))


@bp.post("/fleet/parts/<part_id>/supersede")
def supersede_part(part_id):
    require_roles("PartsClerk")
    part = get_part_or_404(part_id)
    data = body()
    new_part_id = data.get("new_part_id")
    if new_part_id is not None and new_part_id not in db["parts"]:
        raise err("ERR_NOT_FOUND", f"Part {new_part_id} not found")
    if new_part_id is None:
        raise err("ERR_VALIDATION", "Missing required field: new_part_id")
    if new_part_id == part_id:
        raise err("ERR_VALIDATION", "A part cannot supersede itself")
    part["superseded_by_id"] = new_part_id
    mark_dirty("parts", part["id"])
    return success(ser.part(part))


@bp.get("/fleet/parts/<part_id>/emissions-inspections")
def part_inspections(part_id):
    require_roles(*ALL)
    get_part_or_404(part_id)
    items = sort_default([i for i in db["inspections"].values()
                          if i.get("failed_component_part_id") == part_id])
    page, meta_p = paginate(items)
    return success([ser.inspection(i) for i in page], response_type="array",
                   pagination=meta_p)


@bp.get("/fleet/parts/<part_id>/campaigns")
def part_campaigns(part_id):
    require_roles(*ALL)
    get_part_or_404(part_id)
    items = sort_default([c for c in db["campaigns"].values()
                          if c.get("required_part_id") == part_id])
    page, meta_p = paginate(items)
    return success([ser.campaign(c) for c in page], response_type="array",
                   pagination=meta_p)


# ---------------------------------------------------------------------------
# Part lines
# ---------------------------------------------------------------------------
@bp.post("/fleet/work-orders/<wo_id>/part-lines")
def create_part_line(wo_id):
    require_roles("MaintenanceSupervisor", "Mechanic", "PartsClerk")
    wo = get_wo_or_404(wo_id)
    data = body()
    part_id = data.get("part_id")
    part = None
    if part_id is not None:
        part = db["parts"].get(part_id)
        if part is None:
            raise err("ERR_NOT_FOUND", f"Part {part_id} not found")
    if part_id is None:
        raise err("ERR_VALIDATION", "Missing required field: part_id")
    qty = req_int(data, "qty")
    if qty < 1:
        raise err("ERR_VALIDATION", "qty must be >= 1")
    # state legality
    if wo["status"] in dom.WO_TERMINAL:
        raise err("ERR_ALREADY_TERMINAL",
                  f"Work order is {wo['status']}")
    if wo["status"] not in ("DRAFT", "SCHEDULED", "IN_PROGRESS",
                            "AWAITING_PARTS", "REOPENED"):
        raise err("ERR_INVALID_STATE",
                  f"Cannot reserve parts on a work order in {wo['status']}")
    # stock (priority 31) then supersession (priority 32)
    if dom.part_available(part) < qty:
        raise err("ERR_PART_STOCK_INSUFFICIENT",
                  "Available quantity is below the requested qty")
    if part.get("superseded_by_id"):
        raise err("ERR_PART_SUPERSEDED",
                  "Part is superseded and cannot be reserved")
    line = init_common({
        "work_order_id": wo["id"],
        "part_id": part["id"],
        "qty": qty,
        "qty_issued": 0,
        "unit_cost_cents": part["unit_cost_cents"],
        "issue_status": "RESERVED",
        "core_status": "NONE",
        "core_due_date": None,
    })
    db["part_lines"][line["id"]] = line
    part["quantity_reserved"] += qty
    mark_dirty("parts", part["id"])
    dom.recompute_stock_status(part)
    return success(ser.part_line(line), code=201)


@bp.get("/fleet/part-lines/<line_id>")
def get_line(line_id):
    require_roles(*ALL)
    return success(ser.part_line(get_line_or_404(line_id)))


@bp.get("/fleet/part-lines")
def list_lines():
    require_roles(*ALL)
    items = list(db["part_lines"].values())
    for param in ("part_id", "core_status", "issue_status"):
        val = request.args.get(param)
        if val is not None:
            items = [l for l in items if l.get(param) == val]
    items = sort_default(items)
    page, meta_p = paginate(items)
    return success([ser.part_line(l) for l in page], response_type="array",
                   pagination=meta_p)


_LINE_EVENT_ROLES = {
    "ISSUE": ("Mechanic", "PartsClerk"),
    "CONSUME": ("Mechanic", "PartsClerk"),
    "RETURN_UNUSED": ("Mechanic", "PartsClerk"),
    "RELEASE": ("Mechanic", "PartsClerk"),
    "CORE_RETURN": ("PartsClerk",),
}


@bp.post("/fleet/part-lines/<line_id>/events")
def line_event(line_id):
    uid, role = require_roles("Mechanic", "PartsClerk")
    line = get_line_or_404(line_id)
    data = body()
    event_type = req_enum(data, "event_type", set(_LINE_EVENT_ROLES))
    if role not in _LINE_EVENT_ROLES[event_type]:
        raise err("ERR_FORBIDDEN", f"Role {role} may not perform {event_type}")
    handler = {
        "ISSUE": _line_issue,
        "CONSUME": _line_consume,
        "RETURN_UNUSED": _line_return_unused,
        "RELEASE": _line_release,
        "CORE_RETURN": _line_core_return,
    }[event_type]
    handler(line, data)
    return success(ser.part_line(line))


def _line_issue(line, data):
    if line["issue_status"] in dom.LINE_ISSUE_TERMINAL:
        raise err("ERR_ALREADY_TERMINAL",
                  f"Part line is {line['issue_status']}")
    if line["issue_status"] != "RESERVED":
        raise err("ERR_INVALID_STATE", "Only a RESERVED line may be issued")
    wo = db["work_orders"][line["work_order_id"]]
    if wo["status"] not in ("IN_PROGRESS", "AWAITING_PARTS"):
        raise err("ERR_INVALID_STATE",
                  "Parent work order must be IN_PROGRESS or AWAITING_PARTS")
    part = db["parts"][line["part_id"]]
    qty = line["qty"]
    part["quantity_on_hand"] -= qty
    part["quantity_reserved"] -= qty
    mark_dirty("parts", part["id"])
    dom.recompute_stock_status(part)
    line["issue_status"] = "ISSUED"
    line["qty_issued"] = qty
    if part["part_class"] == "REBUILDABLE_CORE":
        charge = (part.get("core_charge_cents") or 0) * qty
        wo["core_charges_accrued_cents"] = (
            wo.get("core_charges_accrued_cents", 0) + charge)
        line["core_status"] = "CORE_PENDING"
        line["core_due_date"] = fmt_date(
            clock_date() + timedelta(days=dom.CORE_RETURN_WINDOW_DAYS))
        mark_dirty("work_orders", wo["id"])
    mark_dirty("part_lines", line["id"])
    # AWAITING_PARTS auto-resume when no RESERVED line remains
    if wo["status"] == "AWAITING_PARTS":
        if not any(l["issue_status"] == "RESERVED" for l in dom.wo_lines(wo["id"])):
            wo["status"] = "IN_PROGRESS"
            mark_dirty("work_orders", wo["id"])
            dom.recompute_bus_availability(db["buses"][wo["bus_id"]])
    dom.recompute_wo_costs(wo)


def _line_consume(line, data):
    if line["issue_status"] in dom.LINE_ISSUE_TERMINAL:
        raise err("ERR_ALREADY_TERMINAL",
                  f"Part line is {line['issue_status']}")
    if line["issue_status"] != "ISSUED":
        raise err("ERR_INVALID_STATE", "Only an ISSUED line may be consumed")
    line["issue_status"] = "CONSUMED"
    mark_dirty("part_lines", line["id"])
    wo = db["work_orders"][line["work_order_id"]]
    dom.recompute_wo_costs(wo)


def _line_return_unused(line, data):
    if line["issue_status"] in dom.LINE_ISSUE_TERMINAL:
        raise err("ERR_ALREADY_TERMINAL",
                  f"Part line is {line['issue_status']}")
    if line["issue_status"] != "ISSUED":
        raise err("ERR_INVALID_STATE",
                  "Only an ISSUED line may be returned unused")
    if line["core_status"] not in ("NONE", "CORE_PENDING"):
        raise err("ERR_INVALID_STATE",
                  "Line core status does not permit an unused return")
    part = db["parts"][line["part_id"]]
    part["quantity_on_hand"] += line["qty"]
    mark_dirty("parts", part["id"])
    dom.recompute_stock_status(part)
    wo = db["work_orders"][line["work_order_id"]]
    if line["core_status"] == "CORE_PENDING":
        charge = (part.get("core_charge_cents") or 0) * line["qty"]
        wo["core_charges_accrued_cents"] = (
            wo.get("core_charges_accrued_cents", 0) - charge)
        line["core_status"] = "CORE_REJECTED"
        line["core_due_date"] = None
        mark_dirty("work_orders", wo["id"])
    line["issue_status"] = "RETURNED"
    line["qty_issued"] = 0
    mark_dirty("part_lines", line["id"])
    dom.recompute_wo_costs(wo)


def _line_release(line, data):
    if line["issue_status"] in dom.LINE_ISSUE_TERMINAL:
        raise err("ERR_ALREADY_TERMINAL",
                  f"Part line is {line['issue_status']}")
    if line["issue_status"] != "RESERVED":
        raise err("ERR_INVALID_STATE", "Only a RESERVED line may be released")
    part = db["parts"][line["part_id"]]
    part["quantity_reserved"] -= line["qty"]
    mark_dirty("parts", part["id"])
    dom.recompute_stock_status(part)
    line["issue_status"] = "RELEASED"
    mark_dirty("part_lines", line["id"])
    # AWAITING_PARTS auto-resume when no RESERVED line remains
    wo = db["work_orders"][line["work_order_id"]]
    if wo["status"] == "AWAITING_PARTS":
        if not any(l["issue_status"] == "RESERVED"
                   for l in dom.wo_lines(wo["id"])):
            wo["status"] = "IN_PROGRESS"
            mark_dirty("work_orders", wo["id"])
            dom.recompute_bus_availability(db["buses"][wo["bus_id"]])


def _line_core_return(line, data):
    if line["core_status"] in dom.CORE_TERMINAL:
        raise err("ERR_CORE_NOT_PENDING",
                  "Line core is not pending or late")
    if line["core_status"] not in ("CORE_PENDING", "CORE_LATE"):
        raise err("ERR_CORE_NOT_PENDING",
                  "Line core is not pending or late")
    condition = data.get("core_condition")
    if condition not in ("GOOD", "BAD"):
        raise err("ERR_VALIDATION", "core_condition must be GOOD or BAD")
    part = db["parts"][line["part_id"]]
    wo = db["work_orders"][line["work_order_id"]]
    from datetime import datetime as _dt
    due = _dt.strptime(line["core_due_date"], "%Y-%m-%d").date()
    today = clock_date()
    credit = 0
    if condition == "BAD":
        new_status = "CORE_REJECTED"
    elif today <= due:
        new_status = "CORE_CREDITED"
        credit = (part.get("core_charge_cents") or 0) * line["qty"]
    elif today <= due + timedelta(days=dom.CORE_LATE_GRACE_DAYS):
        new_status = "CORE_CREDITED"
        credit = int(dom._rhup(
            dom._dec((part.get("core_charge_cents") or 0) * line["qty"])
            * dom.LATE_TIER_PCT, 0))
    else:
        new_status = "CORE_REJECTED"
    line["core_status"] = new_status
    line["core_due_date"] = None
    mark_dirty("part_lines", line["id"])
    if credit:
        wo["core_credits_cents"] = wo.get("core_credits_cents", 0) + credit
        mark_dirty("work_orders", wo["id"])
        dom.recompute_wo_costs(wo)
