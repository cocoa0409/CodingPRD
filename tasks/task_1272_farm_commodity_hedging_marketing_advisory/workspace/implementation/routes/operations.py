"""GrowerOperation endpoints + performance-report + cash-flow-projection."""

import math
from datetime import date, timedelta
from decimal import Decimal

from flask import Blueprint, request

import db
from db import DB
from errors import ApiError
from helpers import (
    D, r2, r4, to_float, req_body, require_fields, req_string, req_enum, opt_enum,
    req_int, pagination_params, page_slice, get_or_404, parse_date, month_bounds,
)
from middleware import get_auth, require_role, check_grower_ownership
from response import success_object, success_list
from serializers import ser_operation


bp = Blueprint("operations", __name__)


@bp.route("/advisory/operations", methods=["POST"])
def create_operation():
    user_id, role = get_auth()
    require_role(role, ["CommodityAdvisor"])
    body = req_body()
    require_fields(body, ["name", "primary_commodity", "crop_year", "risk_profile"])
    name = req_string(body, "name")
    commodity = req_enum(body, "primary_commodity", {"CORN", "SOYBEAN", "WHEAT"})
    crop_year = req_int(body, "crop_year")
    risk_profile = req_enum(body, "risk_profile", {"CONSERVATIVE", "BALANCED", "AGGRESSIVE"})
    yield_method = opt_enum(body, "yield_method", {"APH", "TREND"}, default="APH")

    oid = db.new_id()
    now = db.now_iso()
    op = {
        "id": oid,
        "name": name,
        "primary_commodity": commodity,
        "crop_year": crop_year,
        "risk_profile": risk_profile,
        "yield_method": yield_method,
        "over_sold_flag": False,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    DB.operations[oid] = op
    return success_object(ser_operation(op), status=201)


@bp.route("/advisory/operations/<operationId>", methods=["GET"])
def get_operation(operationId):
    user_id, role = get_auth()
    require_role(role, ["CommodityAdvisor", "Grower", "ComplianceOfficer", "PlatformAdmin"])
    op = get_or_404(DB.operations, operationId, "GrowerOperation")
    check_grower_ownership(user_id, role, op["id"])
    return success_object(ser_operation(op))


# ---------------------------------------------------------------------------
# Performance report
# ---------------------------------------------------------------------------

@bp.route("/advisory/operations/<operationId>/performance-report", methods=["GET"])
def performance_report(operationId):
    user_id, role = get_auth()
    require_role(role, ["CommodityAdvisor", "Grower"])
    op = get_or_404(DB.operations, operationId, "GrowerOperation")
    check_grower_ownership(user_id, role, op["id"])

    benchmark_method = request.args.get("benchmark_method") or "MARKETING_YEAR_AVG"
    if benchmark_method not in {"MARKETING_YEAR_AVG", "HARVEST_WINDOW_AVG"}:
        raise ApiError("ERR_VALIDATION", "benchmark_method must be MARKETING_YEAR_AVG or HARVEST_WINDOW_AVG", 400)

    priced = [
        c for c in DB.contracts.values()
        if c["operation_id"] == op["id"]
        and c["pricing_status"] == "PRICED"
        and c["fulfillment_status"] in {"OPEN", "PARTIALLY_DELIVERED", "DELIVERED", "DEFAULTED"}
    ]
    priced_count = len(priced)
    if priced_count == 0:
        weighted_avg = None
    else:
        num = sum(D(c["bushels"]) * D(c["effective_price"]) for c in priced)
        den = sum(D(c["bushels"]) for c in priced)
        weighted_avg = r4(num / den)

    cy = op["crop_year"]
    if benchmark_method == "MARKETING_YEAR_AVG":
        window_start = date(cy, 6, 1)
        window_end = date(cy + 1, 5, 31)
    else:
        window_start = date(cy, 10, 1)
        window_end = date(cy, 10, 31)

    ticks = []
    for t in DB.market_ticks.values():
        if t["kind"] != "SETTLEMENT":
            continue
        if t["commodity"] != op["primary_commodity"]:
            continue
        pd = parse_date(t["price_date"])
        if window_start <= pd <= window_end:
            ticks.append(t)

    tick_count = len(ticks)
    if tick_count == 0:
        benchmark_price = None
    else:
        total = sum(D(t["price"]) for t in ticks)
        benchmark_price = r4(total / tick_count)

    if weighted_avg is None or benchmark_price is None:
        outperformance = None
    else:
        outperformance = int(
            ((weighted_avg - benchmark_price) / benchmark_price * Decimal(10000)).quantize(
                Decimal("1"), rounding="ROUND_HALF_UP"
            )
        )

    result = {
        "weighted_avg_sale_price": to_float(weighted_avg) if weighted_avg is not None else None,
        "benchmark_price": to_float(benchmark_price) if benchmark_price is not None else None,
        "outperformance_bps": outperformance,
        "priced_contract_count": priced_count,
        "benchmark_tick_count": tick_count,
    }
    return success_object(result)


# ---------------------------------------------------------------------------
# Cash-flow projection
# ---------------------------------------------------------------------------

@bp.route("/advisory/operations/<operationId>/cash-flow-projection", methods=["GET"])
def cash_flow_projection(operationId):
    user_id, role = get_auth()
    require_role(role, ["CommodityAdvisor", "Grower"])
    op = get_or_404(DB.operations, operationId, "GrowerOperation")
    check_grower_ownership(user_id, role, op["id"])

    through_raw = request.args.get("through_date")
    through_date = parse_date(through_raw) if through_raw else None

    # Collect contributing months
    contributing_months = set()

    # inflows: CONFIRMED non-voided tickets for operation contracts
    inflow_by_month = {}
    for t in DB.tickets.values():
        if t["status"] != "CONFIRMED":
            continue
        contract = DB.contracts.get(t["contract_id"])
        if contract is None or contract["operation_id"] != op["id"]:
            continue
        d = parse_date(t["delivery_date"])
        key = (d.year, d.month)
        inflow_by_month[key] = inflow_by_month.get(key, Decimal("0")) + D(t["ticket_value_dollars"])
        contributing_months.add(key)

    # outflows: storage lots occupying a month
    lot_list = [l for l in DB.storage_lots.values() if l["operation_id"] == op["id"]]
    # For occupancy we need to know each month each lot occupies. Iterate over months between start and end_ref.
    lot_occupancy = []  # (lot, set of month keys)
    for lot in lot_list:
        start = parse_date(lot["start_date"])
        end_ref = parse_date(lot["actual_end_date"]) if lot.get("actual_end_date") else parse_date(lot["planned_end_date"])
        months = set()
        cur = date(start.year, start.month, 1)
        last_month = date(end_ref.year, end_ref.month, 1)
        while cur <= last_month:
            first, last = month_bounds(cur.year, cur.month)
            # lot occupies month m when start_date <= last day of m AND end_ref >= first day of m
            if start <= last and end_ref >= first:
                months.add((cur.year, cur.month))
            # advance month
            if cur.month == 12:
                cur = date(cur.year + 1, 1, 1)
            else:
                cur = date(cur.year, cur.month + 1, 1)
        lot_occupancy.append((lot, months))
        contributing_months.update(months)

    # LONG_PUT premium in execution month
    premium_by_month = {}
    for p in DB.positions.values():
        if p["operation_id"] != op["id"]:
            continue
        if p["instrument"] != "LONG_PUT":
            continue
        if p["status"] not in {"OPEN", "OFFSET", "LIQUIDATED"}:
            continue
        exec_dt = p["created_at"]
        # parse "YYYY-MM-DD..." from created_at
        d = parse_date(exec_dt[:10])
        key = (d.year, d.month)
        cost = D(p["bushels"]) * D(p["premium_per_bushel"])
        premium_by_month[key] = premium_by_month.get(key, Decimal("0")) + cost
        contributing_months.add(key)

    # Determine month range
    if not contributing_months:
        result = {
            "buckets": [],
            "total_inflow": 0.0,
            "total_outflow": 0.0,
            "net_cash_flow": 0.0,
        }
        return success_object(result)

    sorted_months = sorted(contributing_months)
    if through_date is not None:
        end_key = (through_date.year, through_date.month)
        sorted_months = [m for m in sorted_months if m <= end_key]

    buckets = []
    total_inflow = Decimal("0")
    total_outflow = Decimal("0")
    cumulative = Decimal("0")
    for key in sorted_months:
        inflow = inflow_by_month.get(key, Decimal("0"))
        storage_out = Decimal("0")
        for lot, months in lot_occupancy:
            if key in months:
                storage_out += D(lot["bushels"]) * D(lot["cost_per_bushel_month"])
        premium_out = premium_by_month.get(key, Decimal("0"))
        outflow = storage_out + premium_out
        net = inflow - outflow
        cumulative += net
        total_inflow += inflow
        total_outflow += outflow
        buckets.append({
            "month": f"{key[0]:04d}-{key[1]:02d}",
            "inflow": to_float(r2(inflow)),
            "outflow": to_float(r2(outflow)),
            "net_cash_flow": to_float(r2(net)),
            "cumulative_cash_flow": to_float(r2(cumulative)),
        })

    result = {
        "buckets": buckets,
        "total_inflow": to_float(r2(total_inflow)),
        "total_outflow": to_float(r2(total_outflow)),
        "net_cash_flow": to_float(r2(total_inflow - total_outflow)),
    }
    return success_object(result)
