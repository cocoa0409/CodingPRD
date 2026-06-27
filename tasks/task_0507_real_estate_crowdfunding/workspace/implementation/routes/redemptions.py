"""Redemptions: queue, sweep, force-fulfill, window, cancel (PRD §3.7)."""
from decimal import Decimal

from flask import Blueprint, request

import db
from errors import err
from middleware import require_role
from response import success, list_success
from services import calc, domain, serialize
from services.paginate import get_pagination, order_and_page
from services import validate as V

bp = Blueprint("redemptions", __name__)

READ_ROLES = {"FundManager", "ComplianceOfficer", "Operator", "Investor"}


# ============================ CREATE ============================
@bp.post("/redemption-requests")
def create_redemption():
    user_id, _ = require_role({"Investor"})
    body = V.get_body()
    holding_id = V.req_str(body, "holding_id")
    shares_requested = V.req_number(body, "shares_requested")
    expected_holding_version = V.req_int(body, "expected_holding_version")

    holding = domain.get_holding(holding_id)

    # Ownership (priority 3): investor must own the holding
    if holding["investor_id"] != user_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Not the owner of this holding")

    # OCC (priority 6): expected_holding_version
    if holding["version"] != expected_holding_version:
        raise err("ERR_STALE_HOLDING_VERSION", "Stale holding version")

    fund = domain.fund_of_holding(holding)

    # Insufficient shares (priority 11): > 0 and <= shares_owned
    if shares_requested <= 0 or shares_requested > holding["shares_owned"]:
        raise err("ERR_INSUFFICIENT_SHARES", "Invalid shares_requested")

    # Winding-down prohibition (priority 12)
    if fund["status"] == "WINDING_DOWN":
        raise err("ERR_FUND_WINDING_DOWN", "Fund is winding down")

    e = db.base_fields()
    e.update({
        "holding_id": holding_id,
        "shares_requested": calc.round_shares(shares_requested),
        "status": "QUEUED",
        "queue_seq": db.next_queue_seq(),
        "gross_value_cents": None,
        "penalty_cents": None,
        "net_proceeds_cents": None,
        "penalty_tier_rate_bps": None,
    })
    db.redemption_requests[e["id"]] = e
    # Bumps parent holding's version (PRD §3.7)
    db.touch(holding)
    return success(serialize.redemption_request(e), status=201)


@bp.get("/redemption-requests/<rid>")
def get_redemption(rid):
    require_role(READ_ROLES)
    e = domain.get_redemption(rid)
    return success(serialize.redemption_request(e))


@bp.get("/redemption-requests")
def list_redemptions():
    require_role(READ_ROLES)
    limit, offset = get_pagination()
    items = list(db.redemption_requests.values())
    hid = request.args.get("holding_id")
    if hid is not None:
        items = [r for r in items if r["holding_id"] == hid]
    page, total = order_and_page(items, limit, offset)
    return list_success([serialize.redemption_request(r) for r in page], limit, offset, total)


@bp.post("/redemption-requests/<rid>/cancel")
def cancel_redemption(rid):
    user_id, _ = require_role({"Investor"})
    r = domain.get_redemption(rid)
    holding = domain.get_holding(r["holding_id"])
    # Ownership (priority 3)
    if holding["investor_id"] != user_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Not the owner of this redemption")
    if r["status"] not in ("QUEUED", "DEFERRED"):
        raise err("ERR_INVALID_STATE", "Redemption not cancellable")
    r["status"] = "CANCELLED"
    db.touch(r)
    return success(serialize.redemption_request(r))


# ============================ FULFILL CORE ============================
def _fulfill(request_obj, holding, fund):
    """Apply pricing + penalty + cascade for a QUEUED->FULFILLED transition.
    Returns the gross_value_cents of the fulfilled request."""
    shares = request_obj["shares_requested"]
    gross_value_cents = calc.gross_value(shares, fund["nav_per_share_cents"])
    age = calc.penalty_age_quarters(fund["current_valuation_seq"], holding["first_acquired_seq"])
    rate_bps = calc.penalty_tier_rate_bps(age)
    penalty_cents = calc.penalty_amount(gross_value_cents, rate_bps)
    net_proceeds_cents = gross_value_cents - penalty_cents

    # Holding cascade: shares_owned reduced; cost_basis reduced proportionally
    prev_shares = holding["shares_owned"]
    prev_basis = holding["cost_basis_cents"]
    if prev_shares > 0:
        proportion = Decimal(shares) / Decimal(prev_shares)
        basis_reduction = calc.round_cents(Decimal(prev_basis) * proportion)
    else:
        basis_reduction = 0
    holding["shares_owned"] = calc.round_shares(prev_shares - shares)
    holding["cost_basis_cents"] = prev_basis - basis_reduction
    if holding["shares_owned"] == 0:
        holding["first_acquired_seq"] = None

    request_obj["status"] = "FULFILLED"
    request_obj["gross_value_cents"] = gross_value_cents
    request_obj["penalty_cents"] = penalty_cents
    request_obj["net_proceeds_cents"] = net_proceeds_cents
    request_obj["penalty_tier_rate_bps"] = rate_bps

    # Fund cascade
    fund["total_capital_cents"] -= gross_value_cents
    domain.recompute_fund_derived(fund)

    db.touch(request_obj)
    db.touch(holding)
    db.touch(fund)
    return gross_value_cents


# ============================ FORCE-FULFILL ============================
@bp.post("/redemption-requests/<rid>/force-fulfill")
def force_fulfill(rid):
    require_role({"Operator"})
    r = domain.get_redemption(rid)
    if r["status"] != "QUEUED":
        raise err("ERR_INVALID_STATE", "Redemption not QUEUED")
    holding = domain.get_holding(r["holding_id"])
    fund = domain.fund_of_holding(holding)

    # Winding-down prohibition (priority 12)
    if fund["status"] == "WINDING_DOWN":
        raise err("ERR_FUND_WINDING_DOWN", "Fund is winding down")

    # Share sufficiency (priority 11)
    if holding["shares_owned"] < r["shares_requested"]:
        raise err("ERR_INSUFFICIENT_SHARES", "Holding has insufficient shares")

    # Cap check: gross_value must not push fulfilled gross above quarterly cap.
    cap = calc.redemption_cap(fund["total_capital_cents"])
    gross_value_cents = calc.gross_value(r["shares_requested"], fund["nav_per_share_cents"])
    if gross_value_cents > cap:
        raise err("ERR_REDEMPTION_CAP_REACHED", "Would exceed quarterly redemption cap")

    _fulfill(r, holding, fund)
    return success(serialize.redemption_request(r))


# ============================ SWEEP ============================
@bp.post("/funds/<fund_id>/run-redemption-sweep")
def run_sweep(fund_id):
    require_role({"Operator"})
    fund = domain.get_fund(fund_id)
    # Winding-down prohibition (priority 12)
    if fund["status"] == "WINDING_DOWN":
        raise err("ERR_FUND_WINDING_DOWN", "Fund is winding down")

    # Cap at start of sweep
    cap = calc.redemption_cap(fund["total_capital_cents"])

    sc_ids = domain.share_class_ids_of_fund(fund_id)
    holding_ids = {h["id"] for h in db.holdings.values() if h["share_class_id"] in sc_ids}

    queued = [r for r in db.redemption_requests.values()
              if r["holding_id"] in holding_ids and r["status"] == "QUEUED"]
    queued.sort(key=lambda r: r["queue_seq"])

    running = 0
    for r in queued:
        holding = db.holdings[r["holding_id"]]
        # Share sufficiency is a fulfillment precondition (skip-not-fulfillable -> defer? )
        # Per state machine: QUEUED->FULFILLED requires shares_owned >= shares_requested.
        # If insufficient, it cannot fulfill; treat as not-fulfillable this sweep -> DEFERRED.
        if holding["shares_owned"] < r["shares_requested"]:
            r["status"] = "DEFERRED"
            db.touch(r)
            continue
        gross_value_cents = calc.gross_value(r["shares_requested"], fund["nav_per_share_cents"])
        if running + gross_value_cents <= cap:
            _fulfill(r, holding, fund)
            running += gross_value_cents
        else:
            r["status"] = "DEFERRED"
            db.touch(r)

    return success(serialize.fund(fund))


# ============================ OPEN WINDOW ============================
@bp.post("/funds/<fund_id>/open-redemption-window")
def open_window(fund_id):
    require_role({"Operator"})
    fund = domain.get_fund(fund_id)
    sc_ids = domain.share_class_ids_of_fund(fund_id)
    holding_ids = {h["id"] for h in db.holdings.values() if h["share_class_id"] in sc_ids}
    for r in db.redemption_requests.values():
        if r["holding_id"] in holding_ids and r["status"] == "DEFERRED":
            r["status"] = "QUEUED"
            db.touch(r)
    return success(serialize.fund(fund))
