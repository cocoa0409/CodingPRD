"""Permit endpoints: request, list, get, approve, revoke (with movement
suspension cascade for vapor-controlled tanks)."""
from flask import Blueprint, request

from clock import CLOCK
from db import STORE, new_id
from errors import err
from middleware import require_roles, current_user
from response import success_object, success_list
from serializers import permit_view
from services.common import touch, lazy_permit, get_tank_or_404
from validation import (get_body, req_enum, req_string, req_datetime, opt_string,
                        sort_and_page, PERMIT_TYPES)

bp = Blueprint("permits", __name__)


def _get_permit_or_404(permit_id):
    permit = STORE.permits.get(permit_id)
    if permit is None:
        raise err("ERR_PERMIT_NOT_FOUND", "Permit %s not found" % permit_id)
    lazy_permit(permit)
    return permit


@bp.post("/permits")
def create_permit():
    require_roles("TerminalOperator")
    body = get_body()
    permit_type = req_enum(body, "permit_type", PERMIT_TYPES)
    tank_id = req_string(body, "tank_id")
    valid_from = req_datetime(body, "valid_from")
    valid_until = req_datetime(body, "valid_until")
    if not valid_until > valid_from:
        raise err("ERR_VALIDATION", "valid_until must be strictly after valid_from")
    get_tank_or_404(tank_id)
    now = CLOCK.now()
    permit = {
        "id": new_id(),
        "permit_type": permit_type,
        "tank_id": tank_id,
        "valid_from": valid_from,
        "valid_until": valid_until,
        "status": "REQUESTED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    STORE.permits[permit["id"]] = permit
    return success_object(permit_view(permit), status=201)


@bp.get("/permits")
def list_permits():
    current_user()
    rows = list(STORE.permits.values())
    tank_id = request.args.get("tank_id")
    if tank_id is not None:
        rows = [p for p in rows if p["tank_id"] == tank_id]
    permit_type = request.args.get("permit_type")
    if permit_type is not None:
        rows = [p for p in rows if p["permit_type"] == permit_type]
    for p in rows:
        lazy_permit(p)
    status_filter = request.args.get("status")
    if status_filter is not None:
        rows = [p for p in rows if p["status"] == status_filter]
    page, total, limit, offset = sort_and_page(rows)
    return success_list([permit_view(p) for p in page], total, limit, offset)


@bp.get("/permits/<permitId>")
def get_permit(permitId):
    current_user()
    permit = _get_permit_or_404(permitId)
    return success_object(permit_view(permit))


@bp.post("/permits/<permitId>/approve")
def approve_permit(permitId):
    require_roles("TerminalManager")
    permit = _get_permit_or_404(permitId)
    if permit["status"] != "REQUESTED":
        raise err("ERR_INVALID_STATE",
                  "Permit %s is %s; approve requires REQUESTED"
                  % (permitId, permit["status"]))
    permit["status"] = "APPROVED"
    touch(permit)
    return success_object(permit_view(permit))


@bp.post("/permits/<permitId>/revoke")
def revoke_permit(permitId):
    require_roles("TerminalManager")
    body = get_body()
    opt_string(body, "revoked_reason")
    permit = _get_permit_or_404(permitId)
    if permit["status"] != "APPROVED":
        raise err("ERR_INVALID_STATE",
                  "Permit %s is %s; revoke requires APPROVED"
                  % (permitId, permit["status"]))
    permit["status"] = "REVOKED"
    touch(permit)
    # Cascade: IN_PROGRESS movements on this tank of a VRU_REQUIRED tank
    # transition to SUSPENDED (PRD 2.8).
    tank = STORE.tanks.get(permit["tank_id"])
    if tank is not None and tank["vapor_control_class"] == "VRU_REQUIRED":
        for m in STORE.movements.values():
            if m["tank_id"] == tank["id"] and m["status"] == "IN_PROGRESS":
                m["status"] = "SUSPENDED"
                touch(m)
    return success_object(permit_view(permit))
