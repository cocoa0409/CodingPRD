"""AccessBadge endpoints (SCAFFOLD 1.5, PRD 3.8)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_ZONE_NOT_FOUND, ERR_BADGE_NOT_FOUND,
    ERR_BADGE_INVALID_TRANSITION, ERR_ZONE_NOT_ACTIVE, ERR_BADGE_WINDOW_OVERLAP,
    ERR_INVALID_REQUEST,
)
from middleware import authorized
from response import success_object, success_list
from serializers import badge_view
from services import new_common, touch
from util import parse_dt
from validate import (
    get_body, reject_unknown_fields, req_str, req_enum, req_datetime,
    opt_nullable_str, require_path, require_body_fk, parse_pagination,
)

bp = Blueprint("access_badges", __name__)

ALL_ROLES = ["ZoneOperator", "Importer", "CustomsOfficer", "GateOfficer"]

# Reachable badge transitions from each status (SCAFFOLD 1.2 AccessBadge).
_BADGE_TRANSITIONS = {
    "ACTIVE": {"SUSPENDED", "REVOKED"},
    "SUSPENDED": {"ACTIVE", "REVOKED"},
    "REVOKED": set(),
}


@bp.route("/zones/access-badges", methods=["POST"])
def create_badge():
    caller = authorized(["ZoneOperator"])
    body = get_body()
    reject_unknown_fields(body, {"zone_id", "holder_name", "employer_ref",
                                 "valid_from", "valid_until"})
    zone_id = req_str(body, "zone_id")
    zone = require_body_fk("zones", zone_id, ERR_ZONE_NOT_FOUND, "zone_id")
    holder_name = req_str(body, "holder_name")
    employer_ref = opt_nullable_str(body, "employer_ref")
    valid_from = parse_dt(req_datetime(body, "valid_from"))
    valid_until = parse_dt(req_datetime(body, "valid_until"))
    # Schema (priority 4): valid_until must be strictly after valid_from.
    if valid_until <= valid_from:
        raise_error(ERR_INVALID_REQUEST, "valid_until must be strictly after valid_from")

    # Temporal (priority 8): closed-interval overlap for same (zone_id, holder_name)
    # among ACTIVE/SUSPENDED badges; touching bounds conflict.
    for other in db["access_badges"].values():
        if (other["zone_id"] == zone["id"] and other["holder_name"] == holder_name
                and other["status"] in ("ACTIVE", "SUSPENDED")):
            if valid_from <= other["valid_until"] and other["valid_from"] <= valid_until:
                raise_error(ERR_BADGE_WINDOW_OVERLAP,
                            "badge validity window overlaps an existing badge for this holder")

    badge = new_common()
    badge.update({
        "zone_id": zone["id"],
        "holder_name": holder_name,
        "employer_ref": employer_ref,
        "valid_from": valid_from,
        "valid_until": valid_until,
        "status": "ACTIVE",
    })
    db["access_badges"][badge["id"]] = badge
    return success_object(badge_view(badge), status=201)


@bp.route("/zones/access-badges", methods=["GET"])
def list_badges():
    authorized(ALL_ROLES)
    limit, offset = parse_pagination()
    zone_id = request.args.get("zone_id")
    holder_name = request.args.get("holder_name")
    status = request.args.get("status")
    items = sorted(db["access_badges"].values(), key=lambda b: (b["created_at"], b["id"]))
    if zone_id is not None:
        items = [b for b in items if b["zone_id"] == zone_id]
    if holder_name is not None:
        items = [b for b in items if b["holder_name"] == holder_name]
    if status is not None:
        items = [b for b in items if b["status"] == status]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([badge_view(b) for b in page], total, limit, offset)


@bp.route("/zones/access-badges/<badgeId>", methods=["GET"])
def get_badge(badgeId):
    authorized(ALL_ROLES)
    badge = require_path("access_badges", badgeId, ERR_BADGE_NOT_FOUND)
    return success_object(badge_view(badge))


@bp.route("/zones/access-badges/<badgeId>/transition", methods=["POST"])
def transition_badge(badgeId):
    caller = authorized(["ZoneOperator"])
    badge = require_path("access_badges", badgeId, ERR_BADGE_NOT_FOUND)
    body = get_body()
    reject_unknown_fields(body, {"to_status"})
    to_status = req_enum(body, "to_status", {"SUSPENDED", "ACTIVE", "REVOKED"})

    if to_status not in _BADGE_TRANSITIONS.get(badge["status"], set()):
        raise_error(ERR_BADGE_INVALID_TRANSITION,
                    f"badge cannot move from {badge['status']} to {to_status}")
    zone = db["zones"][badge["zone_id"]]
    if zone["status"] != "ACTIVE":
        raise_error(ERR_ZONE_NOT_ACTIVE, "operation requires zone.status == ACTIVE")

    badge["status"] = to_status
    touch(badge)
    return success_object(badge_view(badge))
