"""Tenancies and certifications (create with OCC, finalize, HUD axis)."""
from flask import Blueprint, request

import db
import domain
from core import (
    ApiError, authenticate, authorize, require_ownership, get_or_404,
    owner_applicant_id, json_body, need_enum, need_dt, need_int,
    opt_int_nonneg, pagination, ok, ok_list, _is_int,
)

bp = Blueprint("tenancy_certs", __name__)


def _paged(records):
    limit, offset = pagination()
    ordered = db.sorted_by_created(records)
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return [db.serialize(r) for r in page], limit, offset, total


# ---------------------------------------------------------------------------
# Tenancies
# ---------------------------------------------------------------------------
@bp.route("/pha/tenancies/<tid>", methods=["GET"])
def get_tenancy(tid):
    uid, role = authenticate()
    authorize(role, {"IntakeClerk", "HousingSpecialist", "PropertyManager", "Applicant"})
    tenancy = get_or_404(db.tenancies, tid, "ERR_TENANCY_NOT_FOUND")
    require_ownership(role, uid, owner_applicant_id("tenancy", tenancy))
    return ok(db.serialize(tenancy))


@bp.route("/pha/tenancies", methods=["GET"])
def list_tenancies():
    uid, role = authenticate()
    authorize(role, {"IntakeClerk", "HousingSpecialist", "PropertyManager", "Applicant"})
    applicant_id = request.args.get("applicant_id")
    unit_id = request.args.get("unit_id")
    records = list(db.tenancies.values())
    if applicant_id:
        records = [t for t in records if t["applicant_id"] == applicant_id]
    if unit_id:
        records = [t for t in records if t["unit_id"] == unit_id]
    items, limit, offset, total = _paged(records)
    return ok_list(items, limit, offset, total)


# ---------------------------------------------------------------------------
# Certifications
# ---------------------------------------------------------------------------
@bp.route("/pha/tenancies/<tid>/certifications", methods=["POST"])
def create_certification(tid):
    uid, role = authenticate()
    authorize(role, {"HousingSpecialist"})
    tenancy = get_or_404(db.tenancies, tid, "ERR_TENANCY_NOT_FOUND")
    body = json_body()
    # OCC (priority 4) — ahead of body field validation.
    expected = body.get("expected_tenancy_version")
    if expected is None or not _is_int(expected):
        raise ApiError("ERR_VALIDATION", "expected_tenancy_version is required")
    if expected != tenancy["version"]:
        raise ApiError("ERR_STALE_VERSION", "tenancy version has advanced")
    cert_type = need_enum(body, "cert_type", {"INITIAL", "ANNUAL"})
    effective_date = need_dt(body, "effective_date")
    childcare = opt_int_nonneg(body, "childcare_expenses_annual_cents", 0)
    medical = opt_int_nonneg(body, "medical_expenses_annual_cents", 0)
    cert = db.create(
        db.certifications,
        tenancy_id=tenancy["id"],
        source_interim_change_id=None,
        cert_type=cert_type,
        status="DRAFT",
        hud_status="NOT_SUBMITTED",
        effective_date=effective_date,
        childcare_expenses_annual_cents=childcare,
        medical_expenses_annual_cents=medical,
        annual_gross_income_cents=0,
        annual_adjusted_income_cents=0,
        ttp_cents=0,
    )
    db.bump(tenancy)  # creating a cert increments the parent tenancy's version
    return ok(db.serialize(cert), 201)


@bp.route("/pha/certifications/<cid>", methods=["GET"])
def get_certification(cid):
    uid, role = authenticate()
    authorize(role, {"IntakeClerk", "HousingSpecialist", "PropertyManager", "Applicant"})
    cert = get_or_404(db.certifications, cid, "ERR_CERTIFICATION_NOT_FOUND")
    require_ownership(role, uid, owner_applicant_id("certification", cert))
    return ok(db.serialize(cert))


@bp.route("/pha/certifications", methods=["GET"])
def list_certifications():
    uid, role = authenticate()
    authorize(role, {"IntakeClerk", "HousingSpecialist", "PropertyManager", "Applicant"})
    tenancy_id = request.args.get("tenancy_id")
    source = request.args.get("source_interim_change_id")
    records = list(db.certifications.values())
    if tenancy_id:
        records = [c for c in records if c["tenancy_id"] == tenancy_id]
    if source:
        records = [c for c in records if c["source_interim_change_id"] == source]
    items, limit, offset, total = _paged(records)
    return ok_list(items, limit, offset, total)


@bp.route("/pha/certifications/<cid>/finalize", methods=["POST"])
def finalize(cid):
    uid, role = authenticate()
    authorize(role, {"HousingSpecialist"})
    cert = get_or_404(db.certifications, cid, "ERR_CERTIFICATION_NOT_FOUND")
    if cert["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "certification is not DRAFT")
    tenancy = db.tenancies[cert["tenancy_id"]]
    if tenancy["status"] != "ACTIVE":
        raise ApiError("ERR_TENANCY_NOT_ACTIVE", "tenancy is not ACTIVE")
    prior = domain.current_effective_cert(tenancy["id"])
    if prior is not None and cert["effective_date"] <= prior["effective_date"]:
        raise ApiError("ERR_CERT_PERIOD_OVERLAP", "effective_date must be strictly later")
    if cert["cert_type"] == "INITIAL":
        gross = domain.compute_gross(tenancy["applicant_id"], "INITIAL")
        unit = db.units[tenancy["unit_id"]]
        if gross > unit["income_limit_cents"]:
            raise ApiError("ERR_OVER_INCOME", "anticipated gross exceeds unit income limit")
    domain.finalize_certification(cert)
    return ok(db.serialize(cert))


@bp.route("/pha/certifications/<cid>/hud-submit", methods=["POST"])
def hud_submit(cid):
    uid, role = authenticate()
    authorize(role, {"HousingSpecialist"})
    cert = get_or_404(db.certifications, cid, "ERR_CERTIFICATION_NOT_FOUND")
    if cert["status"] != "EFFECTIVE" or cert["hud_status"] not in ("NOT_SUBMITTED", "REJECTED"):
        raise ApiError("ERR_INVALID_STATE", "cert not EFFECTIVE or hud_status not submittable")
    db.touch(cert, hud_status="SUBMITTED")
    return ok(db.serialize(cert))


@bp.route("/pha/certifications/<cid>/hud-result", methods=["POST"])
def hud_result(cid):
    uid, role = authenticate()
    authorize(role, {"HousingSpecialist"})
    cert = get_or_404(db.certifications, cid, "ERR_CERTIFICATION_NOT_FOUND")
    if cert["hud_status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", "hud_status is not SUBMITTED")
    body = json_body()
    result = need_enum(body, "result", {"ACCEPTED", "REJECTED"})
    db.touch(cert, hud_status=result)
    return ok(db.serialize(cert))
