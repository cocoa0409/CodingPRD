"""Terminal endpoints."""
import re
from zoneinfo import ZoneInfo

from flask import Blueprint

import db
from errors import err_invalid_request, err_invalid_state
from middleware import require_roles
from response import success, success_list
from routes.common import (as_int, body_json, get_path, new_record, paginate,
                           ser_terminal, touch)

bp = Blueprint("terminals", __name__)

_CODE_RE = re.compile(r"^[A-Z]{3}$")
_READ_ROLES = ("TerminalAdmin", "Dispatcher", "DockSupervisor", "RatingClerk", "OsdClerk")


@bp.route("/ltl/terminals", methods=["POST"])
@require_roles("TerminalAdmin")
def create_terminal():
    body = body_json()
    code = body.get("code")
    if not isinstance(code, str) or not _CODE_RE.match(code):
        raise err_invalid_request("code must be exactly three uppercase letters A-Z")
    if any(t["code"] == code for t in db.store["terminals"].values()):
        raise err_invalid_request("code must be unique across terminals")
    name = body.get("name")
    if not isinstance(name, str) or not name:
        raise err_invalid_request("name must be a non-empty string")
    dock_doors = as_int(body, "dock_doors", minimum=1)
    timezone_name = body.get("timezone", "America/Chicago")
    if not isinstance(timezone_name, str):
        raise err_invalid_request("timezone must be an IANA timezone name")
    try:
        ZoneInfo(timezone_name)
    except Exception:
        raise err_invalid_request("timezone must be a valid IANA timezone name")
    rec = new_record({
        "code": code, "name": name, "dock_doors": dock_doors,
        "timezone": timezone_name, "status": "ACTIVE",
    })
    db.store["terminals"][rec["id"]] = rec
    return success(ser_terminal(rec), 201)


@bp.route("/ltl/terminals", methods=["GET"])
@require_roles(*_READ_ROLES)
def list_terminals():
    page, total, limit, offset = paginate(db.store["terminals"].values())
    return success_list([ser_terminal(t) for t in page], total, limit, offset)


@bp.route("/ltl/terminals/<terminalId>", methods=["GET"])
@require_roles(*_READ_ROLES)
def get_terminal(terminalId):
    return success(ser_terminal(get_path("terminals", terminalId)))


@bp.route("/ltl/terminals/<terminalId>/close", methods=["POST"])
@require_roles("TerminalAdmin")
def close_terminal(terminalId):
    terminal = get_path("terminals", terminalId)
    if terminal["status"] != "ACTIVE":
        raise err_invalid_state("Only an ACTIVE terminal can be closed")
    terminal["status"] = "CLOSED"
    touch(terminal)
    return success(ser_terminal(terminal))
