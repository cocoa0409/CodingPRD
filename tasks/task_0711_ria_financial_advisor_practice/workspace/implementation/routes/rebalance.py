"""RebalanceOrder endpoints & state machine (PRD §3.7)."""

from flask import Blueprint, request

from db import db
from errors import err
from middleware import authenticate, authorize
from response import created, ok, list_ok
from services.common import stamp_new, touch
from services.lookup import get_or_404, ref_or_422
from services.recompute import recompute_account_drift, _approved_ips_for_client
from util import body, require_str, require_enum, pagination, paginate
from util import round_half_up

bp = Blueprint("rebalance", __name__)

READ_ROLES = {"Advisor", "ComplianceOfficer", "BillingAdmin"}
ACTIONS = {"APPROVE", "REJECT", "EXECUTE"}


def serialize(o):
    return {
        "id": o["id"],
        "account_id": o["account_id"],
        "target_portfolio_id": o["target_portfolio_id"],
        "trade_equity_delta_cents": o["trade_equity_delta_cents"],
        "status": o["status"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


def _target_equity_cents(account, model_equity_pct):
    return round_half_up(account["market_value_cents"] * model_equity_pct / 100)


@bp.route("/rebalance-orders", methods=["POST"])
def create():
    _, role = authenticate()
    authorize(role, {"Advisor"})
    data = body()
    account_id = require_str(data, "account_id")
    account = ref_or_422(db.accounts, account_id, "account_id")
    ips = _approved_ips_for_client(account["client_id"])
    if ips is None:
        raise err("ERR_NO_APPROVED_IPS", "Account's client has no APPROVED IPS")
    portfolio = db.portfolios.get(ips["target_portfolio_id"])
    model_equity_pct = portfolio["model_equity_pct"] if portfolio else 0
    target_equity = _target_equity_cents(account, model_equity_pct)
    delta = target_equity - account["equity_value_cents"]
    o = {
        "account_id": account_id,
        "target_portfolio_id": ips["target_portfolio_id"],
        "trade_equity_delta_cents": delta,
        "status": "PROPOSED",
    }
    stamp_new(o)
    db.rebalance_orders[o["id"]] = o
    return created(serialize(o))


@bp.route("/rebalance-orders/<oid>", methods=["GET"])
def read(oid):
    _, role = authenticate()
    authorize(role, READ_ROLES)
    o = get_or_404(db.rebalance_orders, oid)
    return ok(serialize(o))


@bp.route("/rebalance-orders", methods=["GET"])
def list_():
    _, role = authenticate()
    authorize(role, READ_ROLES)
    limit, offset = pagination()
    account_id = request.args.get("account_id")
    target_portfolio_id = request.args.get("target_portfolio_id")
    items = list(db.rebalance_orders.values())
    if account_id is not None:
        items = [x for x in items if x["account_id"] == account_id]
    if target_portfolio_id is not None:
        items = [x for x in items if x["target_portfolio_id"] == target_portfolio_id]
    items = sorted(items, key=lambda x: (x["created_at"], x["id"]))
    page = paginate(items, limit, offset)
    return list_ok([serialize(x) for x in page], limit, offset, len(items))


@bp.route("/rebalance-orders/<oid>/state", methods=["POST"])
def state(oid):
    _, role = authenticate()
    authorize(role, {"Advisor", "ComplianceOfficer"})
    o = get_or_404(db.rebalance_orders, oid)
    data = body()
    action = require_enum(data, "action", ACTIONS)
    account = db.accounts.get(o["account_id"])

    if action == "APPROVE":
        authorize(role, {"ComplianceOfficer"})
        if o["status"] != "PROPOSED":
            raise err("ERR_INVALID_STATE", "APPROVE requires PROPOSED")
        if account is None or account["status"] != "ACTIVE":
            raise err("ERR_CROSS_ENTITY_PRECONDITION", "Linked account must be ACTIVE")
        ips = _approved_ips_for_client(account["client_id"]) if account else None
        if ips is None:
            raise err("ERR_CROSS_ENTITY_PRECONDITION",
                      "Account's client must have an APPROVED IPS")
        o["status"] = "APPROVED"
        touch(o)

    elif action == "REJECT":
        authorize(role, {"ComplianceOfficer"})
        if o["status"] != "PROPOSED":
            raise err("ERR_INVALID_STATE", "REJECT requires PROPOSED")
        o["status"] = "REJECTED"
        touch(o)

    elif action == "EXECUTE":
        authorize(role, {"Advisor"})
        if o["status"] != "APPROVED":
            raise err("ERR_INVALID_STATE", "EXECUTE requires APPROVED")
        if account is None or account["status"] != "ACTIVE":
            raise err("ERR_INVALID_STATE", "Linked account must be ACTIVE")
        portfolio = db.portfolios.get(o["target_portfolio_id"])
        model_equity_pct = portfolio["model_equity_pct"] if portfolio else 0
        account["equity_value_cents"] = _target_equity_cents(account, model_equity_pct)
        touch(account)
        recompute_account_drift(account)
        o["status"] = "EXECUTED"
        touch(o)

    return ok(serialize(o))
