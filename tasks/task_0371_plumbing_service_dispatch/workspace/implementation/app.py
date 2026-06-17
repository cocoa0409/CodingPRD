"""Plumbing Service Dispatch API — Flask application.

All routes mounted under /plumbing. In-memory store, empty on every boot.
"""
import os
from datetime import datetime, timezone

from flask import Flask, request

import clock
import db
import helpers as H
import pricing
import serializers as S
from errors import (ApiError, err,
                    ERR_UNAUTHORIZED, ERR_NOT_FOUND, ERR_INVALID_REQUEST,
                    ERR_INVALID_STATE, ERR_STALE_JOB_VERSION,
                    ERR_SKILL_INSUFFICIENT, ERR_LICENSE_REQUIRED,
                    ERR_TECH_DOUBLE_BOOKED, ERR_INSPECTOR_CAPACITY_FULL,
                    ERR_EMPTY_ESTIMATE, ERR_INSUFFICIENT_STOCK,
                    ERR_WARRANTY_EXPIRED, ERR_CREDIT_LIMIT_EXCEEDED,
                    ERR_VALIDATION)
from middleware import authenticate, require_role
import response as R

app = Flask(__name__)

# --- enums -----------------------------------------------------------------
PLAN_TIERS = {"NONE", "SILVER", "GOLD"}
FLAT_RATE_CATEGORIES = {"LEAK", "DRAIN", "WATER_HEATER", "REPIPE", "GENERAL"}
JOB_CATEGORIES = {"LEAK", "DRAIN", "WATER_HEATER", "REPIPE"}
JOB_PRIORITIES = {"STANDARD", "EMERGENCY"}
TECH_STATUSES = {"AVAILABLE", "ON_CALL", "OFF_DUTY"}
LINE_TYPES = {"FLAT_RATE", "PART"}
INSPECTION_RESULTS = {"PASSED", "FAILED"}


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------
@app.errorhandler(ApiError)
def _handle_api_error(e):
    return R.error_response(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def _handle_404(e):
    return R.error_response("ERR_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(405)
def _handle_405(e):
    return R.error_response("ERR_NOT_FOUND", "Method not allowed", 404)


@app.errorhandler(Exception)
def _handle_unexpected(e):
    if isinstance(e, ApiError):
        return R.error_response(e.error_id, e.message, e.http_status)
    return R.error_response("ERR_INVALID_REQUEST", "Unexpected error: %s" % e, 400)


# ---------------------------------------------------------------------------
# Parse helpers for datetimes
# ---------------------------------------------------------------------------
def parse_iso_datetime(value, field="timestamp"):
    if not isinstance(value, str):
        raise err(ERR_INVALID_REQUEST, "%s must be an ISO 8601 string" % field)
    v = value.strip()
    try:
        if v.endswith("Z"):
            v = v[:-1] + "+00:00"
        dt = datetime.fromisoformat(v)
    except ValueError:
        raise err(ERR_INVALID_REQUEST, "%s must be a valid ISO 8601 datetime" % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_iso_datetime_opt(body, field):
    if field not in body or body[field] is None:
        return None, None
    raw = body[field]
    dt = parse_iso_datetime(raw, field)
    return dt, clock.iso(dt)


# ===========================================================================
# Configuration: membership plans, flat-rate items, parts
# ===========================================================================
@app.route("/plumbing/membership-plans", methods=["POST"])
def create_membership_plan():
    _, role = authenticate()
    require_role(role, {"OfficeManager"})
    body = H.get_json_body()
    tier_code = H.as_enum(body, "tier_code", PLAN_TIERS)
    name = H.as_str(body, "name")
    pct = H.as_number(body, "labor_discount_pct", minimum=0, maximum=1)
    waives = H.as_bool(body, "waives_trip_fee")
    annual = H.as_int(body, "annual_fee_cents")
    # tier_code unique across plans.
    for p in db.membership_plans.values():
        if p["tier_code"] == tier_code:
            raise err(ERR_INVALID_REQUEST, "tier_code already exists: %s" % tier_code)
    rec = db.base_fields(common=False)
    rec.update({
        "tier_code": tier_code, "name": name, "labor_discount_pct": pct,
        "waives_trip_fee": waives, "annual_fee_cents": annual,
    })
    db.membership_plans[rec["id"]] = rec
    return R.success(S.membership_plan(rec), 201)


@app.route("/plumbing/membership-plans/<rid>", methods=["GET"])
def get_membership_plan(rid):
    _, role = authenticate()
    require_role(role, {"OfficeManager", "Dispatcher", "Technician", "Customer"})
    rec = H.find_or_404(db.membership_plans, rid, "MembershipPlan")
    return R.success(S.membership_plan(rec), 200)


@app.route("/plumbing/flat-rate-items", methods=["POST"])
def create_flat_rate_item():
    _, role = authenticate()
    require_role(role, {"OfficeManager"})
    body = H.get_json_body()
    code = H.as_str(body, "code")
    category = H.as_enum(body, "category", FLAT_RATE_CATEGORIES)
    base_price = H.as_int(body, "base_price_cents", minimum=0)
    skill = H.as_int(body, "skill_required", minimum=1, maximum=5)
    requires_permit = H.as_bool(body, "requires_permit", required=False, default=False)
    for f in db.flat_rate_items.values():
        if f["code"] == code:
            raise err(ERR_INVALID_REQUEST, "code already exists: %s" % code)
    rec = db.base_fields(common=False)
    rec.update({
        "code": code, "category": category, "base_price_cents": base_price,
        "skill_required": skill, "requires_permit": requires_permit,
    })
    db.flat_rate_items[rec["id"]] = rec
    return R.success(S.flat_rate_item(rec), 201)


@app.route("/plumbing/flat-rate-items/<rid>", methods=["GET"])
def get_flat_rate_item(rid):
    _, role = authenticate()
    require_role(role, {"OfficeManager", "Dispatcher", "Technician", "Customer"})
    rec = H.find_or_404(db.flat_rate_items, rid, "FlatRateItem")
    return R.success(S.flat_rate_item(rec), 200)


@app.route("/plumbing/parts", methods=["POST"])
def create_part():
    _, role = authenticate()
    require_role(role, {"OfficeManager"})
    body = H.get_json_body()
    sku = H.as_str(body, "sku")
    name = H.as_str(body, "name")
    list_price = H.as_int(body, "list_price_cents", minimum=0)
    for p in db.parts.values():
        if p["sku"] == sku:
            raise err(ERR_INVALID_REQUEST, "sku already exists: %s" % sku)
    rec = db.base_fields(common=False)
    rec.update({"sku": sku, "name": name, "list_price_cents": list_price})
    db.parts[rec["id"]] = rec
    return R.success(S.part(rec), 201)


@app.route("/plumbing/parts/<rid>", methods=["GET"])
def get_part(rid):
    _, role = authenticate()
    require_role(role, {"OfficeManager", "Dispatcher", "Technician", "Customer"})
    rec = H.find_or_404(db.parts, rid, "Part")
    return R.success(S.part(rec), 200)


# ===========================================================================
# Customers
# ===========================================================================
@app.route("/plumbing/customers", methods=["POST"])
def create_customer():
    _, role = authenticate()
    require_role(role, {"OfficeManager", "Dispatcher"})
    body = H.get_json_body()
    name = H.as_str(body, "name")
    address = H.as_str(body, "service_address")
    plan_id = H.as_str(body, "membership_plan_id", required=False, default=None)
    credit_limit = H.as_int(body, "credit_limit_cents", required=False, default=100000,
                            minimum=0)
    if plan_id is not None:
        H.find_or_404(db.membership_plans, plan_id, "MembershipPlan")
    rec = db.base_fields(common=True)
    rec.update({
        "name": name, "service_address": address, "membership_plan_id": plan_id,
        "credit_limit_cents": credit_limit, "committed_credit_cents": 0,
    })
    db.customers[rec["id"]] = rec
    return R.success(S.generic(rec), 201)


@app.route("/plumbing/customers/<rid>", methods=["GET"])
def get_customer(rid):
    _, role = authenticate()
    require_role(role, {"OfficeManager", "Dispatcher", "Technician", "Customer"})
    rec = H.find_or_404(db.customers, rid, "Customer")
    return R.success(S.generic(rec), 200)


@app.route("/plumbing/customers", methods=["GET"])
def list_customers():
    _, role = authenticate()
    require_role(role, {"OfficeManager", "Dispatcher"})
    limit, offset = H.parse_pagination()
    plan_id = request.args.get("membership_plan_id")
    recs = list(db.customers.values())
    if plan_id is not None:
        recs = [c for c in recs if c.get("membership_plan_id") == plan_id]
    recs = H.sort_by_created(recs)
    page, total = H.paginate(recs, limit, offset)
    return R.list_success([S.generic(c) for c in page], limit, offset, total)


@app.route("/plumbing/customers/<rid>", methods=["PATCH"])
def patch_customer(rid):
    _, role = authenticate()
    require_role(role, {"OfficeManager"})
    rec = H.find_or_404(db.customers, rid, "Customer")
    body = H.get_json_body()
    new_limit = H.as_int(body, "credit_limit_cents", required=False, default=None,
                         minimum=0)
    if "membership_plan_id" in body:
        plan_id = body["membership_plan_id"]
        if plan_id is not None:
            if not isinstance(plan_id, str):
                raise err(ERR_INVALID_REQUEST, "membership_plan_id must be a string")
            H.find_or_404(db.membership_plans, plan_id, "MembershipPlan")
        rec["membership_plan_id"] = plan_id
    if new_limit is not None:
        rec["credit_limit_cents"] = new_limit
    db.touch(rec)
    return R.success(S.generic(rec), 200)


# ===========================================================================
# Technicians
# ===========================================================================
@app.route("/plumbing/technicians", methods=["POST"])
def create_technician():
    _, role = authenticate()
    require_role(role, {"OfficeManager"})
    body = H.get_json_body()
    name = H.as_str(body, "name")
    skill = H.as_int(body, "skill_level", minimum=1, maximum=5)
    licensed = H.as_bool(body, "licensed_for_permits", required=False, default=False)
    rec = db.base_fields(common=True)
    rec.update({
        "name": name, "skill_level": skill, "licensed_for_permits": licensed,
        "status": "AVAILABLE", "lifetime_completed_count": 0,
        "lifetime_callback_count": 0, "needs_restock_skus": 0,
    })
    db.technicians[rec["id"]] = rec
    return R.success(S.generic(rec), 201)


@app.route("/plumbing/technicians/<rid>", methods=["GET"])
def get_technician(rid):
    _, role = authenticate()
    require_role(role, {"OfficeManager", "Dispatcher", "Technician", "Customer"})
    rec = H.find_or_404(db.technicians, rid, "Technician")
    return R.success(S.generic(rec), 200)


@app.route("/plumbing/technicians/<rid>/set-status", methods=["POST"])
def set_technician_status(rid):
    _, role = authenticate()
    require_role(role, {"OfficeManager", "Dispatcher"})
    rec = H.find_or_404(db.technicians, rid, "Technician")
    body = H.get_json_body()
    status = H.as_enum(body, "status", TECH_STATUSES)
    rec["status"] = status
    db.touch(rec)
    return R.success(S.generic(rec), 200)


@app.route("/plumbing/technicians/<rid>/callback-rate", methods=["GET"])
def technician_callback_rate(rid):
    _, role = authenticate()
    require_role(role, {"OfficeManager", "Dispatcher"})
    tech = H.find_or_404(db.technicians, rid, "Technician")

    lifetime_completed = tech["lifetime_completed_count"]
    lifetime_callbacks = tech["lifetime_callback_count"]
    lifetime_rate = pricing.rate_4dp(lifetime_callbacks, lifetime_completed)

    # Rolling: the technician's completed jobs (completed at least once, completed
    # by this technician), ordered by completed_at DESC, tie-break created_at DESC,
    # take most recent ROLLING_WINDOW.
    completed_jobs = [j for j in db.service_jobs.values()
                      if j.get("_completing_technician_id") == rid
                      and j.get("completed_at") is not None]
    completed_jobs.sort(
        key=lambda j: (j["completed_at"], j["created_at"]), reverse=True)
    window = completed_jobs[:pricing.ROLLING_WINDOW]
    rolling_denom = min(pricing.ROLLING_WINDOW, lifetime_completed)
    rolling_num = 0
    for j in window:
        has_cb = any(cb["original_job_id"] == j["id"] for cb in db.callbacks.values())
        if has_cb:
            rolling_num += 1
    rolling_rate = pricing.rate_4dp(rolling_num, rolling_denom)

    data = {
        "lifetime_callback_rate": lifetime_rate,
        "rolling_callback_rate": rolling_rate,
        "lifetime_completed_count": lifetime_completed,
        "lifetime_callback_count": lifetime_callbacks,
    }
    return R.success(data, 200)


@app.route("/plumbing/technicians/<rid>/truck-stock", methods=["GET"])
def list_technician_truck_stock(rid):
    _, role = authenticate()
    require_role(role, {"OfficeManager", "Dispatcher", "Technician"})
    H.find_or_404(db.technicians, rid, "Technician")
    limit, offset = H.parse_pagination()
    recs = [t for t in db.truck_stock.values() if t["technician_id"] == rid]
    recs = H.sort_by_created(recs)
    page, total = H.paginate(recs, limit, offset)
    return R.list_success([S.generic(t) for t in page], limit, offset, total)


# ===========================================================================
# Truck stock
# ===========================================================================
def _recompute_truck_stock_flags(tech_id):
    """Recompute needs_restock for each of a technician's truck-stock rows and
    the technician's needs_restock_skus counter. Does not touch versions of the
    rows here (callers manage row versions explicitly)."""
    count = 0
    for ts in db.truck_stock.values():
        if ts["technician_id"] != tech_id:
            continue
        if ts["needs_restock"]:
            count += 1
    tech = db.technicians.get(tech_id)
    if tech is not None:
        tech["needs_restock_skus"] = count


@app.route("/plumbing/truck-stock", methods=["POST"])
def create_truck_stock():
    _, role = authenticate()
    require_role(role, {"OfficeManager"})
    body = H.get_json_body()
    tech_id = H.as_str(body, "technician_id")
    part_id = H.as_str(body, "part_id")
    quantity = H.as_int(body, "quantity", minimum=0)
    reorder_point = H.as_int(body, "reorder_point", required=False, default=2,
                             minimum=0)
    H.find_or_404(db.technicians, tech_id, "Technician")
    H.find_or_404(db.parts, part_id, "Part")

    # Create-or-restock: if a row already exists for this technician+part, set
    # its quantity (and reorder_point) and bump version. Otherwise create.
    existing = None
    for ts in db.truck_stock.values():
        if ts["technician_id"] == tech_id and ts["part_id"] == part_id:
            existing = ts
            break
    if existing is not None:
        existing["quantity"] = quantity
        existing["reorder_point"] = reorder_point
        existing["needs_restock"] = quantity <= reorder_point
        db.touch(existing)
        _recompute_truck_stock_flags(tech_id)
        # needs_restock_skus changed on the technician -> bump its version too.
        db.touch(db.technicians[tech_id])
        return R.success(S.generic(existing), 201)

    rec = db.base_fields(common=True)
    rec.update({
        "technician_id": tech_id, "part_id": part_id, "quantity": quantity,
        "reorder_point": reorder_point, "needs_restock": quantity <= reorder_point,
    })
    db.truck_stock[rec["id"]] = rec
    _recompute_truck_stock_flags(tech_id)
    db.touch(db.technicians[tech_id])
    return R.success(S.generic(rec), 201)


@app.route("/plumbing/truck-stock", methods=["GET"])
def list_truck_stock():
    _, role = authenticate()
    require_role(role, {"OfficeManager", "Dispatcher", "Technician"})
    limit, offset = H.parse_pagination()
    part_id = request.args.get("part_id")
    tech_id = request.args.get("technician_id")
    recs = list(db.truck_stock.values())
    if part_id is not None:
        recs = [t for t in recs if t["part_id"] == part_id]
    if tech_id is not None:
        recs = [t for t in recs if t["technician_id"] == tech_id]
    recs = H.sort_by_created(recs)
    page, total = H.paginate(recs, limit, offset)
    return R.list_success([S.generic(t) for t in page], limit, offset, total)


@app.route("/plumbing/truck-stock/<rid>", methods=["GET"])
def get_truck_stock(rid):
    _, role = authenticate()
    require_role(role, {"OfficeManager", "Dispatcher", "Technician"})
    rec = H.find_or_404(db.truck_stock, rid, "TruckStock")
    return R.success(S.generic(rec), 200)


# ===========================================================================
# Inspectors
# ===========================================================================
@app.route("/plumbing/inspectors", methods=["POST"])
def create_inspector():
    _, role = authenticate()
    require_role(role, {"OfficeManager"})
    body = H.get_json_body()
    name = H.as_str(body, "name")
    jurisdiction = H.as_str(body, "jurisdiction")
    max_daily = H.as_int(body, "max_daily_inspections", required=False, default=4,
                         minimum=1)
    rec = db.base_fields(common=True)
    rec.update({
        "name": name, "jurisdiction": jurisdiction,
        "max_daily_inspections": max_daily,
    })
    db.inspectors[rec["id"]] = rec
    return R.success(S.generic(rec), 201)


@app.route("/plumbing/inspectors/<rid>", methods=["GET"])
def get_inspector(rid):
    _, role = authenticate()
    require_role(role, {"OfficeManager", "Dispatcher"})
    rec = H.find_or_404(db.inspectors, rid, "Inspector")
    return R.success(S.generic(rec), 200)


# ===========================================================================
# Service jobs
# ===========================================================================
@app.route("/plumbing/service-jobs", methods=["POST"])
def create_service_job():
    _, role = authenticate()
    require_role(role, {"Dispatcher", "OfficeManager"})
    body = H.get_json_body()
    customer_id = H.as_str(body, "customer_id")
    category = H.as_enum(body, "category", JOB_CATEGORIES)
    priority = H.as_enum(body, "priority", JOB_PRIORITIES, required=False,
                         default="STANDARD")
    H.find_or_404(db.customers, customer_id, "Customer")
    window_dt, window_iso = parse_iso_datetime_opt(body, "window_start")
    rec = db.base_fields(common=True)
    rec.update({
        "customer_id": customer_id, "category": category, "priority": priority,
        "window_start": window_iso, "after_hours": False, "status": "RECEIVED",
        "authorized_estimate_id": None, "authorized_amount_cents": 0,
        "completed_at": None,
        # internal bookkeeping
        "_completing_technician_id": None,
        "_ever_completed": False,
        "_consumed_parts": None,
    })
    db.service_jobs[rec["id"]] = rec
    return R.success(S.generic(rec), 201)


@app.route("/plumbing/service-jobs/<rid>", methods=["GET"])
def get_service_job(rid):
    _, role = authenticate()
    require_role(role, {"OfficeManager", "Dispatcher", "Technician", "Customer"})
    rec = H.find_or_404(db.service_jobs, rid, "ServiceJob")
    return R.success(S.generic(rec), 200)


@app.route("/plumbing/service-jobs", methods=["GET"])
def list_service_jobs():
    _, role = authenticate()
    require_role(role, {"OfficeManager", "Dispatcher", "Customer"})
    limit, offset = H.parse_pagination()
    customer_id = request.args.get("customer_id")
    authorized_estimate_id = request.args.get("authorized_estimate_id")
    status = request.args.get("status")
    recs = list(db.service_jobs.values())
    if customer_id is not None:
        recs = [j for j in recs if j["customer_id"] == customer_id]
    if authorized_estimate_id is not None:
        recs = [j for j in recs if j.get("authorized_estimate_id") == authorized_estimate_id]
    if status is not None:
        recs = [j for j in recs if j["status"] == status]
    recs = H.sort_by_created(recs)
    page, total = H.paginate(recs, limit, offset)
    return R.list_success([S.generic(j) for j in page], limit, offset, total)


def _job_confirmed_assignment(job_id):
    """Return the assignment for this job that is currently in a non-terminal
    active state (CONFIRMED/EN_ROUTE/ON_SITE)."""
    for a in db.dispatch_assignments.values():
        if a["job_id"] == job_id and a["status"] in ("CONFIRMED", "EN_ROUTE", "ON_SITE"):
            return a
    return None


def _job_owner_technician_id(job):
    """The technician who owns the job for field-flow ownership checks
    (start-work, complete).

    PRD §2.1: the technician who owns the job's confirmed assignment drives the
    field flow. While the job is still working through its first lifecycle the
    active (CONFIRMED/EN_ROUTE/ON_SITE) assignment carries the owner. After a
    completion the assignment is CLOSED (and on a reopen there is no fresh
    active assignment), so the owner is the technician who completed the job
    most recently — recorded on the job at completion time. We also fall back
    to a CLOSED assignment's technician for robustness.
    """
    active = _job_confirmed_assignment(job["id"])
    if active is not None:
        return active["technician_id"]
    if job.get("_completing_technician_id"):
        return job["_completing_technician_id"]
    # Fall back to the most recent CLOSED assignment for the job.
    closed = [a for a in db.dispatch_assignments.values()
              if a["job_id"] == job["id"] and a["status"] == "CLOSED"]
    if closed:
        closed.sort(key=lambda a: (a["created_at"], a["_seq"]))
        return closed[-1]["technician_id"]
    return None


@app.route("/plumbing/service-jobs/<rid>/start-work", methods=["POST"])
def start_work(rid):
    user_id, role = authenticate()
    require_role(role, {"Technician"})
    job = H.find_or_404(db.service_jobs, rid, "ServiceJob")

    # Ownership: only the technician owning the job's assignment may start.
    owner = _job_owner_technician_id(job)
    if owner is None or owner != user_id:
        raise err(ERR_UNAUTHORIZED, "Acting technician does not own this job")

    if job["status"] not in ("AUTHORIZED", "REOPENED"):
        raise err(ERR_INVALID_STATE, "Job not in AUTHORIZED/REOPENED state")

    est_id = job.get("authorized_estimate_id")
    estimate = db.estimates.get(est_id) if est_id else None

    if job["status"] == "AUTHORIZED":
        if estimate is None or estimate["status"] != "APPROVED":
            raise err(ERR_INVALID_STATE, "Authorized estimate must be APPROVED")
        job["status"] = "IN_PROGRESS"
        db.touch(job)
    else:  # REOPENED
        if estimate is None or estimate["status"] not in ("APPROVED", "CONSUMED"):
            raise err(ERR_INVALID_STATE,
                      "Authorized estimate must be APPROVED or CONSUMED")
        # Re-arm the estimate to APPROVED for a fresh completion.
        estimate["status"] = "APPROVED"
        db.touch(estimate)
        job["status"] = "IN_PROGRESS"
        db.touch(job)
    return R.success(S.generic(job), 200)


@app.route("/plumbing/service-jobs/<rid>/complete", methods=["POST"])
def complete_job(rid):
    user_id, role = authenticate()
    require_role(role, {"Technician"})
    job = H.find_or_404(db.service_jobs, rid, "ServiceJob")

    # Ownership.
    owner = _job_owner_technician_id(job)
    if owner is None or owner != user_id:
        raise err(ERR_UNAUTHORIZED, "Acting technician does not own this job")
    # The currently active assignment (if any) is closed on completion.
    assignment = _job_confirmed_assignment(rid)

    body = H.get_json_body()
    # Validate consumed_parts structure (ERR_INVALID_REQUEST priority 4).
    if "consumed_parts" not in body or body["consumed_parts"] is None:
        raise err(ERR_INVALID_REQUEST, "Missing required field: consumed_parts")
    raw = body["consumed_parts"]
    if not isinstance(raw, list):
        raise err(ERR_INVALID_REQUEST, "consumed_parts must be a list")
    consumed = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise err(ERR_INVALID_REQUEST, "consumed_parts entries must be objects")
        pid = entry.get("part_id")
        units = entry.get("units")
        if not isinstance(pid, str):
            raise err(ERR_INVALID_REQUEST, "consumed_parts.part_id must be a string")
        if isinstance(units, bool) or not isinstance(units, int):
            raise err(ERR_INVALID_REQUEST, "consumed_parts.units must be an integer")
        if units < 1:
            raise err(ERR_INVALID_REQUEST, "consumed_parts.units must be >= 1")
        consumed.append({"part_id": pid, "units": units})

    # Existence of referenced parts (priority 3, body FK).
    for cp in consumed:
        H.find_or_404(db.parts, cp["part_id"], "Part")

    # State (priority 5).
    if job["status"] != "IN_PROGRESS":
        raise err(ERR_INVALID_STATE, "Job not IN_PROGRESS")

    # Permit gate (cross-entity state): if a permit exists, it must be PASSED.
    job_permits = [p for p in db.permits.values() if p["job_id"] == rid]
    if job_permits:
        if not all(p["status"] == "PASSED" for p in job_permits):
            raise err(ERR_INVALID_STATE, "Job permit must be PASSED before completion")

    # Aggregate consumed units per part, then check stock sufficiency.
    agg = {}
    for cp in consumed:
        agg[cp["part_id"]] = agg.get(cp["part_id"], 0) + cp["units"]

    # Map: technician's truck-stock row per part.
    def tech_stock_for(pid):
        for ts in db.truck_stock.values():
            if ts["technician_id"] == user_id and ts["part_id"] == pid:
                return ts
        return None

    for pid, units in agg.items():
        ts = tech_stock_for(pid)
        if ts is None or ts["quantity"] < units:
            raise err(ERR_INSUFFICIENT_STOCK,
                      "Insufficient truck stock for part %s" % pid)

    # --- all checks passed: perform side effects ---
    customer = db.customers[job["customer_id"]]

    # Decrement truck stock and recompute restock flags.
    affected_rows = []
    for pid, units in agg.items():
        ts = tech_stock_for(pid)
        ts["quantity"] -= units
        ts["needs_restock"] = ts["quantity"] <= ts["reorder_point"]
        db.touch(ts)
        affected_rows.append(ts)
    if affected_rows:
        _recompute_truck_stock_flags(user_id)
        db.touch(db.technicians[user_id])

    # Estimate -> CONSUMED.
    est_id = job.get("authorized_estimate_id")
    estimate = db.estimates.get(est_id) if est_id else None
    if estimate is not None:
        estimate["status"] = "CONSUMED"
        db.touch(estimate)

    # lifetime_completed_count: only on the first time this job reaches COMPLETED.
    tech = db.technicians[user_id]
    if not job.get("_ever_completed"):
        tech["lifetime_completed_count"] += 1
        db.touch(tech)
    job["_ever_completed"] = True
    job["_completing_technician_id"] = user_id

    # Record consumed parts on the job (for invoice void / restore on reopen).
    job["_consumed_parts"] = [dict(cp) for cp in
                              [{"part_id": p, "units": u} for p, u in agg.items()]]

    # completed_at + status.
    job["completed_at"] = clock.now_iso()
    job["status"] = "COMPLETED"

    # Create invoice with final totals.
    labor, parts_total, total = pricing.compute_invoice_totals(
        job, customer, job["_consumed_parts"])
    inv = db.base_fields(common=True)
    inv.update({
        "job_id": rid, "status": "FINALIZED",
        "final_labor_cents": labor, "final_parts_cents": parts_total,
        "final_total_cents": total,
    })
    db.invoices[inv["id"]] = inv

    # Close the active assignment ON_SITE -> CLOSED.
    if assignment is not None and assignment["status"] == "ON_SITE":
        assignment["status"] = "CLOSED"
        db.touch(assignment)

    # If this completion resolves an accepted callback (reopen cycle), mark it.
    for cb in db.callbacks.values():
        if cb["original_job_id"] == rid and cb["status"] == "ACCEPTED":
            cb["status"] = "RESOLVED"
            db.touch(cb)

    db.touch(job)
    return R.success(S.generic(job), 200)


@app.route("/plumbing/service-jobs/<rid>/cancel", methods=["POST"])
def cancel_job(rid):
    _, role = authenticate()
    require_role(role, {"Dispatcher", "OfficeManager"})
    job = H.find_or_404(db.service_jobs, rid, "ServiceJob")
    if job["status"] not in ("RECEIVED", "DISPATCHED", "EN_ROUTE", "ON_SITE",
                             "AUTHORIZED"):
        raise err(ERR_INVALID_STATE, "Job cannot be cancelled in its current state")

    # Credit release.
    if job["authorized_amount_cents"] > 0:
        customer = db.customers[job["customer_id"]]
        customer["committed_credit_cents"] -= job["authorized_amount_cents"]
        if customer["committed_credit_cents"] < 0:
            customer["committed_credit_cents"] = 0
        db.touch(customer)
        job["authorized_amount_cents"] = 0

    # Cancel non-terminal dispatch assignments.
    for a in db.dispatch_assignments.values():
        if a["job_id"] == rid and a["status"] not in ("CLOSED", "CANCELLED"):
            a["status"] = "CANCELLED"
            db.touch(a)

    # Decline PRESENTED/APPROVED estimates.
    for e in db.estimates.values():
        if e["job_id"] == rid and e["status"] in ("PRESENTED", "APPROVED"):
            e["status"] = "DECLINED"
            db.touch(e)

    # Void applied permits.
    for p in db.permits.values():
        if p["job_id"] == rid and p["status"] == "APPLIED":
            p["status"] = "VOIDED"
            db.touch(p)

    job["status"] = "CANCELLED"
    db.touch(job)
    return R.success(S.generic(job), 200)


# ===========================================================================
# Dispatch assignments
# ===========================================================================
@app.route("/plumbing/dispatch-assignments", methods=["POST"])
def create_dispatch_assignment():
    _, role = authenticate()
    require_role(role, {"Dispatcher"})
    body = H.get_json_body()
    job_id = H.as_str(body, "job_id")
    tech_id = H.as_str(body, "technician_id")
    # required field presence first (priority 4 handled per-field below as needed),
    # but existence (priority 3) precedes invalid_request per PRD §2.6? Actually
    # §2.6 orders existence (3) before invalid_request (4). However path/body FK
    # existence applies to resources; the window fields are well-formedness. We
    # resolve FKs first.
    H.find_or_404(db.service_jobs, job_id, "ServiceJob")
    H.find_or_404(db.technicians, tech_id, "Technician")

    # Well-formedness of window fields (priority 4).
    H.require_fields(body, ["window_start", "window_end", "eta", "expected_job_version"])
    expected_version = H.as_int(body, "expected_job_version")
    ws_dt = parse_iso_datetime(body["window_start"], "window_start")
    we_dt = parse_iso_datetime(body["window_end"], "window_end")
    eta_dt = parse_iso_datetime(body["eta"], "eta")

    # window_end strictly after window_start -> ERR_VALIDATION (422).
    if we_dt <= ws_dt:
        raise err(ERR_VALIDATION, "window_end must be strictly after window_start")

    job = db.service_jobs[job_id]
    # OCC (priority 6).
    if expected_version != job["version"]:
        raise err(ERR_STALE_JOB_VERSION, "Stale job version")

    rec = db.base_fields(common=True)
    rec.update({
        "job_id": job_id, "technician_id": tech_id,
        "window_start": clock.iso(ws_dt), "window_end": clock.iso(we_dt),
        "eta": clock.iso(eta_dt), "status": "PROPOSED",
        "_window_start_dt": ws_dt, "_window_end_dt": we_dt,
    })
    db.dispatch_assignments[rec["id"]] = rec
    # creating a dispatch assignment bumps the parent job's version.
    db.touch(job)
    return R.success(S.generic(rec), 201)


@app.route("/plumbing/dispatch-assignments/<rid>", methods=["GET"])
def get_dispatch_assignment(rid):
    _, role = authenticate()
    require_role(role, {"OfficeManager", "Dispatcher", "Technician"})
    rec = H.find_or_404(db.dispatch_assignments, rid, "DispatchAssignment")
    return R.success(S.generic(rec), 200)


@app.route("/plumbing/dispatch-assignments", methods=["GET"])
def list_dispatch_assignments():
    _, role = authenticate()
    require_role(role, {"OfficeManager", "Dispatcher", "Technician"})
    limit, offset = H.parse_pagination()
    job_id = request.args.get("job_id")
    tech_id = request.args.get("technician_id")
    status = request.args.get("status")
    recs = list(db.dispatch_assignments.values())
    if job_id is not None:
        recs = [a for a in recs if a["job_id"] == job_id]
    if tech_id is not None:
        recs = [a for a in recs if a["technician_id"] == tech_id]
    if status is not None:
        recs = [a for a in recs if a["status"] == status]
    recs = H.sort_by_created(recs)
    page, total = H.paginate(recs, limit, offset)
    return R.list_success([S.generic(a) for a in page], limit, offset, total)


def _job_intended_max_skill(job_id):
    """Max FlatRateItem.skill_required across the job's intended flat-rate work.

    The job's intended flat-rate work is the set of FLAT_RATE estimate lines on
    the job's estimates (any non-terminal estimate). We take the maximum across
    all FLAT_RATE lines of every estimate belonging to the job.
    """
    max_skill = 0
    est_ids = {e["id"] for e in db.estimates.values() if e["job_id"] == job_id}
    for line in db.estimate_lines.values():
        if line["estimate_id"] in est_ids and line["line_type"] == "FLAT_RATE":
            item = db.flat_rate_items.get(line["flat_rate_item_id"])
            if item is not None and item["skill_required"] > max_skill:
                max_skill = item["skill_required"]
    return max_skill


def _job_requires_permit(job_id):
    """True if any FLAT_RATE line of the job's estimates references a flat-rate
    item with requires_permit=true."""
    est_ids = {e["id"] for e in db.estimates.values() if e["job_id"] == job_id}
    for line in db.estimate_lines.values():
        if line["estimate_id"] in est_ids and line["line_type"] == "FLAT_RATE":
            item = db.flat_rate_items.get(line["flat_rate_item_id"])
            if item is not None and item["requires_permit"]:
                return True
    return False


@app.route("/plumbing/dispatch-assignments/<rid>/confirm", methods=["POST"])
def confirm_assignment(rid):
    _, role = authenticate()
    require_role(role, {"Dispatcher"})
    assignment = H.find_or_404(db.dispatch_assignments, rid, "DispatchAssignment")

    # State (priority 5).
    if assignment["status"] != "PROPOSED":
        raise err(ERR_INVALID_STATE, "Assignment not PROPOSED")

    tech = db.technicians[assignment["technician_id"]]
    job = db.service_jobs[assignment["job_id"]]

    # Availability gate (state-level per PRD §3.2: OFF_DUTY cannot be confirmed).
    if tech["status"] not in ("AVAILABLE", "ON_CALL"):
        raise err(ERR_INVALID_STATE, "Technician is not available")

    # Skill gate (priority 7).
    max_skill = _job_intended_max_skill(assignment["job_id"])
    if tech["skill_level"] < max_skill:
        raise err(ERR_SKILL_INSUFFICIENT, "Technician skill insufficient")

    # License gate (priority 8).
    if _job_requires_permit(assignment["job_id"]) and not tech["licensed_for_permits"]:
        raise err(ERR_LICENSE_REQUIRED, "Technician not licensed for permits")

    # Overlap gate (priority 9): expand requested window by TRAVEL_BUFFER on each
    # side; compare half-open [start, end) against other active assignments of
    # this technician (CONFIRMED/EN_ROUTE/ON_SITE).
    from datetime import timedelta
    buffer = timedelta(minutes=pricing.TRAVEL_BUFFER_MINUTES)
    req_start = assignment["_window_start_dt"] - buffer
    req_end = assignment["_window_end_dt"] + buffer
    for other in db.dispatch_assignments.values():
        if other["id"] == rid:
            continue
        if other["technician_id"] != tech["id"]:
            continue
        if other["status"] not in ("CONFIRMED", "EN_ROUTE", "ON_SITE"):
            continue
        o_start = other["_window_start_dt"]
        o_end = other["_window_end_dt"]
        # half-open overlap test
        if req_start < o_end and o_start < req_end:
            raise err(ERR_TECH_DOUBLE_BOOKED, "Technician double-booked")

    # All checks pass.
    assignment["status"] = "CONFIRMED"
    db.touch(assignment)

    if job["status"] == "RECEIVED":
        # Freeze after_hours based on the confirmed window_start.
        ws = assignment["_window_start_dt"]
        is_weekend = ws.weekday() >= 5  # Saturday=5, Sunday=6
        is_after = ws.hour >= pricing.AFTER_HOURS_CUTOFF_HOUR
        job["after_hours"] = bool(is_after or is_weekend)
        job["status"] = "DISPATCHED"
        db.touch(job)
    return R.success(S.generic(assignment), 200)


@app.route("/plumbing/dispatch-assignments/<rid>/depart", methods=["POST"])
def depart_assignment(rid):
    user_id, role = authenticate()
    require_role(role, {"Technician"})
    assignment = H.find_or_404(db.dispatch_assignments, rid, "DispatchAssignment")
    if assignment["technician_id"] != user_id:
        raise err(ERR_UNAUTHORIZED, "Technician does not own this assignment")
    if assignment["status"] != "CONFIRMED":
        raise err(ERR_INVALID_STATE, "Assignment not CONFIRMED")
    job = db.service_jobs[assignment["job_id"]]
    if job["status"] != "DISPATCHED":
        raise err(ERR_INVALID_STATE, "Job not DISPATCHED")
    assignment["status"] = "EN_ROUTE"
    db.touch(assignment)
    job["status"] = "EN_ROUTE"
    db.touch(job)
    return R.success(S.generic(assignment), 200)


@app.route("/plumbing/dispatch-assignments/<rid>/arrive", methods=["POST"])
def arrive_assignment(rid):
    user_id, role = authenticate()
    require_role(role, {"Technician"})
    assignment = H.find_or_404(db.dispatch_assignments, rid, "DispatchAssignment")
    if assignment["technician_id"] != user_id:
        raise err(ERR_UNAUTHORIZED, "Technician does not own this assignment")
    if assignment["status"] != "EN_ROUTE":
        raise err(ERR_INVALID_STATE, "Assignment not EN_ROUTE")
    job = db.service_jobs[assignment["job_id"]]
    if job["status"] != "EN_ROUTE":
        raise err(ERR_INVALID_STATE, "Job not EN_ROUTE")
    assignment["status"] = "ON_SITE"
    db.touch(assignment)
    job["status"] = "ON_SITE"
    db.touch(job)
    return R.success(S.generic(assignment), 200)


@app.route("/plumbing/dispatch-assignments/<rid>/cancel", methods=["POST"])
def cancel_assignment(rid):
    _, role = authenticate()
    require_role(role, {"Dispatcher"})
    assignment = H.find_or_404(db.dispatch_assignments, rid, "DispatchAssignment")
    if assignment["status"] not in ("PROPOSED", "CONFIRMED", "EN_ROUTE", "ON_SITE"):
        raise err(ERR_INVALID_STATE, "Assignment cannot be cancelled")
    assignment["status"] = "CANCELLED"
    db.touch(assignment)
    return R.success(S.generic(assignment), 200)


# ===========================================================================
# Estimates
# ===========================================================================
@app.route("/plumbing/service-jobs/<rid>/estimates", methods=["POST"])
def create_estimate(rid):
    _, role = authenticate()
    require_role(role, {"Technician"})
    job = H.find_or_404(db.service_jobs, rid, "ServiceJob")
    body = H.get_json_body()
    H.require_fields(body, ["expected_job_version"])
    expected_version = H.as_int(body, "expected_job_version")
    # OCC (priority 6).
    if expected_version != job["version"]:
        raise err(ERR_STALE_JOB_VERSION, "Stale job version")
    rec = db.base_fields(common=True)
    rec.update({
        "job_id": rid, "status": "DRAFT",
        "labor_subtotal_cents": 0, "parts_subtotal_cents": 0, "discount_cents": 0,
        "trip_fee_cents": 0, "emergency_surcharge_cents": 0, "estimate_total_cents": 0,
    })
    db.estimates[rec["id"]] = rec
    db.touch(job)  # creating an estimate bumps the job's version.
    return R.success(S.generic(rec), 201)


@app.route("/plumbing/service-jobs/<rid>/estimates", methods=["GET"])
def list_job_estimates(rid):
    _, role = authenticate()
    require_role(role, {"OfficeManager", "Dispatcher", "Technician", "Customer"})
    H.find_or_404(db.service_jobs, rid, "ServiceJob")
    limit, offset = H.parse_pagination()
    recs = [e for e in db.estimates.values() if e["job_id"] == rid]
    recs = H.sort_by_created(recs)
    page, total = H.paginate(recs, limit, offset)
    return R.list_success([S.generic(e) for e in page], limit, offset, total)


@app.route("/plumbing/estimates/<rid>", methods=["GET"])
def get_estimate(rid):
    _, role = authenticate()
    require_role(role, {"OfficeManager", "Dispatcher", "Technician", "Customer"})
    rec = H.find_or_404(db.estimates, rid, "Estimate")
    return R.success(S.generic(rec), 200)


@app.route("/plumbing/estimates/<rid>/lines", methods=["POST"])
def add_estimate_line(rid):
    _, role = authenticate()
    require_role(role, {"Technician"})
    estimate = H.find_or_404(db.estimates, rid, "Estimate")
    body = H.get_json_body()
    line_type = H.as_enum(body, "line_type", LINE_TYPES)
    quantity = H.as_int(body, "quantity", minimum=1)
    flat_rate_item_id = body.get("flat_rate_item_id")
    part_id = body.get("part_id")

    # Type/ref agreement (ERR_INVALID_REQUEST).
    if line_type == "FLAT_RATE":
        if not isinstance(flat_rate_item_id, str) or part_id is not None:
            raise err(ERR_INVALID_REQUEST,
                      "FLAT_RATE line requires flat_rate_item_id and null part_id")
        H.find_or_404(db.flat_rate_items, flat_rate_item_id, "FlatRateItem")
        part_id = None
    else:  # PART
        if not isinstance(part_id, str) or flat_rate_item_id is not None:
            raise err(ERR_INVALID_REQUEST,
                      "PART line requires part_id and null flat_rate_item_id")
        H.find_or_404(db.parts, part_id, "Part")
        flat_rate_item_id = None

    # State: lines may be added only while estimate is DRAFT or REVISED.
    if estimate["status"] not in ("DRAFT", "REVISED"):
        raise err(ERR_INVALID_STATE, "Estimate not in DRAFT/REVISED state")

    rec = db.base_fields(common=True)
    rec.update({
        "estimate_id": rid, "line_type": line_type,
        "flat_rate_item_id": flat_rate_item_id, "part_id": part_id,
        "quantity": quantity, "unit_price_cents": 0, "line_total_cents": 0,
    })
    db.estimate_lines[rec["id"]] = rec
    return R.success(S.generic(rec), 201)


@app.route("/plumbing/estimates/<rid>/lines", methods=["GET"])
def list_estimate_lines(rid):
    _, role = authenticate()
    require_role(role, {"OfficeManager", "Dispatcher", "Technician", "Customer"})
    H.find_or_404(db.estimates, rid, "Estimate")
    limit, offset = H.parse_pagination()
    recs = [l for l in db.estimate_lines.values() if l["estimate_id"] == rid]
    recs = H.sort_by_created(recs)
    page, total = H.paginate(recs, limit, offset)
    return R.list_success([S.generic(l) for l in page], limit, offset, total)


@app.route("/plumbing/estimate-lines/<rid>", methods=["GET"])
def get_estimate_line(rid):
    _, role = authenticate()
    require_role(role, {"OfficeManager", "Dispatcher", "Technician", "Customer"})
    rec = H.find_or_404(db.estimate_lines, rid, "EstimateLine")
    return R.success(S.generic(rec), 200)


@app.route("/plumbing/estimate-lines", methods=["GET"])
def list_estimate_lines_filtered():
    _, role = authenticate()
    require_role(role, {"OfficeManager", "Dispatcher", "Technician"})
    limit, offset = H.parse_pagination()
    estimate_id = request.args.get("estimate_id")
    flat_rate_item_id = request.args.get("flat_rate_item_id")
    part_id = request.args.get("part_id")
    recs = list(db.estimate_lines.values())
    if estimate_id is not None:
        recs = [l for l in recs if l["estimate_id"] == estimate_id]
    if flat_rate_item_id is not None:
        recs = [l for l in recs if l.get("flat_rate_item_id") == flat_rate_item_id]
    if part_id is not None:
        recs = [l for l in recs if l.get("part_id") == part_id]
    recs = H.sort_by_created(recs)
    page, total = H.paginate(recs, limit, offset)
    return R.list_success([S.generic(l) for l in page], limit, offset, total)


@app.route("/plumbing/estimates/<rid>/present", methods=["POST"])
def present_estimate(rid):
    _, role = authenticate()
    require_role(role, {"Technician"})
    estimate = H.find_or_404(db.estimates, rid, "Estimate")
    job = db.service_jobs[estimate["job_id"]]
    # State: estimate DRAFT or REVISED, job ON_SITE.
    if estimate["status"] not in ("DRAFT", "REVISED"):
        raise err(ERR_INVALID_STATE, "Estimate not in DRAFT/REVISED state")
    if job["status"] != "ON_SITE":
        raise err(ERR_INVALID_STATE, "Job not ON_SITE")
    # Non-empty (priority 11).
    lines = [l for l in db.estimate_lines.values() if l["estimate_id"] == rid]
    if not lines:
        raise err(ERR_EMPTY_ESTIMATE, "Estimate has no lines")
    customer = db.customers[job["customer_id"]]
    pricing.price_estimate(estimate, job, customer)
    estimate["status"] = "PRESENTED"
    db.touch(estimate)
    return R.success(S.generic(estimate), 200)


@app.route("/plumbing/estimates/<rid>/revise", methods=["POST"])
def revise_estimate(rid):
    _, role = authenticate()
    require_role(role, {"Technician"})
    estimate = H.find_or_404(db.estimates, rid, "Estimate")
    if estimate["status"] != "PRESENTED":
        raise err(ERR_INVALID_STATE, "Estimate not PRESENTED")
    estimate["status"] = "REVISED"
    db.touch(estimate)
    return R.success(S.generic(estimate), 200)


@app.route("/plumbing/estimates/<rid>/approve", methods=["POST"])
def approve_estimate(rid):
    user_id, role = authenticate()
    require_role(role, {"Customer"})
    estimate = H.find_or_404(db.estimates, rid, "Estimate")
    job = db.service_jobs[estimate["job_id"]]
    # Ownership: acting customer must own the job.
    if job["customer_id"] != user_id:
        raise err(ERR_UNAUTHORIZED, "Customer does not own this job")
    # State: estimate PRESENTED, job ON_SITE.
    if estimate["status"] != "PRESENTED":
        raise err(ERR_INVALID_STATE, "Estimate not PRESENTED")
    if job["status"] != "ON_SITE":
        raise err(ERR_INVALID_STATE, "Job not ON_SITE")
    customer = db.customers[job["customer_id"]]
    # Fiscal (priority 14).
    available = customer["credit_limit_cents"] - customer["committed_credit_cents"]
    if available < estimate["estimate_total_cents"]:
        raise err(ERR_CREDIT_LIMIT_EXCEEDED, "Insufficient available credit")

    # Side effects.
    estimate["status"] = "APPROVED"
    db.touch(estimate)
    job["authorized_estimate_id"] = estimate["id"]
    job["authorized_amount_cents"] = estimate["estimate_total_cents"]
    job["status"] = "AUTHORIZED"
    db.touch(job)
    customer["committed_credit_cents"] += estimate["estimate_total_cents"]
    db.touch(customer)

    # Permit auto-create cascade if any approved FLAT_RATE line requires permit.
    flat_lines = [l for l in db.estimate_lines.values()
                  if l["estimate_id"] == estimate["id"] and l["line_type"] == "FLAT_RATE"]
    needs_permit = any(
        db.flat_rate_items[l["flat_rate_item_id"]]["requires_permit"]
        for l in flat_lines)
    if needs_permit:
        # Jurisdiction derived from the customer (use service_address as code).
        jurisdiction = customer.get("service_address")
        permit = db.base_fields(common=True)
        permit.update({
            "job_id": job["id"], "jurisdiction": jurisdiction,
            "status": "APPLIED", "reapply_count": 0,
        })
        db.permits[permit["id"]] = permit

    return R.success(S.generic(estimate), 200)


@app.route("/plumbing/estimates/<rid>/decline", methods=["POST"])
def decline_estimate(rid):
    user_id, role = authenticate()
    require_role(role, {"Customer"})
    estimate = H.find_or_404(db.estimates, rid, "Estimate")
    job = db.service_jobs[estimate["job_id"]]
    if job["customer_id"] != user_id:
        raise err(ERR_UNAUTHORIZED, "Customer does not own this job")
    if estimate["status"] not in ("PRESENTED", "REVISED"):
        raise err(ERR_INVALID_STATE, "Estimate not in PRESENTED/REVISED state")
    estimate["status"] = "DECLINED"
    db.touch(estimate)
    return R.success(S.generic(estimate), 200)


# ===========================================================================
# Permits & inspections
# ===========================================================================
@app.route("/plumbing/service-jobs/<rid>/permits", methods=["GET"])
def list_job_permits(rid):
    _, role = authenticate()
    require_role(role, {"OfficeManager", "Dispatcher", "Technician"})
    H.find_or_404(db.service_jobs, rid, "ServiceJob")
    limit, offset = H.parse_pagination()
    recs = [p for p in db.permits.values() if p["job_id"] == rid]
    recs = H.sort_by_created(recs)
    page, total = H.paginate(recs, limit, offset)
    return R.list_success([S.generic(p) for p in page], limit, offset, total)


@app.route("/plumbing/permits/<rid>", methods=["GET"])
def get_permit(rid):
    _, role = authenticate()
    require_role(role, {"OfficeManager", "Dispatcher", "Technician"})
    rec = H.find_or_404(db.permits, rid, "Permit")
    return R.success(S.generic(rec), 200)


@app.route("/plumbing/permits/<rid>/issue", methods=["POST"])
def issue_permit(rid):
    _, role = authenticate()
    require_role(role, {"OfficeManager"})
    permit = H.find_or_404(db.permits, rid, "Permit")
    if permit["status"] == "APPLIED":
        permit["status"] = "ISSUED"
        db.touch(permit)
    elif permit["status"] == "FAILED":
        permit["status"] = "ISSUED"
        permit["reapply_count"] += 1
        db.touch(permit)
    else:
        raise err(ERR_INVALID_STATE, "Permit not in APPLIED/FAILED state")
    return R.success(S.generic(permit), 200)


@app.route("/plumbing/permits/<rid>/inspections", methods=["POST"])
def schedule_inspection(rid):
    _, role = authenticate()
    require_role(role, {"OfficeManager"})
    permit = H.find_or_404(db.permits, rid, "Permit")
    body = H.get_json_body()
    inspector_id = H.as_str(body, "inspector_id")
    scheduled_date = H.as_str(body, "scheduled_date")
    inspector = H.find_or_404(db.inspectors, inspector_id, "Inspector")
    # State (priority 5).
    if permit["status"] != "ISSUED":
        raise err(ERR_INVALID_STATE, "Permit not ISSUED")
    # Jurisdiction match (priority 8).
    if inspector["jurisdiction"] != permit["jurisdiction"]:
        raise err(ERR_LICENSE_REQUIRED, "Inspector jurisdiction mismatch")
    # Capacity (priority 10): inspector must hold < max_daily PENDING visits on date.
    pending_on_date = sum(
        1 for v in db.inspection_visits.values()
        if v["inspector_id"] == inspector_id
        and v["scheduled_date"] == scheduled_date
        and v["result"] == "PENDING")
    if pending_on_date >= inspector["max_daily_inspections"]:
        raise err(ERR_INSPECTOR_CAPACITY_FULL, "Inspector daily capacity full")

    visit = db.base_fields(common=True)
    visit.update({
        "permit_id": rid, "inspector_id": inspector_id,
        "scheduled_date": scheduled_date, "result": "PENDING",
    })
    db.inspection_visits[visit["id"]] = visit
    permit["status"] = "INSPECTION_SCHEDULED"
    db.touch(permit)
    return R.success(S.generic(visit), 201)


@app.route("/plumbing/permits/<rid>/inspections", methods=["GET"])
def list_permit_inspections(rid):
    _, role = authenticate()
    require_role(role, {"OfficeManager", "Dispatcher", "Technician"})
    H.find_or_404(db.permits, rid, "Permit")
    limit, offset = H.parse_pagination()
    recs = [v for v in db.inspection_visits.values() if v["permit_id"] == rid]
    recs = H.sort_by_created(recs)
    page, total = H.paginate(recs, limit, offset)
    return R.list_success([S.generic(v) for v in page], limit, offset, total)


@app.route("/plumbing/inspections", methods=["GET"])
def list_inspections():
    _, role = authenticate()
    require_role(role, {"OfficeManager", "Dispatcher"})
    limit, offset = H.parse_pagination()
    inspector_id = request.args.get("inspector_id")
    scheduled_date = request.args.get("scheduled_date")
    result = request.args.get("result")
    recs = list(db.inspection_visits.values())
    if inspector_id is not None:
        recs = [v for v in recs if v["inspector_id"] == inspector_id]
    if scheduled_date is not None:
        recs = [v for v in recs if v["scheduled_date"] == scheduled_date]
    if result is not None:
        recs = [v for v in recs if v["result"] == result]
    recs = H.sort_by_created(recs)
    page, total = H.paginate(recs, limit, offset)
    return R.list_success([S.generic(v) for v in page], limit, offset, total)


@app.route("/plumbing/inspections/<rid>", methods=["GET"])
def get_inspection(rid):
    _, role = authenticate()
    require_role(role, {"OfficeManager", "Dispatcher", "Technician"})
    rec = H.find_or_404(db.inspection_visits, rid, "InspectionVisit")
    return R.success(S.generic(rec), 200)


@app.route("/plumbing/inspections/<rid>/record", methods=["POST"])
def record_inspection(rid):
    _, role = authenticate()
    require_role(role, {"OfficeManager"})
    visit = H.find_or_404(db.inspection_visits, rid, "InspectionVisit")
    body = H.get_json_body()
    result = H.as_enum(body, "result", INSPECTION_RESULTS)
    if visit["result"] != "PENDING":
        raise err(ERR_INVALID_STATE, "Inspection not PENDING")
    permit = db.permits[visit["permit_id"]]
    visit["result"] = result
    db.touch(visit)
    if result == "PASSED":
        permit["status"] = "PASSED"
    else:
        permit["status"] = "FAILED"
    db.touch(permit)
    return R.success(S.generic(visit), 200)


# ===========================================================================
# Invoices
# ===========================================================================
@app.route("/plumbing/service-jobs/<rid>/invoices", methods=["GET"])
def list_job_invoices(rid):
    _, role = authenticate()
    require_role(role, {"OfficeManager", "Dispatcher", "Customer"})
    H.find_or_404(db.service_jobs, rid, "ServiceJob")
    limit, offset = H.parse_pagination()
    recs = [i for i in db.invoices.values() if i["job_id"] == rid]
    recs = H.sort_by_created(recs)
    page, total = H.paginate(recs, limit, offset)
    return R.list_success([S.generic(i) for i in page], limit, offset, total)


@app.route("/plumbing/invoices/<rid>", methods=["GET"])
def get_invoice(rid):
    _, role = authenticate()
    require_role(role, {"OfficeManager", "Dispatcher", "Customer"})
    rec = H.find_or_404(db.invoices, rid, "Invoice")
    return R.success(S.generic(rec), 200)


# ===========================================================================
# Callbacks
# ===========================================================================
@app.route("/plumbing/callbacks", methods=["POST"])
def create_callback():
    user_id, role = authenticate()
    require_role(role, {"Customer"})
    body = H.get_json_body()
    original_job_id = H.as_str(body, "original_job_id")
    reason = H.as_str(body, "reason")
    job = H.find_or_404(db.service_jobs, original_job_id, "ServiceJob")
    # Ownership: customer must own the job.
    if job["customer_id"] != user_id:
        raise err(ERR_UNAUTHORIZED, "Customer does not own this job")
    # A callback may only be filed against a COMPLETED job.
    if job["status"] != "COMPLETED":
        raise err(ERR_WARRANTY_EXPIRED, "Callback only allowed on COMPLETED job")

    # within_warranty: days_elapsed = floor((now - completed_at)/86400); <=90.
    completed_dt = parse_iso_datetime(job["completed_at"], "completed_at")
    now_dt = clock.now()
    elapsed_seconds = (now_dt - completed_dt).total_seconds()
    days_elapsed = int(elapsed_seconds // 86400)
    within = days_elapsed <= pricing.WARRANTY_DAYS

    rec = db.base_fields(common=True)
    rec.update({
        "original_job_id": original_job_id, "reason": reason,
        "status": "OPEN", "within_warranty": bool(within),
    })
    db.callbacks[rec["id"]] = rec

    # Increment the completing technician's lifetime_callback_count by 1.
    tech_id = job.get("_completing_technician_id")
    if tech_id and tech_id in db.technicians:
        db.technicians[tech_id]["lifetime_callback_count"] += 1
        db.touch(db.technicians[tech_id])

    return R.success(S.generic(rec), 201)


@app.route("/plumbing/callbacks/<rid>", methods=["GET"])
def get_callback(rid):
    _, role = authenticate()
    require_role(role, {"OfficeManager", "Dispatcher", "Customer"})
    rec = H.find_or_404(db.callbacks, rid, "Callback")
    return R.success(S.generic(rec), 200)


@app.route("/plumbing/service-jobs/<rid>/callbacks", methods=["GET"])
def list_job_callbacks(rid):
    _, role = authenticate()
    require_role(role, {"OfficeManager", "Dispatcher", "Customer"})
    H.find_or_404(db.service_jobs, rid, "ServiceJob")
    limit, offset = H.parse_pagination()
    recs = [c for c in db.callbacks.values() if c["original_job_id"] == rid]
    recs = H.sort_by_created(recs)
    page, total = H.paginate(recs, limit, offset)
    return R.list_success([S.generic(c) for c in page], limit, offset, total)


@app.route("/plumbing/callbacks/<rid>/accept", methods=["POST"])
def accept_callback(rid):
    _, role = authenticate()
    require_role(role, {"OfficeManager"})
    callback = H.find_or_404(db.callbacks, rid, "Callback")
    job = db.service_jobs[callback["original_job_id"]]
    # State (priority 5): callback OPEN.
    if callback["status"] != "OPEN":
        raise err(ERR_INVALID_STATE, "Callback not OPEN")
    # Original job must be COMPLETED.
    if job["status"] != "COMPLETED":
        raise err(ERR_INVALID_STATE, "Original job not COMPLETED")
    # Warranty (priority 13).
    if not callback["within_warranty"]:
        raise err(ERR_WARRANTY_EXPIRED, "Callback not within warranty")

    # Compensating reversal.
    callback["status"] = "ACCEPTED"
    db.touch(callback)

    # Void the job's invoice(s).
    voided_invoices = []
    for inv in db.invoices.values():
        if inv["job_id"] == job["id"] and inv["status"] == "FINALIZED":
            inv["status"] = "VOIDED"
            db.touch(inv)
            voided_invoices.append(inv)

    # Restore consumed truck stock to the completing technician.
    tech_id = job.get("_completing_technician_id")
    consumed = job.get("_consumed_parts") or []
    restored_any = False
    if tech_id and consumed:
        for cp in consumed:
            for ts in db.truck_stock.values():
                if ts["technician_id"] == tech_id and ts["part_id"] == cp["part_id"]:
                    ts["quantity"] += cp["units"]
                    ts["needs_restock"] = ts["quantity"] <= ts["reorder_point"]
                    db.touch(ts)
                    restored_any = True
                    break
        if restored_any and tech_id in db.technicians:
            _recompute_truck_stock_flags(tech_id)
            db.touch(db.technicians[tech_id])

    # Release committed credit by the job's authorized amount.
    if job["authorized_amount_cents"] > 0:
        customer = db.customers[job["customer_id"]]
        customer["committed_credit_cents"] -= job["authorized_amount_cents"]
        if customer["committed_credit_cents"] < 0:
            customer["committed_credit_cents"] = 0
        db.touch(customer)

    # Job COMPLETED -> REOPENED.
    job["status"] = "REOPENED"
    db.touch(job)
    return R.success(S.generic(callback), 200)


@app.route("/plumbing/callbacks/<rid>/reject", methods=["POST"])
def reject_callback(rid):
    _, role = authenticate()
    require_role(role, {"OfficeManager"})
    callback = H.find_or_404(db.callbacks, rid, "Callback")
    if callback["status"] != "OPEN":
        raise err(ERR_INVALID_STATE, "Callback not OPEN")
    callback["status"] = "REJECTED"
    db.touch(callback)
    return R.success(S.generic(callback), 200)


# ===========================================================================
# Test-driving: clock control
# ===========================================================================
@app.route("/plumbing/_clock/set", methods=["POST"])
def set_clock():
    _, role = authenticate()
    require_role(role, {"OfficeManager"})
    body = H.get_json_body()
    to_iso = H.as_str(body, "to_iso8601")
    dt = parse_iso_datetime(to_iso, "to_iso8601")
    clock.set_now(dt)
    return R.success({}, 200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
