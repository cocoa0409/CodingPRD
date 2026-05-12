"""Activity endpoints — drafts, review, lifecycle, list, ranking, roles."""
import random

from flask import Blueprint, g, request

import db
from clock import parse_iso
from errors import (
    ERR_FORBIDDEN,
    ERR_INVALID_INPUT,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    err,
)
from middleware import auth_required
from pagination import parse_pagination, slice_sorted
from response import list_response, success
from services.audit import emit_sync
from services.occ import check_occ
from validators import (
    as_enum,
    as_int,
    as_iso,
    as_lat,
    as_lng,
    as_number,
    as_str,
    opt_field,
    require_field,
)
from views import view_activity, view_activity_role


bp = Blueprint("activities", __name__)


def _validate_role_label(label):
    return as_str(label, "role_label", 1, 40)


@bp.post("/activities")
@auth_required(["Organizer"])
def create_activity():
    body = request.get_json(silent=True) or {}
    title = as_str(require_field(body, "title"), "title", 1, 120)
    description = as_str(require_field(body, "description"), "description", 1, 2000)
    location_lat = as_lat(require_field(body, "location_lat"))
    location_lng = as_lng(require_field(body, "location_lng"))
    start_at = as_iso(require_field(body, "start_at"), "start_at")
    end_at = as_iso(require_field(body, "end_at"), "end_at")
    recruit_open_at = as_iso(require_field(body, "recruit_open_at"), "recruit_open_at")
    recruit_close_at = as_iso(require_field(body, "recruit_close_at"), "recruit_close_at")
    required_skill_codes = opt_field(body, "required_skill_codes", []) or []
    if not isinstance(required_skill_codes, list):
        raise err(ERR_INVALID_INPUT, "required_skill_codes must be a list")
    for c in required_skill_codes:
        if not isinstance(c, str):
            raise err(ERR_INVALID_INPUT, "required_skill_codes entries must be strings")
    position_quota = as_int(require_field(body, "position_quota"), "position_quota", 1, 1000)
    difficulty = opt_field(body, "difficulty", "MEDIUM") or "MEDIUM"
    difficulty = as_enum(difficulty, "difficulty", {"EASY", "MEDIUM", "HARD"})
    hour_rule_type = opt_field(body, "hour_rule_type", "ACTUAL_DURATION") or "ACTUAL_DURATION"
    hour_rule_type = as_enum(hour_rule_type, "hour_rule_type",
                             {"ACTUAL_DURATION", "FIXED_VALUE", "ROLE_COEFFICIENT"})
    fixed_hour_value = opt_field(body, "fixed_hour_value", None)
    if hour_rule_type == "FIXED_VALUE":
        if fixed_hour_value is None:
            raise err(ERR_INVALID_INPUT, "fixed_hour_value required for FIXED_VALUE")
        fixed_hour_value = as_number(fixed_hour_value, "fixed_hour_value", 0.25, 24)

    # PRD §3.3: time-ordering validation belongs to /submit, not draft creation.
    row = {
        "organizer_id": g.user_id,
        "title": title,
        "description": description,
        "location_lat": location_lat,
        "location_lng": location_lng,
        "start_at": body["start_at"],
        "end_at": body["end_at"],
        "recruit_open_at": body["recruit_open_at"],
        "recruit_close_at": body["recruit_close_at"],
        "required_skill_codes": required_skill_codes,
        "position_quota": position_quota,
        "filled_positions": 0,
        "difficulty": difficulty,
        "hour_rule_type": hour_rule_type,
        "fixed_hour_value": fixed_hour_value,
        "requires_sensitive_clearance": False,
        "status": "DRAFT",
        "site_code": None,
    }
    db.init_common(row)
    db.activities[row["id"]] = row
    return success(view_activity(row), status_code=201)


@bp.post("/activities/<aid>/submit")
@auth_required(["Organizer"])
def submit_activity(aid):
    act = db.activities.get(aid)
    if not act:
        raise err(ERR_NOT_FOUND, "activity not found")
    if act["organizer_id"] != g.user_id:
        raise err(ERR_FORBIDDEN, "ownership mismatch")
    body = request.get_json(silent=True) or {}
    check_occ(act, body)
    with db.lock():
        if act["status"] != "DRAFT":
            raise err(ERR_INVALID_STATE, "must be DRAFT")

        # Re-check temporal ordering and quota
        ro = parse_iso(act["recruit_open_at"])
        rc = parse_iso(act["recruit_close_at"])
        s = parse_iso(act["start_at"])
        e = parse_iso(act["end_at"])
        if not (ro < rc and rc < s and s < e):
            raise err(ERR_INVALID_INPUT, "temporal ordering invalid")
        if act["position_quota"] < 1:
            raise err(ERR_INVALID_INPUT, "position_quota must be >= 1")

        # All required_skill_codes must resolve
        skill_by_code = {s["code"]: s for s in db.skills.values()}
        sensitive = False
        for code in act.get("required_skill_codes", []):
            if code not in skill_by_code:
                raise err(ERR_NOT_FOUND, f"required_skill_codes contains unknown code: {code}")
            if skill_by_code[code].get("sensitivity_level") == "SENSITIVE":
                sensitive = True

        act["requires_sensitive_clearance"] = sensitive
        act["status"] = "UNDER_REVIEW"
        db.touch(act)
    return success(view_activity(act))


@bp.post("/activities/<aid>/approve")
@auth_required(["SkillAdmin"])
def approve_activity(aid):
    act = db.activities.get(aid)
    if not act:
        raise err(ERR_NOT_FOUND, "activity not found")
    body = request.get_json(silent=True) or {}
    check_occ(act, body)
    with db.lock():
        if act["status"] != "UNDER_REVIEW":
            raise err(ERR_INVALID_STATE, "must be UNDER_REVIEW")
        act["status"] = "PUBLISHED"
        # Mint 6-digit numeric site code
        act["site_code"] = "".join(str(random.randint(0, 9)) for _ in range(6))
        db.touch(act)
        emit_sync("PARTNER_ORG", "ACTIVITY_PUBLISHED", {"activity_id": act["id"]})
        emit_sync("IM", "ACTIVITY_PUBLISHED", {"activity_id": act["id"]})
    return success(view_activity(act))


@bp.post("/activities/<aid>/reject")
@auth_required(["SkillAdmin"])
def reject_activity(aid):
    act = db.activities.get(aid)
    if not act:
        raise err(ERR_NOT_FOUND, "activity not found")
    body = request.get_json(silent=True) or {}
    check_occ(act, body)
    with db.lock():
        if act["status"] != "UNDER_REVIEW":
            raise err(ERR_INVALID_STATE, "must be UNDER_REVIEW")
        act["status"] = "REJECTED"
        db.touch(act)
    return success(view_activity(act))


@bp.post("/activities/<aid>/revise")
@auth_required(["Organizer"])
def revise_activity(aid):
    act = db.activities.get(aid)
    if not act:
        raise err(ERR_NOT_FOUND, "activity not found")
    if act["organizer_id"] != g.user_id:
        raise err(ERR_FORBIDDEN, "ownership mismatch")
    body = request.get_json(silent=True) or {}
    check_occ(act, body)
    with db.lock():
        if act["status"] != "REJECTED":
            raise err(ERR_INVALID_STATE, "must be REJECTED")
        act["status"] = "DRAFT"
        db.touch(act)
    return success(view_activity(act))


@bp.post("/activities/<aid>/shelve")
@auth_required(["Organizer"])
def shelve_activity(aid):
    act = db.activities.get(aid)
    if not act:
        raise err(ERR_NOT_FOUND, "activity not found")
    if act["organizer_id"] != g.user_id:
        raise err(ERR_FORBIDDEN, "ownership mismatch")
    body = request.get_json(silent=True) or {}
    check_occ(act, body)
    with db.lock():
        if act["status"] not in {"PUBLISHED", "RECRUITING"}:
            raise err(ERR_INVALID_STATE, "may only shelve PUBLISHED or RECRUITING")
        if int(act.get("filled_positions", 0)) != 0:
            raise err(ERR_INVALID_STATE, "filled_positions must be zero to shelve")
        act["status"] = "SHELVED"
        db.touch(act)
    return success(view_activity(act))


@bp.get("/activities/<aid>")
@auth_required(["Volunteer", "Organizer", "SkillAdmin"])
def get_activity(aid):
    act = db.activities.get(aid)
    if not act:
        raise err(ERR_NOT_FOUND, "activity not found")
    return success(view_activity(act))


@bp.get("/activities")
@auth_required(["Volunteer", "Organizer", "SkillAdmin"])
def list_activities():
    limit, offset = parse_pagination()
    status = request.args.get("status")
    skill_code = request.args.get("skill_code")
    rows = list(db.activities.values())
    if status:
        rows = [r for r in rows if r.get("status") == status]
    if skill_code:
        rows = [r for r in rows if skill_code in (r.get("required_skill_codes") or [])]
    page, total = slice_sorted(rows, limit, offset)
    return list_response([view_activity(r) for r in page], limit, offset, total)


@bp.post("/activities/<aid>/roles")
@auth_required(["Organizer"])
def create_role(aid):
    act = db.activities.get(aid)
    if not act:
        raise err(ERR_NOT_FOUND, "activity not found")
    if act["organizer_id"] != g.user_id:
        raise err(ERR_FORBIDDEN, "ownership mismatch")
    body = request.get_json(silent=True) or {}
    role_label = _validate_role_label(require_field(body, "role_label"))
    coefficient_in = opt_field(body, "coefficient", 1.0)
    if coefficient_in is None:
        coefficient_in = 1.0
    coefficient = as_number(coefficient_in, "coefficient", 0.5, 3.0)
    coefficient = db.round2(coefficient)

    with db.lock():
        # Unique role_label within activity
        for r in db.activity_roles.values():
            if r["activity_id"] == aid and r["role_label"] == role_label:
                raise err(ERR_INVALID_INPUT, "role_label must be unique within activity")
        row = {
            "activity_id": aid,
            "role_label": role_label,
            "coefficient": coefficient,
        }
        db.init_common(row, with_version=False)
        db.activity_roles[row["id"]] = row
    return success(view_activity_role(row), status_code=201)


@bp.get("/activities/<aid>/recommended-volunteers")
@auth_required(["Organizer", "SkillAdmin"])
def recommended_volunteers(aid):
    act = db.activities.get(aid)
    if not act:
        raise err(ERR_NOT_FOUND, "activity not found")
    required = set(act.get("required_skill_codes") or [])

    # For each volunteer compute historical-participation score = count of past
    # COMPLETED applications on activities sharing >= 1 required_skill_code with this one.
    scores = {}
    for app in db.applications.values():
        if app["status"] != "COMPLETED":
            continue
        other_act = db.activities.get(app["activity_id"])
        if not other_act:
            continue
        if other_act["id"] == aid:
            continue
        other_codes = set(other_act.get("required_skill_codes") or [])
        if not (required & other_codes):
            continue
        vid = app["volunteer_id"]
        scores[vid] = scores.get(vid, 0) + 1

    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))[:20]
    items = []
    for vid, score in ranked:
        v = db.volunteers.get(vid)
        if not v:
            continue
        items.append({"volunteer_id": vid, "score": score,
                      "full_name": v.get("full_name")})
    return success({"items": items, "activity_id": aid})
