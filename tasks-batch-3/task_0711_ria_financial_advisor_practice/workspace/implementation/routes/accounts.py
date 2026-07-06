"""Account endpoints, valuation, and state machine (PRD §3.3)."""

from flask import Blueprint, request

from db import db
from errors import err
from middleware import authenticate, authorize
from response import created, ok, list_ok
from services.common import stamp_new, touch
from services.lookup import get_or_404, ref_or_422
from services.recompute import recompute_household_aggregation, recompute_account_drift
from util import (body, require_str, require_enum, require_bool, opt_nonneg_int,
                  require_nonneg_int, pagination, paginate)

bp = Blueprint("accounts", __name__)

READ_ROLES = {"Advisor", "ComplianceOfficer", "BillingAdmin"}
ACCOUNT_TYPES = {"TAXABLE", "IRA", "ROTH", "TRUST", "HELD_AWAY_401K"}
ACTIONS = {"ACTIVATE", "FREEZE", "UNFREEZE", "CLOSE"}


def serialize(a):
    return {
        "id": a["id"],
        "household_id": a["household_id"],
        "client_id": a["client_id"],
        "custodian": a["custodian"],
        "account_type": a["account_type"],
        "held_away": a["held_away"],
        "billable": a["billable"],
        "market_value_cents": a["market_value_cents"],
        "equity_value_cents": a["equity_value_cents"],
        "drift_bps": a["drift_bps"],
        "rebalance_flagged": a["rebalance_flagged"],
        "status": a["status"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


@bp.route("/accounts", methods=["POST"])
def create():
    _, role = authenticate()
    authorize(role, {"Advisor"})
    data = body()
    household_id = require_str(data, "household_id")
    client_id = require_str(data, "client_id")
    custodian = require_str(data, "custodian")
    account_type = require_enum(data, "account_type", ACCOUNT_TYPES)
    held_away = require_bool(data, "held_away", False)
    billable = require_bool(data, "billable", True)
    market_value_cents = opt_nonneg_int(data, "market_value_cents", 0)
    equity_value_cents = opt_nonneg_int(data, "equity_value_cents", 0)
    # body-reference existence (priority 4)
    ref_or_422(db.households, household_id, "household_id")
    ref_or_422(db.clients, client_id, "client_id")
    # allocation validity (priority 11)
    if equity_value_cents > market_value_cents:
        raise err("ERR_ALLOCATION_INVALID", "equity_value_cents exceeds market_value_cents")
    a = {
        "household_id": household_id,
        "client_id": client_id,
        "custodian": custodian,
        "account_type": account_type,
        "held_away": held_away,
        "billable": billable,
        "market_value_cents": market_value_cents,
        "equity_value_cents": equity_value_cents,
        "drift_bps": 0,
        "rebalance_flagged": False,
        "status": "PENDING",
    }
    stamp_new(a)
    db.accounts[a["id"]] = a
    return created(serialize(a))


@bp.route("/accounts/<aid>", methods=["GET"])
def read(aid):
    _, role = authenticate()
    authorize(role, READ_ROLES)
    a = get_or_404(db.accounts, aid)
    return ok(serialize(a))


@bp.route("/accounts", methods=["GET"])
def list_():
    _, role = authenticate()
    authorize(role, READ_ROLES)
    limit, offset = pagination()
    household_id = request.args.get("household_id")
    client_id = request.args.get("client_id")
    items = list(db.accounts.values())
    if household_id is not None:
        items = [a for a in items if a["household_id"] == household_id]
    if client_id is not None:
        items = [a for a in items if a["client_id"] == client_id]
    items = sorted(items, key=lambda x: (x["created_at"], x["id"]))
    page = paginate(items, limit, offset)
    return list_ok([serialize(x) for x in page], limit, offset, len(items))


@bp.route("/accounts/<aid>/valuation", methods=["POST"])
def valuation(aid):
    _, role = authenticate()
    authorize(role, {"Advisor"})
    a = get_or_404(db.accounts, aid)
    data = body()
    market_value_cents = require_nonneg_int(data, "market_value_cents")
    equity_value_cents = require_nonneg_int(data, "equity_value_cents")
    if equity_value_cents > market_value_cents:
        raise err("ERR_ALLOCATION_INVALID", "equity_value_cents exceeds market_value_cents")
    a["market_value_cents"] = market_value_cents
    a["equity_value_cents"] = equity_value_cents
    touch(a)
    # reconcile drift then household aggregation/tier
    recompute_account_drift(a)
    household = db.households.get(a["household_id"])
    if household:
        recompute_household_aggregation(household, include_tier=True)
    return ok(serialize(a))


@bp.route("/accounts/<aid>/state", methods=["POST"])
def state(aid):
    _, role = authenticate()
    authorize(role, {"Advisor"})
    a = get_or_404(db.accounts, aid)
    data = body()
    action = require_enum(data, "action", ACTIONS)
    household = db.households.get(a["household_id"])

    if action == "ACTIVATE":
        if a["status"] != "PENDING":
            raise err("ERR_INVALID_STATE", "ACTIVATE requires PENDING")
        client = db.clients.get(a["client_id"])
        if client is None or client["onboarding_status"] not in {"IPS_SIGNED", "ACTIVE"}:
            raise err("ERR_CROSS_ENTITY_PRECONDITION",
                      "Owning client must be IPS_SIGNED or ACTIVE")
        if household is None or household["status"] != "ACTIVE":
            raise err("ERR_CROSS_ENTITY_PRECONDITION", "Owning household must be ACTIVE")
        a["status"] = "ACTIVE"
        touch(a)
        recompute_household_aggregation(household, include_tier=True)

    elif action == "FREEZE":
        if a["status"] != "ACTIVE":
            raise err("ERR_INVALID_STATE", "FREEZE requires ACTIVE")
        a["status"] = "FROZEN"
        touch(a)
        # cancel any PROPOSED rebalance order for this account
        for order in db.rebalance_orders.values():
            if order["account_id"] == aid and order["status"] == "PROPOSED":
                order["status"] = "REJECTED"
                touch(order)
        if household:
            recompute_household_aggregation(household, include_tier=False)

    elif action == "UNFREEZE":
        if a["status"] != "FROZEN":
            raise err("ERR_INVALID_STATE", "UNFREEZE requires FROZEN")
        if household is None or household["status"] != "ACTIVE":
            raise err("ERR_INVALID_STATE", "Owning household must be ACTIVE")
        a["status"] = "ACTIVE"
        touch(a)
        recompute_household_aggregation(household, include_tier=False)

    elif action == "CLOSE":
        if a["status"] not in {"ACTIVE", "FROZEN"}:
            raise err("ERR_INVALID_STATE", "CLOSE requires ACTIVE or FROZEN")
        # no open fee run referencing owning household in DRAFT/CALCULATED
        open_run = any(
            r["household_id"] == a["household_id"] and r["status"] in {"DRAFT", "CALCULATED"}
            for r in db.fee_runs.values()
        )
        if open_run:
            raise err("ERR_FEE_RUN_OPEN", "Cannot close account while a fee run is in flight")
        a["status"] = "CLOSED"
        touch(a)
        if household:
            recompute_household_aggregation(household, include_tier=True)

    return ok(serialize(a))


@bp.route("/accounts/<aid>/rebalance-orders", methods=["GET"])
def list_rebalance_orders(aid):
    from routes.rebalance import serialize as serialize_order
    _, role = authenticate()
    authorize(role, READ_ROLES)
    get_or_404(db.accounts, aid)
    limit, offset = pagination()
    items = [o for o in db.rebalance_orders.values() if o["account_id"] == aid]
    items = sorted(items, key=lambda x: (x["created_at"], x["id"]))
    page = paginate(items, limit, offset)
    return list_ok([serialize_order(x) for x in page], limit, offset, len(items))
