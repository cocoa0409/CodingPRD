from flask import Blueprint, request

from db import db
from errors import ApiError, ERR_TERMINAL_NOT_FROZEN, ERR_TERMINAL_NOT_OPEN, not_found
from helpers import (
    get_body, list_query, new_entity, ser_terminal, touch,
)
from middleware import ALL_ROLES, require_roles
from response import success_list, success_object

bp = Blueprint("terminals", __name__)


def _get_terminal(terminal_id):
    t = db.terminals.get(terminal_id)
    if t is None:
        raise not_found("Terminal {} does not exist".format(terminal_id))
    return t


@bp.post("/rack/terminals")
def create_terminal():
    require_roles(["PlatformAdmin"])
    body = get_body()
    t = new_entity({
        "terminal_code": body.get("terminal_code"),
        "legal_name": body.get("legal_name"),
        "state_code": body.get("state_code"),
        "county_code": body.get("county_code"),
        "city_code": body.get("city_code"),
        "rack_status": "OPEN",
        "inventory_gallons": 0,
        "daily_allocation_pool_gallons": 0,
    })
    db.terminals[t["id"]] = t
    return success_object(ser_terminal(t), 201)


@bp.get("/rack/terminals/<terminalId>")
def get_terminal(terminalId):
    require_roles(ALL_ROLES)
    return success_object(ser_terminal(_get_terminal(terminalId)))


@bp.get("/rack/terminals")
def list_terminals():
    require_roles(ALL_ROLES)
    page, total, limit, offset = list_query(
        db.terminals.values(), request.args, ["state_code", "rack_status"]
    )
    return success_list([ser_terminal(t) for t in page], total, limit, offset)


@bp.post("/rack/terminals/<terminalId>/freeze")
def freeze_terminal(terminalId):
    require_roles(["TerminalOperator"])
    t = _get_terminal(terminalId)
    if t["rack_status"] not in ("OPEN", "SHORTAGE"):
        raise ApiError(
            ERR_TERMINAL_NOT_OPEN, 409,
            "Terminal must be OPEN or SHORTAGE to freeze",
        )
    t["rack_status"] = "FROZEN"
    touch(t)
    return success_object(ser_terminal(t))


@bp.post("/rack/terminals/<terminalId>/unfreeze")
def unfreeze_terminal(terminalId):
    require_roles(["TerminalOperator"])
    t = _get_terminal(terminalId)
    if t["rack_status"] != "FROZEN":
        raise ApiError(
            ERR_TERMINAL_NOT_FROZEN, 409,
            "Terminal must be FROZEN to unfreeze",
        )
    t["rack_status"] = "OPEN"
    touch(t)
    return success_object(ser_terminal(t))


@bp.post("/rack/terminals/<terminalId>/inventory/adjust")
def adjust_inventory(terminalId):
    require_roles(["TerminalOperator"])
    t = _get_terminal(terminalId)
    body = get_body()
    delta = body.get("delta_gallons", 0)
    try:
        delta = int(delta)
    except (TypeError, ValueError):
        delta = 0
    t["inventory_gallons"] += delta
    touch(t)
    return success_object(ser_terminal(t))
