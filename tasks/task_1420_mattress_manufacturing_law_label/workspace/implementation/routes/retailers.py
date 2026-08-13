"""Retailer + credit-adjustment endpoints."""
from flask import Blueprint, request

import clock
import db
import errors
import middleware
import response
from routes.helpers import as_bool, as_int, as_string, body, check_occ, optional, require
from services import cascade

bp = Blueprint("retailers", __name__)


def retailer_view(r):
    return {
        "id": r["id"],
        "retailer_name": r["retailer_name"],
        "drop_ship_enabled": r["drop_ship_enabled"],
        "recycling_enrolled": r["recycling_enrolled"],
        "credit_limit_cents": r["credit_limit_cents"],
        "credit_balance_cents": r["credit_balance_cents"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def adjustment_view(a):
    return {
        "id": a["id"],
        "retailer_id": a["retailer_id"],
        "amount_cents": a["amount_cents"],
        "reason": a["reason"],
        "source": a["source"],
        "source_id": a["source_id"],
        "created_at": a["created_at"],
    }


def _get_retailer(rid):
    r = db.retailers.get(rid)
    if r is None:
        errors.raise_err(errors.ERR_RETAILER_NOT_FOUND, "retailer not found")
    return r


@bp.route("/retailers", methods=["POST"])
def create_retailer():
    middleware.require_roles(["PlantManager"])
    data = body()
    name = as_string(require(data, "retailer_name"), "retailer_name")
    drop_ship = as_bool(require(data, "drop_ship_enabled"), "drop_ship_enabled")
    enrolled = as_bool(require(data, "recycling_enrolled"), "recycling_enrolled")
    limit = as_int(require(data, "credit_limit_cents"), "credit_limit_cents")
    retailer = {
        "id": db.new_id(),
        "retailer_name": name,
        "drop_ship_enabled": drop_ship,
        "recycling_enrolled": enrolled,
        "credit_limit_cents": limit,
        "credit_balance_cents": 0,
        "created_at": clock.now_iso(),
        "updated_at": clock.now_iso(),
        "version": 1,
    }
    db.put(db.retailers, retailer)
    return response.success_object(retailer_view(retailer), 201)


@bp.route("/retailers", methods=["GET"])
def list_retailers():
    middleware.require_roles(middleware.ALL_ROLES)
    items = list(db.retailers.values())
    q = request.args.get("drop_ship_enabled")
    if q is not None:
        want = q.lower() == "true"
        items = [r for r in items if r["drop_ship_enabled"] == want]
    q = request.args.get("recycling_enrolled")
    if q is not None:
        want = q.lower() == "true"
        items = [r for r in items if r["recycling_enrolled"] == want]
    items.sort(key=lambda r: r["_seq"])
    return response.success_list([retailer_view(r) for r in items])


@bp.route("/retailers/<retailerId>", methods=["GET"])
def get_retailer(retailerId):
    middleware.require_roles(middleware.ALL_ROLES)
    r = _get_retailer(retailerId)
    return response.success_object(retailer_view(r))


@bp.route("/retailers/<rid>/credit-adjustments", methods=["POST"])
def post_manual_adjustment(rid):
    middleware.require_roles(["PlantManager"])
    retailer = _get_retailer(rid)
    data = body()
    amount = as_int(require(data, "amount_cents"), "amount_cents")
    reason = as_string(require(data, "reason"), "reason")
    check_occ(require(data, "expected_retailer_version"), retailer["version"])
    adj = cascade.post_credit_adjustment(retailer, amount, reason, "MANUAL", None)
    return response.success_object(adjustment_view(adj), 201)


@bp.route("/retailers/<rid>/credit-adjustments", methods=["GET"])
def list_adjustments(rid):
    middleware.require_roles(middleware.ALL_ROLES)
    retailer = _get_retailer(rid)
    items = [a for a in db.credit_adjustments.values() if a["retailer_id"] == retailer["id"]]
    items.sort(key=lambda a: a["_seq"])
    return response.success_list([adjustment_view(a) for a in items])
