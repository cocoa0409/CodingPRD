"""Assumption sets, rate curve snapshots, valuation runs."""
from flask import Blueprint

import calcs
import cascades
import serial
from core import (READ_REF, R_HEDGE, R_VALUATION, authenticate, body_of, f_date, f_dec,
                  f_enum, f_id, f_int, f_str, fail, filter_eq, fmt_date, lookup, new_row,
                  ok, paginate, rows, sort_created, touch)

bp = Blueprint("group_b", __name__)


# ---------------------------------------------------------------- assumption sets
@bp.post("/msr/assumption-sets")
def create_assumption_set():
    authenticate(R_VALUATION)
    body = body_of("assumption_name", "cpr_pct", "discount_rate_pct",
                   "cost_to_service_annual_cents", "float_earnings_rate_pct",
                   "projection_years")
    name = f_str(body, "assumption_name", max_len=80)
    cpr = f_dec(body, "cpr_pct", minimum=0, exclusive_min=True, maximum=100,
                exclusive_max=True, places=4)
    discount = f_dec(body, "discount_rate_pct", minimum=0, exclusive_min=True,
                     maximum=40, places=4)
    cost = f_int(body, "cost_to_service_annual_cents", minimum=0)
    float_rate = f_dec(body, "float_earnings_rate_pct", minimum=0, maximum=40, places=4)
    years = f_int(body, "projection_years", required=False, minimum=1, maximum=10, default=3)

    row = new_row("assumption_sets", versioned=False)
    row.update({"assumption_name": name, "cpr_pct": cpr, "discount_rate_pct": discount,
                "cost_to_service_annual_cents": cost, "float_earnings_rate_pct": float_rate,
                "projection_years": years})
    return ok(serial.ser_assumption_set(row), 201)


@bp.get("/msr/assumption-sets/<aset_id>")
def get_assumption_set(aset_id):
    authenticate(READ_REF)
    row = lookup("assumption_sets", aset_id, "ERR_ASSUMPTION_SET_NOT_FOUND")
    return ok(serial.ser_assumption_set(row))


# ---------------------------------------------------------------- rate curves
@bp.post("/msr/rate-curves")
def create_rate_curve():
    user_id, _ = authenticate(R_HEDGE)
    body = body_of("as_of_date", "base_rate_bps", "primary_secondary_spread_bps")
    as_of = f_date(body, "as_of_date")
    base_rate = f_int(body, "base_rate_bps", minimum=100, maximum=8000)
    spread = f_int(body, "primary_secondary_spread_bps", required=False, minimum=0,
                   maximum=200, default=25)

    incumbent = calcs.active_curve()
    if incumbent is not None and as_of <= incumbent["_as_of"]:
        fail("ERR_RATE_CURVE_DATE_NOT_ADVANCING",
             "as_of_date must be strictly later than the incumbent ACTIVE snapshot")

    row = new_row("rate_curves")
    row.update({"as_of_date": fmt_date(as_of), "_as_of": as_of, "base_rate_bps": base_rate,
                "primary_secondary_spread_bps": spread, "status": "ACTIVE",
                "superseded_at": None, "published_by_user_id": user_id})

    if incumbent is not None:
        cascades.supersede_curve_cascade(incumbent)
    cascades.remark_open_hedges(row)
    return ok(serial.ser_rate_curve(row), 201)


@bp.get("/msr/rate-curves/<curve_id>")
def get_rate_curve(curve_id):
    authenticate(READ_REF)
    row = lookup("rate_curves", curve_id, "ERR_RATE_CURVE_NOT_FOUND")
    return ok(serial.ser_rate_curve(row))


@bp.get("/msr/rate-curves")
def list_rate_curves():
    authenticate(READ_REF)
    items = calcs.curves_ranked()
    items = filter_eq(items, "status")
    return paginate(items, serial.ser_rate_curve)


# ---------------------------------------------------------------- valuation runs
@bp.post("/msr/portfolios/<pf_id>/valuation-runs")
def create_valuation_run(pf_id):
    user_id, _ = authenticate(R_VALUATION)
    body = body_of("assumption_set_id", "method", "expected_portfolio_version")
    aset_id = f_id(body, "assumption_set_id")
    method = f_enum(body, "method", ("DETERMINISTIC_STATIC", "OAS_SHOCK_WEIGHTED"))
    expected = f_int(body, "expected_portfolio_version", minimum=0)

    portfolio = lookup("portfolios", pf_id, "ERR_PORTFOLIO_NOT_FOUND")
    aset = lookup("assumption_sets", aset_id, "ERR_ASSUMPTION_SET_NOT_FOUND")
    if portfolio["status"] != "TAPE_LOCKED":
        fail("ERR_TAPE_NOT_LOCKED", "a valuation run requires a locked tape")
    if expected != portfolio["version"]:
        fail("ERR_STALE_PORTFOLIO_VERSION",
             "expected_portfolio_version does not match the stored portfolio version")
    curve = calcs.require_active_curve()

    result = calcs.msr_fair_value(pf_id, aset, curve, method)
    existing = [r for r in rows("valuation_runs") if r["portfolio_id"] == pf_id]
    sequence_no = max([r["sequence_no"] for r in existing], default=0) + 1

    row = new_row("valuation_runs")
    row.update({"portfolio_id": pf_id, "assumption_set_id": aset_id,
                "rate_curve_snapshot_id": curve["id"], "method": method,
                "sequence_no": sequence_no, "status": "COMPLETED",
                "value_cents": result["value_cents"],
                "value_bps_of_upb": result["value_bps_of_upb"],
                "included_loan_count": result["included_loan_count"],
                "effective_discount_rate_pct": result["effective_discount_rate_pct"],
                "scenario_values": result["scenario_values"],
                "run_by_user_id": user_id, "staled_at": None})

    cascades.supersede_older_runs(pf_id, row["id"])
    touch(portfolio)
    return ok(serial.ser_valuation_run(row), 201)


@bp.get("/msr/valuation-runs/<run_id>")
def get_valuation_run(run_id):
    authenticate(READ_REF)
    row = lookup("valuation_runs", run_id, "ERR_VALUATION_RUN_NOT_FOUND")
    return ok(serial.ser_valuation_run(row))


@bp.get("/msr/valuation-runs")
def list_valuation_runs():
    authenticate(READ_REF)
    items = sort_created(rows("valuation_runs"))
    items = filter_eq(items, "portfolio_id")
    items = filter_eq(items, "assumption_set_id")
    items = filter_eq(items, "rate_curve_snapshot_id")
    items = filter_eq(items, "method")
    items = filter_eq(items, "status")
    return paginate(items, serial.ser_valuation_run)
