"""Terminal endpoints + provisioning state machine (PRD 3.3)."""
from flask import Blueprint, request

from db import db
from errors import err
from middleware import get_auth, require_roles
from models import (_stamp_create, serialize, touch, get_or_404,
                    parse_pagination, paginate, sort_by_created)
from response import success
from validate import require_body, req_str

terminals_bp = Blueprint("terminals", __name__)


def _serialize_terminal(t):
    return serialize(t)


@terminals_bp.route("/terminals", methods=["POST"])
def create_terminal():
    _, role = get_auth()
    require_roles(role, {"LicensingAdmin"})
    body = require_body(request.get_json(silent=True))

    retailer_id = req_str(body, "retailer_id")
    serial_number = req_str(body, "serial_number")

    # Existence of FK retailer first (left-to-right).
    get_or_404(db.retailers, retailer_id, "retailer")

    for t in db.terminals.values():
        if t["serial_number"] == serial_number:
            raise err("ERR_DUPLICATE_RESOURCE", "serial_number already exists")

    terminal = {
        "retailer_id": retailer_id,
        "serial_number": serial_number,
        "status": "PROVISIONED",
        "tickets_sold_count": 0,
    }
    _stamp_create(terminal)
    db.terminals[terminal["id"]] = terminal
    return success(_serialize_terminal(terminal), 201)


@terminals_bp.route("/terminals/<tid>", methods=["GET"])
def get_terminal(tid):
    _, role = get_auth()
    require_roles(role, {"LotteryOfficer", "LicensingAdmin", "TerminalOperator"})
    terminal = get_or_404(db.terminals, tid, "terminal")
    return success(_serialize_terminal(terminal), 200)


@terminals_bp.route("/terminals", methods=["GET"])
def list_terminals():
    _, role = get_auth()
    require_roles(role, {"LotteryOfficer", "LicensingAdmin", "TerminalOperator"})
    limit, offset = parse_pagination(request.args)
    rows = list(db.terminals.values())
    retailer_f = request.args.get("retailer_id")
    if retailer_f is not None:
        rows = [t for t in rows if t["retailer_id"] == retailer_f]
    status_f = request.args.get("status")
    if status_f is not None:
        rows = [t for t in rows if t["status"] == status_f]
    rows = sort_by_created(rows)
    page, meta = paginate(rows, limit, offset)
    return success([_serialize_terminal(t) for t in page], 200, pagination=meta)


@terminals_bp.route("/terminals/<tid>/activate", methods=["POST"])
def activate_terminal(tid):
    _, role = get_auth()
    require_roles(role, {"LicensingAdmin"})
    terminal = get_or_404(db.terminals, tid, "terminal")
    if terminal["status"] != "PROVISIONED":
        raise err("ERR_INVALID_STATE", "terminal not PROVISIONED")
    retailer = db.retailers.get(terminal["retailer_id"])
    if retailer is None or retailer["license_status"] != "ACTIVE":
        raise err("ERR_RETAILER_NOT_LICENSED", "owning retailer not licensed")
    terminal["status"] = "ACTIVE"
    touch(terminal)
    return success(_serialize_terminal(terminal), 200)


@terminals_bp.route("/terminals/<tid>/deactivate", methods=["POST"])
def deactivate_terminal(tid):
    _, role = get_auth()
    require_roles(role, {"LicensingAdmin"})
    terminal = get_or_404(db.terminals, tid, "terminal")
    if terminal["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "terminal not ACTIVE")
    terminal["status"] = "DEACTIVATED"
    touch(terminal)
    return success(_serialize_terminal(terminal), 200)
