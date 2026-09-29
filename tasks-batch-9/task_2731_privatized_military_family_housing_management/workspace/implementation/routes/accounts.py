"""Reinvestment accounts: expenditures and the metrics-run checkpoint (PRD 3.10)."""

from flask import Blueprint

import middleware as mw
import response as resp
from db import (base_row, bump, db, month_bounds, now, now_iso, parse_date,
                parse_dt, parse_period, sort_rows, today)
from errors import ApiError
from services import calc, core, lookup

bp = Blueprint("accounts", __name__)

ACCOUNT_READ_ROLES = (mw.PLATFORM_ADMIN, mw.PROPERTY_MANAGER,
                      mw.INSTALLATION_HOUSING_OFFICE)
ACCOUNT_OPS_ROLES = (mw.PROPERTY_MANAGER, mw.PLATFORM_ADMIN)
FISCAL_YEAR_MIN = 2024
FISCAL_YEAR_MAX = 2030


@bp.post("/reinvestment-accounts")
def open_account():
    mw.authenticate((mw.PLATFORM_ADMIN,))
    body = mw.json_body()
    installation_id = mw.v_id(body, "installation_id")
    fiscal_year = mw.v_int(body, "fiscal_year", minimum=FISCAL_YEAR_MIN,
                           maximum=FISCAL_YEAR_MAX)
    opening = mw.v_int(body, "opening_balance_cents", minimum=0)
    basis = mw.v_enum(body, "occupancy_basis", mw.OCCUPANCY_BASES)
    installation = lookup.installation(installation_id)

    row = base_row()
    row["installation_id"] = installation["id"]
    row["fiscal_year"] = fiscal_year
    row["opening_balance_cents"] = opening
    row["contributions_cents"] = 0
    row["expenditures_cents"] = 0
    row["closing_balance_cents"] = opening
    row["occupancy_basis"] = basis
    row["occupancy_rate_pct"] = 0
    row["net_collected_cents"] = 0
    row["habitability_penalty_pct"] = 0
    row["performance_incentive_fee_cents"] = 0
    row["metrics_run_epoch"] = 0
    row["last_metrics_run_at"] = None
    db.accounts[row["id"]] = row
    return resp.created(row)


@bp.get("/reinvestment-accounts/<account_id>")
def get_account(account_id):
    mw.authenticate(ACCOUNT_READ_ROLES)
    return resp.ok(lookup.account(account_id))


@bp.get("/reinvestment-accounts")
def list_accounts():
    mw.authenticate(ACCOUNT_READ_ROLES)
    limit, offset = mw.pagination()
    installation_id = mw.q_str("installation_id")
    fiscal_year = mw.q_int("fiscal_year")
    basis = mw.q_enum("occupancy_basis", mw.OCCUPANCY_BASES)
    rows = sort_rows(list(db.accounts.values()))
    if installation_id is not None:
        rows = [r for r in rows if r["installation_id"] == installation_id]
    if fiscal_year is not None:
        rows = [r for r in rows if int(r["fiscal_year"]) == fiscal_year]
    if basis is not None:
        rows = [r for r in rows if r["occupancy_basis"] == basis]
    return resp.page(rows, limit, offset)


@bp.post("/reinvestment-accounts/<account_id>/expenditures")
def authorize_expenditure(account_id):
    mw.authenticate(ACCOUNT_OPS_ROLES)
    body = mw.json_body()
    expected_version = mw.v_int(body, "expected_account_version")
    amount = mw.v_int(body, "amount_cents", minimum=0)
    mw.v_str(body, "purpose")
    account = lookup.account(account_id)
    lookup.check_account_version(account, expected_version)

    if amount > int(account["closing_balance_cents"]):
        raise ApiError("ERR_REINVESTMENT_BALANCE_INSUFFICIENT")

    account["expenditures_cents"] = int(account["expenditures_cents"]) + amount
    core.recompute_closing(account)
    bump(account)
    return resp.ok(account)


# ------------------------------------------------------- metrics-run checkpoint

def _period_is_future(period):
    year, month = parse_period(period)
    current = today()
    return (year, month) > (current.year, current.month)


def _net_collected(installation_id, period):
    total = 0
    for lease in lookup.leases_of_installation(installation_id):
        for txn in lookup.transactions_of(lease["id"]):
            if txn["period_month"] == period:
                total += int(txn["amount_cents"])
    return total


def _escalated_in_period(installation_id, first_day, last_day):
    count = 0
    for order in lookup.work_orders_of_installation(installation_id):
        if int(order["escalation_level"]) < 1:
            continue
        reported = parse_dt(order["reported_at"]).date()
        if first_day <= reported <= last_day:
            count += 1
    return count


@bp.post("/reinvestment-accounts/<account_id>/metrics-run")
def metrics_run(account_id):
    mw.authenticate(ACCOUNT_OPS_ROLES)
    body = mw.json_body()
    period = mw.v_period(body, "period_month")
    account = lookup.account(account_id)

    if (account["id"], period) in db.metrics_runs or _period_is_future(period):
        raise ApiError("ERR_PERIOD_ALREADY_POSTED")

    installation = lookup.installation(account["installation_id"])
    first_day, last_day = month_bounds(period)
    units = lookup.units_of(installation["id"])
    leases_by_unit = {}
    for unit in units:
        leases_by_unit[unit["id"]] = lookup.leases_of_unit(unit["id"])

    rate = calc.occupancy_rate(account["occupancy_basis"], units, leases_by_unit,
                               first_day, last_day)
    net_collected = _net_collected(installation["id"], period)
    escalated = _escalated_in_period(installation["id"], first_day, last_day)
    _base_fee, _mult, penalty, fee = calc.incentive_fee(
        net_collected, installation["incentive_base_pct"], rate, escalated)

    account["occupancy_rate_pct"] = float(rate)
    account["net_collected_cents"] = net_collected
    account["habitability_penalty_pct"] = float(penalty)
    account["performance_incentive_fee_cents"] = fee
    account["contributions_cents"] = int(account["contributions_cents"]) \
        + calc.contribution_from(net_collected)
    core.recompute_closing(account)
    account["metrics_run_epoch"] = int(account["metrics_run_epoch"]) + 1
    account["last_metrics_run_at"] = now_iso()
    bump(account)
    db.metrics_runs.add((account["id"], period))
    return resp.ok(account)
