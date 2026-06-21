"""Violation endpoints (PRD §3.5)."""
from flask import Blueprint, g, request

import db
from errors import (
    ApiError,
    ERR_REFERENCE_NOT_FOUND,
    ERR_SUPERVISEE_CLOSED,
)
from middleware import require_roles
from response import object_response, array_response
from serialize import public, public_list
from services import violation as svc
from services.common import (
    TERMINAL_SUPERVISEE_STATES,
    apply_page,
    check_enum,
    get_body,
    get_child_or_404,
    get_supervisee_or_404,
    paginate,
    require_fields,
    require_str,
    sorted_by_created,
)

bp = Blueprint("violations", __name__)

VIOLATION_CLASSES = {"TECHNICAL", "MISDEMEANOR", "FELONY", "ABSCOND"}


@bp.post("/supervisees/<sid>/violations")
@require_roles("Officer")
def create(sid):
    s = get_supervisee_or_404(sid)
    body = get_body()
    require_fields(body, ["violation_class", "filed_by_officer_id"])
    check_enum(body["violation_class"], VIOLATION_CLASSES, "violation_class")
    require_str(body["filed_by_officer_id"], "filed_by_officer_id")

    source_drug_test_id = body.get("source_drug_test_id")

    # Body FK existence (ERR_REFERENCE_NOT_FOUND, 422).
    if body["filed_by_officer_id"] not in db.officers:
        raise ApiError(*ERR_REFERENCE_NOT_FOUND, "filed_by_officer_id not found.")
    if source_drug_test_id is not None and source_drug_test_id not in db.drug_tests:
        raise ApiError(*ERR_REFERENCE_NOT_FOUND, "source_drug_test_id not found.")

    # Closed-supervisee guard (PRD §3.11).
    if s["status"] in TERMINAL_SUPERVISEE_STATES:
        raise ApiError(*ERR_SUPERVISEE_CLOSED, "Supervisee case is closed.")

    rec = db.common_create_fields(versioned=True)
    rec.update(
        {
            "supervisee_id": s["id"],
            "filed_by_officer_id": body["filed_by_officer_id"],
            "violation_class": body["violation_class"],
            "source_drug_test_id": source_drug_test_id,
            "points": 0,
            "status": "FILED",
            "sustained_by_actor_id": None,
        }
    )
    db.violations[rec["id"]] = rec
    return object_response(public(rec), 201)


@bp.get("/supervisees/<sid>/violations")
@require_roles("Officer", "SupervisingJudge", "CompactAdministrator")
def list_violations(sid):
    get_supervisee_or_404(sid)
    limit, offset = paginate(request.args)
    records = [v for v in db.violations.values() if v.get("supervisee_id") == sid]
    status = request.args.get("status")
    if status is not None:
        records = [r for r in records if r["status"] == status]
    filed_by = request.args.get("filed_by_officer_id")
    if filed_by is not None:
        records = [r for r in records if r["filed_by_officer_id"] == filed_by]
    sdt = request.args.get("source_drug_test_id")
    if sdt is not None:
        records = [r for r in records if r.get("source_drug_test_id") == sdt]
    records = sorted_by_created(records)
    page, total = apply_page(records, limit, offset)
    return array_response(public_list(page), limit, offset, total)


@bp.get("/supervisees/<sid>/violations/<vid>")
@require_roles("Officer", "SupervisingJudge", "CompactAdministrator")
def get_violation(sid, vid):
    get_supervisee_or_404(sid)
    rec = get_child_or_404(db.violations, vid, sid, label="Violation")
    return object_response(public(rec), 200)


@bp.post("/supervisees/<sid>/violations/<vid>/sustain")
@require_roles("SupervisingJudge")
def sustain(sid, vid):
    s = get_supervisee_or_404(sid)
    v = get_child_or_404(db.violations, vid, sid, label="Violation")
    svc.sustain(s, v, g.user_id)
    return object_response(public(v), 200)


@bp.post("/supervisees/<sid>/violations/<vid>/dismiss")
@require_roles("SupervisingJudge")
def dismiss(sid, vid):
    get_supervisee_or_404(sid)
    v = get_child_or_404(db.violations, vid, sid, label="Violation")
    svc.dismiss(v)
    return object_response(public(v), 200)


@bp.post("/supervisees/<sid>/violations/<vid>/appeal")
@require_roles("Officer")
def appeal(sid, vid):
    s = get_supervisee_or_404(sid)
    v = get_child_or_404(db.violations, vid, sid, label="Violation")
    svc.appeal(s, v)
    return object_response(public(v), 200)
