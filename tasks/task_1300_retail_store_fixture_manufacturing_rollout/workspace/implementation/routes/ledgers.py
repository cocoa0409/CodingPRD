"""AtticStockLedger endpoints."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_LEDGER_NOT_FOUND,
    ERR_LEDGER_INVALID_STATE,
    ERR_PROGRAM_NOT_CLOSEOUT_PENDING,
    ERR_STALE_VERSION,
    ERR_STOCK_UNDERFLOW,
)
from middleware import require_roles
from response import success_object, success_list
from services.calculations import attic_recovery_value, reorder_required
from services.serializers import serialize, serialize_list
from util import (
    apply_filters,
    get_json_body,
    paginate,
    parse_pagination,
    require_enum,
    sort_by_created_at,
)

bp = Blueprint("ledgers", __name__)

DISPOSITION_TYPES = {"RETURN_VENDOR", "SCRAP", "DONATE"}


def _get_ledger_or_404(ledger_id: str) -> dict:
    ledger = db.ledgers.get(ledger_id)
    if ledger is None:
        raise_err(ERR_LEDGER_NOT_FOUND, "AtticStockLedger id does not exist")
    return ledger


@bp.route("/attic-stock-ledgers", methods=["GET"])
@require_roles("Any")
def list_ledgers(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = sort_by_created_at(list(db.ledgers.values()))
    items = apply_filters(items, ["kit_id", "status"])
    page, total = paginate(items, limit, offset)
    return success_list(serialize_list(page), limit, offset, total)


@bp.route("/attic-stock-ledgers/<ledger_id>", methods=["GET"])
@require_roles("Any")
def get_ledger(ledger_id: str, _user_id: str, _role: str):
    ledger = _get_ledger_or_404(ledger_id)
    return success_object(serialize(ledger))


@bp.route("/attic-stock-ledgers/<ledger_id>/adjust", methods=["POST"])
@require_roles("WarehouseLead")
def adjust_ledger(ledger_id: str, _user_id: str, _role: str):
    ledger = _get_ledger_or_404(ledger_id)
    if ledger["status"] not in ("ACTIVE", "DEPLETED"):
        raise_err(ERR_LEDGER_INVALID_STATE, "adjust requires ledger ACTIVE or DEPLETED")
    body = get_json_body()

    delta = body.get("delta")
    if delta is None or isinstance(delta, bool) or not isinstance(delta, int):
        raise_err(ERR_INVALID_REQUEST, "delta is required and must be an integer")

    expected = body.get("expected_ledger_version")
    if expected is None or isinstance(expected, bool) or not isinstance(expected, int):
        raise_err(ERR_INVALID_REQUEST, "expected_ledger_version is required and must be an integer")
    if expected != ledger["version"]:
        raise_err(ERR_STALE_VERSION, "expected_ledger_version does not match the ledger's current version")

    new_qty = ledger["quantity_on_hand"] + delta
    if new_qty < 0:
        raise_err(ERR_STOCK_UNDERFLOW, "adjust would drive quantity_on_hand below 0")

    if "reorder_point" in body and body["reorder_point"] is not None:
        rp = body["reorder_point"]
        if isinstance(rp, bool) or not isinstance(rp, int):
            raise_err(ERR_INVALID_REQUEST, "reorder_point must be an integer")
        ledger["reorder_point"] = rp

    ledger["quantity_on_hand"] = new_qty
    ledger["reorder_required"] = reorder_required(ledger["quantity_on_hand"], ledger["reorder_point"])

    # Auto-oscillation ACTIVE <-> DEPLETED at quantity 0
    if new_qty == 0 and ledger["status"] == "ACTIVE":
        ledger["status"] = "DEPLETED"
    elif new_qty > 0 and ledger["status"] == "DEPLETED":
        ledger["status"] = "ACTIVE"

    db.touch(ledger)
    return success_object(serialize(ledger))


@bp.route("/attic-stock-ledgers/<ledger_id>/dispose", methods=["POST"])
@require_roles("ProgramManager")
def dispose_ledger(ledger_id: str, _user_id: str, _role: str):
    ledger = _get_ledger_or_404(ledger_id)
    if ledger["status"] not in ("ACTIVE", "DEPLETED"):
        raise_err(ERR_LEDGER_INVALID_STATE, "dispose requires ledger ACTIVE or DEPLETED")
    body = get_json_body()
    disposition_type = require_enum(body, "disposition_type", DISPOSITION_TYPES)

    kit = db.kits.get(ledger["kit_id"])
    program = db.programs.get(kit["program_id"]) if kit else None
    if program is None or program["status"] != "CLOSEOUT_PENDING":
        raise_err(ERR_PROGRAM_NOT_CLOSEOUT_PENDING, "dispose requires program CLOSEOUT_PENDING")

    recovery = attic_recovery_value(ledger, program, disposition_type)
    ledger["disposition_type"] = disposition_type
    ledger["recovery_value_cents"] = recovery
    program["closeout_recovery_cents"] += recovery
    db.touch(program)
    ledger["status"] = "DISPOSED"
    db.touch(ledger)
    return success_object(serialize(ledger))
