"""Interim changes, grievances/eviction, and the logical clock control."""
from flask import Blueprint, request

import db
import domain
from core import (
    ApiError, authenticate, authorize, require_ownership, get_or_404,
    owner_applicant_id, json_body, need_str, need_enum, need_dt,
    pagination, ok, ok_list,
)

bp = Blueprint("interim_grievance", __name__)


def _paged(records):
    limit, offset = pagination()
    ordered = db.sorted_by_created(records)
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return [db.serialize(r) for r in page], limit, offset, total


# ---------------------------------------------------------------------------
# Interim changes
# ---------------------------------------------------------------------------
@bp.route("/pha/tenancies/<tid>/interim-changes", methods=["POST"])
def report_interim(tid):
    uid, role = authenticate()
    authorize(role, {"Applicant"})
    tenancy = get_or_404(db.tenancies, tid, "ERR_TENANCY_NOT_FOUND")
    require_ownership(role, uid, owner_applicant_id("tenancy", tenancy))
    if tenancy["status"] != "ACTIVE":
        raise ApiError("ERR_TENANCY_NOT_ACTIVE", "tenancy is not ACTIVE")
    body = json_body()
    change_type = need_enum(body, "change_type", {"INCOME_DECREASE", "INCOME_INCREASE", "COMPOSITION"})
    effective_date = need_dt(body, "effective_date")
    change = db.create(
        db.interim_changes,
        tenancy_id=tenancy["id"],
        change_type=change_type,
        status="REPORTED",
        reported_at=db.now(),
        effective_date=effective_date,
    )
    return ok(db.serialize(change), 201)


@bp.route("/pha/tenancies/<tid>/interim-changes", methods=["GET"])
def list_interim(tid):
    uid, role = authenticate()
    authorize(role, {"IntakeClerk", "HousingSpecialist", "PropertyManager", "Applicant"})
    tenancy = get_or_404(db.tenancies, tid, "ERR_TENANCY_NOT_FOUND")
    require_ownership(role, uid, owner_applicant_id("tenancy", tenancy))
    records = [c for c in db.interim_changes.values() if c["tenancy_id"] == tid]
    items, limit, offset, total = _paged(records)
    return ok_list(items, limit, offset, total)


@bp.route("/pha/interim-changes/<iid>/process", methods=["POST"])
def process_interim(iid):
    uid, role = authenticate()
    authorize(role, {"HousingSpecialist"})
    change = get_or_404(db.interim_changes, iid, "ERR_INTERIM_CHANGE_NOT_FOUND")
    if change["status"] != "REPORTED":
        raise ApiError("ERR_INVALID_STATE", "interim change is not REPORTED")
    body = json_body()
    decision = need_enum(body, "decision", {"PROCESS", "DENY"})
    if decision == "DENY":
        db.touch(change, status="DENIED")
        return ok(db.serialize(change))
    tenancy = db.tenancies[change["tenancy_id"]]
    if tenancy["status"] != "ACTIVE":
        raise ApiError("ERR_TENANCY_NOT_ACTIVE", "tenancy is not ACTIVE")
    cert = db.create(
        db.certifications,
        tenancy_id=tenancy["id"],
        source_interim_change_id=change["id"],
        cert_type="INTERIM",
        status="DRAFT",
        hud_status="NOT_SUBMITTED",
        effective_date=change["effective_date"],
        childcare_expenses_annual_cents=0,
        medical_expenses_annual_cents=0,
        annual_gross_income_cents=0,
        annual_adjusted_income_cents=0,
        ttp_cents=0,
    )
    domain.finalize_certification(cert)
    db.touch(change, status="PROCESSED")
    return ok(db.serialize(change))


# ---------------------------------------------------------------------------
# Grievances / eviction
# ---------------------------------------------------------------------------
@bp.route("/pha/tenancies/<tid>/grievances", methods=["POST"])
def file_grievance(tid):
    uid, role = authenticate()
    authorize(role, {"Applicant", "PropertyManager"})
    tenancy = get_or_404(db.tenancies, tid, "ERR_TENANCY_NOT_FOUND")
    require_ownership(role, uid, owner_applicant_id("tenancy", tenancy))
    if tenancy["status"] != "ACTIVE":
        raise ApiError("ERR_TENANCY_NOT_ACTIVE", "tenancy is not ACTIVE")
    body = json_body()
    grievance_type = need_enum(body, "grievance_type", {"GRIEVANCE", "EVICTION"})
    reason = need_str(body, "reason", allow_empty=True)
    grievance = db.create(
        db.grievances,
        tenancy_id=tenancy["id"],
        grievance_type=grievance_type,
        status="FILED",
        reason=reason,
        filed_at=db.now(),
    )
    return ok(db.serialize(grievance), 201)


@bp.route("/pha/tenancies/<tid>/grievances", methods=["GET"])
def list_grievances(tid):
    uid, role = authenticate()
    authorize(role, {"IntakeClerk", "HousingSpecialist", "PropertyManager", "Applicant"})
    tenancy = get_or_404(db.tenancies, tid, "ERR_TENANCY_NOT_FOUND")
    require_ownership(role, uid, owner_applicant_id("tenancy", tenancy))
    records = [g for g in db.grievances.values() if g["tenancy_id"] == tid]
    items, limit, offset, total = _paged(records)
    return ok_list(items, limit, offset, total)


@bp.route("/pha/grievances/<gid>/decide", methods=["POST"])
def decide_grievance(gid):
    uid, role = authenticate()
    authorize(role, {"PropertyManager"})
    grievance = get_or_404(db.grievances, gid, "ERR_GRIEVANCE_NOT_FOUND")
    if grievance["status"] != "FILED":
        raise ApiError("ERR_INVALID_STATE", "grievance is not FILED")
    body = json_body()
    outcome = need_enum(body, "outcome", {"SUSTAINED", "OVERRULED"})
    db.touch(grievance, status=outcome)
    if outcome == "OVERRULED" and grievance["grievance_type"] == "EVICTION":
        tenancy = db.tenancies.get(grievance["tenancy_id"])
        if tenancy and tenancy["status"] == "ACTIVE":
            domain.terminate_tenancy(tenancy)
    return ok(db.serialize(grievance))


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
@bp.route("/pha/_clock/set_current_utc", methods=["POST"])
def set_clock():
    uid, role = authenticate()
    authorize(role, {"IntakeClerk", "HousingSpecialist", "PropertyManager"})
    body = json_body()
    instant = need_dt(body, "to_iso8601")
    db.set_clock(instant)
    from db import _fmt_dt
    return ok({"current_utc": _fmt_dt(instant)})
