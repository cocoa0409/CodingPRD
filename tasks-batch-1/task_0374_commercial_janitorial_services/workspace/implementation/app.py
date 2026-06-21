"""Commercial Janitorial Services API — Flask entry point.

In-memory only. Boots empty every process; no seeding. State stored in the
`db` Store object (plain Python dicts keyed by id).
"""
import math
import os

from flask import Flask, request

from db import db, new_common, now_iso, touch
from errors import ApiError, err
from helpers import (as_int, as_number, as_str, check_enum, get_body, get_pagination,
                     paginate, require_fields)
from middleware import get_caller, require_role
from response import error_response, list_response, success
import services as svc

app = Flask(__name__)


# ===========================================================================
# Error handling
# ===========================================================================
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


# ===========================================================================
# Lookup helpers (existence)
# ===========================================================================
def find_or_404(collection, rid):
    row = collection.get(rid)
    if row is None:
        raise err("ERR_NOT_FOUND", "Resource not found")
    return row


def fk_or_404(collection, rid):
    row = collection.get(rid)
    if row is None:
        raise err("ERR_FK_NOT_FOUND", "Referenced resource does not exist")
    return row


# Validation helpers for numeric ranges
def check_minutes(value, field):
    as_int(value, field)
    if value < 0 or value > 1440:
        raise err("ERR_INVALID_REQUEST", "%s must be in 0..1440" % field)
    return value


def check_minute_of_day(value, field):
    as_int(value, field)
    if value < 0 or value > 1439:
        raise err("ERR_INVALID_REQUEST", "%s must be in 0..1439" % field)
    return value


# ===========================================================================
# ClientContact ownership check (priority 3)
# ===========================================================================
def ensure_site_contact(user_id, site):
    if site["contact_user_id"] != user_id:
        raise err("ERR_NOT_SITE_CONTACT", "Caller is not the site contact")


# ===========================================================================
# Crew double-booking guard (priority 11, PRD 3.3)
# ===========================================================================
def check_crew_double_booked(crew_id, service_date, start_min, end_min, exclude_visit_id=None):
    for v in db.visits.values():
        if v["id"] == exclude_visit_id:
            continue
        if v["crew_id"] != crew_id:
            continue
        if v["service_date"] != service_date:
            continue
        if v["status"] not in ("SCHEDULED", "IN_PROGRESS"):
            continue
        # half-open overlap: [start, end) vs [v.start, v.end); adjacency allowed.
        if start_min < v["planned_end_min"] and v["planned_start_min"] < end_min:
            raise err("ERR_CREW_DOUBLE_BOOKED", "Crew is double-booked for this interval")


# ===========================================================================
# Schedule window conflict (priority 12, PRD 3.2 — closed interval)
# ===========================================================================
def check_schedule_conflict(crew_id, weekday, start_min, end_min, exclude_schedule_id=None):
    for s in db.schedules.values():
        if s["id"] == exclude_schedule_id:
            continue
        if s["status"] != "ACTIVE":
            continue
        if s["assigned_crew_id"] != crew_id:
            continue
        if s["weekday"] != weekday:
            continue
        # closed-interval: touching boundary IS a conflict.
        if start_min <= s["window_end_min"] and s["window_start_min"] <= end_min:
            raise err("ERR_SCHEDULE_WINDOW_CONFLICT", "Schedule window conflicts")


# ===========================================================================
# Billing period resolution on visit completion / credit posting
# ===========================================================================
def open_billing_period_for(contract, period_month):
    """Find an OPEN billing period for the contract+month, or open one if the
    contract is ACTIVE. Returns the period or None."""
    for p in db.billing_periods.values():
        if (p["contract_id"] == contract["id"] and p["period_month"] == period_month
                and p["status"] == "OPEN"):
            return p
    if contract["status"] != "ACTIVE":
        return None
    # No OPEN period exists; open a new one (only if not duplicate of any state).
    for p in db.billing_periods.values():
        if p["contract_id"] == contract["id"] and p["period_month"] == period_month:
            # A period exists for this month but is not OPEN; do not capture.
            return None
    period = new_common()
    period.update({
        "contract_id": contract["id"],
        "period_month": period_month,
        "base_cents": contract["monthly_base_cents"],
        "periodic_cents": 0,
        "callback_credit_cents": 0,
        "holdback_cents": 0,
        "total_cents": contract["monthly_base_cents"],
        "mean_quality_score": None,
        "status": "OPEN",
    })
    db.billing_periods[period["id"]] = period
    return period


def active_contract_for_site(site_id):
    for c in db.contracts.values():
        if c["site_id"] == site_id and c["status"] == "ACTIVE":
            return c
    return None


def month_of(service_date):
    # service_date is YYYY-MM-DD; month is YYYY-MM
    return service_date[:7]


# ===========================================================================
# ACCOUNTS
# ===========================================================================
@app.route("/accounts", methods=["POST"])
def create_account():
    _, role = get_caller()
    require_role(role, {"AccountManager"})
    body = get_body()
    require_fields(body, ["name", "billing_email"])
    as_str(body["name"], "name")
    as_str(body["billing_email"], "billing_email")
    acct = new_common()
    acct.update({
        "name": body["name"],
        "billing_email": body["billing_email"],
        "status": "ACTIVE",
        "open_complaint_count": 0,
    })
    db.accounts[acct["id"]] = acct
    return success(svc.serialize(acct, "account"), status=201)


@app.route("/accounts/<account_id>", methods=["GET"])
def get_account(account_id):
    _, role = get_caller()
    require_role(role, {"AccountManager", "FieldSupervisor"})
    acct = find_or_404(db.accounts, account_id)
    return success(svc.serialize(acct, "account"))


@app.route("/accounts", methods=["GET"])
def list_accounts():
    _, role = get_caller()
    require_role(role, {"AccountManager"})
    limit, offset = get_pagination()
    rows = list(db.accounts.values())
    status_f = request.args.get("status")
    if status_f is not None:
        rows = [r for r in rows if r["status"] == status_f]
    page, total = paginate(rows, limit, offset)
    return list_response([svc.serialize(r, "account") for r in page], limit, offset, total)


@app.route("/accounts/<account_id>/suspend", methods=["POST"])
def suspend_account(account_id):
    _, role = get_caller()
    require_role(role, {"AccountManager"})
    acct = find_or_404(db.accounts, account_id)
    acct["status"] = "SUSPENDED"
    touch(acct)
    return success(svc.serialize(acct, "account"))


# ===========================================================================
# SITES
# ===========================================================================
@app.route("/sites", methods=["POST"])
def create_site():
    _, role = get_caller()
    require_role(role, {"AccountManager"})
    body = get_body()
    require_fields(body, ["account_id", "contact_user_id", "label", "cleanable_sqft", "floor_type"])
    acct = fk_or_404(db.accounts, body["account_id"])
    as_str(body["contact_user_id"], "contact_user_id")
    as_str(body["label"], "label")
    as_int(body["cleanable_sqft"], "cleanable_sqft")
    if body["cleanable_sqft"] <= 0:
        raise err("ERR_INVALID_REQUEST", "cleanable_sqft must be > 0")
    check_enum(body["floor_type"], "floor_type", {"CARPET", "VCT", "TERRAZZO", "CONCRETE"})
    quality_target = body.get("quality_target", 85)
    if quality_target is None:
        quality_target = 85
    as_int(quality_target, "quality_target")
    if quality_target < 0 or quality_target > 100:
        raise err("ERR_INVALID_REQUEST", "quality_target must be in 0..100")
    # account must be ACTIVE to create a new site beneath it (PRD 3.1)
    if acct["status"] != "ACTIVE":
        raise err("ERR_ACCOUNT_NOT_ACTIVE", "Owning account is not ACTIVE")
    site = new_common()
    site.update({
        "account_id": body["account_id"],
        "contact_user_id": body["contact_user_id"],
        "label": body["label"],
        "cleanable_sqft": body["cleanable_sqft"],
        "floor_type": body["floor_type"],
        "quality_target": quality_target,
        "status": "ACTIVE",
    })
    db.sites[site["id"]] = site
    return success(svc.serialize(site, "site"), status=201)


@app.route("/sites/<site_id>", methods=["GET"])
def get_site(site_id):
    user_id, role = get_caller()
    require_role(role, {"AccountManager", "FieldSupervisor", "ClientContact"})
    site = find_or_404(db.sites, site_id)
    if role == "ClientContact":
        ensure_site_contact(user_id, site)
    return success(svc.serialize(site, "site"))


@app.route("/sites", methods=["GET"])
def list_sites():
    _, role = get_caller()
    require_role(role, {"AccountManager", "FieldSupervisor"})
    limit, offset = get_pagination()
    rows = list(db.sites.values())
    account_f = request.args.get("account_id")
    if account_f is not None:
        rows = [r for r in rows if r["account_id"] == account_f]
    page, total = paginate(rows, limit, offset)
    return list_response([svc.serialize(r, "site") for r in page], limit, offset, total)


@app.route("/sites/<site_id>/archive", methods=["POST"])
def archive_site(site_id):
    _, role = get_caller()
    require_role(role, {"AccountManager"})
    site = find_or_404(db.sites, site_id)
    site["status"] = "ARCHIVED"
    touch(site)
    return success(svc.serialize(site, "site"))


# ===========================================================================
# SERVICE CONTRACTS
# ===========================================================================
@app.route("/contracts", methods=["POST"])
def create_contract():
    _, role = get_caller()
    require_role(role, {"AccountManager"})
    body = get_body()
    require_fields(body, ["site_id", "monthly_base_cents", "hourly_rate_cents"])
    site = fk_or_404(db.sites, body["site_id"])
    as_int(body["monthly_base_cents"], "monthly_base_cents")
    if body["monthly_base_cents"] <= 0:
        raise err("ERR_INVALID_REQUEST", "monthly_base_cents must be > 0")
    as_int(body["hourly_rate_cents"], "hourly_rate_cents")
    if body["hourly_rate_cents"] <= 0:
        raise err("ERR_INVALID_REQUEST", "hourly_rate_cents must be > 0")
    ccp = body.get("callback_credit_pct", 0.10)
    if ccp is None:
        ccp = 0.10
    as_number(ccp, "callback_credit_pct")
    if ccp < 0.0 or ccp > 1.0:
        raise err("ERR_INVALID_REQUEST", "callback_credit_pct must be in 0.0..1.0")
    qhp = body.get("quality_holdback_pct", 0.05)
    if qhp is None:
        qhp = 0.05
    as_number(qhp, "quality_holdback_pct")
    if qhp < 0.0 or qhp > 1.0:
        raise err("ERR_INVALID_REQUEST", "quality_holdback_pct must be in 0.0..1.0")
    contract = new_common()
    contract.update({
        "site_id": body["site_id"],
        "monthly_base_cents": body["monthly_base_cents"],
        "hourly_rate_cents": body["hourly_rate_cents"],
        "callback_credit_pct": ccp,
        "quality_holdback_pct": qhp,
        "status": "DRAFT",
    })
    db.contracts[contract["id"]] = contract
    return success(svc.serialize(contract, "contract"), status=201)


@app.route("/contracts/<contract_id>", methods=["GET"])
def get_contract(contract_id):
    _, role = get_caller()
    require_role(role, {"AccountManager"})
    contract = find_or_404(db.contracts, contract_id)
    return success(svc.serialize(contract, "contract"))


@app.route("/contracts", methods=["GET"])
def list_contracts():
    _, role = get_caller()
    require_role(role, {"AccountManager"})
    limit, offset = get_pagination()
    rows = list(db.contracts.values())
    site_f = request.args.get("site_id")
    if site_f is not None:
        rows = [r for r in rows if r["site_id"] == site_f]
    page, total = paginate(rows, limit, offset)
    return list_response([svc.serialize(r, "contract") for r in page], limit, offset, total)


@app.route("/contracts/<contract_id>/activate", methods=["POST"])
def activate_contract(contract_id):
    _, role = get_caller()
    require_role(role, {"AccountManager"})
    contract = find_or_404(db.contracts, contract_id)
    if contract["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Contract is not DRAFT")
    site = db.sites.get(contract["site_id"])
    if site is not None and site["status"] != "ACTIVE":
        raise err("ERR_SITE_ARCHIVED", "Site is archived")
    acct = svc.account_for_contract(contract)
    if acct is not None and acct["status"] != "ACTIVE":
        raise err("ERR_ACCOUNT_NOT_ACTIVE", "Owning account is not ACTIVE")
    contract["status"] = "ACTIVE"
    touch(contract)
    return success(svc.serialize(contract, "contract"))


@app.route("/contracts/<contract_id>/terminate", methods=["POST"])
def terminate_contract(contract_id):
    _, role = get_caller()
    require_role(role, {"AccountManager"})
    contract = find_or_404(db.contracts, contract_id)
    if contract["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Contract is not ACTIVE")
    for p in db.billing_periods.values():
        if p["contract_id"] == contract["id"] and p["status"] in ("OPEN", "REOPENED"):
            raise err("ERR_PERIOD_OPEN", "Contract has an open billing period")
    contract["status"] = "TERMINATED"
    touch(contract)
    return success(svc.serialize(contract, "contract"))


# ===========================================================================
# CREW
# ===========================================================================
@app.route("/crew", methods=["POST"])
def create_crew():
    _, role = get_caller()
    require_role(role, {"AccountManager", "FieldSupervisor"})
    body = get_body()
    require_fields(body, ["full_name"])
    as_str(body["full_name"], "full_name")
    cap = body.get("shift_capacity_min", 480)
    if cap is None:
        cap = 480
    as_int(cap, "shift_capacity_min")
    if cap <= 0:
        raise err("ERR_INVALID_REQUEST", "shift_capacity_min must be > 0")
    crew = new_common()
    crew.update({
        "full_name": body["full_name"],
        "shift_capacity_min": cap,
        "status": "AVAILABLE",
    })
    db.crew[crew["id"]] = crew
    return success(svc.serialize(crew, "crew"), status=201)


@app.route("/crew/<crew_id>", methods=["GET"])
def get_crew(crew_id):
    _, role = get_caller()
    require_role(role, {"AccountManager", "FieldSupervisor"})
    crew = find_or_404(db.crew, crew_id)
    return success(svc.serialize(crew, "crew"))


@app.route("/crew/<crew_id>/deactivate", methods=["POST"])
def deactivate_crew(crew_id):
    _, role = get_caller()
    require_role(role, {"FieldSupervisor"})
    crew = find_or_404(db.crew, crew_id)
    crew["status"] = "INACTIVE"
    touch(crew)
    return success(svc.serialize(crew, "crew"))


# ===========================================================================
# RECURRING SCHEDULES
# ===========================================================================
@app.route("/schedules", methods=["POST"])
def create_schedule():
    _, role = get_caller()
    require_role(role, {"FieldSupervisor"})
    body = get_body()
    require_fields(body, ["site_id", "weekday", "window_start_min", "window_end_min", "assigned_crew_id"])
    site = fk_or_404(db.sites, body["site_id"])
    crew = fk_or_404(db.crew, body["assigned_crew_id"])
    as_int(body["weekday"], "weekday")
    if body["weekday"] < 0 or body["weekday"] > 6:
        raise err("ERR_INVALID_REQUEST", "weekday must be in 0..6")
    check_minute_of_day(body["window_start_min"], "window_start_min")
    as_int(body["window_end_min"], "window_end_min")
    if body["window_end_min"] < 1 or body["window_end_min"] > 1440:
        raise err("ERR_INVALID_REQUEST", "window_end_min must be in 1..1440")
    if body["window_end_min"] <= body["window_start_min"]:
        raise err("ERR_INVALID_REQUEST", "window_end_min must be > window_start_min")
    # site must be ACTIVE to accept new schedules (PRD 3.1)
    if site["status"] != "ACTIVE":
        raise err("ERR_SITE_ARCHIVED", "Site is archived")
    # assigned crew must be AVAILABLE (PRD 3.2)
    if crew["status"] != "AVAILABLE":
        raise err("ERR_CREW_INACTIVE", "Assigned crew is inactive")
    check_schedule_conflict(body["assigned_crew_id"], body["weekday"],
                            body["window_start_min"], body["window_end_min"])
    sched = new_common()
    sched.update({
        "site_id": body["site_id"],
        "weekday": body["weekday"],
        "window_start_min": body["window_start_min"],
        "window_end_min": body["window_end_min"],
        "assigned_crew_id": body["assigned_crew_id"],
        "status": "ACTIVE",
    })
    db.schedules[sched["id"]] = sched
    return success(svc.serialize(sched, "schedule"), status=201)


@app.route("/schedules/<schedule_id>", methods=["GET"])
def get_schedule(schedule_id):
    _, role = get_caller()
    require_role(role, {"AccountManager", "FieldSupervisor"})
    sched = find_or_404(db.schedules, schedule_id)
    return success(svc.serialize(sched, "schedule"))


@app.route("/schedules", methods=["GET"])
def list_schedules():
    _, role = get_caller()
    require_role(role, {"AccountManager", "FieldSupervisor"})
    limit, offset = get_pagination()
    rows = list(db.schedules.values())
    site_f = request.args.get("site_id")
    if site_f is not None:
        rows = [r for r in rows if r["site_id"] == site_f]
    crew_f = request.args.get("assigned_crew_id")
    if crew_f is not None:
        rows = [r for r in rows if r["assigned_crew_id"] == crew_f]
    page, total = paginate(rows, limit, offset)
    return list_response([svc.serialize(r, "schedule") for r in page], limit, offset, total)


@app.route("/schedules/<schedule_id>/pause", methods=["POST"])
def pause_schedule(schedule_id):
    _, role = get_caller()
    require_role(role, {"FieldSupervisor"})
    sched = find_or_404(db.schedules, schedule_id)
    if sched["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Schedule is not ACTIVE")
    sched["status"] = "PAUSED"
    touch(sched)
    return success(svc.serialize(sched, "schedule"))


@app.route("/schedules/<schedule_id>/resume", methods=["POST"])
def resume_schedule(schedule_id):
    _, role = get_caller()
    require_role(role, {"FieldSupervisor"})
    sched = find_or_404(db.schedules, schedule_id)
    if sched["status"] != "PAUSED":
        raise err("ERR_INVALID_STATE", "Schedule is not PAUSED")
    crew = db.crew.get(sched["assigned_crew_id"])
    if crew is not None and crew["status"] != "AVAILABLE":
        raise err("ERR_CREW_INACTIVE", "Assigned crew is inactive")
    check_schedule_conflict(sched["assigned_crew_id"], sched["weekday"],
                            sched["window_start_min"], sched["window_end_min"],
                            exclude_schedule_id=sched["id"])
    sched["status"] = "ACTIVE"
    touch(sched)
    return success(svc.serialize(sched, "schedule"))


# ===========================================================================
# VISITS
# ===========================================================================
def _create_visit(site, crew, visit_kind, service_date, start_min, end_min,
                  schedule_id=None, periodic_job=None, complaint_id=None):
    visit = new_common()
    visit.update({
        "site_id": site["id"],
        "schedule_id": schedule_id,
        "crew_id": crew["id"],
        "visit_kind": visit_kind,
        "service_date": service_date,
        "planned_start_min": start_min,
        "planned_end_min": end_min,
        "estimated_labor_min": svc.estimate_labor_minutes(site, visit_kind, periodic_job),
        "actual_labor_min": 0,
        "periodic_job_id": periodic_job["id"] if periodic_job else None,
        "complaint_id": complaint_id,
        "billing_period_id": None,
        "status": "SCHEDULED",
    })
    db.visits[visit["id"]] = visit
    return visit


@app.route("/visits", methods=["POST"])
def create_visit():
    _, role = get_caller()
    require_role(role, {"FieldSupervisor"})
    body = get_body()
    require_fields(body, ["site_id", "crew_id", "service_date", "planned_start_min", "planned_end_min"])
    site = fk_or_404(db.sites, body["site_id"])
    crew = fk_or_404(db.crew, body["crew_id"])
    schedule_id = body.get("schedule_id")
    if schedule_id is not None:
        fk_or_404(db.schedules, schedule_id)
    as_str(body["service_date"], "service_date")
    check_minute_of_day(body["planned_start_min"], "planned_start_min")
    as_int(body["planned_end_min"], "planned_end_min")
    if body["planned_end_min"] < 1 or body["planned_end_min"] > 1440:
        raise err("ERR_INVALID_REQUEST", "planned_end_min must be in 1..1440")
    if body["planned_end_min"] <= body["planned_start_min"]:
        raise err("ERR_INVALID_REQUEST", "planned_end_min must be > planned_start_min")
    visit_kind = body.get("visit_kind", "ROUTINE")
    if visit_kind is None:
        visit_kind = "ROUTINE"
    check_enum(visit_kind, "visit_kind", {"ROUTINE", "PERIODIC", "CALLBACK"})
    check_crew_double_booked(crew["id"], body["service_date"],
                             body["planned_start_min"], body["planned_end_min"])
    periodic_job = None
    visit = _create_visit(site, crew, visit_kind, body["service_date"],
                          body["planned_start_min"], body["planned_end_min"],
                          schedule_id=schedule_id, periodic_job=periodic_job)
    return success(svc.serialize(visit, "visit"), status=201)


@app.route("/visits/<visit_id>", methods=["GET"])
def get_visit(visit_id):
    user_id, role = get_caller()
    require_role(role, {"AccountManager", "FieldSupervisor", "ClientContact"})
    visit = find_or_404(db.visits, visit_id)
    if role == "ClientContact":
        site = db.sites.get(visit["site_id"])
        if site is not None:
            ensure_site_contact(user_id, site)
    return success(svc.serialize(visit, "visit"))


@app.route("/visits", methods=["GET"])
def list_visits():
    _, role = get_caller()
    require_role(role, {"AccountManager", "FieldSupervisor"})
    limit, offset = get_pagination()
    rows = list(db.visits.values())
    for key in ["site_id", "crew_id", "schedule_id", "complaint_id",
                "periodic_job_id", "billing_period_id", "service_date"]:
        val = request.args.get(key)
        if val is not None:
            rows = [r for r in rows if r.get(key) == val]
    page, total = paginate(rows, limit, offset)
    return list_response([svc.serialize(r, "visit") for r in page], limit, offset, total)


@app.route("/visits/<visit_id>/start", methods=["POST"])
def start_visit(visit_id):
    _, role = get_caller()
    require_role(role, {"FieldSupervisor"})
    visit = find_or_404(db.visits, visit_id)
    if visit["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Visit is not SCHEDULED")
    crew = db.crew.get(visit["crew_id"])
    if crew is not None and crew["status"] != "AVAILABLE":
        raise err("ERR_CREW_INACTIVE", "Crew is inactive")
    site = db.sites.get(visit["site_id"])
    if site is not None and site["status"] != "ACTIVE":
        raise err("ERR_SITE_ARCHIVED", "Site is archived")
    visit["status"] = "IN_PROGRESS"
    touch(visit)
    return success(svc.serialize(visit, "visit"))


@app.route("/visits/<visit_id>/complete", methods=["POST"])
def complete_visit(visit_id):
    _, role = get_caller()
    require_role(role, {"FieldSupervisor"})
    visit = find_or_404(db.visits, visit_id)
    if visit["status"] != "IN_PROGRESS":
        raise err("ERR_INVALID_STATE", "Visit is not IN_PROGRESS")
    entries = [te for te in db.time_entries.values() if te["visit_id"] == visit["id"]]
    has_completed = any(te["status"] == "COMPLETED" for te in entries)
    has_open = any(te["status"] == "OPEN" for te in entries)
    if not has_completed:
        raise err("ERR_NO_TIME_ENTRY", "No completed time entry for visit")
    if has_open:
        raise err("ERR_OPEN_TIME_ENTRY", "An open time entry remains")
    # Recompute actual_labor_min.
    visit["actual_labor_min"] = svc.actual_labor_minutes(visit)
    visit["status"] = "COMPLETED"
    # Settle into billing.
    contract = active_contract_for_site(visit["site_id"])
    if contract is not None:
        period = open_billing_period_for(contract, month_of(visit["service_date"]))
        if period is not None:
            visit["billing_period_id"] = period["id"]
            svc.compute_period_total(period, final=False)
            touch(period)
    touch(visit)
    # PERIODIC visit -> linked job BILLED.
    if visit["visit_kind"] == "PERIODIC" and visit.get("periodic_job_id"):
        job = db.periodic_jobs.get(visit["periodic_job_id"])
        if job is not None and job["status"] == "DISPATCHED":
            job["status"] = "BILLED"
            touch(job)
    return success(svc.serialize(visit, "visit"))


@app.route("/visits/<visit_id>/miss", methods=["POST"])
def miss_visit(visit_id):
    _, role = get_caller()
    require_role(role, {"FieldSupervisor"})
    visit = find_or_404(db.visits, visit_id)
    if visit["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Visit is not SCHEDULED")
    visit["status"] = "MISSED"
    touch(visit)
    return success(svc.serialize(visit, "visit"))


@app.route("/visits/<visit_id>/cancel", methods=["POST"])
def cancel_visit(visit_id):
    _, role = get_caller()
    require_role(role, {"FieldSupervisor"})
    visit = find_or_404(db.visits, visit_id)
    if visit["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Visit is not SCHEDULED")
    visit["status"] = "CANCELLED"
    touch(visit)
    return success(svc.serialize(visit, "visit"))


# ===========================================================================
# TIME ENTRIES
# ===========================================================================
@app.route("/time-entries", methods=["POST"])
def create_time_entry():
    _, role = get_caller()
    require_role(role, {"FieldSupervisor"})
    body = get_body()
    require_fields(body, ["visit_id", "crew_id", "clock_in_min"])
    visit = fk_or_404(db.visits, body["visit_id"])
    crew = fk_or_404(db.crew, body["crew_id"])
    check_minute_of_day(body["clock_in_min"], "clock_in_min")
    te = new_common()
    te.update({
        "visit_id": body["visit_id"],
        "crew_id": body["crew_id"],
        "clock_in_min": body["clock_in_min"],
        "clock_out_min": None,
        "clocked_min": 0,
        "status": "OPEN",
    })
    db.time_entries[te["id"]] = te
    return success(svc.serialize(te, "time_entry"), status=201)


@app.route("/time-entries/<time_entry_id>", methods=["GET"])
def get_time_entry(time_entry_id):
    _, role = get_caller()
    require_role(role, {"AccountManager", "FieldSupervisor"})
    te = find_or_404(db.time_entries, time_entry_id)
    return success(svc.serialize(te, "time_entry"))


@app.route("/time-entries", methods=["GET"])
def list_time_entries():
    _, role = get_caller()
    require_role(role, {"AccountManager", "FieldSupervisor"})
    limit, offset = get_pagination()
    rows = list(db.time_entries.values())
    visit_f = request.args.get("visit_id")
    if visit_f is not None:
        rows = [r for r in rows if r["visit_id"] == visit_f]
    crew_f = request.args.get("crew_id")
    if crew_f is not None:
        rows = [r for r in rows if r["crew_id"] == crew_f]
    page, total = paginate(rows, limit, offset)
    return list_response([svc.serialize(r, "time_entry") for r in page], limit, offset, total)


@app.route("/time-entries/<time_entry_id>/clock-out", methods=["POST"])
def clock_out(time_entry_id):
    _, role = get_caller()
    require_role(role, {"FieldSupervisor"})
    te = find_or_404(db.time_entries, time_entry_id)
    body = get_body()
    require_fields(body, ["clock_out_min"])
    as_int(body["clock_out_min"], "clock_out_min")
    if body["clock_out_min"] < 1 or body["clock_out_min"] > 1440:
        raise err("ERR_INVALID_REQUEST", "clock_out_min must be in 1..1440")
    if te["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Time entry is not OPEN")
    if body["clock_out_min"] <= te["clock_in_min"]:
        raise err("ERR_INVALID_CLOCK_RANGE", "clock_out_min must be > clock_in_min")
    visit = db.visits.get(te["visit_id"])
    if visit is None or visit["status"] != "IN_PROGRESS":
        raise err("ERR_INVALID_STATE", "Parent visit is not IN_PROGRESS")
    # Shift-capacity guard: crew daily total across same service local-day.
    crew = db.crew.get(te["crew_id"])
    this_clocked = body["clock_out_min"] - te["clock_in_min"]
    service_date = visit["service_date"]
    other_total = 0
    for o in db.time_entries.values():
        if o["id"] == te["id"]:
            continue
        if o["crew_id"] != te["crew_id"]:
            continue
        if o["status"] != "COMPLETED":
            continue
        ov = db.visits.get(o["visit_id"])
        if ov is None or ov["service_date"] != service_date:
            continue
        other_total += o["clocked_min"]
    if crew is not None and (other_total + this_clocked) > crew["shift_capacity_min"]:
        raise err("ERR_SHIFT_CAPACITY_EXCEEDED", "Shift capacity exceeded")
    te["clock_out_min"] = body["clock_out_min"]
    te["clocked_min"] = this_clocked
    te["status"] = "COMPLETED"
    touch(te)
    return success(svc.serialize(te, "time_entry"))


@app.route("/time-entries/<time_entry_id>/void", methods=["POST"])
def void_time_entry(time_entry_id):
    _, role = get_caller()
    require_role(role, {"FieldSupervisor"})
    te = find_or_404(db.time_entries, time_entry_id)
    if te["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Time entry is not OPEN")
    te["status"] = "VOIDED"
    touch(te)
    return success(svc.serialize(te, "time_entry"))


# ===========================================================================
# INSPECTIONS
# ===========================================================================
@app.route("/inspections", methods=["POST"])
def create_inspection():
    _, role = get_caller()
    require_role(role, {"FieldSupervisor"})
    body = get_body()
    require_fields(body, ["visit_id", "score"])
    visit = fk_or_404(db.visits, body["visit_id"])
    as_int(body["score"], "score")
    if body["score"] < 0 or body["score"] > 100:
        raise err("ERR_INVALID_REQUEST", "score must be in 0..100")
    notes = body.get("notes")
    if notes is not None and not isinstance(notes, str):
        raise err("ERR_INVALID_REQUEST", "notes must be a string")
    site = db.sites.get(visit["site_id"])
    deficient = False
    if site is not None:
        deficient = body["score"] < site["quality_target"]
    insp = new_common()
    insp.update({
        "visit_id": body["visit_id"],
        "score": body["score"],
        "deficient": deficient,
        "notes": notes,
    })
    db.inspections[insp["id"]] = insp
    return success(svc.serialize(insp, "inspection"), status=201)


@app.route("/inspections/<inspection_id>", methods=["GET"])
def get_inspection(inspection_id):
    user_id, role = get_caller()
    require_role(role, {"AccountManager", "FieldSupervisor", "ClientContact"})
    insp = find_or_404(db.inspections, inspection_id)
    if role == "ClientContact":
        visit = db.visits.get(insp["visit_id"])
        if visit is not None:
            site = db.sites.get(visit["site_id"])
            if site is not None:
                ensure_site_contact(user_id, site)
    return success(svc.serialize(insp, "inspection"))


@app.route("/inspections", methods=["GET"])
def list_inspections():
    _, role = get_caller()
    require_role(role, {"AccountManager", "FieldSupervisor"})
    limit, offset = get_pagination()
    rows = list(db.inspections.values())
    visit_f = request.args.get("visit_id")
    if visit_f is not None:
        rows = [r for r in rows if r["visit_id"] == visit_f]
    page, total = paginate(rows, limit, offset)
    return list_response([svc.serialize(r, "inspection") for r in page], limit, offset, total)


# ===========================================================================
# PERIODIC JOBS
# ===========================================================================
@app.route("/periodic-jobs", methods=["POST"])
def create_periodic_job():
    _, role = get_caller()
    require_role(role, {"AccountManager"})
    body = get_body()
    require_fields(body, ["site_id", "job_type", "quoted_hours", "requested_date"])
    site = fk_or_404(db.sites, body["site_id"])
    check_enum(body["job_type"], "job_type", {"STRIP_WAX", "DEEP_CARPET"})
    as_number(body["quoted_hours"], "quoted_hours")
    if body["quoted_hours"] <= 0:
        raise err("ERR_INVALID_REQUEST", "quoted_hours must be > 0")
    as_str(body["requested_date"], "requested_date")
    job = new_common()
    job.update({
        "site_id": body["site_id"],
        "job_type": body["job_type"],
        "quoted_hours": body["quoted_hours"],
        "requested_date": body["requested_date"],
        "visit_id": None,
        "status": "REQUESTED",
    })
    db.periodic_jobs[job["id"]] = job
    return success(svc.serialize(job, "periodic_job"), status=201)


@app.route("/periodic-jobs/<periodic_job_id>", methods=["GET"])
def get_periodic_job(periodic_job_id):
    _, role = get_caller()
    require_role(role, {"AccountManager", "FieldSupervisor"})
    job = find_or_404(db.periodic_jobs, periodic_job_id)
    return success(svc.serialize(job, "periodic_job"))


@app.route("/periodic-jobs", methods=["GET"])
def list_periodic_jobs():
    _, role = get_caller()
    require_role(role, {"AccountManager", "FieldSupervisor"})
    limit, offset = get_pagination()
    rows = list(db.periodic_jobs.values())
    site_f = request.args.get("site_id")
    if site_f is not None:
        rows = [r for r in rows if r["site_id"] == site_f]
    page, total = paginate(rows, limit, offset)
    return list_response([svc.serialize(r, "periodic_job") for r in page], limit, offset, total)


@app.route("/periodic-jobs/<periodic_job_id>/dispatch", methods=["POST"])
def dispatch_periodic_job(periodic_job_id):
    _, role = get_caller()
    require_role(role, {"FieldSupervisor"})
    job = find_or_404(db.periodic_jobs, periodic_job_id)
    body = get_body()
    require_fields(body, ["crew_id", "service_date", "planned_start_min", "planned_end_min"])
    crew = fk_or_404(db.crew, body["crew_id"])
    as_str(body["service_date"], "service_date")
    check_minute_of_day(body["planned_start_min"], "planned_start_min")
    as_int(body["planned_end_min"], "planned_end_min")
    if body["planned_end_min"] < 1 or body["planned_end_min"] > 1440:
        raise err("ERR_INVALID_REQUEST", "planned_end_min must be in 1..1440")
    if body["planned_end_min"] <= body["planned_start_min"]:
        raise err("ERR_INVALID_REQUEST", "planned_end_min must be > planned_start_min")
    if job["status"] != "REQUESTED":
        raise err("ERR_INVALID_STATE", "Periodic job is not REQUESTED")
    site = db.sites.get(job["site_id"])
    if site is not None and site["status"] != "ACTIVE":
        raise err("ERR_SITE_ARCHIVED", "Site is archived")
    if job["job_type"] == "STRIP_WAX" and site is not None and site["floor_type"] not in ("VCT", "TERRAZZO"):
        raise err("ERR_FLOOR_INELIGIBLE", "Floor not eligible for strip/wax")
    if crew["status"] != "AVAILABLE":
        raise err("ERR_CREW_INACTIVE", "Assigned crew is inactive")
    check_crew_double_booked(crew["id"], body["service_date"],
                             body["planned_start_min"], body["planned_end_min"])
    visit = _create_visit(site, crew, "PERIODIC", body["service_date"],
                          body["planned_start_min"], body["planned_end_min"],
                          periodic_job=job)
    job["visit_id"] = visit["id"]
    job["status"] = "DISPATCHED"
    touch(job)
    return success(svc.serialize(job, "periodic_job"))


@app.route("/periodic-jobs/<periodic_job_id>/cancel", methods=["POST"])
def cancel_periodic_job(periodic_job_id):
    _, role = get_caller()
    require_role(role, {"AccountManager"})
    job = find_or_404(db.periodic_jobs, periodic_job_id)
    if job["status"] != "REQUESTED":
        raise err("ERR_INVALID_STATE", "Periodic job is not REQUESTED")
    job["status"] = "CANCELLED"
    touch(job)
    return success(svc.serialize(job, "periodic_job"))


# ===========================================================================
# COMPLAINTS
# ===========================================================================
@app.route("/complaints", methods=["POST"])
def create_complaint():
    user_id, role = get_caller()
    require_role(role, {"ClientContact", "AccountManager"})
    body = get_body()
    require_fields(body, ["site_id", "severity", "description"])
    site = fk_or_404(db.sites, body["site_id"])
    if role == "ClientContact":
        ensure_site_contact(user_id, site)
    visit_id = body.get("visit_id")
    if visit_id is not None:
        fk_or_404(db.visits, visit_id)
    check_enum(body["severity"], "severity", {"MINOR", "MAJOR"})
    as_str(body["description"], "description")
    complaint = new_common()
    complaint.update({
        "site_id": body["site_id"],
        "visit_id": visit_id,
        "severity": body["severity"],
        "description": body["description"],
        "callback_visit_id": None,
        "credit_applied_cents": 0,
        "status": "OPEN",
        "posted_billing_period_id": None,
    })
    db.complaints[complaint["id"]] = complaint
    acct = svc.account_for_site(site)
    if acct is not None:
        svc.recompute_open_complaint_count(acct)
    return success(svc.serialize(complaint, "complaint"), status=201)


@app.route("/complaints/<complaint_id>", methods=["GET"])
def get_complaint(complaint_id):
    user_id, role = get_caller()
    require_role(role, {"AccountManager", "FieldSupervisor", "ClientContact"})
    complaint = find_or_404(db.complaints, complaint_id)
    if role == "ClientContact":
        site = db.sites.get(complaint["site_id"])
        if site is not None:
            ensure_site_contact(user_id, site)
    return success(svc.serialize(complaint, "complaint"))


@app.route("/complaints", methods=["GET"])
def list_complaints():
    _, role = get_caller()
    require_role(role, {"AccountManager", "FieldSupervisor"})
    limit, offset = get_pagination()
    rows = list(db.complaints.values())
    site_f = request.args.get("site_id")
    if site_f is not None:
        rows = [r for r in rows if r["site_id"] == site_f]
    status_f = request.args.get("status")
    if status_f is not None:
        rows = [r for r in rows if r["status"] == status_f]
    page, total = paginate(rows, limit, offset)
    return list_response([svc.serialize(r, "complaint") for r in page], limit, offset, total)


@app.route("/complaints/<complaint_id>/acknowledge", methods=["POST"])
def acknowledge_complaint(complaint_id):
    _, role = get_caller()
    require_role(role, {"FieldSupervisor"})
    complaint = find_or_404(db.complaints, complaint_id)
    if complaint["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Complaint is not OPEN")
    complaint["status"] = "ACKNOWLEDGED"
    touch(complaint)
    site = db.sites.get(complaint["site_id"])
    acct = svc.account_for_site(site) if site else None
    if acct is not None:
        svc.recompute_open_complaint_count(acct)
    return success(svc.serialize(complaint, "complaint"))


@app.route("/complaints/<complaint_id>/schedule-callback", methods=["POST"])
def schedule_callback(complaint_id):
    _, role = get_caller()
    require_role(role, {"FieldSupervisor"})
    complaint = find_or_404(db.complaints, complaint_id)
    body = get_body()
    require_fields(body, ["crew_id", "service_date", "planned_start_min", "planned_end_min"])
    crew = fk_or_404(db.crew, body["crew_id"])
    as_str(body["service_date"], "service_date")
    check_minute_of_day(body["planned_start_min"], "planned_start_min")
    as_int(body["planned_end_min"], "planned_end_min")
    if body["planned_end_min"] < 1 or body["planned_end_min"] > 1440:
        raise err("ERR_INVALID_REQUEST", "planned_end_min must be in 1..1440")
    if body["planned_end_min"] <= body["planned_start_min"]:
        raise err("ERR_INVALID_REQUEST", "planned_end_min must be > planned_start_min")
    if complaint["status"] != "ACKNOWLEDGED":
        raise err("ERR_INVALID_STATE", "Complaint is not ACKNOWLEDGED")
    site = db.sites.get(complaint["site_id"])
    if site is not None and site["status"] != "ACTIVE":
        raise err("ERR_SITE_ARCHIVED", "Site is archived")
    if crew["status"] != "AVAILABLE":
        raise err("ERR_CREW_INACTIVE", "Assigned crew is inactive")
    check_crew_double_booked(crew["id"], body["service_date"],
                             body["planned_start_min"], body["planned_end_min"])
    visit = _create_visit(site, crew, "CALLBACK", body["service_date"],
                          body["planned_start_min"], body["planned_end_min"],
                          complaint_id=complaint["id"])
    complaint["callback_visit_id"] = visit["id"]
    complaint["status"] = "CALLBACK_SCHEDULED"
    touch(complaint)
    return success(svc.serialize(complaint, "complaint"))


@app.route("/complaints/<complaint_id>/resolve", methods=["POST"])
def resolve_complaint(complaint_id):
    _, role = get_caller()
    require_role(role, {"FieldSupervisor"})
    complaint = find_or_404(db.complaints, complaint_id)
    if complaint["status"] != "CALLBACK_SCHEDULED":
        raise err("ERR_INVALID_STATE", "Complaint is not CALLBACK_SCHEDULED")
    callback_visit = db.visits.get(complaint.get("callback_visit_id"))
    if callback_visit is None or callback_visit["status"] != "COMPLETED":
        raise err("ERR_CALLBACK_NOT_COMPLETE", "Callback visit is not COMPLETED")
    site = db.sites.get(complaint["site_id"])
    contract = active_contract_for_site(complaint["site_id"]) if site else None
    if contract is not None:
        credit = svc.callback_credit(complaint, contract)
        complaint["credit_applied_cents"] = credit
        # Post into the OPEN billing period for the callback visit's month.
        period = open_billing_period_for(contract, month_of(callback_visit["service_date"]))
        if period is not None:
            complaint["posted_billing_period_id"] = period["id"]
            svc.compute_period_total(period, final=False)
            touch(period)
    complaint["status"] = "RESOLVED"
    touch(complaint)
    acct = svc.account_for_site(site) if site else None
    if acct is not None:
        svc.recompute_open_complaint_count(acct)
    return success(svc.serialize(complaint, "complaint"))


@app.route("/complaints/<complaint_id>/reopen", methods=["POST"])
def reopen_complaint(complaint_id):
    user_id, role = get_caller()
    require_role(role, {"ClientContact"})
    complaint = find_or_404(db.complaints, complaint_id)
    site = db.sites.get(complaint["site_id"])
    if site is not None:
        ensure_site_contact(user_id, site)
    if complaint["status"] != "RESOLVED":
        raise err("ERR_INVALID_STATE", "Complaint is not RESOLVED")
    if complaint["severity"] != "MAJOR":
        raise err("ERR_REOPEN_NOT_ALLOWED", "Only MAJOR complaints may reopen")
    complaint["status"] = "OPEN"
    complaint["callback_visit_id"] = None
    touch(complaint)
    acct = svc.account_for_site(site) if site else None
    if acct is not None:
        svc.recompute_open_complaint_count(acct)
    return success(svc.serialize(complaint, "complaint"))


# ===========================================================================
# BILLING PERIODS
# ===========================================================================
@app.route("/billing-periods", methods=["POST"])
def open_billing_period():
    _, role = get_caller()
    require_role(role, {"AccountManager"})
    body = get_body()
    require_fields(body, ["contract_id", "period_month"])
    contract = fk_or_404(db.contracts, body["contract_id"])
    as_str(body["period_month"], "period_month")
    # uniqueness (contract, month)
    for p in db.billing_periods.values():
        if p["contract_id"] == contract["id"] and p["period_month"] == body["period_month"]:
            raise err("ERR_DUPLICATE_PERIOD", "Period already exists for contract/month")
    if contract["status"] != "ACTIVE":
        raise err("ERR_CONTRACT_NOT_ACTIVE", "Backing contract is not ACTIVE")
    period = new_common()
    period.update({
        "contract_id": contract["id"],
        "period_month": body["period_month"],
        "base_cents": contract["monthly_base_cents"],
        "periodic_cents": 0,
        "callback_credit_cents": 0,
        "holdback_cents": 0,
        "total_cents": contract["monthly_base_cents"],
        "mean_quality_score": None,
        "status": "OPEN",
    })
    db.billing_periods[period["id"]] = period
    return success(svc.serialize(period, "billing_period"), status=201)


@app.route("/billing-periods/<billing_period_id>", methods=["GET"])
def get_billing_period(billing_period_id):
    _, role = get_caller()
    require_role(role, {"AccountManager"})
    period = find_or_404(db.billing_periods, billing_period_id)
    return success(svc.serialize(period, "billing_period"))


@app.route("/billing-periods", methods=["GET"])
def list_billing_periods():
    _, role = get_caller()
    require_role(role, {"AccountManager"})
    limit, offset = get_pagination()
    rows = list(db.billing_periods.values())
    contract_f = request.args.get("contract_id")
    if contract_f is not None:
        rows = [r for r in rows if r["contract_id"] == contract_f]
    status_f = request.args.get("status")
    if status_f is not None:
        rows = [r for r in rows if r["status"] == status_f]
    page, total = paginate(rows, limit, offset)
    return list_response([svc.serialize(r, "billing_period") for r in page], limit, offset, total)


def _account_for_period(period):
    contract = db.contracts.get(period["contract_id"])
    if contract is None:
        return None
    return svc.account_for_contract(contract)


def _delete_invoice_lines(period):
    to_delete = [lid for lid, line in db.invoice_lines.items()
                 if line["billing_period_id"] == period["id"]]
    for lid in to_delete:
        del db.invoice_lines[lid]


def _emit_invoice_lines(period):
    """Emit the four ledger rows: BASE, PERIODIC, CALLBACK_CREDIT, HOLDBACK."""
    rows = [
        ("BASE", period["base_cents"], "Monthly base charge"),
        ("PERIODIC", period["periodic_cents"], "Periodic add-on charges"),
        ("CALLBACK_CREDIT", -period["callback_credit_cents"], "Callback credits"),
        ("HOLDBACK", -period["holdback_cents"], "Quality holdback"),
    ]
    for line_type, amount, memo in rows:
        common = new_common(with_version=False)
        line = {
            "id": common["id"],
            "created_at": common["created_at"],
            "_seq": common["_seq"],
            "billing_period_id": period["id"],
            "line_type": line_type,
            "amount_cents": amount,
            "memo": memo,
        }
        db.invoice_lines[line["id"]] = line


@app.route("/billing-periods/<billing_period_id>/close", methods=["POST"])
def close_billing_period(billing_period_id):
    _, role = get_caller()
    require_role(role, {"AccountManager"})
    period = find_or_404(db.billing_periods, billing_period_id)
    body = get_body()
    require_fields(body, ["expected_account_version"])
    as_int(body["expected_account_version"], "expected_account_version")
    if period["status"] not in ("OPEN", "REOPENED"):
        raise err("ERR_INVALID_STATE", "Period is not OPEN or REOPENED")
    acct = _account_for_period(period)
    if acct is not None and body["expected_account_version"] != acct["version"]:
        raise err("ERR_STALE_VERSION", "Account version is stale")
    # No captured visit may be IN_PROGRESS.
    for v in db.visits.values():
        if v.get("billing_period_id") == period["id"] and v["status"] == "IN_PROGRESS":
            raise err("ERR_VISIT_IN_PROGRESS", "A captured visit is in progress")
    svc.compute_period_total(period, final=True)
    _delete_invoice_lines(period)
    _emit_invoice_lines(period)
    period["status"] = "CLOSED"
    touch(period)
    if acct is not None:
        touch(acct)
    return success(svc.serialize(period, "billing_period"))


@app.route("/billing-periods/<billing_period_id>/reopen", methods=["POST"])
def reopen_billing_period(billing_period_id):
    _, role = get_caller()
    require_role(role, {"AccountManager"})
    period = find_or_404(db.billing_periods, billing_period_id)
    body = get_body()
    require_fields(body, ["expected_account_version"])
    as_int(body["expected_account_version"], "expected_account_version")
    if period["status"] != "CLOSED":
        raise err("ERR_INVALID_STATE", "Period is not CLOSED")
    acct = _account_for_period(period)
    if acct is not None and body["expected_account_version"] != acct["version"]:
        raise err("ERR_STALE_VERSION", "Account version is stale")
    _delete_invoice_lines(period)
    svc.compute_period_total(period, final=False)
    period["status"] = "REOPENED"
    touch(period)
    if acct is not None:
        touch(acct)
    return success(svc.serialize(period, "billing_period"))


@app.route("/billing-periods/<billing_period_id>/invoice", methods=["POST"])
def invoice_billing_period(billing_period_id):
    _, role = get_caller()
    require_role(role, {"AccountManager"})
    period = find_or_404(db.billing_periods, billing_period_id)
    if period["status"] != "CLOSED":
        raise err("ERR_INVALID_STATE", "Period is not CLOSED")
    period["status"] = "INVOICED"
    touch(period)
    return success(svc.serialize(period, "billing_period"))


@app.route("/billing-periods/<billing_period_id>/invoice-lines", methods=["GET"])
def list_invoice_lines(billing_period_id):
    _, role = get_caller()
    require_role(role, {"AccountManager"})
    period = find_or_404(db.billing_periods, billing_period_id)
    limit, offset = get_pagination()
    rows = [l for l in db.invoice_lines.values() if l["billing_period_id"] == period["id"]]
    page, total = paginate(rows, limit, offset)
    return list_response([svc.serialize(r, "invoice_line") for r in page], limit, offset, total)


# ===========================================================================
# SUPPLY ORDERS
# ===========================================================================
@app.route("/supply-orders", methods=["POST"])
def create_supply_order():
    _, role = get_caller()
    require_role(role, {"FieldSupervisor", "AccountManager"})
    body = get_body()
    require_fields(body, ["site_id", "sku", "quantity"])
    site = fk_or_404(db.sites, body["site_id"])
    check_enum(body["sku"], "sku", {"PAPER_TOWEL", "TRASH_LINER", "FLOOR_FINISH", "RESTROOM_KIT"})
    as_int(body["quantity"], "quantity")
    if body["quantity"] <= 0:
        raise err("ERR_INVALID_REQUEST", "quantity must be > 0")
    order = new_common()
    order.update({
        "site_id": body["site_id"],
        "sku": body["sku"],
        "quantity": body["quantity"],
        "status": "REQUESTED",
    })
    db.supply_orders[order["id"]] = order
    return success(svc.serialize(order, "supply_order"), status=201)


@app.route("/supply-orders/<supply_order_id>", methods=["GET"])
def get_supply_order(supply_order_id):
    _, role = get_caller()
    require_role(role, {"AccountManager", "FieldSupervisor"})
    order = find_or_404(db.supply_orders, supply_order_id)
    return success(svc.serialize(order, "supply_order"))


@app.route("/supply-orders", methods=["GET"])
def list_supply_orders():
    _, role = get_caller()
    require_role(role, {"AccountManager", "FieldSupervisor"})
    limit, offset = get_pagination()
    rows = list(db.supply_orders.values())
    site_f = request.args.get("site_id")
    if site_f is not None:
        rows = [r for r in rows if r["site_id"] == site_f]
    page, total = paginate(rows, limit, offset)
    return list_response([svc.serialize(r, "supply_order") for r in page], limit, offset, total)


@app.route("/supply-orders/<supply_order_id>/fulfill", methods=["POST"])
def fulfill_supply_order(supply_order_id):
    _, role = get_caller()
    require_role(role, {"FieldSupervisor"})
    order = find_or_404(db.supply_orders, supply_order_id)
    if order["status"] != "REQUESTED":
        raise err("ERR_INVALID_STATE", "Supply order is not REQUESTED")
    order["status"] = "FULFILLED"
    touch(order)
    return success(svc.serialize(order, "supply_order"))


@app.route("/supply-orders/<supply_order_id>/cancel", methods=["POST"])
def cancel_supply_order(supply_order_id):
    _, role = get_caller()
    require_role(role, {"AccountManager", "FieldSupervisor"})
    order = find_or_404(db.supply_orders, supply_order_id)
    if order["status"] != "REQUESTED":
        raise err("ERR_INVALID_STATE", "Supply order is not REQUESTED")
    order["status"] = "CANCELLED"
    touch(order)
    return success(svc.serialize(order, "supply_order"))


# ===========================================================================
# TEST-DRIVING CLOCK (no auth headers required)
# ===========================================================================
@app.route("/_clock/set", methods=["POST"])
def set_clock():
    # PlatformAdmin only, but this endpoint is exempt from the standard
    # auth-header requirement (PRD 2.1, 3.11). If a role header is present it
    # must be PlatformAdmin; otherwise it is accepted for test orchestration.
    role = request.headers.get("X-User-Role")
    if role is not None and role != "PlatformAdmin":
        raise err("ERR_FORBIDDEN", "Only PlatformAdmin may set the clock")
    body = get_body()
    require_fields(body, ["to_iso8601"])
    db._clock = body["to_iso8601"]
    return success({}, status=200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    # Serve with waitress (a robust pure-Python WSGI server) when available.
    # The Werkzeug dev server (app.run) intermittently corrupts reused keep-alive
    # connections under heavy concurrent host load (8 parallel test rounds, each
    # rebooting the server per test), surfacing as client-side BadStatusLine /
    # ConnectionError flakiness. Waitress handles connection lifecycle reliably.
    try:
        from waitress import serve
        serve(app, host="0.0.0.0", port=port, threads=8)
    except ImportError:
        app.run(host="0.0.0.0", port=port, threaded=True)
