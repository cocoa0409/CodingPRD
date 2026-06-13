"""Septic & Well Service API — Flask entry point.

In-memory storage only; the store starts empty on every boot. Reads $PORT,
binds 0.0.0.0, runs in the foreground.
"""
import os

from flask import Flask, request

from errors import ApiError, err
from response import object_response, array_response, error_response
from auth import current_identity, require_roles
from validation import (
    get_body,
    require_fields,
    require_string,
    require_int,
    optional_int,
    require_enum,
    optional_bool,
)
from db import db, common_create, touch, new_id
from timeutil import iso_ms, parse_iso, parse_date
from clock import clock
import calculations as calc
import services as svc
import serializers as ser

app = Flask(__name__)

ALL_ROLES = ["Dispatcher", "ComplianceOfficer", "FieldTech", "Customer"]
WORK_TYPES = {"PUMPING", "INSPECTION", "EMERGENCY", "REPAIR"}
ASSET_TYPES = {"SEPTIC_TANK", "WELL"}
INSPECTION_RESULTS = {"PASS", "CONDITIONAL", "FAIL"}


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------
@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return error_response("ERR_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_NOT_FOUND", "Method not allowed", 404)


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    return error_response("ERR_INVALID_REQUEST", "Unexpected error: %s" % e, 400)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------
def auth():
    """Validate auth headers and return (user_id, role)."""
    return current_identity()


def get_or_404(collection, rid):
    obj = collection.get(rid)
    if obj is None:
        raise err("ERR_NOT_FOUND", "Resource not found")
    return obj


def fk_or_422(collection, rid):
    obj = collection.get(rid)
    if obj is None:
        raise err("ERR_FK_NOT_FOUND", "Referenced resource does not exist")
    return obj


def paginate(items):
    """Apply limit/offset query params. Returns (page_items, limit, offset, total)."""
    total = len(items)
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer")
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    page = items[offset:offset + limit]
    return page, limit, offset, total


def sorted_by_created(values):
    """Sort entities by creation order ascending (created_at, _seq tie-break)."""
    return sorted(values, key=lambda e: (e["created_at"], e.get("_seq", 0)))


# ===========================================================================
# Account
# ===========================================================================
@app.route("/accounts", methods=["POST"])
def create_account():
    _, role = auth()
    require_roles(role, ["Dispatcher"])
    body = get_body()
    require_fields(body, ["name", "billing_email"])
    name = require_string(body, "name")
    email = require_string(body, "billing_email")
    a = common_create()
    a.update({
        "name": name,
        "billing_email": email,
        "standing": "GOOD",
        "outstanding_balance_cents": 0,
        "_seq": db.next_seq(),
    })
    db.accounts[a["id"]] = a
    return object_response(ser.account_out(a), 201)


@app.route("/accounts/<rid>", methods=["GET"])
def get_account(rid):
    _, role = auth()
    require_roles(role, ALL_ROLES)
    a = get_or_404(db.accounts, rid)
    return object_response(ser.account_out(a), 200)


@app.route("/accounts/<rid>/sites", methods=["GET"])
def list_account_sites(rid):
    _, role = auth()
    require_roles(role, ALL_ROLES)
    get_or_404(db.accounts, rid)
    items = sorted_by_created([s for s in db.sites.values() if s["account_id"] == rid])
    page, limit, offset, total = paginate(items)
    return array_response([ser.site_out(s) for s in page], limit, offset, total)


@app.route("/accounts/<rid>/hold", methods=["POST"])
def account_hold(rid):
    _, role = auth()
    require_roles(role, ["Dispatcher"])
    a = get_or_404(db.accounts, rid)
    if a["standing"] != "GOOD":
        raise err("ERR_INVALID_STATE", "Account is not in GOOD standing")
    # Set HOLD.
    a["standing"] = "HOLD"
    # Cascade: cancel the account's sites' work orders that are on the calendar
    # — those in SCHEDULED or DISPATCHED (i.e., assigned to a route). Bare DRAFT
    # work orders that were never scheduled are not yet on the calendar and are
    # left untouched, so a later schedule attempt surfaces ERR_ACCOUNT_ON_HOLD
    # against the still-DRAFT order. (The cascade-cancel system transitions in
    # the state machine are defined only for SCHEDULED/DISPATCHED -> CANCELLED.)
    site_ids = {s["id"] for s in db.sites.values() if s["account_id"] == rid}
    affected_routes = set()
    for w in db.work_orders.values():
        if w["site_id"] in site_ids and w["status"] in ("SCHEDULED", "DISPATCHED"):
            had_route = w["route_id"]
            w["status"] = "CANCELLED"
            w["route_id"] = None
            w["technician_id"] = None
            touch(w)
            if had_route:
                affected_routes.add(had_route)
    for route_id in affected_routes:
        route = db.routes.get(route_id)
        if route is not None:
            svc.recompute_route_counters(route)
    touch(a)  # increments version by 1 (the hold itself)
    return object_response(ser.account_out(a), 200)


@app.route("/accounts/<rid>/release-hold", methods=["POST"])
def account_release_hold(rid):
    _, role = auth()
    require_roles(role, ["Dispatcher"])
    a = get_or_404(db.accounts, rid)
    if a["standing"] != "HOLD":
        raise err("ERR_INVALID_STATE", "Account is not on HOLD")
    a["standing"] = "GOOD"
    touch(a)
    return object_response(ser.account_out(a), 200)


# ===========================================================================
# Technician
# ===========================================================================
@app.route("/technicians", methods=["POST"])
def create_technician():
    _, role = auth()
    require_roles(role, ["Dispatcher"])
    body = get_body()
    require_fields(body, ["name", "shift_start_minute", "shift_end_minute"])
    name = require_string(body, "name")
    start = require_int(body, "shift_start_minute")
    end = require_int(body, "shift_end_minute")
    certified = optional_bool(body, "certified_for_wells", False)
    # priority 13 field-range invariants
    if not (0 <= start <= 1440):
        raise err("ERR_VALIDATION", "shift_start_minute out of range")
    if not (0 <= end <= 1440):
        raise err("ERR_VALIDATION", "shift_end_minute out of range")
    if end <= start:
        raise err("ERR_VALIDATION", "shift_end_minute must be greater than shift_start_minute")
    t = common_create()
    t.update({
        "name": name,
        "shift_start_minute": start,
        "shift_end_minute": end,
        "certified_for_wells": certified,
        "status": "ACTIVE",
        "_seq": db.next_seq(),
    })
    db.technicians[t["id"]] = t
    return object_response(ser.technician_out(t), 201)


@app.route("/technicians/<rid>", methods=["GET"])
def get_technician(rid):
    _, role = auth()
    require_roles(role, ALL_ROLES)
    t = get_or_404(db.technicians, rid)
    return object_response(ser.technician_out(t), 200)


@app.route("/technicians/<rid>/suspend", methods=["POST"])
def technician_suspend(rid):
    _, role = auth()
    require_roles(role, ["Dispatcher"])
    t = get_or_404(db.technicians, rid)
    if t["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Technician is not ACTIVE")
    t["status"] = "SUSPENDED"
    # Revert DISPATCHED WOs of this technician to SCHEDULED, clearing technician_id.
    for w in db.work_orders.values():
        if w["technician_id"] == rid and w["status"] == "DISPATCHED":
            w["status"] = "SCHEDULED"
            w["technician_id"] = None
            touch(w)
            # Route counters unaffected (SCHEDULED still counted) — no recompute.
    touch(t)
    return object_response(ser.technician_out(t), 200)


@app.route("/technicians/<rid>/reinstate", methods=["POST"])
def technician_reinstate(rid):
    _, role = auth()
    require_roles(role, ["Dispatcher"])
    t = get_or_404(db.technicians, rid)
    if t["status"] != "SUSPENDED":
        raise err("ERR_INVALID_STATE", "Technician is not SUSPENDED")
    t["status"] = "ACTIVE"
    touch(t)
    return object_response(ser.technician_out(t), 200)


@app.route("/technicians/<rid>/routes", methods=["GET"])
def list_technician_routes(rid):
    _, role = auth()
    require_roles(role, ALL_ROLES)
    get_or_404(db.technicians, rid)
    items = sorted_by_created([r for r in db.routes.values() if r["technician_id"] == rid])
    page, limit, offset, total = paginate(items)
    return array_response([ser.route_out(r) for r in page], limit, offset, total)


# ===========================================================================
# Site
# ===========================================================================
@app.route("/sites", methods=["POST"])
def create_site():
    _, role = auth()
    require_roles(role, ["Dispatcher"])
    body = get_body()
    require_fields(body, ["account_id", "address", "county_code"])
    account_id = require_string(body, "account_id")
    address = require_string(body, "address")
    county_code = require_string(body, "county_code")
    # priority 11 FK before priority 13 range
    fk_or_422(db.accounts, account_id)
    service_minutes = optional_int(body, "service_minutes", 60)
    if service_minutes < 15:
        raise err("ERR_VALIDATION", "service_minutes must be at least 15")
    s = common_create()
    s.update({
        "account_id": account_id,
        "address": address,
        "county_code": county_code,
        "service_minutes": service_minutes,
        "compliance_status": "UNKNOWN",
        "risk_score": 0,
        "last_pumped_date": None,
        "next_pump_due_date": None,
        "_seq": db.next_seq(),
    })
    db.sites[s["id"]] = s
    return object_response(ser.site_out(s), 201)


@app.route("/sites/<rid>", methods=["GET"])
def get_site(rid):
    _, role = auth()
    require_roles(role, ALL_ROLES)
    s = get_or_404(db.sites, rid)
    return object_response(ser.site_out(s), 200)


@app.route("/sites/<rid>/assets", methods=["GET"])
def list_site_assets(rid):
    _, role = auth()
    require_roles(role, ALL_ROLES)
    get_or_404(db.sites, rid)
    items = sorted_by_created([a for a in db.assets.values() if a["site_id"] == rid])
    page, limit, offset, total = paginate(items)
    return array_response([ser.asset_out(a) for a in page], limit, offset, total)


@app.route("/sites/<rid>/service-plans", methods=["GET"])
def list_site_service_plans(rid):
    _, role = auth()
    require_roles(role, ALL_ROLES)
    get_or_404(db.sites, rid)
    items = sorted_by_created([p for p in db.service_plans.values() if p["site_id"] == rid])
    page, limit, offset, total = paginate(items)
    return array_response([ser.service_plan_out(p) for p in page], limit, offset, total)


@app.route("/sites/<rid>/reminders", methods=["GET"])
def list_site_reminders(rid):
    _, role = auth()
    require_roles(role, ALL_ROLES)
    get_or_404(db.sites, rid)
    items = sorted_by_created([r for r in db.reminders.values() if r["site_id"] == rid])
    page, limit, offset, total = paginate(items)
    return array_response([ser.reminder_out(r) for r in page], limit, offset, total)


# ===========================================================================
# Asset
# ===========================================================================
@app.route("/assets", methods=["POST"])
def create_asset():
    _, role = auth()
    require_roles(role, ["Dispatcher"])
    body = get_body()
    require_fields(body, ["site_id", "asset_type", "capacity_gallons", "install_year"])
    site_id = require_string(body, "site_id")
    asset_type = require_enum(body, "asset_type", ASSET_TYPES)
    capacity = require_int(body, "capacity_gallons")
    install_year = require_int(body, "install_year")
    fk_or_422(db.sites, site_id)
    if capacity <= 0:
        raise err("ERR_VALIDATION", "capacity_gallons must be greater than zero")
    a = common_create()
    a.update({
        "site_id": site_id,
        "asset_type": asset_type,
        "capacity_gallons": capacity,
        "install_year": install_year,
        "status": "ACTIVE",
        "_seq": db.next_seq(),
    })
    db.assets[a["id"]] = a
    return object_response(ser.asset_out(a), 201)


@app.route("/assets/<rid>", methods=["GET"])
def get_asset(rid):
    _, role = auth()
    require_roles(role, ALL_ROLES)
    a = get_or_404(db.assets, rid)
    return object_response(ser.asset_out(a), 200)


# ===========================================================================
# ServicePlan
# ===========================================================================
@app.route("/service-plans", methods=["POST"])
def create_service_plan():
    _, role = auth()
    require_roles(role, ["Dispatcher"])
    body = get_body()
    require_fields(body, ["site_id", "frequency_months", "estimated_gallons", "expected_site_version"])
    site_id = require_string(body, "site_id")
    frequency = require_int(body, "frequency_months")
    est_gallons = require_int(body, "estimated_gallons")
    expected_version = require_int(body, "expected_site_version")
    site = fk_or_422(db.sites, site_id)
    # priority 13 field-range
    if not (1 <= frequency <= 120):
        raise err("ERR_VALIDATION", "frequency_months must be between 1 and 120")
    if est_gallons <= 0:
        raise err("ERR_VALIDATION", "estimated_gallons must be greater than zero")
    # priority 60 OCC
    if expected_version != site["version"]:
        raise err("ERR_STALE_VERSION", "expected_site_version does not match site version")
    # supersede prior ACTIVE plan
    prior = svc.active_service_plan(site_id)
    if prior is not None:
        prior["status"] = "SUPERSEDED"
        touch(prior)
    p = common_create()
    p.update({
        "site_id": site_id,
        "frequency_months": frequency,
        "estimated_gallons": est_gallons,
        "status": "ACTIVE",
        "_seq": db.next_seq(),
    })
    db.service_plans[p["id"]] = p
    # recompute site next_pump_due_date and bump site version
    svc.reconcile_site_due_date(site)
    return object_response(ser.service_plan_out(p), 201)


@app.route("/service-plans/<rid>", methods=["GET"])
def get_service_plan(rid):
    _, role = auth()
    require_roles(role, ALL_ROLES)
    p = get_or_404(db.service_plans, rid)
    return object_response(ser.service_plan_out(p), 200)


# ===========================================================================
# WorkOrder
# ===========================================================================
@app.route("/work-orders", methods=["POST"])
def create_work_order():
    _, role = auth()
    require_roles(role, ["Dispatcher"])
    body = get_body()
    require_fields(body, ["site_id", "work_type", "scheduled_date", "window_start_minute"])
    site_id = require_string(body, "site_id")
    work_type = require_enum(body, "work_type", WORK_TYPES)
    scheduled_date = require_string(body, "scheduled_date")
    window_start = require_int(body, "window_start_minute")
    estimated_gallons = optional_int(body, "estimated_gallons", None)
    fk_or_422(db.sites, site_id)
    if not (0 <= window_start <= 1440):
        raise err("ERR_VALIDATION", "window_start_minute out of range")
    w = common_create()
    w.update({
        "site_id": site_id,
        "route_id": None,
        "technician_id": None,
        "work_type": work_type,
        "scheduled_date": scheduled_date,
        "window_start_minute": window_start,
        "estimated_gallons": estimated_gallons,
        "measured_gallons": None,
        "emergency_surcharge_applies": (work_type == "EMERGENCY"),
        "status": "DRAFT",
        "billing_status": "UNBILLED",
        "estimated_cost_cents": 0,
        "final_cost_cents": 0,
        "invoice_total_cents": 0,
        "window_end_minute": None,
        "_seq": db.next_seq(),
    })
    db.work_orders[w["id"]] = w
    return object_response(ser.work_order_out(w), 201)


@app.route("/work-orders/<rid>", methods=["GET"])
def get_work_order(rid):
    _, role = auth()
    require_roles(role, ALL_ROLES)
    w = get_or_404(db.work_orders, rid)
    return object_response(ser.work_order_out(w), 200)


@app.route("/work-orders", methods=["GET"])
def list_work_orders():
    _, role = auth()
    require_roles(role, ALL_ROLES)
    site_id = request.args.get("site_id")
    technician_id = request.args.get("technician_id")
    route_id = request.args.get("route_id")
    status = request.args.get("status")
    items = list(db.work_orders.values())
    if site_id is not None:
        items = [w for w in items if w["site_id"] == site_id]
    if technician_id is not None:
        items = [w for w in items if w["technician_id"] == technician_id]
    if route_id is not None:
        items = [w for w in items if w["route_id"] == route_id]
    if status is not None:
        items = [w for w in items if w["status"] == status]
    items = sorted_by_created(items)
    page, limit, offset, total = paginate(items)
    return array_response([ser.work_order_out(w) for w in page], limit, offset, total)


def _is_well_job(work_order):
    """A well job: the site has any ACTIVE WELL asset (well asset / well inspection)."""
    site_id = work_order["site_id"]
    for a in db.assets.values():
        if a["site_id"] == site_id and a["asset_type"] == "WELL" and a["status"] == "ACTIVE":
            return True
    return False


@app.route("/work-orders/<rid>/schedule", methods=["POST"])
def work_order_schedule(rid):
    _, role = auth()
    require_roles(role, ["Dispatcher"])
    w = get_or_404(db.work_orders, rid)
    body = get_body()
    require_fields(body, ["route_id"])
    route_id = require_string(body, "route_id")
    route = fk_or_422(db.routes, route_id)
    # priority 20 state: schedule defined only from DRAFT
    if w["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "schedule is only defined from DRAFT")
    site = db.sites.get(w["site_id"])
    account = db.accounts.get(site["account_id"]) if site else None
    # Ordered business checks (PRD §3.4):
    # 30 account standing
    if account is None or account["standing"] != "GOOD":
        raise err("ERR_ACCOUNT_ON_HOLD", "Owning account is on HOLD")
    # 25 route open
    if route["status"] != "OPEN":
        raise err("ERR_ROUTE_LOCKED", "Route is LOCKED")
    technician = db.technicians.get(route["technician_id"])
    service_minutes = site["service_minutes"]
    window_start = w["window_start_minute"]
    window_end = window_start + service_minutes
    scheduled_date = w["scheduled_date"]
    # 35 technician window overlap (half-open [start,end))
    for other in db.work_orders.values():
        if other["id"] == w["id"]:
            continue
        if other["status"] not in ("SCHEDULED", "DISPATCHED"):
            continue
        o_route = db.routes.get(other["route_id"])
        if o_route is None or o_route["technician_id"] != route["technician_id"]:
            continue
        if other["scheduled_date"] != scheduled_date:
            continue
        o_start = other["window_start_minute"]
        o_end = other["window_end_minute"]
        if o_start is None or o_end is None:
            continue
        # half-open overlap
        if window_start < o_end and o_start < window_end:
            raise err("ERR_TECH_WINDOW_CONFLICT", "Technician window overlaps another work order")
    # 36 site day-buffer (closed interval + buffer)
    for other in db.work_orders.values():
        if other["id"] == w["id"]:
            continue
        if other["status"] not in ("SCHEDULED", "DISPATCHED"):
            continue
        if other["site_id"] != w["site_id"]:
            continue
        if other["scheduled_date"] != scheduled_date:
            continue
        o_start = other["window_start_minute"]
        o_end = other["window_end_minute"]
        if o_start is None or o_end is None:
            continue
        # gap = later.start - earlier.end ; require >= SITE_BUFFER_MINUTES
        if window_start >= o_start:
            gap = window_start - o_end
        else:
            gap = o_start - window_end
        if gap < calc.SITE_BUFFER_MINUTES:
            raise err("ERR_SITE_BUFFER_CONFLICT", "Window too close to other work at this site")
    # 37 shift bounds: both window_start and window_end within [shift_start, shift_end]
    if technician is not None:
        if window_start < technician["shift_start_minute"] or window_end > technician["shift_end_minute"]:
            raise err("ERR_OUTSIDE_SHIFT", "Window outside technician shift")
    # Apply side effects.
    w["status"] = "SCHEDULED"
    w["route_id"] = route_id
    w["window_end_minute"] = window_end
    # default estimated_gallons from active plan for PUMPING when omitted
    if w["estimated_gallons"] is None and w["work_type"] == "PUMPING":
        plan = svc.active_service_plan(w["site_id"])
        if plan is not None:
            w["estimated_gallons"] = plan["estimated_gallons"]
    est_gallons = w["estimated_gallons"] if w["estimated_gallons"] is not None else 0
    w["estimated_cost_cents"] = calc.work_order_cost(est_gallons, w["emergency_surcharge_applies"])
    touch(w)
    svc.recompute_route_counters(route)
    return object_response(ser.work_order_out(w), 200)


@app.route("/work-orders/<rid>/dispatch", methods=["POST"])
def work_order_dispatch(rid):
    _, role = auth()
    require_roles(role, ["Dispatcher"])
    w = get_or_404(db.work_orders, rid)
    if w["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "dispatch is only defined from SCHEDULED")
    route = db.routes.get(w["route_id"])
    technician = db.technicians.get(route["technician_id"]) if route else None
    # 31 technician active
    if technician is None or technician["status"] != "ACTIVE":
        raise err("ERR_TECH_SUSPENDED", "Technician is suspended")
    # 32 well certification
    if _is_well_job(w) and not technician["certified_for_wells"]:
        raise err("ERR_TECH_NOT_CERTIFIED", "Technician is not certified for wells")
    w["status"] = "DISPATCHED"
    w["technician_id"] = route["technician_id"]
    touch(w)
    return object_response(ser.work_order_out(w), 200)


@app.route("/work-orders/<rid>/revert", methods=["POST"])
def work_order_revert(rid):
    _, role = auth()
    require_roles(role, ["Dispatcher"])
    w = get_or_404(db.work_orders, rid)
    if w["status"] != "DISPATCHED":
        raise err("ERR_INVALID_STATE", "revert is only defined from DISPATCHED")
    route = db.routes.get(w["route_id"])
    # 25 route must be OPEN
    if route is not None and route["status"] != "OPEN":
        raise err("ERR_ROUTE_LOCKED", "Route is LOCKED")
    w["status"] = "SCHEDULED"
    w["technician_id"] = None
    touch(w)
    return object_response(ser.work_order_out(w), 200)


@app.route("/work-orders/<rid>/start", methods=["POST"])
def work_order_start(rid):
    user_id, role = auth()
    require_roles(role, ["FieldTech"])
    w = get_or_404(db.work_orders, rid)
    if w["status"] != "DISPATCHED":
        raise err("ERR_INVALID_STATE", "start is only defined from DISPATCHED")
    if w["technician_id"] != user_id:
        raise err("ERR_FORBIDDEN", "Field tech may only start own work order")
    w["status"] = "IN_PROGRESS"
    touch(w)
    return object_response(ser.work_order_out(w), 200)


@app.route("/work-orders/<rid>/complete", methods=["POST"])
def work_order_complete(rid):
    user_id, role = auth()
    require_roles(role, ["FieldTech"])
    w = get_or_404(db.work_orders, rid)
    body = get_body()
    if w["status"] != "IN_PROGRESS":
        raise err("ERR_INVALID_STATE", "complete is only defined from IN_PROGRESS")
    if w["technician_id"] != user_id:
        raise err("ERR_FORBIDDEN", "Field tech may only complete own work order")
    measured = optional_int(body, "measured_gallons", None)
    # 50 measurement required for PUMPING/EMERGENCY
    if w["work_type"] in ("PUMPING", "EMERGENCY"):
        if measured is None or measured < 0:
            raise err("ERR_MEASUREMENT_REQUIRED", "measured_gallons required for PUMPING/EMERGENCY")
    if measured is not None:
        w["measured_gallons"] = measured
    w["status"] = "COMPLETED"
    # final cost
    gallons = w["measured_gallons"] if w["measured_gallons"] is not None else 0
    w["final_cost_cents"] = calc.work_order_cost(gallons, w["emergency_surcharge_applies"])
    # invoice total = final + sum(repair line totals) (round-per-line-then-sum)
    lines = sorted_by_created([rl for rl in db.repair_lines.values() if rl["work_order_id"] == w["id"]])
    w["invoice_total_cents"] = calc.invoice_total(w["final_cost_cents"], lines)
    touch(w)
    # route counters recompute (left counted set)
    route = db.routes.get(w["route_id"])
    if route is not None:
        svc.recompute_route_counters(route)
    # PUMPING/EMERGENCY site cascade
    if w["work_type"] in ("PUMPING", "EMERGENCY"):
        site = db.sites.get(w["site_id"])
        if site is not None:
            site["last_pumped_date"] = w["scheduled_date"]
            svc.reconcile_site_due_date(site)
            svc.emit_pump_due_reminder(site)
    return object_response(ser.work_order_out(w), 200)


@app.route("/work-orders/<rid>/cancel", methods=["POST"])
def work_order_cancel(rid):
    _, role = auth()
    require_roles(role, ["Dispatcher"])
    w = get_or_404(db.work_orders, rid)
    if w["status"] not in ("DRAFT", "SCHEDULED", "DISPATCHED"):
        raise err("ERR_INVALID_STATE", "cancel is not defined from this state")
    had_route = w["route_id"]
    from_state = w["status"]
    w["status"] = "CANCELLED"
    w["route_id"] = None
    w["technician_id"] = None
    touch(w)
    if from_state in ("SCHEDULED", "DISPATCHED") and had_route:
        route = db.routes.get(had_route)
        if route is not None:
            svc.recompute_route_counters(route)
    return object_response(ser.work_order_out(w), 200)


@app.route("/work-orders/<rid>/invoice", methods=["POST"])
def work_order_invoice(rid):
    _, role = auth()
    require_roles(role, ["Dispatcher"])
    w = get_or_404(db.work_orders, rid)
    # billing axis: UNBILLED -> INVOICED
    if w["billing_status"] != "UNBILLED":
        raise err("ERR_INVALID_STATE", "invoice is only defined from UNBILLED")
    if w["status"] != "COMPLETED":
        raise err("ERR_INVALID_STATE", "Work order must be COMPLETED to invoice")
    w["billing_status"] = "INVOICED"
    touch(w)
    site = db.sites.get(w["site_id"])
    account = db.accounts.get(site["account_id"]) if site else None
    if account is not None:
        account["outstanding_balance_cents"] += w["invoice_total_cents"]
        touch(account)
    return object_response(ser.work_order_out(w), 200)


@app.route("/work-orders/<rid>/pay", methods=["POST"])
def work_order_pay(rid):
    _, role = auth()
    require_roles(role, ["Dispatcher"])
    w = get_or_404(db.work_orders, rid)
    if w["billing_status"] != "INVOICED":
        raise err("ERR_INVALID_STATE", "pay is only defined from INVOICED")
    w["billing_status"] = "PAID"
    touch(w)
    site = db.sites.get(w["site_id"])
    account = db.accounts.get(site["account_id"]) if site else None
    if account is not None:
        account["outstanding_balance_cents"] -= w["invoice_total_cents"]
        touch(account)
    return object_response(ser.work_order_out(w), 200)


@app.route("/work-orders/<rid>/repair-lines", methods=["GET"])
def list_work_order_repair_lines(rid):
    _, role = auth()
    require_roles(role, ALL_ROLES)
    get_or_404(db.work_orders, rid)
    items = sorted_by_created([rl for rl in db.repair_lines.values() if rl["work_order_id"] == rid])
    page, limit, offset, total = paginate(items)
    return array_response([ser.repair_line_out(rl) for rl in page], limit, offset, total)


@app.route("/work-orders/<rid>/inspection-reports", methods=["GET"])
def list_work_order_inspection_reports(rid):
    _, role = auth()
    require_roles(role, ALL_ROLES)
    get_or_404(db.work_orders, rid)
    items = sorted_by_created([ir for ir in db.inspection_reports.values() if ir["work_order_id"] == rid])
    page, limit, offset, total = paginate(items)
    return array_response([ser.inspection_report_out(ir) for ir in page], limit, offset, total)


# ===========================================================================
# RepairLine
# ===========================================================================
@app.route("/repair-lines", methods=["POST"])
def create_repair_line():
    _, role = auth()
    require_roles(role, ["Dispatcher", "FieldTech"])
    body = get_body()
    require_fields(body, ["work_order_id", "part_name", "quantity", "unit_price_cents"])
    work_order_id = require_string(body, "work_order_id")
    part_name = require_string(body, "part_name")
    quantity = require_int(body, "quantity")
    unit_price = require_int(body, "unit_price_cents")
    tax_rate_bps = optional_int(body, "tax_rate_bps", 0)
    fk_or_422(db.work_orders, work_order_id)
    # priority 13 field-range
    if quantity <= 0:
        raise err("ERR_VALIDATION", "quantity must be greater than zero")
    if unit_price < 0:
        raise err("ERR_VALIDATION", "unit_price_cents must be at least zero")
    if not (0 <= tax_rate_bps <= 2000):
        raise err("ERR_VALIDATION", "tax_rate_bps must be between 0 and 2000")
    rl = common_create()
    rl.update({
        "work_order_id": work_order_id,
        "part_name": part_name,
        "quantity": quantity,
        "unit_price_cents": unit_price,
        "tax_rate_bps": tax_rate_bps,
        "line_total_cents": calc.repair_line_total(quantity, unit_price, tax_rate_bps),
        "_seq": db.next_seq(),
    })
    db.repair_lines[rl["id"]] = rl
    return object_response(ser.repair_line_out(rl), 201)


# ===========================================================================
# Route
# ===========================================================================
@app.route("/routes", methods=["POST"])
def create_route():
    _, role = auth()
    require_roles(role, ["Dispatcher"])
    body = get_body()
    require_fields(body, ["technician_id", "route_date"])
    technician_id = require_string(body, "technician_id")
    route_date = require_string(body, "route_date")
    fk_or_422(db.technicians, technician_id)
    r = common_create()
    r.update({
        "technician_id": technician_id,
        "route_date": route_date,
        "status": "OPEN",
        "assigned_stop_count": 0,
        "booked_minutes": 0,
        "optimized_sequence": [],
        "_seq": db.next_seq(),
    })
    db.routes[r["id"]] = r
    return object_response(ser.route_out(r), 201)


@app.route("/routes/<rid>", methods=["GET"])
def get_route(rid):
    _, role = auth()
    require_roles(role, ALL_ROLES)
    r = get_or_404(db.routes, rid)
    return object_response(ser.route_out(r), 200)


@app.route("/routes/<rid>/work-orders", methods=["GET"])
def list_route_work_orders(rid):
    _, role = auth()
    require_roles(role, ALL_ROLES)
    get_or_404(db.routes, rid)
    items = sorted_by_created([w for w in db.work_orders.values() if w["route_id"] == rid])
    page, limit, offset, total = paginate(items)
    return array_response([ser.work_order_out(w) for w in page], limit, offset, total)


@app.route("/routes/<rid>/optimize", methods=["POST"])
def route_optimize(rid):
    _, role = auth()
    require_roles(role, ["Dispatcher"])
    r = get_or_404(db.routes, rid)
    # 25 locked routes reject optimize
    if r["status"] != "OPEN":
        raise err("ERR_ROUTE_LOCKED", "Route is LOCKED")
    candidates = [
        w for w in db.work_orders.values()
        if w["route_id"] == rid and w["status"] in ("SCHEDULED", "DISPATCHED")
    ]
    candidates.sort(key=lambda w: (w["window_start_minute"], w["created_at"], w.get("_seq", 0)))
    r["optimized_sequence"] = [w["id"] for w in candidates]
    touch(r)
    return object_response(ser.route_out(r), 200)


@app.route("/routes/<rid>/lock", methods=["POST"])
def route_lock(rid):
    _, role = auth()
    require_roles(role, ["Dispatcher"])
    r = get_or_404(db.routes, rid)
    if r["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "lock is only defined from OPEN")
    r["status"] = "LOCKED"
    touch(r)
    return object_response(ser.route_out(r), 200)


# ===========================================================================
# InspectionReport
# ===========================================================================
@app.route("/inspection-reports", methods=["POST"])
def create_inspection_report():
    _, role = auth()
    require_roles(role, ["ComplianceOfficer"])
    body = get_body()
    require_fields(body, ["work_order_id"])
    work_order_id = require_string(body, "work_order_id")
    defect_count = optional_int(body, "defect_count", 0)
    fk_or_422(db.work_orders, work_order_id)
    if defect_count < 0:
        raise err("ERR_VALIDATION", "defect_count must be at least zero")
    ir = common_create()
    ir.update({
        "work_order_id": work_order_id,
        "result": None,
        "defect_count": defect_count,
        "status": "DRAFT",
        "finalized_at": None,
        "_seq": db.next_seq(),
    })
    db.inspection_reports[ir["id"]] = ir
    return object_response(ser.inspection_report_out(ir), 201)


@app.route("/inspection-reports/<rid>", methods=["GET"])
def get_inspection_report(rid):
    _, role = auth()
    require_roles(role, ALL_ROLES)
    ir = get_or_404(db.inspection_reports, rid)
    return object_response(ser.inspection_report_out(ir), 200)


@app.route("/inspection-reports/<rid>", methods=["PATCH"])
def patch_inspection_report(rid):
    _, role = auth()
    require_roles(role, ["ComplianceOfficer"])
    ir = get_or_404(db.inspection_reports, rid)
    body = get_body()
    # priority 21 immutable when not DRAFT
    if ir["status"] != "DRAFT":
        raise err("ERR_IMMUTABLE", "FINALIZED report is immutable")
    changed = False
    if "result" in body and body["result"] is not None:
        result = require_enum(body, "result", INSPECTION_RESULTS)
        ir["result"] = result
        changed = True
    if "defect_count" in body and body["defect_count"] is not None:
        dc = require_int(body, "defect_count")
        if dc < 0:
            raise err("ERR_VALIDATION", "defect_count must be at least zero")
        ir["defect_count"] = dc
        changed = True
    if changed:
        touch(ir)
    return object_response(ser.inspection_report_out(ir), 200)


@app.route("/inspection-reports/<rid>/finalize", methods=["POST"])
def finalize_inspection_report(rid):
    _, role = auth()
    require_roles(role, ["ComplianceOfficer"])
    ir = get_or_404(db.inspection_reports, rid)
    body = get_body()
    # priority 20 state: finalize defined only from DRAFT
    if ir["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "finalize is only defined from DRAFT")
    # result required
    result = body.get("result")
    if result is None:
        result = ir["result"]
    if result is None:
        raise err("ERR_INVALID_REQUEST", "result is required to finalize")
    if result not in INSPECTION_RESULTS:
        raise err("ERR_INVALID_REQUEST", "result must be one of PASS, CONDITIONAL, FAIL")
    # linked work order must be COMPLETED + INSPECTION
    wo = db.work_orders.get(ir["work_order_id"])
    if wo is None or wo["status"] != "COMPLETED" or wo["work_type"] != "INSPECTION":
        raise err("ERR_INVALID_STATE", "Linked work order must be a COMPLETED INSPECTION")
    ir["result"] = result
    ir["status"] = "FINALIZED"
    ir["finalized_at"] = iso_ms(clock.now())
    touch(ir)
    # site compliance + provisional risk
    site = db.sites.get(wo["site_id"])
    if site is not None:
        mapping = {"PASS": "COMPLIANT", "CONDITIONAL": "CONDITIONAL", "FAIL": "NON_COMPLIANT"}
        site["compliance_status"] = mapping[result]
        newest = svc.newest_active_asset_install_year(site["id"])
        current_year = clock.now().year
        site["risk_score"] = calc.site_risk_provisional(
            result, ir["defect_count"], newest, current_year
        )
        touch(site)
    return object_response(ser.inspection_report_out(ir), 200)


# ===========================================================================
# PermitFiling
# ===========================================================================
@app.route("/permit-filings", methods=["POST"])
def create_permit_filing():
    _, role = auth()
    require_roles(role, ["ComplianceOfficer"])
    body = get_body()
    require_fields(body, ["inspection_report_id", "site_id"])
    inspection_report_id = require_string(body, "inspection_report_id")
    site_id = require_string(body, "site_id")
    fk_or_422(db.inspection_reports, inspection_report_id)
    site = fk_or_422(db.sites, site_id)
    pf = common_create()
    pf.update({
        "inspection_report_id": inspection_report_id,
        "site_id": site_id,
        "county_code": site["county_code"],
        "status": "DRAFT",
        "submission_count": 0,
        "decision_reason": None,
        "_seq": db.next_seq(),
    })
    db.permit_filings[pf["id"]] = pf
    return object_response(ser.permit_filing_out(pf), 201)


@app.route("/permit-filings/<rid>", methods=["GET"])
def get_permit_filing(rid):
    _, role = auth()
    require_roles(role, ALL_ROLES)
    pf = get_or_404(db.permit_filings, rid)
    return object_response(ser.permit_filing_out(pf), 200)


@app.route("/permit-filings", methods=["GET"])
def list_permit_filings():
    _, role = auth()
    require_roles(role, ALL_ROLES)
    site_id = request.args.get("site_id")
    inspection_report_id = request.args.get("inspection_report_id")
    status = request.args.get("status")
    items = list(db.permit_filings.values())
    if site_id is not None:
        items = [p for p in items if p["site_id"] == site_id]
    if inspection_report_id is not None:
        items = [p for p in items if p["inspection_report_id"] == inspection_report_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    items = sorted_by_created(items)
    page, limit, offset, total = paginate(items)
    return array_response([ser.permit_filing_out(p) for p in page], limit, offset, total)


@app.route("/permit-filings/<rid>/submit", methods=["POST"])
def permit_filing_submit(rid):
    _, role = auth()
    require_roles(role, ["ComplianceOfficer"])
    pf = get_or_404(db.permit_filings, rid)
    # 20 state: submit defined only from DRAFT
    if pf["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "submit is only defined from DRAFT")
    report = db.inspection_reports.get(pf["inspection_report_id"])
    site = db.sites.get(pf["site_id"])
    # 40 referential: report FINALIZED
    if report is None or report["status"] != "FINALIZED":
        raise err("ERR_REPORT_NOT_FINALIZED", "Linked inspection report is not FINALIZED")
    # 41 safety: site not NON_COMPLIANT
    if site is not None and site["compliance_status"] == "NON_COMPLIANT":
        raise err("ERR_SITE_NON_COMPLIANT", "Site is NON_COMPLIANT")
    # 42 temporal: cooling-off elapsed
    from datetime import timedelta
    finalized = parse_iso(report["finalized_at"])
    if clock.now() < finalized + timedelta(hours=calc.COOLING_OFF_HOURS):
        raise err("ERR_COOLING_OFF", "Cooling-off window has not elapsed")
    pf["status"] = "SUBMITTED"
    pf["submission_count"] += 1
    if not pf["county_code"] and site is not None:
        pf["county_code"] = site["county_code"]
    touch(pf)
    return object_response(ser.permit_filing_out(pf), 200)


@app.route("/permit-filings/<rid>/decide", methods=["POST"])
def permit_filing_decide(rid):
    _, role = auth()
    require_roles(role, ["ComplianceOfficer"])
    pf = get_or_404(db.permit_filings, rid)
    body = get_body()
    require_fields(body, ["decision"])
    decision = require_enum(body, "decision", {"APPROVE", "REJECT"})
    decision_reason = body.get("decision_reason")
    if pf["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "decide is only defined from SUBMITTED")
    report = db.inspection_reports.get(pf["inspection_report_id"])
    site = db.sites.get(pf["site_id"])
    newest = svc.newest_active_asset_install_year(site["id"]) if site else None
    current_year = clock.now().year
    result = report["result"] if report else None
    defect_count = report["defect_count"] if report else 0
    if decision == "APPROVE":
        pf["status"] = "APPROVED"
        if decision_reason is not None:
            pf["decision_reason"] = decision_reason
        if site is not None:
            site["compliance_status"] = "COMPLIANT"
            site["risk_score"] = calc.site_risk_final_approve(
                result, defect_count, newest, current_year
            )
            touch(site)
    else:  # REJECT
        pf["status"] = "REJECTED"
        pf["decision_reason"] = decision_reason
        if site is not None:
            site["risk_score"] = calc.site_risk_final_reject(
                result, defect_count, newest, current_year
            )
            touch(site)
    touch(pf)
    return object_response(ser.permit_filing_out(pf), 200)


@app.route("/permit-filings/<rid>/reopen", methods=["POST"])
def permit_filing_reopen(rid):
    _, role = auth()
    require_roles(role, ["ComplianceOfficer"])
    pf = get_or_404(db.permit_filings, rid)
    if pf["status"] != "REJECTED":
        raise err("ERR_INVALID_STATE", "reopen is only defined from REJECTED")
    pf["status"] = "DRAFT"
    touch(pf)
    return object_response(ser.permit_filing_out(pf), 200)


# ===========================================================================
# Reminder
# ===========================================================================
@app.route("/reminders/<rid>", methods=["GET"])
def get_reminder(rid):
    _, role = auth()
    require_roles(role, ALL_ROLES)
    r = get_or_404(db.reminders, rid)
    return object_response(ser.reminder_out(r), 200)


@app.route("/reminders/<rid>/acknowledge", methods=["POST"])
def acknowledge_reminder(rid):
    _, role = auth()
    require_roles(role, ["Dispatcher", "Customer"])
    r = get_or_404(db.reminders, rid)
    if r["status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "acknowledge is only defined from PENDING")
    r["status"] = "ACKNOWLEDGED"
    # Reminder is version-less: mutate status only, no touch().
    return object_response(ser.reminder_out(r), 200)


# ===========================================================================
# Test-driving clock
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = auth()
    require_roles(role, ["Dispatcher", "ComplianceOfficer"])
    body = get_body()
    require_fields(body, ["to_iso8601"])
    to_iso = require_string(body, "to_iso8601")
    try:
        dt = parse_iso(to_iso)
    except Exception:
        raise err("ERR_INVALID_REQUEST", "to_iso8601 must be an ISO 8601 instant")
    clock.set(dt)
    return object_response({}, 200)


def _fast_boot_no_reverse_dns():
    """Neutralize a macOS reverse-DNS (PTR) stall in the Werkzeug dev server.

    Werkzeug calls socket.getfqdn(host) for the unspecified bind address
    "0.0.0.0" to compose its startup/request log lines. On macOS that PTR lookup
    times out after ~5s on a cold cache. Under per-test-server isolation the
    server is relaunched before every test, so that stall is paid on every
    test's first request and blows the per-test timeout. Short-circuit getfqdn
    for the unspecified addresses (the result is only used for a cosmetic log
    line; the server still binds 0.0.0.0 and serves identical responses), and
    silence per-request access logging.
    """
    import socket as _socket

    _real = _socket.getfqdn
    _unspecified = {"", "0.0.0.0", "::", "0:0:0:0:0:0:0:0"}

    def _fast(name=""):
        if name in _unspecified:
            return "localhost"
        return _real(name)

    _socket.getfqdn = _fast
    try:
        from werkzeug.serving import WSGIRequestHandler

        WSGIRequestHandler.address_string = lambda self: self.client_address[0]
        WSGIRequestHandler.log_request = lambda self, *a, **k: None
    except Exception:
        pass
    import logging

    logging.getLogger("werkzeug").setLevel(logging.ERROR)


if __name__ == "__main__":
    _fast_boot_no_reverse_dns()
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
