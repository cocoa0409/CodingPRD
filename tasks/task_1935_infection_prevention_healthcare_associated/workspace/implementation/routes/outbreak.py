"""OutbreakInvestigations."""
from flask import Blueprint, request

import db
from errors import (
    ERR_DUPLICATE_OUTBREAK_OPEN,
    ERR_INVALID_REQUEST,
    ERR_OUTBREAK_CLOSE_BLOCKED,
    ERR_OUTBREAK_EMPTY_CLUSTER,
    ERR_OUTBREAK_NOT_CLOSABLE,
    ERR_OUTBREAK_NOT_CONFIRMABLE,
    ERR_OUTBREAK_NOT_FOUND,
    ERR_UNIT_NOT_FOUND,
    raise_err,
)
from middleware import ALL_ROLES, require_roles
from response import success_list, success_object
from services.core import manual_investigation, recompute_posture, touch, _organism_eq, _open_investigation_exists
from services.serializers import outbreak_view
from validate import body, pagination_args, req_string

bp = Blueprint("outbreak", __name__)


@bp.post("/api/outbreak-investigations")
def create_investigation():
    require_roles(["InfectionPreventionist"])
    b = body()
    for f in ("unit_id", "organism"):
        if f not in b or b[f] is None:
            raise_err(ERR_INVALID_REQUEST, f"Missing required field: {f}")
    unit_id = b.get("unit_id")
    if not isinstance(unit_id, str) or not unit_id:
        raise_err(ERR_INVALID_REQUEST, "unit_id must be a string")
    organism = req_string(b, "organism")

    unit = db.units.get(unit_id)
    if unit is None:
        raise_err(ERR_UNIT_NOT_FOUND, "unit id does not exist")

    if _open_investigation_exists(unit_id, organism):
        raise_err(ERR_DUPLICATE_OUTBREAK_OPEN, "an open investigation already exists for this unit + organism")

    inv = manual_investigation(unit_id, organism)
    return success_object(outbreak_view(inv), 201)


@bp.get("/api/outbreak-investigations")
def list_investigations():
    require_roles(ALL_ROLES)
    limit, offset = pagination_args()
    unit_id = request.args.get("unit_id")
    status = request.args.get("status")

    def _match(o):
        if unit_id is not None and o["unit_id"] != unit_id:
            return False
        if status is not None and o["status"] != status:
            return False
        return True

    items = [o for o in db.outbreak_investigations.values() if _match(o)]
    items.sort(key=lambda o: o["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([outbreak_view(o) for o in page], total, limit, offset)


@bp.get("/api/outbreak-investigations/<oid>")
def get_investigation(oid):
    require_roles(ALL_ROLES)
    o = db.outbreak_investigations.get(oid)
    if o is None:
        raise_err(ERR_OUTBREAK_NOT_FOUND, "outbreak investigation id does not exist")
    return success_object(outbreak_view(o))


@bp.post("/api/outbreak-investigations/<oid>/confirm")
def confirm_investigation(oid):
    require_roles(["InfectionControlDirector"])
    o = db.outbreak_investigations.get(oid)
    if o is None:
        raise_err(ERR_OUTBREAK_NOT_FOUND, "outbreak investigation id does not exist")
    if o["status"] != "TRIGGERED":
        raise_err(ERR_OUTBREAK_NOT_CONFIRMABLE, "confirm requires status TRIGGERED")
    if o["contributing_case_count"] < 1:
        raise_err(ERR_OUTBREAK_EMPTY_CLUSTER, "confirm requires at least one contributing case")
    o["status"] = "CONFIRMED"
    touch(o)
    recompute_posture(o["unit_id"])
    return success_object(outbreak_view(o))


@bp.post("/api/outbreak-investigations/<oid>/rule-out")
def rule_out_investigation(oid):
    require_roles(["InfectionControlDirector"])
    b = body()
    if "reason" not in b or b["reason"] is None:
        raise_err(ERR_INVALID_REQUEST, "Missing required field: reason")
    o = db.outbreak_investigations.get(oid)
    if o is None:
        raise_err(ERR_OUTBREAK_NOT_FOUND, "outbreak investigation id does not exist")
    if o["status"] != "TRIGGERED":
        raise_err(ERR_OUTBREAK_NOT_CONFIRMABLE, "rule-out requires status TRIGGERED")
    o["status"] = "RULED_OUT"
    touch(o)
    recompute_posture(o["unit_id"])
    return success_object(outbreak_view(o))


@bp.post("/api/outbreak-investigations/<oid>/close")
def close_investigation(oid):
    require_roles(["InfectionControlDirector"])
    o = db.outbreak_investigations.get(oid)
    if o is None:
        raise_err(ERR_OUTBREAK_NOT_FOUND, "outbreak investigation id does not exist")
    if o["status"] not in ("CONFIRMED", "RULED_OUT"):
        raise_err(ERR_OUTBREAK_NOT_CLOSABLE, "close requires status CONFIRMED or RULED_OUT")
    if o["status"] == "CONFIRMED":
        has_verified_cap = any(
            c for c in db.corrective_action_plans.values()
            if c["source_type"] == "OUTBREAK" and c["source_ref_id"] == o["id"] and c["status"] == "VERIFIED"
        )
        if not has_verified_cap:
            raise_err(ERR_OUTBREAK_CLOSE_BLOCKED, "closing a CONFIRMED investigation requires a VERIFIED outbreak CAP")
    o["status"] = "CLOSED"
    touch(o)
    recompute_posture(o["unit_id"])
    return success_object(outbreak_view(o))
