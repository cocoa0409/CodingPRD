"""Pricing plan routes (create, read, activate with OCC)."""
from flask import Blueprint

import db
import serializers as S
from auth import authenticate, authorize
from errors import err
from helpers import get_json_body, require_resource, require_fields
from response import success
from constants import HOME_SIZES

bp = Blueprint("pricing_plans", __name__)


def _validate_pct(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise err("ERR_INVALID_REQUEST", "%s must be a number" % label)
    if value < 0:
        raise err("ERR_INVALID_REQUEST", "%s must be non-negative" % label)


@bp.route("/cleaning/pricing-plans", methods=["POST"])
def create_plan():
    principal = authenticate()
    authorize(principal, {"PlatformAdmin"})
    body = get_json_body()
    require_fields(body, ["name", "base_price_cents", "deep_clean_surcharge_pct",
                          "move_out_surcharge_pct", "supplies_fee_cents"])
    if not isinstance(body["name"], str) or body["name"] == "":
        raise err("ERR_INVALID_REQUEST", "name must be a non-empty string")
    base = body["base_price_cents"]
    if not isinstance(base, dict):
        raise err("ERR_INVALID_REQUEST", "base_price_cents must be an object")
    for size in HOME_SIZES:
        if size not in base:
            raise err("ERR_INVALID_REQUEST", "base_price_cents missing %s" % size)
        v = base[size]
        if isinstance(v, bool) or not isinstance(v, int) or v < 0:
            raise err("ERR_INVALID_REQUEST", "base_price_cents[%s] must be a non-negative integer" % size)
    _validate_pct(body["deep_clean_surcharge_pct"], "deep_clean_surcharge_pct")
    _validate_pct(body["move_out_surcharge_pct"], "move_out_surcharge_pct")
    fee = body["supplies_fee_cents"]
    if isinstance(fee, bool) or not isinstance(fee, int) or fee < 0:
        raise err("ERR_INVALID_REQUEST", "supplies_fee_cents must be a non-negative integer")
    rec = {
        "name": body["name"],
        "base_price_cents": dict(base),
        "deep_clean_surcharge_pct": body["deep_clean_surcharge_pct"],
        "move_out_surcharge_pct": body["move_out_surcharge_pct"],
        "supplies_fee_cents": fee,
        "active": False,
    }
    db.insert(db.pricing_plans, rec)
    return success(S.pricing_plan(rec), status=201)


@bp.route("/cleaning/pricing-plans/<pid>", methods=["GET"])
def get_plan(pid):
    principal = authenticate()
    authorize(principal, {"PlatformAdmin", "Customer"})
    rec = require_resource(db.pricing_plans, pid, "pricing_plan")
    return success(S.pricing_plan(rec), status=200)


@bp.route("/cleaning/pricing-plans/<pid>/activate", methods=["POST"])
def activate_plan(pid):
    principal = authenticate()
    authorize(principal, {"PlatformAdmin"})
    plan = require_resource(db.pricing_plans, pid, "pricing_plan")
    body = get_json_body()
    # OCC check (priority 15) before request-body validation (priority 16).
    require_fields(body, ["expected_plan_version"])
    expected = body["expected_plan_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise err("ERR_INVALID_REQUEST", "expected_plan_version must be an integer")
    if expected != plan.get("version"):
        raise err("ERR_STALE_VERSION", "plan version mismatch")
    # Deactivate the prior active plan (each gets its own version bump).
    for other in db.pricing_plans.values():
        if other["id"] != plan["id"] and other.get("active"):
            other["active"] = False
            db.touch(other)
    plan["active"] = True
    db.touch(plan)
    return success(S.pricing_plan(plan), status=200)
