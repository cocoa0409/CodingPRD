"""MarkToMarketRun endpoints: open, compute and the publication cascade (PRD 3.7)."""

from flask import Blueprint

import calc
import domain
import fetch
import serializers as ser
import validators as v
from calc import ZERO, r2
from db import db, now_iso, rows_in_order
from errors import fail
from middleware import (HEDGE_ACCOUNTANT, RISK_POLICY_ADMIN,
                        TREASURY_RISK_MANAGER, endpoint, new_row, touch)
from response import created, ok

bp = Blueprint("mtm", __name__)


def _scope():
    """Every instrument EXECUTED at the moment of the call, created_at ASC."""
    return [i for i in rows_in_order(db.instruments) if i["trade_status"] == "EXECUTED"]


@bp.post("/fuel/mark-to-market-runs")
@endpoint(HEDGE_ACCOUNTANT)
def create_run():
    data = v.body()
    period_month = v.get_month(data, "period_month")
    index = v.get_number(data, "settlement_index_usd_per_gal",
                         exclusive_minimum=0, places=4)

    for row in db.mtm_runs.values():
        if row["period_month"] == period_month:
            fail("ERR_DUPLICATE_MTM_PERIOD",
                 "A mark-to-market run already exists for %s." % period_month)

    row = new_row()
    row.update({
        "period_month": period_month,
        "settlement_index_usd_per_gal": index,
        "status": "OPEN",
        "instrument_count": 0,
        "total_mtm_usd": r2(0),
        "designated_mtm_usd": r2(0),
        "undesignated_mtm_usd": r2(0),
        "margin_calls_created": 0,
        "settled_instrument_count": 0,
        "computed_at": None,
        "published_at": None,
    })
    db.mtm_runs[row["id"]] = row
    return created(ser.mtm_run(row))


@bp.get("/fuel/mark-to-market-runs/<run_id>")
@endpoint(RISK_POLICY_ADMIN, TREASURY_RISK_MANAGER, HEDGE_ACCOUNTANT)
def read_run(run_id):
    return ok(ser.mtm_run(fetch.mtm_run(run_id)))


@bp.post("/fuel/mark-to-market-runs/<run_id>/compute")
@endpoint(HEDGE_ACCOUNTANT)
def compute_run(run_id):
    run = fetch.mtm_run(run_id)
    if run["status"] not in ("OPEN", "COMPUTED"):
        fail("ERR_MTM_RUN_INVALID_STATE",
             "Computation is declared only from OPEN and COMPUTED; this run is %s."
             % run["status"])

    index = run["settlement_index_usd_per_gal"]
    scope = _scope()

    total = ZERO
    designated = ZERO
    undesignated = ZERO
    for instrument in scope:
        value = calc.instrument_mtm(instrument, index)
        instrument["mtm_value_usd"] = value
        touch(instrument)
        total += value
        if instrument["accounting_status"] == "DESIGNATED":
            designated += value
        else:
            undesignated += value

    run["instrument_count"] = len(scope)
    run["total_mtm_usd"] = r2(total)
    run["designated_mtm_usd"] = r2(designated)
    run["undesignated_mtm_usd"] = r2(undesignated)
    run["status"] = "COMPUTED"
    run["computed_at"] = now_iso()
    touch(run)
    return ok(ser.mtm_run(run))


@bp.post("/fuel/mark-to-market-runs/<run_id>/publish")
@endpoint(RISK_POLICY_ADMIN)
def publish_run(run_id):
    run = fetch.mtm_run(run_id)
    if run["status"] != "COMPUTED":
        fail("ERR_MTM_RUN_INVALID_STATE",
             "Publication is declared only from COMPUTED; this run is %s." % run["status"])

    scope = _scope()

    run["status"] = "PUBLISHED"
    run["published_at"] = now_iso()
    run["margin_calls_created"] = 0
    run["settled_instrument_count"] = 0
    touch(run)

    # Hop 1: re-run the margin calculation against the published marks, one
    # instrument at a time so the concentration add-on can escalate.
    for instrument in scope:
        counterparty = db.counterparties.get(instrument["counterparty_id"])
        if counterparty is None:
            continue
        instrument["margin_requirement_usd"] = domain.compute_margin_for(
            instrument, counterparty)
        touch(instrument)

    # Hop 2: synthesise margin calls where collateral no longer covers margin.
    for instrument in scope:
        posted = domain.instrument_collateral_posted(instrument)
        if instrument["margin_requirement_usd"] <= posted:
            continue
        row = new_row()
        row.update({
            "counterparty_id": instrument["counterparty_id"],
            "hedge_instrument_id": instrument["id"],
            "collateral_type": "CASH",
            "required_amount_usd": r2(instrument["margin_requirement_usd"] - posted),
            "posted_amount_usd": r2(0),
            "status": "REQUIRED",
            "origin": "MTM_MARGIN_CALL",
            "posted_at": None,
            "returned_at": None,
        })
        db.postings[row["id"]] = row
        run["margin_calls_created"] = run["margin_calls_created"] + 1

    # Hop 3: refresh every affected counterparty ledger.
    for instrument in scope:
        touch(db.counterparties.get(instrument["counterparty_id"]))

    # Part 4: reclassify each owning programme from this run's buckets.
    seen_programs = []
    buckets = {}
    for instrument in scope:
        program_id = instrument["hedge_program_id"]
        if program_id not in buckets:
            buckets[program_id] = [ZERO, ZERO]
            seen_programs.append(program_id)
        bucket = buckets[program_id]
        if instrument["accounting_status"] == "DESIGNATED":
            bucket[0] += instrument["mtm_value_usd"]
        else:
            bucket[1] += instrument["mtm_value_usd"]

    for program_id in seen_programs:
        program = db.programs.get(program_id)
        if program is None:
            continue
        designated, undesignated = buckets[program_id]
        program["designated_mtm_usd"] = r2(designated)
        program["undesignated_mtm_usd"] = r2(undesignated)
        became_breach = domain.refresh_program_compliance(program)
        touch(program)
        if became_breach:
            domain.raise_system_breach_exception(program)

    # Settlement runs last, after the four-part cascade.
    for instrument in scope:
        if instrument["maturity_month"] <= run["period_month"]:
            domain.settle_instrument(instrument, run)

    return ok(ser.mtm_run(run))
