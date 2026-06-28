"""CommissionSettlement endpoints + settlement snapshot (PRD 3.8)."""
from flask import Blueprint, request

from db import db
from errors import err
from middleware import get_auth, require_roles
from models import (_stamp_create, serialize, touch, get_or_404,
                    parse_pagination, paginate, sort_by_created)
from response import success
from util import parse_iso8601
from validate import require_body, req_str, req_int
from calculations import commission_settlement_calc

settlements_bp = Blueprint("settlements", __name__)


def _serialize_settlement(s):
    return serialize(s)


def _window_tickets(retailer_id, period_start, period_end):
    terminal_ids = {t["id"] for t in db.terminals.values()
                    if t["retailer_id"] == retailer_id}
    rows = []
    for t in db.tickets.values():
        if t["terminal_id"] in terminal_ids:
            if period_start <= t["created_at"] < period_end:
                rows.append(t)
    return rows


@settlements_bp.route("/commission-settlements", methods=["POST"])
def create_settlement():
    user_id, role = get_auth()
    require_roles(role, {"LotteryOfficer"})
    body = require_body(request.get_json(silent=True))

    retailer_id = req_str(body, "retailer_id")
    period_start_raw = body.get("period_start")
    period_end_raw = body.get("period_end")
    if period_start_raw is None:
        raise err("ERR_INVALID_REQUEST", "period_start is required")
    if period_end_raw is None:
        raise err("ERR_INVALID_REQUEST", "period_end is required")
    expected_version = req_int(body, "expected_retailer_version")

    period_start = parse_iso8601(period_start_raw, "period_start")
    period_end = parse_iso8601(period_end_raw, "period_end")

    # Existence (priority 3).
    retailer = get_or_404(db.retailers, retailer_id, "retailer")

    # OCC (priority 5).
    if expected_version != retailer["version"]:
        raise err("ERR_STALE_VERSION", "retailer version stale")

    window = _window_tickets(retailer_id, period_start, period_end)
    figures = commission_settlement_calc(retailer, window)

    settlement = {
        "retailer_id": retailer_id,
        "period_start": period_start,
        "period_end": period_end,
        "prepared_by_user_id": user_id,
        "approved_by_user_id": None,
        "gross_commission_cents": figures["gross_commission_cents"],
        "clawback_cents": figures["clawback_cents"],
        "net_settlement_cents": figures["net_settlement_cents"],
        "status": "DRAFT",
    }
    _stamp_create(settlement)
    db.settlements[settlement["id"]] = settlement

    # Preparing a settlement increments the retailer's version.
    touch(retailer)

    return success(_serialize_settlement(settlement), 201)


@settlements_bp.route("/commission-settlements/<sid>", methods=["GET"])
def get_settlement(sid):
    _, role = get_auth()
    require_roles(role, {"LotteryOfficer"})
    settlement = get_or_404(db.settlements, sid, "settlement")
    return success(_serialize_settlement(settlement), 200)


@settlements_bp.route("/commission-settlements", methods=["GET"])
def list_settlements():
    _, role = get_auth()
    require_roles(role, {"LotteryOfficer"})
    limit, offset = parse_pagination(request.args)
    rows = list(db.settlements.values())
    for key in ("retailer_id", "status"):
        f = request.args.get(key)
        if f is not None:
            rows = [s for s in rows if s[key] == f]
    rows = sort_by_created(rows)
    page, meta = paginate(rows, limit, offset)
    return success([_serialize_settlement(s) for s in page], 200, pagination=meta)


@settlements_bp.route("/commission-settlements/<sid>/finalize", methods=["POST"])
def finalize_settlement(sid):
    user_id, role = get_auth()
    require_roles(role, {"LotteryOfficer"})
    settlement = get_or_404(db.settlements, sid, "settlement")
    if settlement["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "settlement not DRAFT")
    # Segregation of duties: approver differs from preparer.
    if user_id == settlement["prepared_by_user_id"]:
        raise err("ERR_SEGREGATION_OF_DUTIES", "approver must differ from preparer")
    settlement["status"] = "FINALIZED"
    settlement["approved_by_user_id"] = user_id
    touch(settlement)
    # Ledger sync on the retailer.
    retailer = db.retailers.get(settlement["retailer_id"])
    if retailer is not None:
        net = settlement["net_settlement_cents"]
        retailer["commission_balance_cents"] = max(0, retailer["commission_balance_cents"] - net)
        retailer["lifetime_settled_cents"] += net
        touch(retailer)
    return success(_serialize_settlement(settlement), 200)


@settlements_bp.route("/commission-settlements/<sid>/void", methods=["POST"])
def void_settlement(sid):
    _, role = get_auth()
    require_roles(role, {"LotteryOfficer"})
    settlement = get_or_404(db.settlements, sid, "settlement")
    if settlement["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "settlement not DRAFT")
    settlement["status"] = "VOIDED"
    touch(settlement)
    return success(_serialize_settlement(settlement), 200)
