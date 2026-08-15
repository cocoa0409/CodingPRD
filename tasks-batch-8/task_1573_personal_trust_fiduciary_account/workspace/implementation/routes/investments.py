"""InvestmentPolicyStatement + InvestmentHolding endpoints."""

from datetime import date
from decimal import Decimal

from flask import Blueprint, request

import clock
import db
import serialize
from errors import (ApiError, ERR_VALIDATION, ERR_INVALID_STATE,
                    ERR_TRUST_NOT_ACTIVE, ERR_RESOURCE_NOT_FOUND,
                    ERR_STALE_VERSION, ERR_IPS_DRIFT_BREACH,
                    ERR_CONCENTRATION_LIMIT_EXCEEDED,
                    ERR_IPS_PERIOD_OVERLAP, ERR_INSUFFICIENT_AVAILABLE_BALANCE)
from middleware import authenticate, require_role
from response import ok, ok_list
from serialize import policy_json, holding_json
from services import workflow, calc
from services.workflow import find_or_404
from validation import get_body, validate, parse_pagination

bp = Blueprint("investments", __name__)

ASSET_CLASSES = {"EQUITY", "FIXED_INCOME", "CASH_EQUIVALENT", "ALTERNATIVE"}
READ_ROLES = {"TrustOfficer", "TrustExecutive", "InvestmentManager"}


# ------------------------------------------------------------- IPS endpoints

@bp.route("/trusts/investment-policy-statements", methods=["POST"])
def create_policy():
    _, role = authenticate()
    data = get_body()
    v = validate(data, [
        ("trust_id", "str", True),
        ("effective_from", "date", True),
        ("effective_to", "date", True),
        ("equity_target_pct", "number", True),
        ("equity_band_pct", "number", True),
        ("fixed_income_target_pct", "number", True),
        ("fixed_income_band_pct", "number", True),
        ("alternatives_allowed", "bool", True),
    ])
    if date.fromisoformat(v["effective_from"]) >= date.fromisoformat(v["effective_to"]):
        raise ApiError(ERR_VALIDATION, 400,
                       "effective_from must be strictly earlier than effective_to")
    require_role(role, {"InvestmentManager"})
    trust = db.trusts.get(v["trust_id"])
    if trust is None:
        raise ApiError(ERR_RESOURCE_NOT_FOUND, 404,
                       "Trust not found: %s" % v["trust_id"])
    if trust["status"] not in ("DRAFT", "UNDER_ACCEPTANCE_REVIEW", "ACTIVE", "SUSPENDED"):
        raise ApiError(ERR_TRUST_NOT_ACTIVE, 409,
                       "Trust status does not permit policy creation")
    p = workflow.new_entity()
    p.update({
        "trust_id": trust["id"],
        "effective_from": v["effective_from"],
        "effective_to": v["effective_to"],
        "equity_target_pct": v["equity_target_pct"],
        "equity_band_pct": v["equity_band_pct"],
        "fixed_income_target_pct": v["fixed_income_target_pct"],
        "fixed_income_band_pct": v["fixed_income_band_pct"],
        "alternatives_allowed": v["alternatives_allowed"],
        "status": "DRAFT",
        "activated_at": None,
    })
    db.policies[p["id"]] = p
    return ok(policy_json(p), status=201)


@bp.route("/trusts/investment-policy-statements", methods=["GET"])
def list_policies():
    _, role = authenticate()
    limit, offset = parse_pagination()
    require_role(role, READ_ROLES)
    filters = []
    for param in ("trust_id", "status"):
        val = request.args.get(param)
        if val is not None:
            filters.append((param, val))
    items, total = workflow.list_page(db.policies, filters, policy_json,
                                      limit, offset)
    return ok_list(items, limit, offset, total)


@bp.route("/trusts/investment-policy-statements/<pid>", methods=["GET"])
def get_policy(pid):
    _, role = authenticate()
    require_role(role, READ_ROLES)
    p = find_or_404(db.policies, pid, "InvestmentPolicyStatement")
    return ok(policy_json(p))


@bp.route("/trusts/investment-policy-statements/<pid>/activate", methods=["POST"])
def activate_policy(pid):
    _, role = authenticate()
    get_body()
    require_role(role, {"InvestmentManager"})
    p = find_or_404(db.policies, pid, "InvestmentPolicyStatement")
    # [6] state
    if p["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409, "Statement must be DRAFT to activate")
    trust = db.trusts.get(p["trust_id"])
    if trust is None or trust["status"] not in ("ACTIVE", "SUSPENDED"):
        raise ApiError(ERR_TRUST_NOT_ACTIVE, 409,
                       "Trust must be ACTIVE or SUSPENDED to activate a policy")
    # [8] half-open windows must not overlap other DRAFT/ACTIVE statements
    new_from = date.fromisoformat(p["effective_from"])
    new_to = date.fromisoformat(p["effective_to"])
    for other in db.policies.values():
        if (other["trust_id"] == p["trust_id"] and other["id"] != p["id"]
                and other["status"] in ("DRAFT", "ACTIVE")):
            o_from = date.fromisoformat(other["effective_from"])
            o_to = date.fromisoformat(other["effective_to"])
            if new_from < o_to and o_from < new_to:
                raise ApiError(ERR_IPS_PERIOD_OVERLAP, 409,
                               "Policy window overlaps another DRAFT/ACTIVE statement")
    # supersede the currently ACTIVE statement of the same trust
    for other in db.policies.values():
        if (other["trust_id"] == p["trust_id"] and other["id"] != p["id"]
                and other["status"] == "ACTIVE"):
            other["status"] = "SUPERSEDED"
            workflow.touch(other)
    p["status"] = "ACTIVE"
    p["activated_at"] = workflow.now_stamp()
    workflow.touch(p)
    # immediate drift check against the new policy
    calc.run_drift_check(trust)
    return ok(policy_json(p))


# --------------------------------------------------------- holdings endpoints

@bp.route("/trusts/investment-holdings", methods=["POST"])
def purchase_holding():
    _, role = authenticate()
    data = get_body()
    v = validate(data, [
        ("trust_id", "str", True),
        ("asset_class", "str", True, ASSET_CLASSES),
        ("ticker", "str", True),
        ("units", "pint", True),
        ("unit_price_cents", "pint", True),
        ("expected_trust_account_version", "int", True),
    ])
    require_role(role, {"InvestmentManager"})
    # [5] existence
    trust = db.trusts.get(v["trust_id"])
    if trust is None:
        raise ApiError(ERR_RESOURCE_NOT_FOUND, 404,
                       "Trust not found: %s" % v["trust_id"])
    # [6] state + OCC
    if trust["status"] not in ("ACTIVE", "SUSPENDED"):
        raise ApiError(ERR_TRUST_NOT_ACTIVE, 409,
                       "Trust must be ACTIVE or SUSPENDED to trade")
    if v["expected_trust_account_version"] != trust["version"]:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "expected_trust_account_version does not match")
    # [7] fiduciary/compliance gates
    if calc.has_overweight_block(trust["id"], v["asset_class"]):
        raise ApiError(ERR_IPS_DRIFT_BREACH, 422,
                       "Asset class has a non-RESOLVED OVERWEIGHT review")
    existing = None
    for h in db.holdings.values():
        if h["trust_id"] == trust["id"] and h["ticker"] == v["ticker"]:
            existing = h
            break
    cost = v["units"] * v["unit_price_cents"]
    units_after = (existing["units"] if existing else 0) + v["units"]
    mv_after = units_after * v["unit_price_cents"]
    # post-trade TMV equals pre-trade TMV (cash debit == MV added)
    tmv = serialize.total_market_value(trust["id"])
    if mv_after * 4 > tmv:
        raise ApiError(ERR_CONCENTRATION_LIMIT_EXCEEDED, 422,
                       "Post-trade holding market value exceeds 25% of total")
    # [11] funds check last
    avail_p = (serialize.principal_balance(trust["id"])
               - serialize.reserved_principal(trust["id"]))
    if cost > avail_p:
        raise ApiError(ERR_INSUFFICIENT_AVAILABLE_BALANCE, 422,
                       "Purchase cost exceeds available principal")
    now_raw = workflow.now_stamp()
    if existing is not None:
        h = existing
        h["units"] = units_after
        h["cost_basis_cents"] += cost
        h["unit_price_cents"] = v["unit_price_cents"]
        h["priced_at"] = now_raw
        h["price_history"].append((clock.now_dt(), v["unit_price_cents"]))
        if h["status"] == "CLOSED":
            h["status"] = "OPEN"
        workflow.touch(h)
    else:
        h = workflow.new_entity()
        h.update({
            "trust_id": trust["id"],
            "asset_class": v["asset_class"],
            "ticker": v["ticker"],
            "units": v["units"],
            "unit_price_cents": v["unit_price_cents"],
            "cost_basis_cents": cost,
            "priced_at": now_raw,
            "status": "OPEN",
            "price_history": [(clock.now_dt(), v["unit_price_cents"])],
        })
        db.holdings[h["id"]] = h
    workflow.append_ledger(
        trust["id"], "INVESTMENT_PURCHASE", "PRINCIPAL", -cost,
        clock.now_date().isoformat(),
        source_entity_type="INVESTMENT_HOLDING", source_entity_id=h["id"])
    workflow.bump_trust(trust)
    return ok(holding_json(h), status=201)


@bp.route("/trusts/investment-holdings", methods=["GET"])
def list_holdings():
    _, role = authenticate()
    limit, offset = parse_pagination()
    require_role(role, READ_ROLES)
    filters = []
    for param in ("trust_id", "asset_class", "status"):
        val = request.args.get(param)
        if val is not None:
            filters.append((param, val))
    items, total = workflow.list_page(db.holdings, filters, holding_json,
                                      limit, offset)
    return ok_list(items, limit, offset, total)


@bp.route("/trusts/investment-holdings/<hid>", methods=["GET"])
def get_holding(hid):
    _, role = authenticate()
    require_role(role, READ_ROLES)
    h = find_or_404(db.holdings, hid, "InvestmentHolding")
    return ok(holding_json(h))


@bp.route("/trusts/investment-holdings/<hid>/update-price", methods=["POST"])
def update_price(hid):
    _, role = authenticate()
    data = get_body()
    v = validate(data, [
        ("unit_price_cents", "pint", True),
        ("priced_at", "datetime", True),
    ])
    require_role(role, {"InvestmentManager"})
    h = find_or_404(db.holdings, hid, "InvestmentHolding")
    trust = db.trusts.get(h["trust_id"])
    if trust is None or trust["status"] not in ("ACTIVE", "SUSPENDED"):
        raise ApiError(ERR_TRUST_NOT_ACTIVE, 409,
                       "Trust must be ACTIVE or SUSPENDED to update prices")
    h["unit_price_cents"] = v["unit_price_cents"]
    h["priced_at"] = v["priced_at"]
    h["price_history"].append((clock.parse_dt(v["priced_at"]), v["unit_price_cents"]))
    workflow.touch(h)
    calc.run_drift_check(trust)
    workflow.bump_trust(trust)
    return ok(holding_json(h))


@bp.route("/trusts/investment-holdings/<hid>/sell", methods=["POST"])
def sell_holding(hid):
    _, role = authenticate()
    data = get_body()
    v = validate(data, [("units", "pint", True)])
    require_role(role, {"InvestmentManager"})
    h = find_or_404(db.holdings, hid, "InvestmentHolding")
    trust = db.trusts.get(h["trust_id"])
    if trust is None or trust["status"] not in ("ACTIVE", "SUSPENDED"):
        raise ApiError(ERR_TRUST_NOT_ACTIVE, 409,
                       "Trust must be ACTIVE or SUSPENDED to trade")
    if h["status"] != "OPEN" or v["units"] > h["units"]:
        raise ApiError(ERR_VALIDATION, 400,
                       "units sold must not exceed units held")
    units_before = h["units"]
    proceeds = v["units"] * h["unit_price_cents"]
    basis_reduction = int(calc.rhu(
        Decimal(h["cost_basis_cents"]) * Decimal(v["units"])
        / Decimal(units_before)))
    h["cost_basis_cents"] -= basis_reduction
    h["units"] -= v["units"]
    if h["units"] == 0:
        h["status"] = "CLOSED"
    workflow.touch(h)
    workflow.append_ledger(
        trust["id"], "INVESTMENT_SALE", "PRINCIPAL", proceeds,
        clock.now_date().isoformat(),
        source_entity_type="INVESTMENT_HOLDING", source_entity_id=h["id"])
    workflow.bump_trust(trust)
    return ok(holding_json(h))
