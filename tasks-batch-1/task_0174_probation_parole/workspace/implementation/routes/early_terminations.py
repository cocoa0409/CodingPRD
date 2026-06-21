"""Early-termination endpoints (PRD §3.9)."""
from flask import Blueprint, request

import db
from calculations import early_termination_eligibility
from errors import (
    ApiError,
    ERR_INVALID_STATE,
    ERR_NOT_ELIGIBLE_FOR_TERMINATION,
)
from middleware import require_roles
from response import object_response, array_response
from serialize import public, public_list
from services.supervisee import cascade_conditions
from services.common import (
    apply_page,
    get_body,
    get_child_or_404,
    get_supervisee_or_404,
    paginate,
    recompute_balances,
    require_datetime,
    require_fields,
    sorted_by_created,
)
from timeutil import parse_iso

bp = Blueprint("early_terminations", __name__)


def _open_violation_count(sid):
    return sum(
        1
        for v in db.violations.values()
        if v.get("supervisee_id") == sid and v["status"] in ("FILED", "APPEALED")
    )


@bp.post("/supervisees/<sid>/early-terminations")
@require_roles("Officer")
def create(sid):
    s = get_supervisee_or_404(sid)
    body = get_body()
    require_fields(body, ["requested_on"])
    require_datetime(body["requested_on"], "requested_on")

    recompute_balances(s)
    requested_dt = parse_iso(body["requested_on"])
    open_v = _open_violation_count(sid)
    months_served, eligibility = early_termination_eligibility(s, requested_dt, open_v)

    rec = db.common_create_fields(versioned=True)
    rec.update(
        {
            "supervisee_id": s["id"],
            "requested_on": body["requested_on"],
            "months_served": months_served,
            "eligibility": eligibility,
            "status": "SUBMITTED",
        }
    )
    db.early_terminations[rec["id"]] = rec
    return object_response(public(rec), 201)


@bp.get("/supervisees/<sid>/early-terminations")
@require_roles("Officer", "SupervisingJudge", "CompactAdministrator")
def list_petitions(sid):
    get_supervisee_or_404(sid)
    limit, offset = paginate(request.args)
    records = [e for e in db.early_terminations.values() if e.get("supervisee_id") == sid]
    status = request.args.get("status")
    if status is not None:
        records = [r for r in records if r["status"] == status]
    records = sorted_by_created(records)
    page, total = apply_page(records, limit, offset)
    return array_response(public_list(page), limit, offset, total)


@bp.get("/supervisees/<sid>/early-terminations/<eid>")
@require_roles("Officer", "SupervisingJudge", "CompactAdministrator")
def get_petition(sid, eid):
    get_supervisee_or_404(sid)
    rec = get_child_or_404(db.early_terminations, eid, sid, label="Early-termination petition")
    return object_response(public(rec), 200)


@bp.post("/supervisees/<sid>/early-terminations/<eid>/grant")
@require_roles("SupervisingJudge")
def grant(sid, eid):
    s = get_supervisee_or_404(sid)
    e = get_child_or_404(db.early_terminations, eid, sid, label="Early-termination petition")
    if e["status"] != "SUBMITTED":
        raise ApiError(*ERR_INVALID_STATE, "Petition is not SUBMITTED.")
    if not e["eligibility"]["eligible"]:
        raise ApiError(*ERR_NOT_ELIGIBLE_FOR_TERMINATION, "Petition is not eligible.")
    if s["status"] != "ACTIVE":
        raise ApiError(*ERR_INVALID_STATE, "Supervisee is not ACTIVE.")
    e["status"] = "GRANTED"
    s["status"] = "TERMINATED_EARLY"
    cascade_conditions(s, ("ACTIVE",), "SATISFIED")
    db.touch(e)
    db.touch(s)
    return object_response(public(e), 200)


@bp.post("/supervisees/<sid>/early-terminations/<eid>/deny")
@require_roles("SupervisingJudge")
def deny(sid, eid):
    get_supervisee_or_404(sid)
    e = get_child_or_404(db.early_terminations, eid, sid, label="Early-termination petition")
    if e["status"] != "SUBMITTED":
        raise ApiError(*ERR_INVALID_STATE, "Petition is not SUBMITTED.")
    e["status"] = "DENIED"
    db.touch(e)
    return object_response(public(e), 200)
