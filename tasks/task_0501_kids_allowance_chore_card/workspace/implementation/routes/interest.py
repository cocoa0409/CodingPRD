"""InterestMatchConfig + InterestAccrual, and InvestmentAccount + InvestmentOrder
endpoints (PRD §3.7, §3.8)."""
from datetime import timedelta

from flask import Blueprint, request

import db
import domain
import serialize
import validate
from clock import parse_iso8601, iso
from errors import err
from middleware import authenticate, require_role, get_json_body
from response import object_response, list_response

bp = Blueprint("interest", __name__)

DAYS_PER_YEAR = 365
BPS_DENOM = 10000


# --------------------- InterestMatchConfig + Accrual -----------------------
@bp.route("/child-accounts/<cid>/interest-match-config", methods=["GET"])
def get_child_config(cid):
    identity = authenticate()
    require_role(identity, {"Parent", "Child", "PlatformAdmin"})
    child = domain.get_child(cid)
    domain.check_child_owner(identity, child)
    items = [c for c in db.interest_match_configs.values() if c["child_account_id"] == cid]
    return list_response([serialize.interest_match_config(c) for c in items], request.args)


@bp.route("/interest-match-configs/<cfgid>", methods=["GET"])
def read_config(cfgid):
    identity = authenticate()
    require_role(identity, {"Parent", "Child", "PlatformAdmin"})
    cfg = domain.get_config(cfgid)
    child = domain.get_child(cfg["child_account_id"])
    domain.check_child_owner(identity, child)
    return object_response(serialize.interest_match_config(cfg))


@bp.route("/interest-match-configs/<cfgid>", methods=["PUT"])
def configure_config(cfgid):
    identity = authenticate()
    require_role(identity, {"Parent"})
    cfg = domain.get_config(cfgid)
    child = domain.get_child(cfg["child_account_id"])
    domain.check_child_owner(identity, child)
    body = get_json_body()

    rate = validate.require_int(body, "annual_rate_bps")
    cap = validate.require_int(body, "monthly_cap_cents")
    method = validate.require_enum(body, "accrual_method", {"WHOLE_PERIOD", "DAILY_AVERAGE"})
    validate.bound_min(rate, 0, "annual_rate_bps")
    validate.bound_min(cap, 0, "monthly_cap_cents")

    cfg["annual_rate_bps"] = rate
    cfg["monthly_cap_cents"] = cap
    cfg["accrual_method"] = method
    cfg["status"] = "ENABLED"
    db.touch(cfg)
    return object_response(serialize.interest_match_config(cfg))


@bp.route("/interest-match-configs/<cfgid>/accrue", methods=["POST"])
def accrue(cfgid):
    identity = authenticate()
    require_role(identity, {"Parent", "PlatformAdmin"})
    cfg = domain.get_config(cfgid)
    child = domain.get_child(cfg["child_account_id"])
    domain.check_family_owner_for_child(identity, child)
    body = get_json_body()

    period_days = validate.require_int(body, "period_days")
    validate.bound_positive(period_days, "period_days")
    avg_balance = None
    if cfg["accrual_method"] == "DAILY_AVERAGE":
        avg_balance = validate.optional_int(body, "avg_balance_cents", None)

    # State (priority 11): config must be ENABLED.
    if cfg["status"] != "ENABLED":
        raise err("ERR_INTEREST_DISABLED", "Interest config is disabled")

    # Money gates (family then child).
    domain.gate_money_movement(child)

    now = db.clock.current()
    window_start = now - timedelta(days=period_days)

    # Accrual-period overlap (PRD §3.7): new window start must be >= latest
    # prior accrued_at (adjacency allowed). Latest prior = max accrued_at,
    # tie-break by max created_at.
    priors = [a for a in db.interest_accruals.values()
              if a["interest_match_config_id"] == cfgid]
    if priors:
        latest = max(priors, key=lambda a: (a["accrued_at"], a["created_at"]))
        latest_accrued = parse_iso8601(latest["accrued_at"])
        if window_start < latest_accrued:
            raise err("ERR_ACCRUAL_PERIOD_OVERLAP", "Accrual window overlaps a prior accrual")

    # Base balance selection by variant.
    save_jar = domain.jar_of_type(child["id"], "SAVE")
    if cfg["accrual_method"] == "DAILY_AVERAGE":
        base = avg_balance if avg_balance is not None else save_jar["balance_cents"]
    else:
        base = save_jar["balance_cents"]

    raw_interest = domain.round_half_up_div(
        base * cfg["annual_rate_bps"] * period_days, BPS_DENOM * DAYS_PER_YEAR
    )
    matched = raw_interest
    if cfg["monthly_cap_cents"] and cfg["monthly_cap_cents"] > 0:
        matched = min(matched, cfg["monthly_cap_cents"])

    # Funding sufficiency (priority 22).
    fam = db.families[child["family_id"]]
    if fam["funding_balance_cents"] < matched:
        raise err("ERR_INSUFFICIENT_FUNDING", "Funding wallet cannot cover the match")

    fam["funding_balance_cents"] -= matched
    db.touch(fam)
    domain.credit_jar(save_jar, matched)

    rec = db.base_fields()
    rec.update({
        "interest_match_config_id": cfgid,
        "child_account_id": child["id"],
        "period_days": period_days,
        "period_start_at": iso(window_start),
        "matched_cents": matched,
        "accrued_at": iso(now),
    })
    db.interest_accruals[rec["id"]] = rec
    return object_response(serialize.interest_accrual(rec), status=201)


@bp.route("/interest-match-configs/<cfgid>/accruals", methods=["GET"])
def list_accruals(cfgid):
    identity = authenticate()
    require_role(identity, {"Parent", "PlatformAdmin"})
    cfg = domain.get_config(cfgid)
    child = domain.get_child(cfg["child_account_id"])
    domain.check_family_owner_for_child(identity, child)
    items = [a for a in db.interest_accruals.values()
             if a["interest_match_config_id"] == cfgid]
    return list_response([serialize.interest_accrual(a) for a in items], request.args)


# ------------------ InvestmentAccount + InvestmentOrder --------------------
@bp.route("/child-accounts/<cid>/investment-account", methods=["POST"])
def enable_investing(cid):
    identity = authenticate()
    require_role(identity, {"Parent"})
    child = domain.get_child(cid)
    domain.check_child_owner(identity, child)

    # State (priority 9): no existing investing account.
    if domain.investment_of_child(cid) is not None:
        raise err("ERR_DUPLICATE_INVEST_ACCOUNT", "Investing already enabled")
    # Child must be ACTIVE.
    if child["status"] == "ARCHIVED":
        raise err("ERR_CHILD_ARCHIVED", "Child account is archived")
    # Teen eligibility (priority 17).
    if not db.compute_is_teen(child):
        raise err("ERR_NOT_TEEN_ELIGIBLE", "Child is not teen-eligible")

    rec = db.base_fields()
    rec.update({
        "child_account_id": cid,
        "cash_cents": 0,
        "holdings": {},
        "status": "ACTIVE",
    })
    db.investment_accounts[rec["id"]] = rec
    return object_response(serialize.investment_account(rec), status=201)


@bp.route("/child-accounts/<cid>/investment-account", methods=["GET"])
def get_child_investment(cid):
    identity = authenticate()
    require_role(identity, {"Parent", "Child", "PlatformAdmin"})
    child = domain.get_child(cid)
    domain.check_child_owner(identity, child)
    items = [a for a in db.investment_accounts.values() if a["child_account_id"] == cid]
    return list_response([serialize.investment_account(a) for a in items], request.args)


@bp.route("/investment-accounts/<iid>", methods=["GET"])
def read_investment(iid):
    identity = authenticate()
    require_role(identity, {"Parent", "Child", "PlatformAdmin"})
    acct = domain.get_investment(iid)
    child = domain.get_child(acct["child_account_id"])
    domain.check_child_owner(identity, child)
    return object_response(serialize.investment_account(acct))


@bp.route("/investment-accounts/<iid>/fund", methods=["POST"])
def fund_investment(iid):
    identity = authenticate()
    require_role(identity, {"Parent"})
    acct = domain.get_investment(iid)
    child = domain.get_child(acct["child_account_id"])
    domain.check_child_owner(identity, child)
    body = get_json_body()
    amount = validate.require_int(body, "amount_cents")
    validate.bound_positive(amount, "amount_cents")

    save_jar = domain.jar_of_type(child["id"], "SAVE")
    if save_jar["balance_cents"] < amount:
        raise err("ERR_INSUFFICIENT_FUNDING", "SAVE jar has insufficient balance")
    domain.debit_jar(save_jar, amount, recompute=False)
    acct["cash_cents"] += amount
    db.touch(acct)
    return object_response(serialize.investment_account(acct))


@bp.route("/investment-accounts/<iid>/orders", methods=["POST"])
def place_order(iid):
    identity = authenticate()
    require_role(identity, {"Parent", "Child"})
    acct = domain.get_investment(iid)
    child = domain.get_child(acct["child_account_id"])
    domain.check_child_owner(identity, child)
    body = get_json_body()

    side = validate.require_enum(body, "side", {"BUY", "SELL"})
    symbol = validate.require_str(body, "symbol")
    shares_milli = validate.require_int(body, "shares_milli")
    price = validate.require_int(body, "price_cents_per_share")
    validate.bound_positive(shares_milli, "shares_milli")
    validate.bound_positive(price, "price_cents_per_share")

    # State (priority 10): account must be ACTIVE.
    if acct["status"] != "ACTIVE":
        raise err("ERR_ACCOUNT_CLOSED", "Investment account is closed")

    gross = domain.round_half_up_div(shares_milli * price, 1000)

    holdings = acct["holdings"]
    if side == "BUY":
        if acct["cash_cents"] < gross:
            raise err("ERR_INSUFFICIENT_INVEST_CASH", "Insufficient investing cash")
        acct["cash_cents"] -= gross
        entry = holdings.get(symbol, {"shares_milli": 0})
        entry["shares_milli"] = entry.get("shares_milli", 0) + shares_milli
        holdings[symbol] = entry
    else:  # SELL
        held = holdings.get(symbol, {"shares_milli": 0}).get("shares_milli", 0)
        if held < shares_milli:
            raise err("ERR_INSUFFICIENT_SHARES", "Insufficient shares for sell")
        holdings[symbol]["shares_milli"] = held - shares_milli
        acct["cash_cents"] += gross
    db.touch(acct)

    rec = db.base_fields()
    rec.update({
        "investment_account_id": iid,
        "side": side,
        "symbol": symbol,
        "shares_milli": shares_milli,
        "price_cents_per_share": price,
        "gross_cents": gross,
        "status": "FILLED",
    })
    db.investment_orders[rec["id"]] = rec
    return object_response(serialize.investment_order(rec), status=201)


@bp.route("/investment-accounts/<iid>/orders", methods=["GET"])
def list_orders(iid):
    identity = authenticate()
    require_role(identity, {"Parent", "Child", "PlatformAdmin"})
    acct = domain.get_investment(iid)
    child = domain.get_child(acct["child_account_id"])
    domain.check_child_owner(identity, child)
    items = [o for o in db.investment_orders.values()
             if o["investment_account_id"] == iid]
    side = request.args.get("side")
    if side is not None:
        items = [o for o in items if o["side"] == side]
    return list_response([serialize.investment_order(o) for o in items], request.args)


@bp.route("/investment-accounts/<iid>/close", methods=["POST"])
def close_investment(iid):
    identity = authenticate()
    require_role(identity, {"Parent"})
    acct = domain.get_investment(iid)
    child = domain.get_child(acct["child_account_id"])
    domain.check_child_owner(identity, child)

    if acct["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Account is not ACTIVE")
    # Holdings must all be empty.
    for sym, entry in acct["holdings"].items():
        if entry.get("shares_milli", 0) != 0:
            raise err("ERR_HOLDINGS_NOT_EMPTY", "Holdings are not empty")

    acct["status"] = "CLOSED"
    cash = acct["cash_cents"]
    if cash > 0:
        save_jar = domain.jar_of_type(child["id"], "SAVE")
        domain.credit_jar(save_jar, cash)  # SAVE jar does not fund the card
        acct["cash_cents"] = 0
    db.touch(acct)
    return object_response(serialize.investment_account(acct))
