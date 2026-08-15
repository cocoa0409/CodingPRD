"""WatermarkProfile routes (PRD §3.3)."""

from flask import Blueprint

import db
from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE
from helpers import (
    new_entity,
    touch,
    get_json_body,
    require_fields,
    check_string,
    check_int,
    check_enum,
    check_bool,
    get_pagination,
    get_filter,
    paginate,
)
from middleware import require_roles
from response import success_object, success_list
from routes.projects import get_project_or_404
from services.transitions import guard_transition

bp = Blueprint("watermark_profiles", __name__)

POSITIONS = (
    "TOP_LEFT",
    "TOP_RIGHT",
    "BOTTOM_LEFT",
    "BOTTOM_RIGHT",
    "CENTER",
    "DIAGONAL_TILE",
)
PROFILE_TERMINAL = ("RETIRED",)
LIST_ROLES = ("PostSupervisor", "DailiesCoordinator")


def serialize(profile):
    return dict(profile)


def get_profile_or_404(project, profile_id):
    profile = db.watermark_profiles.get(profile_id)
    if profile is None or profile["project_id"] != project["id"]:
        raise ApiError(
            ERR_NOT_FOUND, f"WatermarkProfile {profile_id} does not exist", 404
        )
    return profile


def watermark_compliance_score(profile):
    """Score per PRD §3.3: 50 for forensic; min(40, opacity//2); 10 for
    recipient email; 10 bonus for DIAGONAL_TILE; capped at 100."""
    score = 0
    if profile["forensic_enabled"]:
        score += 50
    score += min(40, profile["opacity_pct"] // 2)
    if profile["includes_recipient_email"]:
        score += 10
    if profile["position"] == "DIAGONAL_TILE":
        score += 10
    return min(score, 100)


def tier_gate_satisfied(profile, security_tier):
    score = watermark_compliance_score(profile)
    if security_tier == "STANDARD":
        return score >= 40
    if security_tier == "ELEVATED":
        return score >= 60 and profile["includes_recipient_email"]
    if security_tier == "LOCKDOWN":
        return score >= 90 and profile["forensic_enabled"]
    return False


@bp.route("/post-production/projects/<project_id>/watermark-profiles", methods=["POST"])
def create_profile(project_id):
    require_roles(("PostSupervisor",))
    project = get_project_or_404(project_id)
    body = get_json_body()
    require_fields(
        body,
        (
            "profile_name",
            "opacity_pct",
            "position",
            "includes_recipient_email",
            "forensic_enabled",
        ),
    )
    profile_name = check_string(body, "profile_name")
    opacity_pct = check_int(body, "opacity_pct", min_v=1, max_v=100)
    position = check_enum(body, "position", POSITIONS)
    includes_recipient_email = check_bool(body, "includes_recipient_email")
    forensic_enabled = check_bool(body, "forensic_enabled")
    for existing in db.watermark_profiles.values():
        if (
            existing["project_id"] == project_id
            and existing["profile_name"] == profile_name
        ):
            raise ApiError(
                ERR_INVALID_REQUEST,
                f"profile_name '{profile_name}' already exists in this project",
                400,
            )
    profile = new_entity(
        {
            "project_id": project_id,
            "profile_name": profile_name,
            "opacity_pct": opacity_pct,
            "position": position,
            "includes_recipient_email": includes_recipient_email,
            "forensic_enabled": forensic_enabled,
            "status": "DRAFT",
        }
    )
    db.watermark_profiles[profile["id"]] = profile
    return success_object(serialize(profile), 201)


@bp.route("/post-production/projects/<project_id>/watermark-profiles", methods=["GET"])
def list_profiles(project_id):
    require_roles(LIST_ROLES)
    get_project_or_404(project_id)
    limit, offset = get_pagination()
    items = [w for w in db.watermark_profiles.values() if w["project_id"] == project_id]
    status = get_filter("status")
    if status is not None:
        items = [w for w in items if w["status"] == status]
    window, total = paginate(items, limit, offset)
    return success_list([serialize(w) for w in window], limit, offset, total)


@bp.route(
    "/post-production/projects/<project_id>/watermark-profiles/<profile_id>/activate",
    methods=["POST"],
)
def activate_profile(project_id, profile_id):
    require_roles(("PostSupervisor",))
    project = get_project_or_404(project_id)
    profile = get_profile_or_404(project, profile_id)
    guard_transition(profile, "DRAFT", PROFILE_TERMINAL, "watermark profile")
    # LOCKDOWN tier: forensic_enabled must be true and opacity_pct >= 20.
    if project["security_tier"] == "LOCKDOWN":
        if not (profile["forensic_enabled"] and profile["opacity_pct"] >= 20):
            raise ApiError(
                ERR_INVALID_STATE,
                "LOCKDOWN projects require forensic_enabled true and "
                "opacity_pct >= 20 for profile activation",
                409,
            )
    profile["status"] = "ACTIVE"
    touch(profile)
    return success_object(serialize(profile))


@bp.route(
    "/post-production/projects/<project_id>/watermark-profiles/<profile_id>/retire",
    methods=["POST"],
)
def retire_profile(project_id, profile_id):
    require_roles(("PostSupervisor",))
    project = get_project_or_404(project_id)
    profile = get_profile_or_404(project, profile_id)
    guard_transition(profile, "ACTIVE", PROFILE_TERMINAL, "watermark profile")
    # No PUBLISHED DailiesPackage references this profile.
    for pkg in db.dailies_packages.values():
        if (
            pkg.get("watermark_profile_id") == profile_id
            and pkg["status"] == "PUBLISHED"
        ):
            raise ApiError(
                ERR_INVALID_STATE,
                "A PUBLISHED DailiesPackage references this profile; "
                "retirement refused",
                409,
            )
    profile["status"] = "RETIRED"
    touch(profile)
    return success_object(serialize(profile))


# ---------------------------------------------------------------------------
# Flat alias + reverse reachability
# ---------------------------------------------------------------------------


@bp.route("/post-production/watermark-profiles/<profile_id>", methods=["GET"])
def get_profile_flat(profile_id):
    require_roles(LIST_ROLES)
    profile = db.watermark_profiles.get(profile_id)
    if profile is None:
        raise ApiError(
            ERR_NOT_FOUND, f"WatermarkProfile {profile_id} does not exist", 404
        )
    return success_object(serialize(profile))


@bp.route("/post-production/watermark-profiles/<profile_id>/dailies", methods=["GET"])
def list_profile_dailies(profile_id):
    require_roles(("PostSupervisor", "DailiesCoordinator", "ReviewerLead"))
    profile = db.watermark_profiles.get(profile_id)
    if profile is None:
        raise ApiError(
            ERR_NOT_FOUND, f"WatermarkProfile {profile_id} does not exist", 404
        )
    from routes.dailies import serialize as serialize_package

    limit, offset = get_pagination()
    items = [
        p
        for p in db.dailies_packages.values()
        if p.get("watermark_profile_id") == profile_id
    ]
    status = get_filter("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    window, total = paginate(items, limit, offset)
    return success_list([serialize_package(p) for p in window], limit, offset, total)
