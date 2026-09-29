"""Division orders, the operator response, corrections and revenue
reconciliation (PRD 3.8, 3.9)."""

from decimal import Decimal

from flask import Blueprint, request

import calc
import response
import serializers
from db import db, stamp_new, touch
from errors import ApiError
from guards import (authorize, body, body_ref, get_detail, get_order,
                    pagination, paginate, req_enum, req_int, req_month, req_num)
from services import cascade

bp = Blueprint("dorders", __name__)

PRODUCT_CODES = ("OIL", "GAS", "NGL")


def _require_operator(order, user_id):
    unit = db.units.get(order["unit_id"])
    if unit is None or unit["operator_user_id"] != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    return unit


@bp.route("/division-orders", methods=["POST"])
def create_order():
    user_id, _role = authorize("DivisionOrderAdmin")
    payload = body()
    interest = body_ref(payload, "mineral_interest_id", db.mineral_interests,
                        "ERR_MINERAL_INTEREST_NOT_FOUND")
    unit = body_ref(payload, "unit_id", db.units, "ERR_UNIT_NOT_FOUND")
    if interest is None:
        raise ApiError("ERR_INVALID_REQUEST", "Field 'mineral_interest_id' is required.")
    if unit is None:
        raise ApiError("ERR_INVALID_REQUEST", "Field 'unit_id' is required.")
    expected_unit_version = req_int(payload, "expected_unit_version")
    # rung 10
    if expected_unit_version != unit["version"]:
        raise ApiError("ERR_STALE_UNIT_VERSION")

    expected_decimal, allocation = calc.compute_expected_decimal(interest, unit)

    row = {
        "mineral_interest_id": interest["id"],
        "unit_id": unit["id"],
        "royalty_owner_id": interest["seller_owner_id"],
        "allocation_id": allocation["id"],
        "expected_decimal": expected_decimal,
        "pinned_decimal": None,
        "operator_decimal": None,
        "do_status": "SENT",
        "dispute_reason": "NONE",
        "effective_production_month": None,
        "cumulative_variance_amount": Decimal("0.00"),
        "paid_net_total": Decimal("0.00"),
        "correction_round_count": 0,
        "created_by_user_id": user_id,
    }
    stamp_new(row)
    db.division_orders[row["id"]] = row
    touch(unit)
    return response.created(serializers.order_out(row))


@bp.route("/division-orders/<order_id>", methods=["GET"])
def read_order(order_id):
    authorize("DivisionOrderAdmin", "Operator", "RoyaltyOwner")
    row = get_order(order_id)
    return response.ok(serializers.order_out(row))


@bp.route("/division-orders", methods=["GET"])
def list_orders():
    authorize("DivisionOrderAdmin", "Operator")
    limit, offset = pagination()
    rows = list(db.division_orders.values())
    for field in ("mineral_interest_id", "unit_id", "royalty_owner_id", "do_status"):
        value = request.args.get(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    rows.sort(key=lambda r: r["_seq"])
    page, total = paginate(rows, limit, offset)
    return response.listing([serializers.order_out(r) for r in page], limit, offset, total)


@bp.route("/division-orders/<order_id>/operator-response", methods=["POST"])
def operator_response(order_id):
    user_id, _role = authorize("Operator")
    order = get_order(order_id)
    _require_operator(order, user_id)                       # rung 4
    payload = body()
    operator_decimal = req_num(payload, "operator_decimal", 8, minimum=0)
    effective_production_month = req_month(payload, "effective_production_month")

    if order["do_status"] != "SENT":                          # priority 32
        raise ApiError("ERR_DIVISION_ORDER_STATE_INVALID")

    order["operator_decimal"] = operator_decimal
    if operator_decimal == order["expected_decimal"]:
        order["pinned_decimal"] = order["expected_decimal"]
        order["effective_production_month"] = effective_production_month
        order["do_status"] = "EXECUTED"
        order["dispute_reason"] = "NONE"
    else:
        order["do_status"] = "DISPUTED"
        order["dispute_reason"] = "DECIMAL_MISMATCH"
    touch(order)
    return response.ok(serializers.order_out(order))


@bp.route("/division-orders/<order_id>/correct", methods=["POST"])
def correct_order(order_id):
    user_id, _role = authorize("Operator")
    order = get_order(order_id)
    unit = _require_operator(order, user_id)                 # rung 4
    payload = body()
    corrected_decimal = req_num(payload, "corrected_decimal", 8, minimum=0)

    if order["do_status"] != "DISPUTED":                     # priority 32
        raise ApiError("ERR_DIVISION_ORDER_STATE_INVALID")

    interest = db.mineral_interests.get(order["mineral_interest_id"])
    if interest is None:
        raise ApiError("ERR_MINERAL_INTEREST_NOT_FOUND")
    fresh, allocation = calc.compute_expected_decimal(interest, unit)
    if corrected_decimal != fresh:                           # priority 85
        raise ApiError("ERR_CORRECTED_DECIMAL_MISMATCH")

    order["expected_decimal"] = fresh
    order["allocation_id"] = allocation["id"]
    order["operator_decimal"] = None
    order["do_status"] = "SENT"
    order["dispute_reason"] = "NONE"
    order["correction_round_count"] = order["correction_round_count"] + 1
    touch(order)
    return response.ok(serializers.order_out(order))


# --------------------------------------------------------------------------
# revenue check details
# --------------------------------------------------------------------------
@bp.route("/division-orders/<order_id>/revenue-check-details", methods=["POST"])
def report_detail(order_id):
    authorize("Operator")
    order = get_order(order_id)
    payload = body()
    production_month = req_month(payload, "production_month")
    product_code = req_enum(payload, "product_code", PRODUCT_CODES)
    gross_volume = req_num(payload, "gross_volume", 4, minimum=0)
    gross_value = req_num(payload, "gross_value", 2, minimum=0)
    operator_decimal_used = req_num(payload, "operator_decimal_used", 8, minimum=0)

    if order["do_status"] != "EXECUTED":                     # priority 32
        raise ApiError("ERR_DIVISION_ORDER_STATE_INVALID")
    for existing in db.revenue_details.values():             # priority 71
        if (existing["division_order_id"] == order["id"]
                and existing["production_month"] == production_month
                and existing["product_code"] == product_code):
            raise ApiError("ERR_DUPLICATE_PRODUCTION_MONTH")

    unit = db.units.get(order["unit_id"])
    if unit is None:
        raise ApiError("ERR_UNIT_NOT_FOUND")
    rate = calc.severance_rate(unit["state_code"], product_code)

    # variant 1: what the operator actually paid
    reported_gross_royalty = calc.q2(gross_value * operator_decimal_used)
    severance_tax_amount = calc.q2(reported_gross_royalty * rate)
    net_amount = calc.q2(reported_gross_royalty - severance_tax_amount)

    # variant 2: the pinned settlement variant - the one that moves money
    pinned = order["pinned_decimal"] or Decimal("0.00000000")
    expected_gross_royalty = calc.q2(gross_value * pinned)
    expected_net_amount = calc.net_after_tax(expected_gross_royalty, rate)
    variance_amount = calc.q2(expected_net_amount - net_amount)

    # variant 3: the live audit variant - never moves money
    interest = db.mineral_interests.get(order["mineral_interest_id"])
    audit_decimal = Decimal("0.00000000")
    if interest is not None:
        live, _allocation = calc.try_compute_expected_decimal(interest, unit)
        if live is not None:
            audit_decimal = live
    audit_gross_royalty = calc.q2(gross_value * audit_decimal)
    audit_net_amount = calc.net_after_tax(audit_gross_royalty, rate)
    audit_variance_amount = calc.q2(audit_net_amount - net_amount)

    row = {
        "division_order_id": order["id"],
        "production_month": production_month,
        "product_code": product_code,
        "gross_volume": gross_volume,
        "gross_value": gross_value,
        "operator_decimal_used": operator_decimal_used,
        "reported_gross_royalty": reported_gross_royalty,
        "severance_tax_rate": rate,
        "severance_tax_amount": severance_tax_amount,
        "net_amount": net_amount,
        "expected_gross_royalty": expected_gross_royalty,
        "expected_net_amount": expected_net_amount,
        "variance_amount": variance_amount,
        "audit_decimal": audit_decimal,
        "audit_gross_royalty": audit_gross_royalty,
        "audit_net_amount": audit_net_amount,
        "audit_variance_amount": audit_variance_amount,
        "check_status": "PAID",
    }
    stamp_new(row)
    db.revenue_details[row["id"]] = row

    owner = db.royalty_owners.get(order["royalty_owner_id"])
    reason = cascade.route_revenue_detail(order, row, owner)
    touch(order)
    if reason is not None:
        cascade.upsert_suspense(order, reason, production_month)
    return response.created(serializers.detail_out(row))


@bp.route("/division-orders/<order_id>/revenue-check-details", methods=["GET"])
def list_details(order_id):
    authorize("DivisionOrderAdmin", "Operator", "RoyaltyOwner")
    order = get_order(order_id)
    limit, offset = pagination()
    rows = [d for d in db.revenue_details.values()
            if d["division_order_id"] == order["id"]]
    for field in ("production_month", "check_status"):
        value = request.args.get(field)
        if value is not None:
            rows = [d for d in rows if d[field] == value]
    rows.sort(key=lambda d: d["_seq"])
    page, total = paginate(rows, limit, offset)
    return response.listing([serializers.detail_out(r) for r in page],
                            limit, offset, total)


@bp.route("/revenue-check-details/<detail_id>", methods=["GET"])
def read_detail(detail_id):
    authorize("DivisionOrderAdmin", "Operator", "RoyaltyOwner")
    row = get_detail(detail_id)
    return response.ok(serializers.detail_out(row))
