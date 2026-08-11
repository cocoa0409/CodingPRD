"""Site endpoints."""
from flask import Blueprint, request

import db
from middleware import require_roles
from response import success_object
from services import calculations as calc
from services.common import (
    get_site_or_404,
    init_common,
    paginate,
    parse_body,
    require_fields,
    serialize,
    touch,
    validate_str,
)
from errors import ApiError, ERR_INVALID_REQUEST

bp = Blueprint("sites", __name__)

ALL_ROLES = (
    "PlatformAdmin", "ComplianceManager", "ComplianceEngineer", "SafetyManager",
    "HousekeepingAuditor", "IncidentInvestigator", "InspectorUser",
)


@bp.route("/api/sites", methods=["POST"])
def create_site():
    require_roles("PlatformAdmin")
    body = parse_body()
    require_fields(body, ["name", "address", "ahj_authority", "insurer_id"])
    for f in ("name", "address", "ahj_authority", "insurer_id"):
        validate_str(body, f)

    site = {
        "name": body["name"],
        "address": body["address"],
        "ahj_authority": body["ahj_authority"],
        "insurer_id": body["insurer_id"],
        "posture": "CONDITIONAL",
        "posture_score": 100,
        "open_critical_findings": 0,
        "open_overdue_housekeeping": 0,
        "hot_work_in_progress": 0,
        "last_dha_id": None,
    }
    init_common(site)
    db.sites[site["id"]] = site
    return success_object(serialize(site), 201)


@bp.route("/api/sites", methods=["GET"])
def list_sites():
    require_roles(*ALL_ROLES)
    items = list(db.sites.values())
    posture = request.args.get("posture")
    if posture is not None:
        items = [s for s in items if s["posture"] == posture]
    return paginate(items)


@bp.route("/api/sites/<id>", methods=["GET"])
def get_site(id):
    require_roles(*ALL_ROLES)
    site = get_site_or_404(id)
    return success_object(serialize(site), 200)


@bp.route("/api/sites/<id>", methods=["PATCH"])
def update_site(id):
    require_roles("PlatformAdmin", "ComplianceManager")
    site = get_site_or_404(id)
    body = parse_body()
    for f in ("name", "address", "ahj_authority", "insurer_id"):
        validate_str(body, f)
    changed = False
    for f in ("name", "address", "ahj_authority", "insurer_id"):
        if f in body and body[f] is not None:
            site[f] = body[f]
            changed = True
    if changed:
        touch(site)
    return success_object(serialize(site), 200)


@bp.route("/api/sites/<id>/recompute_posture", methods=["POST"])
def recompute_posture(id):
    require_roles("PlatformAdmin", "ComplianceManager")
    site = get_site_or_404(id)
    calc.site_posture_derivation(site)
    touch(site)
    return success_object(serialize(site), 200)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_roles("PlatformAdmin")
    body = parse_body()
    to_iso8601 = body.get("to_iso8601")
    if not isinstance(to_iso8601, str):
        raise ApiError(ERR_INVALID_REQUEST, "to_iso8601 is required", 400)
    from services.common import parse_iso, run_system_transitions
    dt = parse_iso(to_iso8601, "to_iso8601")
    db.clock.set(dt)
    run_system_transitions()
    return success_object({"current_utc": db.now_iso()}, 200)
