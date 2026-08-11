"""InstallJob endpoints with crew buffer rule and completion cascade."""

from datetime import timedelta

from flask import Blueprint

import db
from errors import (ApiError, err_not_found, err_invalid_request,
                    err_invalid_state)
from middleware import require_role, get_json_body, get_pagination
from response import success_object, success_list
from services.core import (stamp_new, touch, serialize, audit,
                           parse_iso8601, recompute_customer_outstanding)
from services.calculations import issued_quote_total

bp = Blueprint("install_jobs", __name__)

INSTALL_BUFFER_MINUTES = 60
READ_ROLES = ("PlatformAdmin", "InstallCoordinator", "SalesRep")


def _check_crew_overlap_install(crew_id, start_dt, end_dt):
    """Half-open [start-60m, end+60m) overlap against existing same-crew jobs
    in SCHEDULED or IN_PROGRESS. Exactly-adjacent raw boundaries are exempt."""
    buffer = timedelta(minutes=INSTALL_BUFFER_MINUTES)
    p_start = start_dt - buffer
    p_end = end_dt + buffer
    for j in db.install_jobs.values():
        if j["technician_crew_id"] != crew_id:
            continue
        if j["status"] not in ("SCHEDULED", "IN_PROGRESS"):
            continue
        e_start_raw = parse_iso8601(j["scheduled_start_utc"])
        e_end_raw = parse_iso8601(j["scheduled_end_utc"])
        if e_start_raw is None or e_end_raw is None:
            continue
        # exact adjacency exemption: raw end == proposed raw start or vice versa
        if e_end_raw == start_dt or e_start_raw == end_dt:
            continue
        e_start = e_start_raw - buffer
        e_end = e_end_raw + buffer
        if p_start < e_end and e_start < p_end:
            raise ApiError("ERR_CREW_OVERLAP", 409,
                           "Crew has an overlapping install booking")


@bp.post("/stairlift-ops/agreements/<aid>/install-jobs")
def create_install_job(aid):
    user_id, role = require_role("InstallCoordinator")
    ag = db.agreements.get(aid)
    if ag is None:
        raise err_not_found("Agreement not found")
    # PRD 3.5: install booking requires FUNDED; after a FAILED install the
    # agreement remains SCHEDULED and "a fresh install job may be created".
    if ag["status"] not in ("FUNDED", "SCHEDULED"):
        raise err_invalid_state("Agreement must be FUNDED to schedule install")
    body = get_json_body(["technician_crew_id", "scheduled_start_utc",
                          "scheduled_end_utc"])
    crew = body["technician_crew_id"]
    start_s = body["scheduled_start_utc"]
    end_s = body["scheduled_end_utc"]
    if not isinstance(crew, str) or not isinstance(start_s, str) \
            or not isinstance(end_s, str):
        raise err_invalid_request("technician_crew_id and schedule times must be strings")
    start_dt = parse_iso8601(start_s)
    end_dt = parse_iso8601(end_s)
    if start_dt is None or end_dt is None:
        raise err_invalid_request("scheduled times must be ISO 8601")
    if end_dt <= start_dt:
        raise err_invalid_request("scheduled_end_utc must be after start")
    for j in db.install_jobs.values():
        if j["agreement_id"] == aid and j["status"] in ("SCHEDULED", "IN_PROGRESS"):
            raise ApiError("ERR_INSTALL_ALREADY_SCHEDULED", 409,
                           "An install job is already active on this agreement")
    _check_crew_overlap_install(crew, start_dt, end_dt)
    unit = db.equipment_units.get(ag.get("equipment_unit_id"))
    if unit is None or unit["status"] != "RESERVED":
        raise ApiError("ERR_UNIT_NOT_AVAILABLE", 409,
                       "Reserved unit no longer available")
    job = {
        "agreement_id": aid,
        "technician_crew_id": crew,
        "scheduled_start_utc": start_s,
        "scheduled_end_utc": end_s,
        "status": "SCHEDULED",
        "measured_labor_hours": None,
        "installed_rail_length_m": None,
        "completed_at": None,
    }
    stamp_new(job)
    db.install_jobs[job["id"]] = job
    if ag["status"] == "FUNDED":
        ag["status"] = "SCHEDULED"
        touch(ag)
    audit("InstallJob", job["id"], "INSTALL_SCHEDULED", role,
          {"agreement_id": aid})
    return success_object(serialize(job), 201)


@bp.get("/stairlift-ops/agreements/<aid>/install-jobs")
def list_install_jobs(aid):
    require_role(*READ_ROLES)
    if aid not in db.agreements:
        raise err_not_found("Agreement not found")
    limit, offset = get_pagination()
    items = sorted(
        (j for j in db.install_jobs.values() if j["agreement_id"] == aid),
        key=lambda j: j["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize(j) for j in page], limit, offset, total)


@bp.get("/stairlift-ops/install-jobs/<jid>")
def get_install_job(jid):
    require_role(*READ_ROLES)
    j = db.install_jobs.get(jid)
    if j is None:
        raise err_not_found("InstallJob not found")
    return success_object(serialize(j))


@bp.post("/stairlift-ops/install-jobs/<jid>/start")
def start_install_job(jid):
    user_id, role = require_role("InstallCoordinator")
    j = db.install_jobs.get(jid)
    if j is None:
        raise err_not_found("InstallJob not found")
    if j["status"] != "SCHEDULED":
        raise err_invalid_state("InstallJob must be SCHEDULED to start")
    start_dt = parse_iso8601(j["scheduled_start_utc"])
    if start_dt is not None and db.get_now() < start_dt:
        raise ApiError("ERR_TOO_EARLY", 409,
                       "Logical clock has not reached scheduled_start_utc")
    j["status"] = "IN_PROGRESS"
    touch(j)
    audit("InstallJob", j["id"], "INSTALL_STARTED", role, {})
    return success_object(serialize(j))


@bp.post("/stairlift-ops/install-jobs/<jid>/complete")
def complete_install_job(jid):
    user_id, role = require_role("InstallCoordinator")
    j = db.install_jobs.get(jid)
    if j is None:
        raise err_not_found("InstallJob not found")
    if j["status"] != "IN_PROGRESS":
        raise err_invalid_state("InstallJob must be IN_PROGRESS to complete")
    body = get_json_body(["measured_labor_hours", "installed_rail_length_m"])
    labor = body["measured_labor_hours"]
    rail = body["installed_rail_length_m"]
    if isinstance(labor, bool) or not isinstance(labor, int):
        raise err_invalid_request("measured_labor_hours must be an integer")
    if isinstance(rail, bool) or not isinstance(rail, (int, float)):
        raise err_invalid_request("installed_rail_length_m must be a number")
    j["measured_labor_hours"] = labor
    j["installed_rail_length_m"] = rail
    j["status"] = "COMPLETED"
    j["completed_at"] = db.now_iso()
    touch(j)
    audit("InstallJob", j["id"], "INSTALL_COMPLETED", role, {})
    # cascade: Agreement SCHEDULED -> INSTALLED; unit RESERVED -> INSTALLED;
    # customer PROSPECT -> ACTIVE; quote reconciliation if rail delta > 0.5m
    ag = db.agreements.get(j["agreement_id"])
    if ag is not None and ag["status"] == "SCHEDULED":
        ag["status"] = "INSTALLED"
        ag["_installed_at"] = db.now_iso()
        touch(ag)
        audit("Agreement", ag["id"], "AGREEMENT_INSTALLED", "system",
              {"to": "INSTALLED"})
        unit = db.equipment_units.get(ag.get("equipment_unit_id"))
        if unit is not None and unit["status"] == "RESERVED":
            unit["status"] = "INSTALLED"
            touch(unit)
        customer = db.customers.get(ag["customer_id"])
        if customer is not None and customer["status"] == "PROSPECT":
            customer["status"] = "ACTIVE"
            touch(customer)
        # quote reconciliation
        quote = db.quotes.get(ag["quote_id"])
        if quote is not None:
            pinned = quote.get("valid_rail_length_m")
            if pinned is not None and abs(float(rail) - float(pinned)) > 0.5:
                assessment = db.home_assessments.get(quote["home_assessment_id"])
                pm = db.product_models.get(
                    db.product_models_by_code.get(quote["model_code"]))
                if assessment is not None and pm is not None:
                    quote["issued_total_cents"] = issued_quote_total(
                        quote, assessment, pm,
                        rail_length_m=float(rail), labor_hours=labor)
                    touch(quote)
        recompute_customer_outstanding(ag["customer_id"])
    return success_object(serialize(j))


@bp.post("/stairlift-ops/install-jobs/<jid>/fail")
def fail_install_job(jid):
    user_id, role = require_role("InstallCoordinator")
    j = db.install_jobs.get(jid)
    if j is None:
        raise err_not_found("InstallJob not found")
    if j["status"] != "IN_PROGRESS":
        raise err_invalid_state("InstallJob must be IN_PROGRESS to fail")
    j["status"] = "FAILED"
    touch(j)
    audit("InstallJob", j["id"], "INSTALL_FAILED", role, {})
    return success_object(serialize(j))


@bp.post("/stairlift-ops/install-jobs/<jid>/cancel")
def cancel_install_job(jid):
    user_id, role = require_role("InstallCoordinator")
    j = db.install_jobs.get(jid)
    if j is None:
        raise err_not_found("InstallJob not found")
    if j["status"] != "SCHEDULED":
        raise err_invalid_state("InstallJob must be SCHEDULED to cancel")
    j["status"] = "CANCELLED"
    touch(j)
    audit("InstallJob", j["id"], "INSTALL_CANCELLED", role, {})
    return success_object(serialize(j))
