"""Advancement: sign-off, revision loop, approval (PRD §3.5)."""
from datetime import datetime, timezone

from flask import Blueprint, request

from db import db
from errors import (
    err,
    ERR_INVALID_STATE,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_MEMBER_NOT_REGISTERED,
    ERR_REQUIREMENTS_INCOMPLETE,
    ERR_INVALID_REQUEST,
)
from middleware import authenticate, require_roles, BOTH_ROLES, REGISTRAR_ONLY, LEADER_ONLY
from response import object_response, array_response
from serializers import serialize_advancement
from util import new_id, iso_now, round_half_up_2dp
from routes import helpers as h

bp = Blueprint("advancements", __name__)

RANK_TARGETS = {"TENDERFOOT", "SECOND_CLASS", "FIRST_CLASS"}


def _recompute_completion(adv):
    adv["completion_pct"] = round_half_up_2dp(
        adv["requirements_signed"] / adv["requirements_total"] * 100
    )


@bp.post("/members/<member_id>/advancements")
def create_advancement(member_id):
    _, role = authenticate()
    require_roles(role, LEADER_ONLY)
    member = h.get_or_404(db.members, member_id)
    body = h.get_json_body()

    kind = h.require_enum(body, "kind", {"RANK", "BADGE"})
    requirements_total = h.require_int(body, "requirements_total")
    if requirements_total < 1:
        raise err(ERR_INVALID_REQUEST, "requirements_total must be >= 1")

    if kind == "RANK":
        target = h.require_enum(body, "target", RANK_TARGETS)
        badge_code = None
    else:
        # BADGE: target is the badge string carried in badge_code (PRD §3.5).
        badge_code = h.require_string(body, "badge_code")
        target = h.require_string(body, "target")

    now = iso_now(datetime.now(timezone.utc))
    adv = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "member_id": member["id"],
        "kind": kind,
        "target": target,
        "badge_code": badge_code,
        "requirements_total": requirements_total,
        "requirements_signed": 0,
        "completion_pct": 0,
        "submitted_by_user_id": None,
        "status": "DRAFT",
        "_seq": db.next_seq(),
    }
    db.advancements[adv["id"]] = adv
    return object_response(serialize_advancement(adv), status=201)


@bp.get("/advancements/<adv_id>")
def get_advancement(adv_id):
    _, role = authenticate()
    require_roles(role, BOTH_ROLES)
    adv = h.get_or_404(db.advancements, adv_id)
    return object_response(serialize_advancement(adv))


@bp.get("/advancements")
def list_advancements():
    _, role = authenticate()
    require_roles(role, BOTH_ROLES)
    member_id = request.args.get("member_id")
    status = request.args.get("status")
    limit, offset = h.parse_pagination()
    rows = [
        a for a in db.advancements.values()
        if (member_id is None or a["member_id"] == member_id)
        and (status is None or a["status"] == status)
    ]
    rows = h.sort_by_creation(rows)
    page, total = h.paginate(rows, limit, offset)
    return array_response([serialize_advancement(a) for a in page], limit, offset, total)


@bp.post("/advancements/<adv_id>/sign-requirement")
def sign_requirement(adv_id):
    _, role = authenticate()
    require_roles(role, LEADER_ONLY)
    adv = h.get_or_404(db.advancements, adv_id)
    # requirements_signed += 1, capped at requirements_total (PRD §3.5).
    if adv["requirements_signed"] < adv["requirements_total"]:
        adv["requirements_signed"] += 1
        _recompute_completion(adv)
    h.touch_and_bump(adv)
    return object_response(serialize_advancement(adv))


@bp.post("/advancements/<adv_id>/submit")
def submit_advancement(adv_id):
    user_id, role = authenticate()
    require_roles(role, LEADER_ONLY)
    adv = h.get_or_404(db.advancements, adv_id)
    # Submit defined from DRAFT or RETURNED (PRD §3.5).
    if adv["status"] not in ("DRAFT", "RETURNED"):
        raise err(ERR_INVALID_STATE, "submit only from DRAFT or RETURNED")
    # Requirements complete (PRD §3.5) -> ERR_REQUIREMENTS_INCOMPLETE.
    if adv["requirements_signed"] != adv["requirements_total"]:
        raise err(ERR_REQUIREMENTS_INCOMPLETE, "requirements not fully signed")
    adv["status"] = "SUBMITTED"
    adv["submitted_by_user_id"] = user_id
    h.touch_and_bump(adv)
    return object_response(serialize_advancement(adv))


@bp.post("/advancements/<adv_id>/return")
def return_advancement(adv_id):
    _, role = authenticate()
    require_roles(role, REGISTRAR_ONLY)
    adv = h.get_or_404(db.advancements, adv_id)
    if adv["status"] != "SUBMITTED":
        raise err(ERR_INVALID_STATE, "return only from SUBMITTED")
    adv["status"] = "RETURNED"
    h.touch_and_bump(adv)
    return object_response(serialize_advancement(adv))


@bp.post("/advancements/<adv_id>/approve")
def approve_advancement(adv_id):
    user_id, role = authenticate()
    require_roles(role, REGISTRAR_ONLY)
    adv = h.get_or_404(db.advancements, adv_id)

    # State first (PRD §3.9).
    if adv["status"] != "SUBMITTED":
        raise err(ERR_INVALID_STATE, "approve only from SUBMITTED")
    # Segregation of duties: approver != submitter (PRD §3.5).
    if user_id == adv["submitted_by_user_id"]:
        raise err(ERR_SEGREGATION_OF_DUTIES, "approver must differ from submitter")
    # Member must be REGISTERED (PRD §3.5).
    member = db.members.get(adv["member_id"])
    if member is None or member["registration_status"] != "REGISTERED":
        raise err(ERR_MEMBER_NOT_REGISTERED, "member must be REGISTERED for approval")

    adv["status"] = "APPROVED"
    h.touch_and_bump(adv)
    # RANK approval advances the member's rank to the target (PRD §3.5).
    if adv["kind"] == "RANK":
        member["rank"] = adv["target"]
        h.touch_and_bump(member)
    return object_response(serialize_advancement(adv))
