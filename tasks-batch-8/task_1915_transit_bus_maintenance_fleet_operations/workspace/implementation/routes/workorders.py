"""Work order routes: create, events state machine, labor entries, nested lists."""
from datetime import datetime as _dt, timedelta
from decimal import Decimal

from flask import Blueprint, request

from errors import err
from httpkit import (require_roles, caller, body, req_str, req_enum, req_int,
                     req_number, req_date, opt_str, paginate, sort_default,
                     success)
from store import db, init_common, mark_dirty, fmt_date, clock_date, clock_now
from services import domain as dom
from services import cascades
from services import serializers as ser
from routes.buses import get_bus_or_404, ALL

bp = Blueprint("workorders", __name__)


def get_wo_or_404(wo_id):
    wo = db["work_orders"].get(wo_id)
    if wo is None:
        raise err("ERR_NOT_FOUND", f"WorkOrder {wo_id} not found")
    return wo


def _parse_date(s):
    return _dt.strptime(s, "%Y-%m-%d").date()


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------
@bp.post("/fleet/work-orders")
def create_wo():
    require_roles("MaintenanceSupervisor")
    data = body()
    # existence of body FKs (priority 3) before schema (priority 4)
    bus_id = data.get("bus_id")
    bus = None
    if bus_id is not None:
        bus = db["buses"].get(bus_id)
        if bus is None:
            raise err("ERR_NOT_FOUND", f"Bus {bus_id} not found")
    defect = None
    defect_id = data.get("defect_report_id")
    if defect_id is not None:
        defect = db["defects"].get(defect_id)
        if defect is None:
            raise err("ERR_NOT_FOUND", f"DefectReport {defect_id} not found")
    campaign = None
    campaign_id = data.get("campaign_id")
    if campaign_id is not None:
        campaign = db["campaigns"].get(campaign_id)
        if campaign is None:
            raise err("ERR_NOT_FOUND", f"Campaign {campaign_id} not found")
    lead_id = data.get("lead_mechanic_id")
    if lead_id is not None and lead_id not in db["mechanics"]:
        raise err("ERR_NOT_FOUND", f"Mechanic {lead_id} not found")
    # schema (priority 4)
    if bus_id is None:
        raise err("ERR_VALIDATION", "Missing required field: bus_id")
    wo_type = req_enum(data, "wo_type", dom.WO_TYPES)
    priority = req_enum(data, "priority", dom.WO_PRIORITIES)
    start = req_date(data, "planned_start_date")
    end = req_date(data, "planned_end_date")
    if end < start:
        raise err("ERR_VALIDATION",
                  "planned_end_date must be >= planned_start_date")
    est_hours = req_number(data, "estimated_labor_hours")
    est_cost = req_int(data, "estimated_cost_cents")
    if wo_type == "CAMPAIGN" and campaign_id is None:
        raise err("ERR_VALIDATION",
                  "campaign_id is required when wo_type is CAMPAIGN")
    if wo_type != "CAMPAIGN" and campaign_id is not None:
        raise err("ERR_VALIDATION",
                  "campaign_id may only be set when wo_type is CAMPAIGN")
    expected_bus_version = req_int(data, "expected_bus_version")
    # OCC (priority 8)
    if expected_bus_version != bus["version"]:
        raise err("ERR_STALE_BUS_VERSION",
                  "expected_bus_version does not match current Bus.version")
    # referential (priority 17, 18)
    for other in db["work_orders"].values():
        if (other["bus_id"] == bus["id"] and other["wo_type"] == wo_type
                and other["status"] not in dom.WO_TERMINAL):
            raise err("ERR_DUPLICATE_OPEN_WORK_ORDER",
                      "A non-terminal work order of this type exists for the bus")
    if defect is not None:
        for other in db["work_orders"].values():
            if (other.get("defect_report_id") == defect["id"]
                    and other["status"] not in dom.WO_TERMINAL):
                raise err("ERR_DEFECT_ALREADY_LINKED",
                          "Defect report is already linked to a work order")
    # posture gates (priority 27, 28)
    posture = dom.current_posture()["posture"]
    if posture == "YELLOW" and priority == "ELECTIVE":
        raise err("ERR_FLEET_POSTURE_YELLOW",
                  "Posture YELLOW blocks ELECTIVE work-order creation")
    if posture == "RED" and priority in ("ELECTIVE", "ROUTINE"):
        raise err("ERR_FLEET_POSTURE_RED",
                  "Posture RED blocks ELECTIVE and ROUTINE work-order creation")
    # bus not retired (priority 29)
    if bus["service_status"] == "RETIRED":
        raise err("ERR_BUS_RETIRED", "Referenced bus is RETIRED")
    # campaign must be ACTIVE at create (priority 35)
    if campaign is not None and campaign["status"] != "ACTIVE":
        raise err("ERR_CAMPAIGN_NOT_ACTIVE", "Campaign is not ACTIVE")
    # overhaul fiscal cap (priority 43)
    if wo_type == "OVERHAUL":
        cap = int(dom._rhup(Decimal(bus["replacement_cost_cents"])
                            * dom.OVERHAUL_CAP_PCT, 0))
        if est_cost > cap:
            raise err("ERR_OVERHAUL_COST_CAP_EXCEEDED",
                      "OVERHAUL estimate exceeds 40% of replacement cost")

    wo = init_common({
        "bus_id": bus["id"],
        "wo_type": wo_type,
        "priority": priority,
        "defect_report_id": defect_id,
        "campaign_id": campaign_id,
        "emissions_inspection_id": None,
        "lead_mechanic_id": lead_id,
        "planned_start_date": fmt_date(start),
        "planned_end_date": fmt_date(end),
        "estimated_labor_hours": est_hours,
        "estimated_cost_cents": est_cost,
        "odometer_at_open": bus["odometer_miles"],
        "opened_date": fmt_date(clock_date()),
        "started_date": None,
        "closed_date": None,
        "status": "DRAFT",
        "labor_entries": [],
        "labor_total_cents": 0,
        "parts_total_cents": 0,
        "core_charges_accrued_cents": 0,
        "core_credits_cents": 0,
        "parts_net_cents": 0,
        "total_cost_cents": 0,
        "qa_reject_count": 0,
        "qa_note": None,
        "cancel_reason": None,
        "_last_in_progress_at": None,
    })
    db["work_orders"][wo["id"]] = wo
    mark_dirty("buses", bus["id"])  # +1 per PRD
    return success(ser.work_order(wo), code=201)


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------
@bp.get("/fleet/work-orders/<wo_id>")
def get_wo(wo_id):
    require_roles(*ALL)
    return success(ser.work_order(get_wo_or_404(wo_id)))


@bp.get("/fleet/work-orders")
def list_wos():
    require_roles(*ALL)
    items = list(db["work_orders"].values())
    for param in ("bus_id", "campaign_id", "defect_report_id",
                  "lead_mechanic_id", "status"):
        val = request.args.get(param)
        if val is not None:
            items = [w for w in items if w.get(param) == val]
    items = sort_default(items)
    page, meta_p = paginate(items)
    return success([ser.work_order(w) for w in page], response_type="array",
                   pagination=meta_p)


@bp.get("/fleet/work-orders/<wo_id>/part-lines")
def wo_part_lines(wo_id):
    require_roles(*ALL)
    get_wo_or_404(wo_id)
    items = sort_default([l for l in db["part_lines"].values()
                          if l["work_order_id"] == wo_id])
    page, meta_p = paginate(items)
    return success([ser.part_line(l) for l in page], response_type="array",
                   pagination=meta_p)


@bp.get("/fleet/work-orders/<wo_id>/warranty-claims")
def wo_claims(wo_id):
    require_roles(*ALL)
    get_wo_or_404(wo_id)
    items = sort_default([c for c in db["claims"].values()
                          if c["work_order_id"] == wo_id])
    page, meta_p = paginate(items)
    return success([ser.claim(c) for c in page], response_type="array",
                   pagination=meta_p)


@bp.get("/fleet/work-orders/<wo_id>/defect-reports")
def wo_defects(wo_id):
    require_roles(*ALL)
    wo = get_wo_or_404(wo_id)
    items = []
    if wo.get("defect_report_id"):
        d = db["defects"].get(wo["defect_report_id"])
        if d is not None:
            items = [d]
    page, meta_p = paginate(sort_default(items))
    return success([ser.defect(d) for d in page], response_type="array",
                   pagination=meta_p)


# ---------------------------------------------------------------------------
# Labor entries
# ---------------------------------------------------------------------------
@bp.post("/fleet/work-orders/<wo_id>/labor-entries")
def add_labor_entry(wo_id):
    uid, _ = require_roles("Mechanic")
    wo = get_wo_or_404(wo_id)
    data = body()
    work_date = req_date(data, "work_date")
    shift_type = req_enum(data, "shift_type", dom.SHIFT_TYPES)
    hours = req_number(data, "hours")
    # priority 5: hours check before state checks
    if not (hours > 0 and hours <= 16):
        raise err("ERR_LABOR_HOURS_INVALID", "hours must satisfy 0 < hours <= 16")
    # ownership: only the lead mechanic may post labor
    if wo.get("lead_mechanic_id") is None or uid != wo["lead_mechanic_id"]:
        raise err("ERR_FORBIDDEN",
                  "Only the work order's lead mechanic may post labor entries")
    if wo["status"] in dom.WO_TERMINAL:
        raise err("ERR_ALREADY_TERMINAL",
                  f"Work order is {wo['status']}; no labor may be appended")
    amount = dom.labor_amount_cents(hours, shift_type)
    entry = {
        "work_date": fmt_date(work_date),
        "shift_type": shift_type,
        "hours": hours,
        "mechanic_id": uid,
        "amount_cents": amount,
    }
    wo.setdefault("labor_entries", []).append(entry)
    dom.recompute_wo_costs(wo)
    mark_dirty("work_orders", wo["id"])
    return success(ser.work_order(wo), code=201)


# ---------------------------------------------------------------------------
# Events state machine
# ---------------------------------------------------------------------------
_WO_EVENT_ROLES = {
    "SCHEDULE": ("MaintenanceSupervisor",),
    "START": ("MaintenanceSupervisor",),
    "SET_AWAITING_PARTS": ("MaintenanceSupervisor", "Mechanic"),
    "RESUME_WORK": ("MaintenanceSupervisor", "Mechanic"),
    "SUBMIT_QA": ("Mechanic",),
    "QA_CERTIFY": ("Mechanic",),
    "QA_REJECT": ("Mechanic",),
    "CANCEL": ("MaintenanceSupervisor",),
    "ASSIGN": ("MaintenanceSupervisor", "Mechanic"),
}

_WO_FROM_STATES = {
    "SCHEDULE": {"DRAFT"},
    "START": {"SCHEDULED"},
    "SET_AWAITING_PARTS": {"IN_PROGRESS"},
    "RESUME_WORK": {"AWAITING_PARTS", "REOPENED"},
    "SUBMIT_QA": {"IN_PROGRESS"},
    "QA_CERTIFY": {"PENDING_QA"},
    "QA_REJECT": {"PENDING_QA"},
    "CANCEL": {"DRAFT", "SCHEDULED", "IN_PROGRESS", "AWAITING_PARTS",
               "REOPENED", "BLOCKED"},
    "ASSIGN": {"DRAFT", "SCHEDULED", "IN_PROGRESS", "AWAITING_PARTS",
               "PENDING_QA", "REOPENED", "BLOCKED"},
}


@bp.post("/fleet/work-orders/<wo_id>/events")
def wo_event(wo_id):
    uid, role = require_roles("MaintenanceSupervisor", "Mechanic")
    wo = get_wo_or_404(wo_id)
    data = body()
    event_type = req_enum(data, "event_type", set(_WO_EVENT_ROLES))
    # per-event role gate (priority 2)
    if role not in _WO_EVENT_ROLES[event_type]:
        raise err("ERR_FORBIDDEN",
                  f"Role {role} may not perform {event_type}")
    # ownership gates (priority 2)
    if event_type == "SUBMIT_QA":
        if wo.get("lead_mechanic_id") is None or uid != wo["lead_mechanic_id"]:
            raise err("ERR_FORBIDDEN",
                      "Only the lead mechanic may submit a work order for QA")

    # state legality (priorities 6/7)
    if wo["status"] in dom.WO_TERMINAL:
        raise err("ERR_ALREADY_TERMINAL",
                  f"Work order is {wo['status']}; transitions are forbidden")
    if wo["status"] not in _WO_FROM_STATES[event_type]:
        raise err("ERR_INVALID_STATE",
                  f"Cannot {event_type} a work order in {wo['status']}")

    handler = {
        "SCHEDULE": _ev_schedule,
        "START": _ev_start,
        "SET_AWAITING_PARTS": _ev_set_awaiting_parts,
        "RESUME_WORK": _ev_resume_work,
        "SUBMIT_QA": _ev_submit_qa,
        "QA_CERTIFY": _ev_qa_certify,
        "QA_REJECT": _ev_qa_reject,
        "CANCEL": _ev_cancel,
        "ASSIGN": _ev_assign,
    }[event_type]
    handler(wo, data, uid)
    return success(ser.work_order(wo))


def _ev_schedule(wo, data, uid):
    # defect link state (priority 18)
    if wo.get("defect_report_id"):
        d = db["defects"].get(wo["defect_report_id"])
        if d is None or d["status"] not in ("SHOP_QUEUED", "TRIAGED") \
                or d.get("linked_work_order_id"):
            raise err("ERR_DEFECT_ALREADY_LINKED",
                      "Defect report is not linkable (must be SHOP_QUEUED or "
                      "TRIAGED and unlinked)")
    # buffered closed-interval overlap (priority 23)
    new_start = _parse_date(wo["planned_start_date"])
    new_end = _parse_date(wo["planned_end_date"])
    for other in db["work_orders"].values():
        if other["id"] == wo["id"] or other["bus_id"] != wo["bus_id"]:
            continue
        if other["status"] in dom.WO_TERMINAL:
            continue
        o_start = _parse_date(other["planned_start_date"])
        o_end = _parse_date(other["planned_end_date"])
        conflict = not (new_start > o_end + timedelta(days=1)
                        or new_end + timedelta(days=1) < o_start)
        if conflict:
            raise err("ERR_WO_WINDOW_OVERLAP",
                      "Planned window conflicts with another work order")
    # campaign ACTIVE (priority 35)
    if wo.get("campaign_id"):
        camp = db["campaigns"].get(wo["campaign_id"])
        if camp is None or camp["status"] != "ACTIVE":
            raise err("ERR_CAMPAIGN_NOT_ACTIVE", "Campaign is not ACTIVE")
    wo["status"] = "SCHEDULED"
    mark_dirty("work_orders", wo["id"])
    if wo.get("defect_report_id"):
        d = db["defects"][wo["defect_report_id"]]
        d["status"] = "WO_LINKED"
        d["linked_work_order_id"] = wo["id"]
        mark_dirty("defects", d["id"])


def _ev_start(wo, data, uid):
    bus = db["buses"][wo["bus_id"]]
    # lead must be set (priority 4 schema-level)
    if not wo.get("lead_mechanic_id"):
        raise err("ERR_VALIDATION",
                  "lead_mechanic_id must be set before START")
    # cert gate (priorities 10/11)
    if wo["wo_type"] == "CAMPAIGN":
        camp = db["campaigns"].get(wo.get("campaign_id"))
        required = camp.get("required_cert_type") if camp else None
    else:
        required = dom.WO_CERT_MAP.get(wo["wo_type"])
    if required:
        dom.require_cert(wo["lead_mechanic_id"], required)
    # bus not retired (priority 29)
    if bus["service_status"] == "RETIRED":
        raise err("ERR_BUS_RETIRED", "Bus is RETIRED")
    # availability + in-progress exclusion (priority 30)
    dom.recompute_bus_availability(bus)
    if bus["availability_status"] not in ("AVAILABLE", "HELD"):
        raise err("ERR_BUS_NOT_AVAILABLE",
                  "Bus availability is not AVAILABLE or HELD")
    for other in db["work_orders"].values():
        if (other["id"] != wo["id"] and other["bus_id"] == wo["bus_id"]
                and other["status"] in dom.WO_IN_PROGRESS_FAMILY):
            raise err("ERR_BUS_NOT_AVAILABLE",
                      "Another work order is in progress on this bus")
    wo["status"] = "IN_PROGRESS"
    wo["started_date"] = fmt_date(clock_date())
    wo["_last_in_progress_at"] = clock_now().isoformat()
    mark_dirty("work_orders", wo["id"])
    if wo["wo_type"] == "OVERHAUL" and bus["service_status"] == "ACTIVE":
        bus["service_status"] = "OVERHAUL_HOLD"
        mark_dirty("buses", bus["id"])
    dom.recompute_bus_availability(bus)
    dom.recompute_posture()


def _ev_set_awaiting_parts(wo, data, uid):
    wo["status"] = "AWAITING_PARTS"
    mark_dirty("work_orders", wo["id"])
    dom.recompute_bus_availability(db["buses"][wo["bus_id"]])


def _ev_resume_work(wo, data, uid):
    wo["status"] = "IN_PROGRESS"
    wo["_last_in_progress_at"] = clock_now().isoformat()
    mark_dirty("work_orders", wo["id"])
    dom.recompute_bus_availability(db["buses"][wo["bus_id"]])


def _ev_submit_qa(wo, data, uid):
    if not wo.get("labor_entries"):
        raise err("ERR_QA_WITHOUT_LABOR",
                  "At least one labor entry is required before QA submission")
    for line in dom.wo_lines(wo["id"]):
        if line["issue_status"] in ("RESERVED", "ISSUED"):
            raise err("ERR_LINES_UNRESOLVED",
                      "All part lines must be resolved before QA submission")
    if wo["wo_type"] == "EMISSIONS":
        last_entry = wo.get("_last_in_progress_at") or ""
        found = False
        for insp in db["inspections"].values():
            if (insp["bus_id"] == wo["bus_id"] and insp["result"] == "PASS"
                    and insp["created_at"] >= last_entry):
                found = True
                break
        if not found:
            raise err("ERR_EMISSIONS_RETEST_REQUIRED",
                      "A PASS retest recorded at/after the last work start is "
                      "required")
    wo["status"] = "PENDING_QA"
    mark_dirty("work_orders", wo["id"])


def _ev_qa_certify(wo, data, uid):
    dom.require_cert(uid, "QA_AUTHORITY")
    if uid == wo.get("lead_mechanic_id"):
        raise err("ERR_SOD_QA_SELF_CERTIFY",
                  "The lead mechanic may not certify their own work")
    cascades.close_work_order(wo)


def _ev_qa_reject(wo, data, uid):
    dom.require_cert(uid, "QA_AUTHORITY")
    if uid == wo.get("lead_mechanic_id"):
        raise err("ERR_SOD_QA_SELF_CERTIFY",
                  "The lead mechanic may not reject their own work")
    wo["status"] = "REOPENED"
    wo["qa_reject_count"] = wo.get("qa_reject_count", 0) + 1
    note = opt_str(data, "qa_note")
    if note is not None:
        wo["qa_note"] = note
    mark_dirty("work_orders", wo["id"])
    dom.recompute_bus_availability(db["buses"][wo["bus_id"]])


def _ev_cancel(wo, data, uid):
    reason = opt_str(data, "cancel_reason")
    cascades.cancel_work_order(wo, reason)


def _ev_assign(wo, data, uid):
    lead = data.get("lead_mechanic_id")
    if lead is None:
        raise err("ERR_VALIDATION",
                  "lead_mechanic_id is required for ASSIGN")
    if lead not in db["mechanics"]:
        raise err("ERR_NOT_FOUND", f"Mechanic {lead} not found")
    wo["lead_mechanic_id"] = lead
    mark_dirty("work_orders", wo["id"])
