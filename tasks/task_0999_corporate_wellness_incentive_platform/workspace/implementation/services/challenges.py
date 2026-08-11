"""Challenge endpoints (PRD §3.5)."""
from flask import Blueprint

from db import DB
from errors import ApiError, invalid
from middleware import require_roles
from response import success
from services import serializers
from services.common import (
    get_challenge_or_404, get_program_or_404, list_response, parse_body,
    require_fields, stamp_new, touch,
)
from clock import iso_from_dt

bp = Blueprint("challenges", __name__)

_ACTIVITY_TYPES = {"STEPS", "MINUTES", "VISITS"}


@bp.post("/wellness/challenges")
@require_roles("BenefitsAdmin")
def create_challenge():
    body = parse_body()
    vals = require_fields(body, [
        ("program_id", "string", True),
        ("name", "string", True),
        ("activity_type", "enum", True, _ACTIVITY_TYPES),
        ("goal_quantity", "int", True),
        ("points_reward", "int", True),
        ("starts_at", "datetime", True),
        ("ends_at", "datetime", True),
    ])
    get_program_or_404(vals["program_id"])
    starts, ends = vals["starts_at"], vals["ends_at"]
    if not ends > starts:
        raise invalid("ends_at must be strictly after starts_at")
    rec = stamp_new({
        "program_id": vals["program_id"],
        "name": vals["name"],
        "activity_type": vals["activity_type"],
        "goal_quantity": vals["goal_quantity"],
        "points_reward": vals["points_reward"],
        "starts_at": iso_from_dt(starts),
        "ends_at": iso_from_dt(ends),
        "_starts": starts,
        "_ends": ends,
        "completed_count": 0,
        "status": "DRAFT",
    })
    DB.challenges[rec["id"]] = rec
    return success(serializers.challenge(rec), status=201)


@bp.get("/wellness/challenges/<cid>")
@require_roles("PlatformAdmin", "BenefitsAdmin", "Employee")
def get_challenge(cid):
    return success(serializers.challenge(get_challenge_or_404(cid)))


@bp.patch("/wellness/challenges/<cid>")
@require_roles("BenefitsAdmin")
def edit_challenge(cid):
    ch = get_challenge_or_404(cid)
    body = parse_body()
    vals = require_fields(body, [
        ("name", "string", False),
        ("goal_quantity", "int", False),
        ("points_reward", "int", False),
        ("starts_at", "datetime", False),
        ("ends_at", "datetime", False),
        ("expected_challenge_version", "int", True),
    ])
    # OCC (stage 4) precedes state legality (stage 6)
    if vals["expected_challenge_version"] != ch["version"]:
        raise ApiError(
            "ERR_STALE_VERSION",
            "expected_challenge_version does not match the challenge's current version",
        )
    if ch["status"] != "DRAFT":
        raise ApiError(
            "ERR_INVALID_STATE", "Only a DRAFT challenge may be edited"
        )
    if "name" in vals:
        ch["name"] = vals["name"]
    if "goal_quantity" in vals:
        ch["goal_quantity"] = vals["goal_quantity"]
    if "points_reward" in vals:
        ch["points_reward"] = vals["points_reward"]
    if "starts_at" in vals:
        ch["_starts"] = vals["starts_at"]
        ch["starts_at"] = iso_from_dt(vals["starts_at"])
    if "ends_at" in vals:
        ch["_ends"] = vals["ends_at"]
        ch["ends_at"] = iso_from_dt(vals["ends_at"])
    if not ch["_ends"] > ch["_starts"]:
        raise invalid("ends_at must be strictly after starts_at")
    touch(ch)
    return success(serializers.challenge(ch))


@bp.post("/wellness/challenges/<cid>/publish")
@require_roles("BenefitsAdmin")
def publish_challenge(cid):
    ch = get_challenge_or_404(cid)
    if ch["status"] != "DRAFT":
        raise ApiError(
            "ERR_INVALID_STATE", "Only a DRAFT challenge may be published"
        )
    program = DB.programs[ch["program_id"]]
    if program["status"] != "ACTIVE":
        raise ApiError(
            "ERR_PROGRAM_NOT_ACTIVE", "Program must be ACTIVE to publish"
        )
    for other in DB.challenges.values():
        if other["id"] == ch["id"]:
            continue
        if other["program_id"] != ch["program_id"]:
            continue
        if other["activity_type"] != ch["activity_type"]:
            continue
        if other["status"] not in ("PUBLISHED", "ACTIVE"):
            continue
        if ch["_starts"] < other["_ends"] and ch["_ends"] > other["_starts"]:
            raise ApiError(
                "ERR_CHALLENGE_WINDOW_OVERLAP",
                "Same-activity PUBLISHED/ACTIVE challenge window overlap",
            )
    ch["status"] = "PUBLISHED"
    touch(ch)
    return success(serializers.challenge(ch))


@bp.get("/wellness/challenges/<cid>/participations")
@require_roles("PlatformAdmin", "BenefitsAdmin")
def list_challenge_participations(cid):
    get_challenge_or_404(cid)
    items = [p for p in DB.participations.values() if p["challenge_id"] == cid]
    return list_response(items, serializers.participation)
