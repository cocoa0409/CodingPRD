"""Risk-assessment endpoints (PRD §3.2)."""
from flask import Blueprint, request

import db
from middleware import require_roles
from response import object_response, array_response
from serialize import public, public_list
from services import risk as svc
from services.common import (
    apply_page,
    get_body,
    get_child_or_404,
    get_supervisee_or_404,
    paginate,
    require_fields,
    sorted_by_created,
)

bp = Blueprint("risk_assessments", __name__)

INSTRUMENTS = {"LSI_R"}


@bp.post("/supervisees/<sid>/risk-assessments")
@require_roles("Officer")
def create(sid):
    s = get_supervisee_or_404(sid)
    body = get_body()
    require_fields(body, ["domain_scores"])

    instrument = body.get("instrument", "LSI_R")
    if instrument is None:
        instrument = "LSI_R"
    if instrument not in INSTRUMENTS:
        from errors import ApiError

        raise ApiError("ERR_INVALID_REQUEST", 400, "instrument must be LSI_R.")

    # ERR_INCOMPLETE_LSIR_DOMAINS validation (422).
    svc.validate_domain_scores(body["domain_scores"])

    override_level = body.get("override_level")
    override_reason = body.get("override_reason")
    total, derived = svc.compute_preview(body["domain_scores"], override_level, override_reason)

    rec = db.common_create_fields(versioned=True)
    rec.update(
        {
            "supervisee_id": s["id"],
            "instrument": instrument,
            "domain_scores": body["domain_scores"],
            "total_score": total,
            "derived_level": derived,
            "assessment_status": "DRAFT",
            "override_level": override_level,
            "override_reason": override_reason,
        }
    )
    db.risk_assessments[rec["id"]] = rec
    return object_response(public(rec), 201)


@bp.get("/supervisees/<sid>/risk-assessments")
@require_roles("Officer", "SupervisingJudge", "CompactAdministrator")
def list_ra(sid):
    get_supervisee_or_404(sid)
    limit, offset = paginate(request.args)
    records = [r for r in db.risk_assessments.values() if r.get("supervisee_id") == sid]
    status = request.args.get("assessment_status")
    if status is not None:
        records = [r for r in records if r["assessment_status"] == status]
    records = sorted_by_created(records)
    page, total = apply_page(records, limit, offset)
    return array_response(public_list(page), limit, offset, total)


@bp.get("/supervisees/<sid>/risk-assessments/<rid>")
@require_roles("Officer", "SupervisingJudge", "CompactAdministrator")
def get_ra(sid, rid):
    get_supervisee_or_404(sid)
    rec = get_child_or_404(db.risk_assessments, rid, sid, label="Risk assessment")
    return object_response(public(rec), 200)


@bp.post("/supervisees/<sid>/risk-assessments/<rid>/adopt")
@require_roles("Officer")
def adopt(sid, rid):
    s = get_supervisee_or_404(sid)
    rec = get_child_or_404(db.risk_assessments, rid, sid, label="Risk assessment")
    svc.adopt(s, rec)
    return object_response(public(rec), 200)
