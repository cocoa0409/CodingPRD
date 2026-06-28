"""Customers, Plans, ReplacementSkus."""
from flask import Blueprint, request

import errors
from db import db, new_id
from helpers import (serialize, base_system_fields, get_or_404,
                     parse_pagination, paginate, sorted_by_created)
from middleware import require_auth, require_role
from response import ok, ok_list

bp = Blueprint("reference", __name__)


def _body():
    return request.get_json(silent=True) or {}


def _require_str(body, field):
    v = body.get(field)
    if v is None or not isinstance(v, str) or v == "":
        errors.fail(errors.ERR_VALIDATION, f"{field} is required")
    return v


def _require_int(body, field, *, min_val=None, max_val=None, exclusive_min=None):
    v = body.get(field)
    if v is None or isinstance(v, bool) or not isinstance(v, int):
        errors.fail(errors.ERR_VALIDATION, f"{field} must be an integer")
    if min_val is not None and v < min_val:
        errors.fail(errors.ERR_VALIDATION, f"{field} below minimum")
    if exclusive_min is not None and v <= exclusive_min:
        errors.fail(errors.ERR_VALIDATION, f"{field} must be > {exclusive_min}")
    if max_val is not None and v > max_val:
        errors.fail(errors.ERR_VALIDATION, f"{field} above maximum")
    return v


# ---------------- Customers ----------------
@bp.route("/customers", methods=["POST"])
def create_customer():
    _, role = require_auth()
    require_role(role, {"PlatformAdmin"})
    body = _body()
    full_name = _require_str(body, "full_name")
    carrier = _require_str(body, "carrier_account_number")
    for c in db.customers.values():
        if c["carrier_account_number"] == carrier:
            errors.fail(errors.ERR_VALIDATION, "carrier_account_number must be unique")
    cid = new_id()
    cust = {
        "id": cid,
        "full_name": full_name,
        "carrier_account_number": carrier,
        "risk_flag": "GREEN",
        "lifetime_approved_claim_count": 0,
        "_seq": db.next_seq(),
    }
    cust.update(base_system_fields(versioned=True))
    db.customers[cid] = cust
    return ok(serialize(cust), 201)


@bp.route("/customers/<cid>", methods=["GET"])
def get_customer(cid):
    _, role = require_auth()
    require_role(role, {"PlatformAdmin", "Subscriber", "ClaimsAdjuster"})
    cust = get_or_404(db.customers, cid)
    return ok(serialize(cust), 200)


# ---------------- Plans ----------------
@bp.route("/plans", methods=["POST"])
def create_plan():
    _, role = require_auth()
    require_role(role, {"PlatformAdmin"})
    body = _body()
    code = _require_str(body, "code")
    for p in db.plans.values():
        if p["code"] == code:
            errors.fail(errors.ERR_VALIDATION, "code must be unique")
    plan = {
        "id": new_id(),
        "code": code,
        "monthly_premium_cents": _require_int(body, "monthly_premium_cents", min_val=0),
        "base_deductible_cents": _require_int(body, "base_deductible_cents", min_val=0),
        "loss_deductible_multiplier_bps": _require_int(body, "loss_deductible_multiplier_bps", min_val=10000),
        "annual_claim_limit": _require_int(body, "annual_claim_limit", min_val=1),
        "replacement_value_cap_cents": _require_int(body, "replacement_value_cap_cents", exclusive_min=0),
        "_seq": db.next_seq(),
    }
    plan.update(base_system_fields(versioned=False))
    db.plans[plan["id"]] = plan
    return ok(serialize(plan), 201)


@bp.route("/plans/<pid>", methods=["GET"])
def get_plan(pid):
    _, role = require_auth()
    require_role(role, {"PlatformAdmin", "Subscriber", "ClaimsAdjuster"})
    plan = get_or_404(db.plans, pid)
    return ok(serialize(plan), 200)


# ---------------- Replacement SKUs ----------------
@bp.route("/replacement-skus", methods=["POST"])
def create_sku():
    _, role = require_auth()
    require_role(role, {"PlatformAdmin"})
    body = _body()
    sku = {
        "id": new_id(),
        "model_name": _require_str(body, "model_name"),
        "msrp_cents": _require_int(body, "msrp_cents", exclusive_min=0),
        "depreciation_rate_bps_per_month": _require_int(body, "depreciation_rate_bps_per_month", min_val=0, max_val=10000),
        "stock_on_hand": _require_int(body, "stock_on_hand", min_val=0),
        "_seq": db.next_seq(),
    }
    sku.update(base_system_fields(versioned=False))
    db.replacement_skus[sku["id"]] = sku
    return ok(serialize(sku), 201)


@bp.route("/replacement-skus/<sid>", methods=["GET"])
def get_sku(sid):
    _, role = require_auth()
    require_role(role, {"PlatformAdmin", "ClaimsAdjuster", "LogisticsAgent"})
    sku = get_or_404(db.replacement_skus, sid)
    return ok(serialize(sku), 200)
