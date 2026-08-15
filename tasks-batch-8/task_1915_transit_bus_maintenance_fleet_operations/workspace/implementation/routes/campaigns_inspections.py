"""Campaign and EmissionsInspection routes."""
from datetime import timedelta

from flask import Blueprint, request

from errors import err
from httpkit import (require_roles, body, req_str, req_int, req_number,
                     req_enum, req_date, opt_str, opt_int, paginate,
                     sort_default, success)
from store import db, init_common, mark_dirty, fmt_date, clock_date
from services import domain as dom
from services import serializers as ser
from routes.buses import get_bus_or_404, ALL

bp = Blueprint("campaigns_inspections", __name__)


# ---------------------------------------------------------------------------
# Campaigns
# ---------------------------------------------------------------------------
def get_campaign_or_404(campaign_id):
    c = db["campaigns"].get(campaign_id)
    if c is None:
        raise err("ERR_NOT_FOUND", f"Campaign {campaign_id} not found")
    return c


@bp.post("/fleet/campaigns")
def create_campaign():
    require_roles("FleetManager")
    data = body()
    part_id = data.get("required_part_id")
    if part_id is not None and part_id not in db["parts"]:
        raise err("ERR_NOT_FOUND", f"Part {part_id} not found")
    code = req_str(data, "code")
    title = req_str(data, "title")
    year_from = req_int(data, "model_year_from")
    year_to = req_int(data, "model_year_to")
    if year_to < year_from:
        raise err("ERR_VALIDATION",
                  "model_year_to must be >= model_year_from")
    labor_hours = req_number(data, "labor_hours_per_bus")
    deadline = req_date(data, "deadline_date")
    required_cert = opt_str(data, "required_cert_type")
    if required_cert is not None and required_cert not in dom.CERT_TYPES:
        raise err("ERR_VALIDATION", "required_cert_type is not a known cert type")
    camp = init_common({
        "code": code,
        "title": title,
        "model_year_from": year_from,
        "model_year_to": year_to,
        "required_part_id": part_id,
        "required_cert_type": required_cert,
        "labor_hours_per_bus": labor_hours,
        "deadline_date": fmt_date(deadline),
        "status": "DRAFT",
        "scope_bus_ids": [],
        "activated_date": None,
    })
    db["campaigns"][camp["id"]] = camp
    return success(ser.campaign(camp), code=201)


@bp.get("/fleet/campaigns/<cid>")
def get_campaign(cid):
    require_roles(*ALL)
    return success(ser.campaign(get_campaign_or_404(cid)))


@bp.get("/fleet/campaigns")
def list_campaigns():
    require_roles(*ALL)
    items = list(db["campaigns"].values())
    st = request.args.get("status")
    if st is not None:
        items = [c for c in items if c["status"] == st]
    items = sort_default(items)
    page, meta_p = paginate(items)
    return success([ser.campaign(c) for c in page], response_type="array",
                   pagination=meta_p)


@bp.get("/fleet/campaigns/<cid>/work-orders")
def campaign_wos(cid):
    require_roles(*ALL)
    get_campaign_or_404(cid)
    items = sort_default([w for w in db["work_orders"].values()
                          if w.get("campaign_id") == cid])
    page, meta_p = paginate(items)
    return success([ser.work_order(w) for w in page], response_type="array",
                   pagination=meta_p)


_CAMPAIGN_EVENTS = {"ACTIVATE", "SUSPEND", "RESUME", "CLOSE"}
_CAMPAIGN_FROM = {
    "ACTIVATE": {"DRAFT"},
    "SUSPEND": {"ACTIVE"},
    "RESUME": {"SUSPENDED"},
    "CLOSE": {"ACTIVE", "SUSPENDED"},
}


@bp.post("/fleet/campaigns/<cid>/events")
def campaign_event(cid):
    require_roles("FleetManager")
    camp = get_campaign_or_404(cid)
    data = body()
    event_type = req_enum(data, "event_type", _CAMPAIGN_EVENTS)
    if camp["status"] in dom.CAMPAIGN_TERMINAL:
        raise err("ERR_ALREADY_TERMINAL",
                  f"Campaign is {camp['status']}; transitions are forbidden")
    if camp["status"] not in _CAMPAIGN_FROM[event_type]:
        raise err("ERR_INVALID_STATE",
                  f"Cannot {event_type} a campaign in {camp['status']}")

    if event_type == "ACTIVATE":
        scope = [b for b in db["buses"].values()
                 if camp["model_year_from"] <= b["model_year"]
                 <= camp["model_year_to"]
                 and b["service_status"] == "ACTIVE"]
        if not scope:
            raise err("ERR_CAMPAIGN_SCOPE_EMPTY",
                      "Campaign scope is empty")
        scope.sort(key=lambda b: (b["fleet_number"], b["created_at"], b["_seq"]))
        camp["scope_bus_ids"] = [b["id"] for b in scope]
        camp["activated_date"] = fmt_date(clock_date())
        camp["status"] = "ACTIVE"
        # immediate suspension if the required part is backordered
        if camp.get("required_part_id"):
            part = db["parts"].get(camp["required_part_id"])
            if part is not None and part["stock_status"] == "BACKORDERED":
                camp["status"] = "SUSPENDED"
    elif event_type == "SUSPEND":
        camp["status"] = "SUSPENDED"
    elif event_type == "RESUME":
        if camp.get("required_part_id"):
            part = db["parts"].get(camp["required_part_id"])
            if part is not None and part["stock_status"] == "BACKORDERED":
                raise err("ERR_PART_STOCK_INSUFFICIENT",
                          "Required part is BACKORDERED")
        camp["status"] = "ACTIVE"
    elif event_type == "CLOSE":
        camp["status"] = "CLOSED"
    mark_dirty("campaigns", camp["id"])
    return success(ser.campaign(camp))


# ---------------------------------------------------------------------------
# Emissions inspections
# ---------------------------------------------------------------------------
@bp.post("/fleet/emissions-inspections")
def create_inspection():
    require_roles("MaintenanceSupervisor")
    data = body()
    bus_id = data.get("bus_id")
    bus = None
    if bus_id is not None:
        bus = db["buses"].get(bus_id)
        if bus is None:
            raise err("ERR_NOT_FOUND", f"Bus {bus_id} not found")
    part_id = data.get("failed_component_part_id")
    part = None
    if part_id is not None:
        part = db["parts"].get(part_id)
        if part is None:
            raise err("ERR_NOT_FOUND", f"Part {part_id} not found")
    if bus_id is None:
        raise err("ERR_VALIDATION", "Missing required field: bus_id")
    test_type = req_enum(data, "test_type", {"OPACITY", "OBD", "IDLE"})
    test_date = req_date(data, "test_date")
    result = req_enum(data, "result", {"PASS", "FAIL"})
    cert_expiry = data.get("certificate_expiry_date")
    if cert_expiry is not None:
        from httpkit import parse_date_str
        cert_expiry = parse_date_str(cert_expiry, "certificate_expiry_date")
    if result == "PASS" and cert_expiry is None:
        raise err("ERR_VALIDATION",
                  "certificate_expiry_date is required when result is PASS")
    if test_date > clock_date():
        raise err("ERR_VALIDATION",
                  "test_date must not be after the logical clock date")
    if bus["service_status"] == "RETIRED":
        raise err("ERR_BUS_RETIRED", "Referenced bus is RETIRED")

    insp = init_common({
        "bus_id": bus["id"],
        "test_type": test_type,
        "test_date": fmt_date(test_date),
        "result": result,
        "failed_component_part_id": part_id,
        "certificate_expiry_date": fmt_date(cert_expiry) if cert_expiry else None,
        "status": "RECORDED",
    })
    db["inspections"][insp["id"]] = insp

    if result == "PASS":
        bus["emissions_cert_expiry_date"] = fmt_date(cert_expiry)
        bus["emissions_hold"] = False
        mark_dirty("buses", bus["id"])
        dom.recompute_bus_availability(bus)
        dom.recompute_posture()
    else:
        bus["emissions_hold"] = True
        mark_dirty("buses", bus["id"])
        # auto-create EMISSIONS work order in SCHEDULED, EMERGENCY
        today = clock_date()
        wo = init_common({
            "bus_id": bus["id"],
            "wo_type": "EMISSIONS",
            "priority": "EMERGENCY",
            "defect_report_id": None,
            "campaign_id": None,
            "emissions_inspection_id": insp["id"],
            "lead_mechanic_id": None,
            "planned_start_date": fmt_date(today),
            "planned_end_date": fmt_date(today + timedelta(days=7)),
            "estimated_labor_hours": 8,
            "estimated_cost_cents": 0,
            "odometer_at_open": bus["odometer_miles"],
            "opened_date": fmt_date(today),
            "started_date": None,
            "closed_date": None,
            "status": "SCHEDULED",
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
        if part is not None:
            line = init_common({
                "work_order_id": wo["id"],
                "part_id": part["id"],
                "qty": 1,
                "qty_issued": 0,
                "unit_cost_cents": part["unit_cost_cents"],
                "issue_status": "RESERVED",
                "core_status": "NONE",
                "core_due_date": None,
            })
            db["part_lines"][line["id"]] = line
            part["quantity_reserved"] += 1
            mark_dirty("parts", part["id"])
            dom.recompute_stock_status(part)
        dom.recompute_bus_availability(bus)
        dom.recompute_posture()
    return success(ser.inspection(insp), code=201)


@bp.get("/fleet/emissions-inspections/<iid>")
def get_inspection(iid):
    require_roles(*ALL)
    insp = db["inspections"].get(iid)
    if insp is None:
        raise err("ERR_NOT_FOUND", f"EmissionsInspection {iid} not found")
    return success(ser.inspection(insp))


@bp.get("/fleet/emissions-inspections")
def list_inspections():
    require_roles(*ALL)
    items = list(db["inspections"].values())
    bus_id = request.args.get("bus_id")
    if bus_id is not None:
        items = [i for i in items if i["bus_id"] == bus_id]
    fp = request.args.get("failed_component_part_id")
    if fp is not None:
        items = [i for i in items if i.get("failed_component_part_id") == fp]
    items = sort_default(items)
    page, meta_p = paginate(items)
    return success([ser.inspection(i) for i in page], response_type="array",
                   pagination=meta_p)


@bp.get("/fleet/emissions-inspections/<iid>/work-orders")
def inspection_wos(iid):
    require_roles(*ALL)
    insp = db["inspections"].get(iid)
    if insp is None:
        raise err("ERR_NOT_FOUND", f"EmissionsInspection {iid} not found")
    items = sort_default([w for w in db["work_orders"].values()
                          if w.get("emissions_inspection_id") == iid])
    page, meta_p = paginate(items)
    return success([ser.work_order(w) for w in page], response_type="array",
                   pagination=meta_p)
