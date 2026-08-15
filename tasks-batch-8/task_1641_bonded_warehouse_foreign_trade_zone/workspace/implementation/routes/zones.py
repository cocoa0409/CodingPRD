"""Zone endpoints (SCAFFOLD 1.5, PRD 3.1)."""
from flask import Blueprint

from db import db
from errors import (
    raise_error, ERR_ZONE_NOT_FOUND, ERR_ZONE_INVALID_TRANSITION, ERR_ZONE_NOT_EMPTY,
)
from middleware import authorized
from response import success_object, success_list
from serializers import zone_view
from services import new_common, touch
from validate import get_body, reject_unknown_fields, req_str, req_int, req_enum, require_path, parse_pagination

bp = Blueprint("zones", __name__)

ALL_ROLES = ["ZoneOperator", "Importer", "CustomsOfficer", "GateOfficer"]

# Reachable operator transitions from each status (SCAFFOLD 1.2 Zone).
_ZONE_TRANSITIONS = {
    "ACTIVE": {"SUSPENDED", "DEACTIVATED"},
    "SUSPENDED": {"ACTIVE", "DEACTIVATED"},
    "DEACTIVATED": set(),
}


@bp.route("/zones", methods=["POST"])
def create_zone():
    caller = authorized(["ZoneOperator"])
    body = get_body()
    reject_unknown_fields(body, {"name", "zone_code", "bond_coverage_cents"})
    name = req_str(body, "name")
    zone_code = req_str(body, "zone_code")
    bond = req_int(body, "bond_coverage_cents", non_negative=True)

    zone = new_common()
    zone.update({
        "name": name,
        "zone_code": zone_code,
        "bond_coverage_cents": bond,
        "status": "ACTIVE",
        "compliance_posture": "NORMAL",
        "deferred_duty_exposure_cents": 0,
        "active_lot_count": 0,
    })
    db["zones"][zone["id"]] = zone
    return success_object(zone_view(zone), status=201)


@bp.route("/zones", methods=["GET"])
def list_zones():
    authorized(ALL_ROLES)
    limit, offset = parse_pagination()
    items = sorted(db["zones"].values(), key=lambda z: (z["created_at"], z["id"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([zone_view(z) for z in page], total, limit, offset)


@bp.route("/zones/<zoneId>", methods=["GET"])
def get_zone(zoneId):
    authorized(ALL_ROLES)
    zone = require_path("zones", zoneId, ERR_ZONE_NOT_FOUND)
    return success_object(zone_view(zone))


@bp.route("/zones/<zoneId>/transition", methods=["POST"])
def transition_zone(zoneId):
    caller = authorized(["ZoneOperator"])
    zone = require_path("zones", zoneId, ERR_ZONE_NOT_FOUND)
    body = get_body()
    reject_unknown_fields(body, {"to_status"})
    to_status = req_enum(body, "to_status", {"SUSPENDED", "ACTIVE", "DEACTIVATED"})

    if to_status not in _ZONE_TRANSITIONS.get(zone["status"], set()):
        raise_error(ERR_ZONE_INVALID_TRANSITION,
                    f"zone cannot move from {zone['status']} to {to_status}")
    if to_status == "DEACTIVATED" and zone["active_lot_count"] != 0:
        raise_error(ERR_ZONE_NOT_EMPTY, "zone deactivation requires active_lot_count == 0")

    zone["status"] = to_status
    touch(zone)
    return success_object(zone_view(zone))
