"""RemovalJob endpoints with daily-capacity rule and the big removal cascade."""

from datetime import timedelta

from flask import Blueprint

import db
from errors import (ApiError, err_not_found, err_invalid_request,
                    err_invalid_state)
from middleware import require_role, get_json_body, get_pagination
from response import success_object, success_list
from services.core import (stamp_new, touch, serialize, audit,
                           parse_iso8601, recompute_customer_outstanding)
from services.calculations import buyback_offer, whole_months_between

bp = Blueprint("removal_jobs", __name__)

REMOVAL_DAILY_CAPACITY = 2
READ_ROLES = ("PlatformAdmin", "InstallCoordinator", "SalesRep")


def _check_daily_capacity(crew_id, start_dt):
    day = start_dt.date()
    count = 0
    for r in db.removal_jobs.values():
        if r["technician_crew_id"] != crew_id or r["status"] != "SCHEDULED":
            continue
        r_start = parse_iso8601(r["scheduled_start_utc"])
        if r_start is not None and r_start.date() == day:
            count += 1
    if count >= REMOVAL_DAILY_CAPACITY:
        raise ApiError("ERR_CREW_OVERLAP", 409,
                       "Crew daily removal capacity reached")


@bp.post("/stairlift-ops/agreements/<aid>/removal-jobs")
def create_removal_job(aid):
    user_id, role = require_role("InstallCoordinator")
    ag = db.agreements.get(aid)
    if ag is None:
        raise err_not_found("Agreement not found")
    if ag["status"] != "ACTIVE":
        raise err_invalid_state("Agreement must be ACTIVE to schedule removal")
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
    # fiscal/temporal gates
    if ag["mode"] == "RENTAL":
        if ag.get("paid_to_date_cents", 0) < ag["list_price_cents"]:
            raise ApiError("ERR_RENTAL_BALANCE_OUTSTANDING", 402,
                           "Rental must be fully paid before removal")
    else:  # PURCHASE cooling-off: 30 days since INSTALLED
        installed_at = ag.get("_installed_at")
        if installed_at:
            inst_dt = parse_iso8601(installed_at)
            if inst_dt is not None and \
                    db.get_now() < inst_dt + timedelta(days=30):
                raise ApiError("ERR_REMOVAL_COOLING_OFF", 409,
                               "30-day cooling-off since install has not elapsed")
    _check_daily_capacity(crew, start_dt)
    # buyback offer computed now (per PRD: at RemovalJob creation)
    quote = db.quotes.get(ag["quote_id"])
    pm = db.product_models.get(
        db.product_models_by_code.get(quote["model_code"])) if quote else None
    customer = db.customers.get(ag["customer_id"])
    # condition grade at removal is only known at completion; for the offer we
    # use the unit's current grade as the assessor estimate baseline. The PRD
    # pins computation at job creation; grade factor applies the grade
    # recorded on the removal -- at creation time the unit's current grade is
    # the best available predictor.
    unit = db.equipment_units.get(ag.get("equipment_unit_id"))
    installed_at = ag.get("_installed_at") or ag["created_at"]
    months_installed = whole_months_between(installed_at, db.now_iso())
    grade_for_offer = unit["condition_grade"] if unit else "REFURB_A"
    if grade_for_offer == "NEW":
        grade_for_offer = "REFURB_A"
    offer = buyback_offer(ag, customer, pm, months_installed,
                          grade_for_offer) if (pm and customer) else 0
    job = {
        "agreement_id": aid,
        "technician_crew_id": crew,
        "scheduled_start_utc": start_s,
        "scheduled_end_utc": end_s,
        "status": "SCHEDULED",
        "buyback_offered_cents": offer,
        "condition_grade_at_removal": None,
    }
    stamp_new(job)
    db.removal_jobs[job["id"]] = job
    ag["status"] = "REMOVAL_REQUESTED"
    touch(ag)
    audit("RemovalJob", job["id"], "REMOVAL_SCHEDULED", role,
          {"agreement_id": aid})
    audit("Agreement", ag["id"], "AGREEMENT_REMOVAL_REQUESTED", "system",
          {"to": "REMOVAL_REQUESTED"})
    recompute_customer_outstanding(ag["customer_id"])
    return success_object(serialize(job), 201)


@bp.get("/stairlift-ops/agreements/<aid>/removal-jobs")
def list_removal_jobs(aid):
    require_role(*READ_ROLES)
    if aid not in db.agreements:
        raise err_not_found("Agreement not found")
    limit, offset = get_pagination()
    items = sorted(
        (r for r in db.removal_jobs.values() if r["agreement_id"] == aid),
        key=lambda r: r["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize(r) for r in page], limit, offset, total)


@bp.get("/stairlift-ops/removal-jobs/<rid>")
def get_removal_job(rid):
    require_role(*READ_ROLES)
    r = db.removal_jobs.get(rid)
    if r is None:
        raise err_not_found("RemovalJob not found")
    return success_object(serialize(r))


@bp.post("/stairlift-ops/removal-jobs/<rid>/complete")
def complete_removal_job(rid):
    user_id, role = require_role("InstallCoordinator")
    r = db.removal_jobs.get(rid)
    if r is None:
        raise err_not_found("RemovalJob not found")
    if r["status"] != "SCHEDULED":
        raise err_invalid_state("RemovalJob must be SCHEDULED to complete")
    body = get_json_body(["condition_grade_at_removal"])
    grade = body["condition_grade_at_removal"]
    if grade not in ("REFURB_A", "REFURB_B", "REFURB_C", "RETIRED"):
        raise err_invalid_request("condition_grade_at_removal invalid")
    r["condition_grade_at_removal"] = grade
    r["status"] = "COMPLETED"
    touch(r)
    audit("RemovalJob", r["id"], "REMOVAL_COMPLETED", role, {})
    # cascades
    ag = db.agreements.get(r["agreement_id"])
    if ag is not None and ag["status"] == "REMOVAL_REQUESTED":
        ag["status"] = "REMOVED"
        touch(ag)
        audit("Agreement", ag["id"], "AGREEMENT_REMOVED", "system",
              {"to": "REMOVED"})
        unit = db.equipment_units.get(ag.get("equipment_unit_id"))
        if unit is not None:
            unit["status"] = "REMOVED"
            unit["condition_grade"] = grade
            touch(unit)
        for sp in db.service_plans.values():
            if sp["agreement_id"] == ag["id"] and sp["status"] == "ACTIVE":
                sp["status"] = "CANCELLED"
                touch(sp)
                audit("ServicePlan", sp["id"], "SERVICE_PLAN_CANCELLED",
                      "system", {"reason": "agreement removed"})
        for wc in db.warranty_claims.values():
            if wc["agreement_id"] == ag["id"] and wc["status"] in (
                    "SUBMITTED", "UNDER_REVIEW", "APPROVED"):
                wc["status"] = "DENIED"
                wc["denial_reason"] = "AGREEMENT_REMOVED"
                touch(wc)
                audit("WarrantyClaim", wc["id"], "CLAIM_DENIED", "system",
                      {"reason": "AGREEMENT_REMOVED"})
        recompute_customer_outstanding(ag["customer_id"])
    return success_object(serialize(r))


@bp.post("/stairlift-ops/removal-jobs/<rid>/cancel")
def cancel_removal_job(rid):
    user_id, role = require_role("InstallCoordinator")
    r = db.removal_jobs.get(rid)
    if r is None:
        raise err_not_found("RemovalJob not found")
    if r["status"] != "SCHEDULED":
        raise err_invalid_state("RemovalJob must be SCHEDULED to cancel")
    r["status"] = "CANCELLED"
    touch(r)
    audit("RemovalJob", r["id"], "REMOVAL_CANCELLED", role, {})
    ag = db.agreements.get(r["agreement_id"])
    if ag is not None and ag["status"] == "REMOVAL_REQUESTED":
        ag["status"] = "ACTIVE"
        touch(ag)
        audit("Agreement", ag["id"], "AGREEMENT_REMOVAL_CANCELLED", "system",
              {"to": "ACTIVE"})
        recompute_customer_outstanding(ag["customer_id"])
    return success_object(serialize(r))
