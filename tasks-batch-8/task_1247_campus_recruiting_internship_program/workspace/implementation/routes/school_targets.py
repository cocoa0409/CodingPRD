"""SchoolTarget routes."""

from flask import Blueprint, request

from db import db
from errors import (
    err_validation,
    err_stale_school_target_version,
    err_season_posture_forbidden,
    err_application_state_forbidden,
)
from middleware import require_auth
from response import success_object, success_list
from services.domain import (
    get_season,
    get_school_target,
    school_target_view,
)
from utils import (
    parse_pagination,
    require_string,
    require_int,
    require_enum,
    optional_int,
    stamp_new,
    touch,
)

bp = Blueprint("school_targets", __name__)

TIERS = {"CORE", "TARGET", "EXPLORATORY"}
REGIONS = {"METRO", "REGIONAL", "REMOTE"}


@bp.route("/seasons/<sid>/school-targets", methods=["POST"])
@require_auth(["RecruitingAdmin"])
def create_school_target(sid):
    get_season(sid)  # existence (left-to-right)
    payload = request.get_json(silent=True) or {}
    school_name = require_string(payload, "school_name")
    tier = require_enum(payload, "tier", TIERS)
    application_cap = require_int(payload, "application_cap", min_value=1)
    stipend_region = require_enum(payload, "stipend_region", REGIONS)
    exploding_offer_hours_override = optional_int(
        payload, "exploding_offer_hours_override", default=None, min_value=1
    )

    # Unique within season (case-sensitive)
    for t in db.school_targets.values():
        if t["season_id"] == sid and t["school_name"] == school_name:
            raise err_validation(f"School name {school_name} already exists in season")

    t = {
        "season_id": sid,
        "school_name": school_name,
        "tier": tier,
        "application_cap": application_cap,
        "stipend_region": stipend_region,
        "exploding_offer_hours_override": exploding_offer_hours_override,
        "status": "ACTIVE",
    }
    stamp_new(t)
    db.school_targets[t["id"]] = t
    return success_object(school_target_view(t), 201)


@bp.route("/seasons/<sid>/school-targets", methods=["GET"])
@require_auth(["RecruitingAdmin", "Recruiter"])
def list_school_targets(sid):
    get_season(sid)
    limit, offset = parse_pagination(request.args)
    tier = request.args.get("tier")
    status = request.args.get("status")
    items = [
        t for t in db.school_targets.values()
        if t["season_id"] == sid
        and (tier is None or t["tier"] == tier)
        and (status is None or t["status"] == status)
    ]
    items.sort(key=lambda t: t["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([school_target_view(t) for t in page], total, limit, offset)


@bp.route("/school-targets/<tid>", methods=["GET"])
@require_auth(["RecruitingAdmin", "Recruiter"])
def get_one_school_target(tid):
    t = get_school_target(tid)
    return success_object(school_target_view(t))


@bp.route("/school-targets/<tid>", methods=["PATCH"])
@require_auth(["RecruitingAdmin"])
def patch_school_target(tid):
    t = get_school_target(tid)
    payload = request.get_json(silent=True) or {}
    # OCC (priority 6)
    if "expected_school_target_version" not in payload or payload["expected_school_target_version"] is None:
        raise err_validation("expected_school_target_version is required")
    expected = payload["expected_school_target_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise err_validation("expected_school_target_version must be an integer")
    if expected != t["version"]:
        raise err_stale_school_target_version()

    # Apply edits
    if "tier" in payload and payload["tier"] is not None:
        v = payload["tier"]
        if not isinstance(v, str) or v not in TIERS:
            raise err_validation(f"tier must be one of {sorted(TIERS)}")
        t["tier"] = v
    if "application_cap" in payload and payload["application_cap"] is not None:
        v = payload["application_cap"]
        if isinstance(v, bool) or not isinstance(v, int) or v < 1:
            raise err_validation("application_cap must be an integer >= 1")
        t["application_cap"] = v
    if "stipend_region" in payload and payload["stipend_region"] is not None:
        v = payload["stipend_region"]
        if not isinstance(v, str) or v not in REGIONS:
            raise err_validation(f"stipend_region must be one of {sorted(REGIONS)}")
        t["stipend_region"] = v
    if "exploding_offer_hours_override" in payload:
        v = payload["exploding_offer_hours_override"]
        if v is None:
            t["exploding_offer_hours_override"] = None
        else:
            if isinstance(v, bool) or not isinstance(v, int) or v < 1:
                raise err_validation("exploding_offer_hours_override must be an integer >= 1")
            t["exploding_offer_hours_override"] = v
    touch(t)
    return success_object(school_target_view(t))


@bp.route("/school-targets/<tid>/drop", methods=["POST"])
@require_auth(["RecruitingAdmin"])
def drop_school_target(tid):
    t = get_school_target(tid)
    season = get_season(t["season_id"])
    # Posture gate
    if season["status"] not in ("DRAFT", "OPEN", "SELECTION"):
        raise err_season_posture_forbidden()
    # State gate
    if t["status"] != "ACTIVE":
        raise err_application_state_forbidden("SchoolTarget is not ACTIVE")
    t["status"] = "DROPPED"
    touch(t)
    # Cascade L1: every SCHEDULED CampusEvent of this school -> CANCELLED
    for ev in db.campus_events.values():
        if ev["school_target_id"] == tid and ev["status"] == "SCHEDULED":
            ev["status"] = "CANCELLED"
            touch(ev)
    return success_object(school_target_view(t))
