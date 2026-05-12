"""Dividend plan and distribution routes."""
from datetime import timedelta, timezone
from flask import Blueprint, g

import db
from db import (
    funds, investors, holdings, dividend_plans, dividend_distributions,
    nav_snapshots, stamp_create, stamp_update, public,
)
from clock import now, iso, parse_iso, parse_iso_date, date_to_dt_utc
from errors import err
from middleware import require_auth
from response import success
from services import audit
from services.util import get_body, require_field, check_version
from services.calculations import (
    compute_dividend_amounts, compute_reinvested_shares,
)
from services.holdings import (
    get_or_create_holding, recompute_holding_aggregates, create_lot,
)
from services.nav import find_nav_snapshot


bp = Blueprint("dividends", __name__)


def _validate_dividend_dates(announcement_date, record_date, ex_dividend_date, payment_date):
    if record_date < announcement_date:
        return False
    if ex_dividend_date != record_date + timedelta(days=1):
        return False
    if payment_date < ex_dividend_date:
        return False
    return True


@bp.route("/funds/<id>/dividend-plans", methods=["POST"])
@require_auth(roles={"ProductOperator"})
def announce_dividend(id):
    fund = funds.get(id)
    if not fund:
        raise err("ERR_NOT_FOUND", "Fund not found")
    if fund["status"] != "ON_SHELF":
        raise err("ERR_INVALID_STATE", f"Fund.status={fund['status']}, expected ON_SHELF")

    body = get_body()
    for f in ("announcement_date", "record_date", "ex_dividend_date", "payment_date",
              "dividend_per_share_micros", "tax_rate_bps_domestic", "tax_rate_bps_foreign"):
        require_field(body, f)
    try:
        ad = parse_iso_date(body["announcement_date"])
        rd = parse_iso_date(body["record_date"])
        ed = parse_iso_date(body["ex_dividend_date"])
        pd = parse_iso_date(body["payment_date"])
    except Exception:
        raise err("ERR_DIVIDEND_DATE_INVALID", "Invalid date in dividend plan")

    if not _validate_dividend_dates(ad, rd, ed, pd):
        raise err("ERR_DIVIDEND_DATE_INVALID", "Dividend dates do not satisfy ordering rule")

    plan = {
        "fund_id": fund["id"],
        "announcement_date": iso(date_to_dt_utc(ad)),
        "record_date": iso(date_to_dt_utc(rd)),
        "ex_dividend_date": iso(date_to_dt_utc(ed)),
        "payment_date": iso(date_to_dt_utc(pd)),
        "dividend_per_share_micros": body["dividend_per_share_micros"],
        "status": "ANNOUNCED",
        "tax_rate_bps_domestic": body["tax_rate_bps_domestic"],
        "tax_rate_bps_foreign": body["tax_rate_bps_foreign"],
    }
    stamp_create(plan, common_fields=True)
    dividend_plans[plan["id"]] = plan
    return success(public(plan), 201)


@bp.route("/dividend-plans/<id>/mark-ex-dividend", methods=["POST"])
@require_auth(roles={"NavOperator"})
def mark_ex_dividend(id):
    plan = dividend_plans.get(id)
    if not plan:
        raise err("ERR_NOT_FOUND", "Dividend plan not found")
    body = get_body()
    check_version(body, plan)
    if plan["status"] != "ANNOUNCED":
        raise err("ERR_INVALID_STATE", f"Plan.status={plan['status']}, expected ANNOUNCED")
    fund = funds[plan["fund_id"]]
    if fund["status"] != "ON_SHELF":
        raise err("ERR_INVALID_STATE", f"Fund.status={fund['status']}, expected ON_SHELF")
    ed = parse_iso_date(plan["ex_dividend_date"])
    # date portion of clock >= ex_dividend_date
    if now().astimezone(timezone.utc).date() < ed:
        raise err("ERR_INVALID_STATE", "Clock has not reached ex_dividend_date")

    plan["status"] = "EX_DIVIDEND"
    stamp_update(plan)

    # Snapshot eligible holdings at record_date end -> create DividendDistribution rows
    # We use Holding.shares as currently stored (record_date semantics).
    for h in list(holdings.values()):
        if h["fund_id"] != fund["id"]:
            continue
        if h["shares"] <= 0:
            continue
        investor = investors[h["investor_id"]]
        gross, tax, net_amt = compute_dividend_amounts(
            h["shares"], plan["dividend_per_share_micros"],
            investor["tax_resident_status"],
            plan["tax_rate_bps_domestic"], plan["tax_rate_bps_foreign"],
        )
        dist = {
            "dividend_plan_id": plan["id"],
            "investor_id": investor["id"],
            "eligible_shares": h["shares"],
            "gross_dividend_cents": gross,
            "tax_withheld_cents": tax,
            "net_dividend_cents": net_amt,
            "option": "CASH",
            "reinvested_shares": 0,
        }
        stamp_create(dist, common_fields=False)
        dividend_distributions[dist["id"]] = dist

    audit.write(g.user_id, g.user_role, "DIVIDEND_EXECUTED", "DividendPlan", plan["id"],
                "ANNOUNCED", "EX_DIVIDEND", {})
    return success(public(plan), 200)


@bp.route("/dividend-plans/<id>/distributions/<investor_id>/set-option", methods=["POST"])
@require_auth(roles={"Investor"})
def set_option(id, investor_id):
    plan = dividend_plans.get(id)
    if not plan:
        raise err("ERR_NOT_FOUND", "Dividend plan not found")
    inv = investors.get(investor_id)
    if not inv:
        raise err("ERR_NOT_FOUND", "Investor not found")
    if g.user_id != investor_id:
        raise err("ERR_FORBIDDEN", "Investor may only set their own option")
    body = get_body()
    require_field(body, "option")
    opt = body["option"]
    if opt not in ("CASH", "REINVEST"):
        raise err("ERR_VALIDATION", "option must be CASH or REINVEST")

    # Find the DividendDistribution
    dist = None
    for d in dividend_distributions.values():
        if d["dividend_plan_id"] == id and d["investor_id"] == investor_id:
            dist = d
            break
    if not dist:
        raise err("ERR_NOT_FOUND", "Distribution not found")
    if plan["status"] != "EX_DIVIDEND":
        raise err("ERR_INVALID_STATE", f"Plan.status={plan['status']}, expected EX_DIVIDEND")

    dist["option"] = opt
    return success(public(dist), 200)


@bp.route("/dividend-plans/<id>/execute-payment", methods=["POST"])
@require_auth(roles={"NavOperator"})
def execute_payment(id):
    plan = dividend_plans.get(id)
    if not plan:
        raise err("ERR_NOT_FOUND", "Dividend plan not found")
    body = get_body()
    check_version(body, plan)
    if plan["status"] != "EX_DIVIDEND":
        raise err("ERR_INVALID_STATE", f"Plan.status={plan['status']}, expected EX_DIVIDEND")
    fund = funds[plan["fund_id"]]
    pd = parse_iso_date(plan["payment_date"])
    if now().astimezone(timezone.utc).date() < pd:
        raise err("ERR_INVALID_STATE", "Clock has not reached payment_date")

    ed = parse_iso_date(plan["ex_dividend_date"])
    nav_snap = find_nav_snapshot(fund["id"], ed)
    if not nav_snap or nav_snap["status"] not in ("PUBLISHED", "ADJUSTED"):
        raise err("ERR_INVALID_STATE", "NAV snapshot for ex_dividend_date is not PUBLISHED")

    # For each distribution: cash or reinvest
    for d in list(dividend_distributions.values()):
        if d["dividend_plan_id"] != plan["id"]:
            continue
        investor = investors[d["investor_id"]]
        if d["option"] == "CASH":
            investor["cash_balance_cents"] += d["net_dividend_cents"]
            stamp_update(investor)
        else:
            # REINVEST: compute shares from net/ex-div NAV using HALF_DOWN
            shares = compute_reinvested_shares(d["net_dividend_cents"], nav_snap["nav_per_share_micros"])
            d["reinvested_shares"] = shares
            if shares > 0:
                holding = get_or_create_holding(investor["id"], fund["id"])
                # Lot acquired_at = ex_dividend_date
                create_lot(
                    holding["id"], plan["id"], shares, d["net_dividend_cents"],
                    iso(date_to_dt_utc(ed)),
                )
                recompute_holding_aggregates(investor["id"], fund["id"])
                fund["total_outstanding_shares"] += shares
                stamp_update(fund)

    plan["status"] = "PAID"
    stamp_update(plan)
    audit.write(g.user_id, g.user_role, "DIVIDEND_EXECUTED", "DividendPlan", plan["id"],
                "EX_DIVIDEND", "PAID", {})
    return success(public(plan), 200)


@bp.route("/dividend-plans/<id>/cancel", methods=["POST"])
@require_auth(roles={"ComplianceReviewer"})
def cancel_dividend(id):
    plan = dividend_plans.get(id)
    if not plan:
        raise err("ERR_NOT_FOUND", "Dividend plan not found")
    body = get_body()
    check_version(body, plan)
    if plan["status"] != "ANNOUNCED":
        raise err("ERR_INVALID_STATE", f"Plan.status={plan['status']}, expected ANNOUNCED")
    ed = parse_iso_date(plan["ex_dividend_date"])
    if now().astimezone(timezone.utc).date() >= ed:
        raise err("ERR_INVALID_STATE", "Cannot cancel after ex_dividend_date reached")
    plan["status"] = "CANCELLED"
    stamp_update(plan)
    audit.write(g.user_id, g.user_role, "DIVIDEND_EXECUTED", "DividendPlan", plan["id"],
                "ANNOUNCED", "CANCELLED", {})
    return success(public(plan), 200)


@bp.route("/dividend-plans/<id>", methods=["GET"])
@require_auth(roles={"PlatformAdmin", "ComplianceReviewer", "NavOperator", "Investor"})
def get_dividend(id):
    plan = dividend_plans.get(id)
    if not plan:
        raise err("ERR_NOT_FOUND", "Dividend plan not found")
    out = public(plan).copy()
    dists = [public(d) for d in dividend_distributions.values()
             if d["dividend_plan_id"] == id]
    out["distributions"] = dists
    return success(out, 200)
