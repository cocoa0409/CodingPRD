"""Supervision-condition endpoints (PRD §3.3)."""
from flask import Blueprint, request

import db
from calculations import LEVEL_ORDER, level_ge
from errors import (
    ApiError,
    ERR_INVALID_STATE,
    ERR_LEVEL_TOO_LOW_FOR_CONDITION,
    ERR_SUPERVISEE_CLOSED,
)
from middleware import require_roles
from response import object_response, array_response
from serialize import public, public_list
from services.common import (
    TERMINAL_SUPERVISEE_STATES,
    apply_page,
    check_enum,
    get_body,
    get_child_or_404,
    get_supervisee_or_404,
    paginate,
    require_fields,
    sorted_by_created,
)

bp = Blueprint("conditions", __name__)

CONDITION_TYPES = {
    "DRUG_TESTING",
    "CURFEW",
    "NO_CONTACT",
    "EMPLOYMENT",
    "TREATMENT",
    "ELECTRONIC_MONITORING",
    "TRAVEL_RESTRICTION",
}
LEVELS = set(LEVEL_ORDER.keys())


@bp.post("/supervisees/<sid>/conditions")
@require_roles("Officer")
def create(sid):
    s = get_supervisee_or_404(sid)
    if s["status"] in TERMINAL_SUPERVISEE_STATES:
        raise ApiError(*ERR_SUPERVISEE_CLOSED, "Supervisee case is closed.")
    body = get_body()
    require_fields(body, ["condition_type"])
    check_enum(body["condition_type"], CONDITION_TYPES, "condition_type")

    minimum_level = body.get("minimum_level_required", "MINIMUM")
    if minimum_level is None:
        minimum_level = "MINIMUM"
    check_enum(minimum_level, LEVELS, "minimum_level_required")

    description = body.get("description")

    rec = db.common_create_fields(versioned=True)
    rec.update(
        {
            "supervisee_id": s["id"],
            "condition_type": body["condition_type"],
            "minimum_level_required": minimum_level,
            "status": "PROPOSED",
            "description": description,
        }
    )
    db.conditions[rec["id"]] = rec
    return object_response(public(rec), 201)


@bp.get("/supervisees/<sid>/conditions")
@require_roles("Officer", "SupervisingJudge", "CompactAdministrator")
def list_conditions(sid):
    get_supervisee_or_404(sid)
    limit, offset = paginate(request.args)
    records = [c for c in db.conditions.values() if c.get("supervisee_id") == sid]
    status = request.args.get("status")
    if status is not None:
        records = [r for r in records if r["status"] == status]
    records = sorted_by_created(records)
    page, total = apply_page(records, limit, offset)
    return array_response(public_list(page), limit, offset, total)


@bp.get("/supervisees/<sid>/conditions/<cid>")
@require_roles("Officer", "SupervisingJudge", "CompactAdministrator")
def get_condition(sid, cid):
    get_supervisee_or_404(sid)
    rec = get_child_or_404(db.conditions, cid, sid, label="Condition")
    return object_response(public(rec), 200)


@bp.post("/supervisees/<sid>/conditions/<cid>/activate")
@require_roles("Officer")
def activate(sid, cid):
    s = get_supervisee_or_404(sid)
    c = get_child_or_404(db.conditions, cid, sid, label="Condition")
    # State check first (PROPOSED or SUSPENDED).
    if c["status"] not in ("PROPOSED", "SUSPENDED"):
        raise ApiError(*ERR_INVALID_STATE, "Condition is not PROPOSED or SUSPENDED.")
    if s["status"] != "ACTIVE":
        raise ApiError(*ERR_INVALID_STATE, "Supervisee is not ACTIVE.")
    # Posture gate (ERR_LEVEL_TOO_LOW_FOR_CONDITION, 409).
    if not level_ge(s["supervision_level"], c["minimum_level_required"]):
        raise ApiError(
            *ERR_LEVEL_TOO_LOW_FOR_CONDITION,
            "Supervision level is below the condition's minimum_level_required.",
        )
    c["status"] = "ACTIVE"
    db.touch(c)
    return object_response(public(c), 200)


@bp.post("/supervisees/<sid>/conditions/<cid>/satisfy")
@require_roles("Officer")
def satisfy(sid, cid):
    get_supervisee_or_404(sid)
    c = get_child_or_404(db.conditions, cid, sid, label="Condition")
    if c["status"] != "ACTIVE":
        raise ApiError(*ERR_INVALID_STATE, "Condition is not ACTIVE.")
    c["status"] = "SATISFIED"
    db.touch(c)
    return object_response(public(c), 200)


@bp.post("/supervisees/<sid>/conditions/<cid>/waive")
@require_roles("SupervisingJudge")
def waive(sid, cid):
    get_supervisee_or_404(sid)
    c = get_child_or_404(db.conditions, cid, sid, label="Condition")
    if c["status"] != "PROPOSED":
        raise ApiError(*ERR_INVALID_STATE, "Condition is not PROPOSED.")
    c["status"] = "WAIVED"
    db.touch(c)
    return object_response(public(c), 200)
