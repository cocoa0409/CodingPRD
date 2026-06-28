"""WarrantyClaim routes."""
from datetime import timedelta

from flask import Blueprint, request

import db
import serialize
from errors import err
from response import object_response, array_response
from middleware import get_identity, require_roles
from validate import get_body, require_str, require_enum, parse_pagination, paginate
from services import calc, clock, domain

bp = Blueprint("warranty", __name__)

DEFECT_TYPES = {"HARDWARE", "FINISH", "FIT", "STRUCTURAL"}
ADJUSTMENT_DEFECTS = {"FIT", "FINISH"}
REPLACEMENT_DEFECTS = {"HARDWARE", "STRUCTURAL"}


@bp.post("/warranty-claims")
def file_claim():
    user_id, role = get_identity()
    require_roles(role, {"Customer"})
    body = get_body()
    project_id = require_str(body, "project_id")
    install_job_id = require_str(body, "install_job_id")
    defect_type = require_enum(body, "defect_type", DEFECT_TYPES)
    project = db.projects.get(project_id)
    if project is None:
        raise err("ERR_RESOURCE_NOT_FOUND")
    job = db.install_jobs.get(install_job_id)
    if job is None:
        raise err("ERR_RESOURCE_NOT_FOUND")
    domain.check_project_owner(project, user_id, role)
    if project["status"] != "COMPLETED":
        raise err("ERR_INVALID_STATE")

    # covered: filed within WARRANTY_DAYS of install completion AND defect covered.
    # install_done_at = job.updated_at at the moment completion_status became DONE.
    install_done_at = job["updated_at"]
    window_end = install_done_at + timedelta(days=calc.WARRANTY_DAYS)
    within = clock.now() <= window_end
    covered = within and (defect_type in calc.COVERED_DEFECTS)

    rec = db.stamp_new({
        "project_id": project_id,
        "install_job_id": install_job_id,
        "defect_type": defect_type,
        "status": "FILED",
        "covered": covered,
    })
    db.warranty_claims[rec["id"]] = rec
    return object_response(serialize.warranty_claim(rec), 201)


@bp.get("/warranty-claims/<wid>")
def get_claim(wid):
    _, role = get_identity()
    require_roles(role, {"Customer", "ManufacturingOps", "PlatformAdmin"})
    rec = db.warranty_claims.get(wid)
    if rec is None:
        raise err("ERR_RESOURCE_NOT_FOUND")
    return object_response(serialize.warranty_claim(rec))


@bp.get("/warranty-claims")
def list_claims():
    _, role = get_identity()
    require_roles(role, {"Customer", "ManufacturingOps", "PlatformAdmin"})
    limit, offset = parse_pagination()
    project_id = request.args.get("project_id")
    install_job_id = request.args.get("install_job_id")
    status = request.args.get("status")
    items = []
    for c in db.warranty_claims.values():
        if project_id is not None and c["project_id"] != project_id:
            continue
        if install_job_id is not None and c["install_job_id"] != install_job_id:
            continue
        if status is not None and c["status"] != status:
            continue
        items.append(c)
    page, total = paginate(items, limit, offset)
    return array_response([serialize.warranty_claim(c) for c in page],
                          limit, offset, total)


def _require_claim(wid):
    rec = db.warranty_claims.get(wid)
    if rec is None:
        raise err("ERR_RESOURCE_NOT_FOUND")
    return rec


@bp.post("/warranty-claims/<wid>/approve")
def approve_claim(wid):
    _, role = get_identity()
    require_roles(role, {"ManufacturingOps"})
    rec = _require_claim(wid)
    if rec["status"] != "FILED":
        raise err("ERR_INVALID_STATE")
    if not rec["covered"]:
        raise err("ERR_WARRANTY_NOT_COVERED")
    rec["status"] = "APPROVED"
    db.touch(rec)
    return object_response(serialize.warranty_claim(rec))


@bp.post("/warranty-claims/<wid>/reject")
def reject_claim(wid):
    _, role = get_identity()
    require_roles(role, {"ManufacturingOps"})
    rec = _require_claim(wid)
    if rec["status"] != "FILED":
        raise err("ERR_INVALID_STATE")
    rec["status"] = "REJECTED"
    db.touch(rec)
    return object_response(serialize.warranty_claim(rec))


@bp.post("/warranty-claims/<wid>/schedule-adjustment")
def schedule_adjustment(wid):
    _, role = get_identity()
    require_roles(role, {"ManufacturingOps"})
    rec = _require_claim(wid)
    if rec["status"] != "APPROVED":
        raise err("ERR_INVALID_STATE")
    if rec["defect_type"] not in ADJUSTMENT_DEFECTS:
        raise err("ERR_WARRANTY_BRANCH_MISMATCH")
    rec["status"] = "ADJUSTMENT_SCHEDULED"
    db.touch(rec)
    return object_response(serialize.warranty_claim(rec))


@bp.post("/warranty-claims/<wid>/order-replacement")
def order_replacement(wid):
    _, role = get_identity()
    require_roles(role, {"ManufacturingOps"})
    rec = _require_claim(wid)
    if rec["status"] != "APPROVED":
        raise err("ERR_INVALID_STATE")
    if rec["defect_type"] not in REPLACEMENT_DEFECTS:
        raise err("ERR_WARRANTY_BRANCH_MISMATCH")
    rec["status"] = "REPLACEMENT_ORDERED"
    db.touch(rec)
    return object_response(serialize.warranty_claim(rec))


@bp.post("/warranty-claims/<wid>/resolve")
def resolve_claim(wid):
    _, role = get_identity()
    require_roles(role, {"ManufacturingOps"})
    rec = _require_claim(wid)
    if rec["status"] not in {"ADJUSTMENT_SCHEDULED", "REPLACEMENT_ORDERED"}:
        raise err("ERR_INVALID_STATE")
    rec["status"] = "RESOLVED"
    db.touch(rec)
    return object_response(serialize.warranty_claim(rec))
