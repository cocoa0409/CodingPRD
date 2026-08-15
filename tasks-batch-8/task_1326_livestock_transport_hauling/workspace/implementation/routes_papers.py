"""Health papers, brand inspections, verify-paperwork (PRD 3.4)."""
from datetime import timedelta

from flask import Blueprint, g

import db
import services as svc
from errors import (
    raise_err, ERR_LOAD_NOT_FOUND, ERR_HEALTH_PAPER_NOT_FOUND,
    ERR_BRAND_INSPECTION_NOT_FOUND, ERR_INVALID_TIME_RANGE,
    ERR_PAPERWORK_NOT_PENDING, ERR_LOAD_NOT_PLANNED, ERR_SOD_VIOLATION,
    ERR_PAPER_MISMATCH, ERR_PAPER_EXPIRED, ERR_BRAND_INSPECTION_STALE,
    ERR_PAPERWORK_INCOMPLETE,
)
from middleware import require_role
from response import success
from util import get_body, v_str, v_int, v_enum, v_dt, paginate

bp = Blueprint("papers", __name__)

SPECIES = {"CATTLE", "SWINE", "SHEEP", "HORSES"}
BRAND_FRESH_HOURS = 96
PAPER_CHECK_STATES = {"PLANNED", "PAPERWORK_VERIFIED"}


def load_or_404(load_id):
    ld = db.store["loads"].get(load_id)
    if ld is None:
        raise_err(ERR_LOAD_NOT_FOUND)
    return ld


# ---------------------------------------------------------------- health papers
@bp.post("/haul/loads/<lid>/health-papers")
def create_health_paper(lid):
    require_role("ComplianceOfficer")
    body = get_body()
    cert_number = v_str(body, "cert_number")
    species = v_enum(body, "species", SPECIES)
    head_listed = v_int(body, "head_count_listed", min_value=1)
    issued_at = v_dt(body, "issued_at")
    expires_at = v_dt(body, "expires_at")
    if expires_at <= issued_at:
        raise_err(ERR_INVALID_TIME_RANGE, "expires_at must be after issued_at")
    ld = load_or_404(lid)
    rec = svc.new_common()
    rec.update({
        "load_id": lid, "cert_number": cert_number, "species": species,
        "head_count_listed": head_listed, "issued_at": issued_at,
        "expires_at": expires_at, "status": "PENDING",
        "created_by_user_id": g.user_id, "verified_by_user_id": None,
    })
    db.store["health_papers"][rec["id"]] = rec
    return success(svc.health_paper_json(rec), status=201)


@bp.get("/haul/loads/<lid>/health-papers")
def list_health_papers(lid):
    load_or_404(lid)
    items = sorted(
        (p for p in db.store["health_papers"].values() if p["load_id"] == lid),
        key=lambda p: p["seq"])
    page, meta = paginate([svc.health_paper_json(p) for p in items])
    return success(page, response_type="array", pagination=meta)


@bp.post("/haul/health-papers/<pid>/verify")
def verify_health_paper(pid):
    require_role("ComplianceOfficer")
    p = db.store["health_papers"].get(pid)
    if p is None:
        raise_err(ERR_HEALTH_PAPER_NOT_FOUND)
    if p["status"] != "PENDING":
        raise_err(ERR_PAPERWORK_NOT_PENDING, "paper is not PENDING")
    ld = db.store["loads"].get(p["load_id"])
    if ld["status"] not in PAPER_CHECK_STATES:
        raise_err(ERR_LOAD_NOT_PLANNED, "load must be PLANNED or PAPERWORK_VERIFIED")
    if g.user_id == p["created_by_user_id"]:
        raise_err(ERR_SOD_VIOLATION, "verifier must differ from uploader")
    if p["species"] != ld["species"] or p["head_count_listed"] != ld["declared_head_count"]:
        raise_err(ERR_PAPER_MISMATCH, "paper species/head count does not match the load")
    if p["expires_at"] <= ld["planned_departure_at"]:
        raise_err(ERR_PAPER_EXPIRED, "paper expires at or before planned departure")
    p["status"] = "VERIFIED"
    p["verified_by_user_id"] = g.user_id
    svc.touch(p)
    return success(svc.health_paper_json(p))


@bp.post("/haul/health-papers/<pid>/reject")
def reject_health_paper(pid):
    require_role("ComplianceOfficer")
    p = db.store["health_papers"].get(pid)
    if p is None:
        raise_err(ERR_HEALTH_PAPER_NOT_FOUND)
    if p["status"] != "PENDING":
        raise_err(ERR_PAPERWORK_NOT_PENDING, "paper is not PENDING")
    p["status"] = "REJECTED"
    svc.touch(p)
    return success(svc.health_paper_json(p))


# ---------------------------------------------------------------- brand inspections
@bp.post("/haul/loads/<lid>/brand-inspections")
def create_brand_inspection(lid):
    require_role("ComplianceOfficer")
    body = get_body()
    inspection_no = v_str(body, "inspection_no")
    inspected_at = v_dt(body, "inspected_at")
    brand_owner = v_str(body, "brand_owner")
    head_inspected = v_int(body, "head_count_inspected", min_value=1)
    ld = load_or_404(lid)
    rec = svc.new_common()
    rec.update({
        "load_id": lid, "inspection_no": inspection_no,
        "inspected_at": inspected_at, "brand_owner": brand_owner,
        "head_count_inspected": head_inspected, "status": "PENDING",
        "created_by_user_id": g.user_id, "verified_by_user_id": None,
    })
    db.store["brand_inspections"][rec["id"]] = rec
    return success(svc.brand_inspection_json(rec), status=201)


@bp.get("/haul/loads/<lid>/brand-inspections")
def list_brand_inspections(lid):
    load_or_404(lid)
    items = sorted(
        (b for b in db.store["brand_inspections"].values() if b["load_id"] == lid),
        key=lambda b: b["seq"])
    page, meta = paginate([svc.brand_inspection_json(b) for b in items])
    return success(page, response_type="array", pagination=meta)


@bp.post("/haul/brand-inspections/<bid>/verify")
def verify_brand_inspection(bid):
    require_role("ComplianceOfficer")
    b = db.store["brand_inspections"].get(bid)
    if b is None:
        raise_err(ERR_BRAND_INSPECTION_NOT_FOUND)
    if b["status"] != "PENDING":
        raise_err(ERR_PAPERWORK_NOT_PENDING, "brand inspection is not PENDING")
    ld = db.store["loads"].get(b["load_id"])
    if ld["status"] not in PAPER_CHECK_STATES:
        raise_err(ERR_LOAD_NOT_PLANNED, "load must be PLANNED or PAPERWORK_VERIFIED")
    if g.user_id == b["created_by_user_id"]:
        raise_err(ERR_SOD_VIOLATION, "verifier must differ from uploader")
    if b["head_count_inspected"] != ld["declared_head_count"]:
        raise_err(ERR_PAPER_MISMATCH, "inspected head count does not match the load")
    now = db.now()
    if (b["inspected_at"] > now
            or ld["planned_departure_at"] - b["inspected_at"]
            > timedelta(hours=BRAND_FRESH_HOURS)):
        raise_err(ERR_BRAND_INSPECTION_STALE,
                  "inspection is in the future or more than 96h before departure")
    b["status"] = "VERIFIED"
    b["verified_by_user_id"] = g.user_id
    svc.touch(b)
    return success(svc.brand_inspection_json(b))


@bp.post("/haul/brand-inspections/<bid>/reject")
def reject_brand_inspection(bid):
    require_role("ComplianceOfficer")
    b = db.store["brand_inspections"].get(bid)
    if b is None:
        raise_err(ERR_BRAND_INSPECTION_NOT_FOUND)
    if b["status"] != "PENDING":
        raise_err(ERR_PAPERWORK_NOT_PENDING, "brand inspection is not PENDING")
    b["status"] = "REJECTED"
    svc.touch(b)
    return success(svc.brand_inspection_json(b))


# ---------------------------------------------------------------- verify paperwork
@bp.post("/haul/loads/<lid>/verify-paperwork")
def verify_paperwork(lid):
    require_role("ComplianceOfficer")
    ld = load_or_404(lid)
    if ld["status"] != "PLANNED":
        raise_err(ERR_LOAD_NOT_PLANNED, "verify-paperwork requires PLANNED")
    has_paper = any(
        p["load_id"] == lid and p["status"] == "VERIFIED"
        and p["expires_at"] > ld["planned_departure_at"]
        for p in db.store["health_papers"].values())
    has_brand = any(
        b["load_id"] == lid and b["status"] == "VERIFIED"
        for b in db.store["brand_inspections"].values())
    if not (has_paper and has_brand):
        raise_err(ERR_PAPERWORK_INCOMPLETE,
                  "a VERIFIED health paper and brand inspection are required")
    ld["status"] = "PAPERWORK_VERIFIED"
    svc.touch(ld)
    return success(svc.load_json(ld))
