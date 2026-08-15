"""Serialized harness units: rework, scrap, ship (PRD 3.7)."""
from flask import Blueprint, request

from db import db
from errors import (raise_error, ERR_INVALID_REQUEST, ERR_HARNESS_NOT_TESTABLE,
                    ERR_UNIT_NOT_SHIPPABLE, ERR_REWORK_LIMIT_EXCEEDED)
from middleware import authenticate, ALL_ROLES
from response import success_object
from services import (SCRAP_REASONS, touch, scrap_unit, completion_check,
                      recompute_order_counters, ser_harness_unit, paginated)
from validate import get_body, req_enum, require_path

bp = Blueprint("harness_units", __name__)

LINE_OPERATOR = {"LineOperator"}
QUALITY_INSPECTOR = {"QualityInspector"}
SHIPPING_CLERK = {"ShippingClerk"}


@bp.route("/plant/harness-units/<uid>", methods=["GET"])
def get_harness_unit(uid):
    authenticate(ALL_ROLES)
    unit = require_path("harness_units", uid)
    return success_object(ser_harness_unit(unit), 200)


@bp.route("/plant/harness-units", methods=["GET"])
def list_harness_units():
    authenticate(ALL_ROLES)
    items = list(db["harness_units"].values())
    build_order_id = request.args.get("build_order_id")
    if build_order_id is not None:
        items = [u for u in items if u["build_order_id"] == build_order_id]
    built_by_operator_id = request.args.get("built_by_operator_id")
    if built_by_operator_id is not None:
        items = [u for u in items if u["built_by_operator_id"] == built_by_operator_id]
    status = request.args.get("status")
    if status is not None:
        items = [u for u in items if u["status"] == status]
    return paginated(items, ser_harness_unit)


@bp.route("/plant/harness-units/<uid>/complete-rework", methods=["POST"])
def complete_rework(uid):
    get_body()
    authenticate(LINE_OPERATOR)
    unit = require_path("harness_units", uid)
    # Tier 6 state gate, then tier 9 rework cap (scaffold priority order).
    if unit["status"] != "REWORK":
        raise_error(ERR_INVALID_REQUEST, "unit is not in REWORK")
    if unit["rework_count"] >= 2:
        raise_error(ERR_REWORK_LIMIT_EXCEEDED, "rework_count cap of 2 reached")
    unit["status"] = "BUILT"
    unit["rework_count"] += 1
    unit["continuity_pass"] = False
    unit["hipot_pass"] = False
    unit["_continuity_pass_at"] = None
    unit["_hipot_pass_at"] = None
    touch(unit)
    return success_object(ser_harness_unit(unit), 200)


@bp.route("/plant/harness-units/<uid>/scrap", methods=["POST"])
def scrap_harness_unit(uid):
    body = get_body()
    reason = req_enum(body, "reason", SCRAP_REASONS)
    authenticate(QUALITY_INSPECTOR)
    unit = require_path("harness_units", uid)
    if unit["status"] not in ("BUILT", "REWORK", "SUSPECT"):
        raise_error(ERR_INVALID_REQUEST,
                    "only units in BUILT, REWORK, or SUSPECT may be scrapped")
    scrap_unit(unit, reason)
    return success_object(ser_harness_unit(unit), 200)


@bp.route("/plant/harness-units/<uid>/ship", methods=["POST"])
def ship_harness_unit(uid):
    get_body()
    authenticate(SHIPPING_CLERK)
    unit = require_path("harness_units", uid)
    if unit["status"] != "TEST_PASS":
        raise_error(ERR_UNIT_NOT_SHIPPABLE, "only a TEST_PASS unit may be shipped")
    unit["status"] = "SHIPPED"
    touch(unit)
    order = db["build_orders"].get(unit["build_order_id"])
    if order is not None:
        completion_check(order)
    return success_object(ser_harness_unit(unit), 200)
