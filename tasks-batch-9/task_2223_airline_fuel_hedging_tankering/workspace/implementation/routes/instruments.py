"""HedgeInstrument endpoints: execution, designation, termination, testing."""

from decimal import Decimal

from flask import Blueprint, g

import calc
import domain
import fetch
import serializers as ser
import validators as v
from calc import ZERO, r2, r4
from db import db, now_iso, rows_in_order
from errors import fail
from middleware import (FUEL_ANALYST, HEDGE_ACCOUNTANT, RISK_POLICY_ADMIN,
                        TREASURY_RISK_MANAGER, endpoint, new_row, touch)
from response import created, ok, ok_list
from routes.counterparties import POSTING_ORIGINS, POSTING_STATUSES
from routes.programs import ACCOUNTING_STATUSES, TRADE_STATUSES

bp = Blueprint("instruments", __name__)

TEST_RESULTS = ("PASS", "FAIL")


@bp.get("/fuel/hedge-instruments/<instrument_id>")
@endpoint(RISK_POLICY_ADMIN, FUEL_ANALYST, TREASURY_RISK_MANAGER, HEDGE_ACCOUNTANT)
def read_instrument(instrument_id):
    return ok(ser.instrument(fetch.instrument(instrument_id)))


@bp.get("/fuel/hedge-instruments")
@endpoint(RISK_POLICY_ADMIN, FUEL_ANALYST, TREASURY_RISK_MANAGER, HEDGE_ACCOUNTANT)
def list_instruments():
    limit, offset = v.pagination()
    counterparty_id = v.raw_filter("counterparty_id")
    program_id = v.raw_filter("hedge_program_id")
    trade_status = v.enum_filter("trade_status", TRADE_STATUSES)
    accounting_status = v.enum_filter("accounting_status", ACCOUNTING_STATUSES)
    maturity_month = v.month_filter("maturity_month")

    rows = rows_in_order(db.instruments)
    if counterparty_id is not None:
        rows = [r for r in rows if r["counterparty_id"] == counterparty_id]
    if program_id is not None:
        rows = [r for r in rows if r["hedge_program_id"] == program_id]
    if trade_status is not None:
        rows = [r for r in rows if r["trade_status"] == trade_status]
    if accounting_status is not None:
        rows = [r for r in rows if r["accounting_status"] == accounting_status]
    if maturity_month is not None:
        rows = [r for r in rows if r["maturity_month"] == maturity_month]
    page, total = v.paginate(rows, limit, offset)
    return ok_list([ser.instrument(r) for r in page], limit, offset, total)


@bp.post("/fuel/hedge-instruments/<instrument_id>/execute")
@endpoint(TREASURY_RISK_MANAGER)
def execute_instrument(instrument_id):
    instrument = fetch.instrument(instrument_id)

    if instrument["trade_status"] != "PROPOSED":
        fail("ERR_INSTRUMENT_INVALID_TRADE_STATE",
             "Only a PROPOSED trade may be executed; this one is %s."
             % instrument["trade_status"])

    program = db.programs.get(instrument["hedge_program_id"])
    if program is None or program["status"] != "ACTIVE":
        fail("ERR_PROGRAM_NOT_ACTIVE",
             "The owning programme must be ACTIVE to execute a trade.")

    counterparty = db.counterparties.get(instrument["counterparty_id"])
    if counterparty is None or counterparty["status"] != "APPROVED":
        fail("ERR_COUNTERPARTY_NOT_APPROVED",
             "The facing counterparty must be APPROVED to execute a trade.")

    policy = domain.governing_policy(program)
    basis = program["consumption_basis_gallons"]
    coverage = domain.program_coverage(program)

    # Step 20: the ceiling reads the *unrounded* post-trade delta-adjusted ratio.
    if basis != 0 and policy is not None:
        post_delta = coverage["_delta_executed_raw"] + instrument["delta_adjusted_gallons"]
        exact_pct = post_delta / basis * Decimal(100)
        if exact_pct > policy["max_coverage_pct"]:
            fail("ERR_COVERAGE_LIMIT_EXCEEDED",
                 "Post-trade delta-adjusted coverage would exceed the policy ceiling of %s."
                 % policy["max_coverage_pct"])

    # Step 21: single-counterparty concentration, on the rounded share.
    if policy is not None:
        same_dealer = ZERO
        for sibling in domain.program_instruments(program["id"]):
            if sibling["id"] == instrument["id"]:
                continue
            if sibling["trade_status"] != "EXECUTED":
                continue
            if sibling["counterparty_id"] != counterparty["id"]:
                continue
            same_dealer += sibling["notional_gallons"]
        same_dealer += instrument["notional_gallons"]
        share = r2(0) if basis == 0 else r2(same_dealer / basis * Decimal(100))
        if share > policy["max_single_counterparty_pct"] and not domain.has_approved_exception(
                "COUNTERPARTY_CONCENTRATION", instrument_id=instrument["id"]):
            fail("ERR_EXCEPTION_REQUIRED",
                 "Single-counterparty concentration %s exceeds the policy cap %s and no "
                 "approved concentration exception references this instrument."
                 % (share, policy["max_single_counterparty_pct"]))

    margin = domain.compute_margin_for(instrument, counterparty)

    utilized, _posted, _calls, _pct, _posture = domain.counterparty_ledgers(counterparty)
    if utilized + margin > counterparty["credit_limit_usd"]:
        fail("ERR_COUNTERPARTY_CREDIT_EXCEEDED",
             "Executing this trade would push utilised credit past the counterparty limit.")

    instrument["trade_status"] = "EXECUTED"
    instrument["executed_at"] = now_iso()
    instrument["margin_requirement_usd"] = margin
    touch(instrument)
    touch(counterparty)
    touch(program)
    return ok(ser.instrument(instrument))


@bp.post("/fuel/hedge-instruments/<instrument_id>/designate")
@endpoint(HEDGE_ACCOUNTANT)
def designate_instrument(instrument_id):
    instrument = fetch.instrument(instrument_id)

    if instrument["accounting_status"] == "DESIGNATED":
        fail("ERR_INSTRUMENT_INVALID_ACCOUNTING_STATE",
             "This trade is already DESIGNATED.")
    if instrument["trade_status"] != "EXECUTED":
        fail("ERR_INSTRUMENT_INVALID_TRADE_STATE",
             "Only an EXECUTED trade may be designated; this one is %s."
             % instrument["trade_status"])

    program = db.programs.get(instrument["hedge_program_id"])
    if program is None or program["status"] != "ACTIVE":
        fail("ERR_PROGRAM_NOT_ACTIVE",
             "The owning programme must be ACTIVE to designate a trade.")

    redesignation = instrument["accounting_status"] == "DEDESIGNATED"
    if redesignation and not domain.has_approved_exception(
            "EARNINGS_VOLATILITY_BREACH", instrument_id=instrument["id"]):
        fail("ERR_EXCEPTION_REQUIRED",
             "Re-designating a DEDESIGNATED trade requires an APPROVED "
             "EARNINGS_VOLATILITY_BREACH exception referencing this instrument.")

    instrument["accounting_status"] = "DESIGNATED"
    instrument["designated_at"] = now_iso()
    touch(instrument)

    if redesignation:
        domain.reclassify_into_designated(program, instrument)
        domain.refresh_program_compliance(program)
        touch(program)

    return ok(ser.instrument(instrument))


@bp.post("/fuel/hedge-instruments/<instrument_id>/terminate")
@endpoint(TREASURY_RISK_MANAGER)
def terminate_instrument(instrument_id):
    data = v.body()
    v.get_string(data, "termination_reason", min_len=1)

    instrument = fetch.instrument(instrument_id)
    status = instrument["trade_status"]
    if status not in ("PROPOSED", "EXECUTED"):
        fail("ERR_INSTRUMENT_INVALID_TRADE_STATE",
             "Only a PROPOSED or EXECUTED trade may be terminated; this one is %s."
             % status)

    program = db.programs.get(instrument["hedge_program_id"])

    if status == "PROPOSED":
        instrument["trade_status"] = "TERMINATED"
        touch(instrument)
        touch(program)
        return ok(ser.instrument(instrument))

    # Full compensating cascade for an executed trade.
    instrument["trade_status"] = "TERMINATED"
    instrument["margin_requirement_usd"] = r2(0)
    if instrument["accounting_status"] == "DESIGNATED":
        instrument["accounting_status"] = "DEDESIGNATED"
    touch(instrument)

    domain.return_posted_collateral(instrument)

    counterparty = db.counterparties.get(instrument["counterparty_id"])
    touch(counterparty)
    touch(program)
    return ok(ser.instrument(instrument))


@bp.post("/fuel/hedge-instruments/<instrument_id>/effectiveness-tests")
@endpoint(HEDGE_ACCOUNTANT)
def create_effectiveness_test(instrument_id):
    data = v.body()
    period_month = v.get_month(data, "period_month")
    hedge_change = v.get_number(data, "hedge_change_usd", places=2)
    item_change = v.get_number(data, "hedged_item_change_usd", places=2)
    if hedge_change == 0:
        fail("ERR_INVALID_REQUEST", "Field 'hedge_change_usd' must not be 0.")
    if item_change == 0:
        fail("ERR_INVALID_REQUEST", "Field 'hedged_item_change_usd' must not be 0.")

    instrument = fetch.instrument(instrument_id)
    if instrument["trade_status"] != "EXECUTED":
        fail("ERR_INSTRUMENT_INVALID_TRADE_STATE",
             "Only an EXECUTED trade may be effectiveness-tested; this one is %s."
             % instrument["trade_status"])

    period_ratio, cumulative_ratio, result, new_cum_hedge, new_cum_item = calc.effectiveness(
        hedge_change, item_change,
        instrument["cumulative_hedge_change_usd"],
        instrument["cumulative_item_change_usd"],
    )

    row = new_row(extra_common=False)
    row.update({
        "hedge_instrument_id": instrument["id"],
        "period_month": period_month,
        "hedge_change_usd": hedge_change,
        "hedged_item_change_usd": item_change,
        "period_ratio": period_ratio,
        "cumulative_ratio": cumulative_ratio,
        "result": result,
        "tested_by_user_id": g.user_id,
    })
    db.tests[row["id"]] = row

    instrument["cumulative_hedge_change_usd"] = r2(new_cum_hedge)
    instrument["cumulative_item_change_usd"] = r2(new_cum_item)
    was_designated = instrument["accounting_status"] == "DESIGNATED"
    if result == "FAIL" and was_designated:
        instrument["accounting_status"] = "DEDESIGNATED"
    touch(instrument)

    if result == "FAIL" and was_designated:
        program = db.programs.get(instrument["hedge_program_id"])
        if program is not None:
            domain.de_designation_cascade(program, instrument)

    return created(ser.effectiveness_test(row))


@bp.get("/fuel/hedge-instruments/<instrument_id>/effectiveness-tests")
@endpoint(RISK_POLICY_ADMIN, TREASURY_RISK_MANAGER, HEDGE_ACCOUNTANT)
def list_effectiveness_tests(instrument_id):
    limit, offset = v.pagination()
    result = v.enum_filter("result", TEST_RESULTS)

    instrument = fetch.instrument(instrument_id)
    rows = domain.instrument_tests(instrument["id"])
    if result is not None:
        rows = [r for r in rows if r["result"] == result]
    page, total = v.paginate(rows, limit, offset)
    return ok_list([ser.effectiveness_test(r) for r in page], limit, offset, total)


@bp.get("/fuel/hedge-instruments/<instrument_id>/collateral-postings")
@endpoint(RISK_POLICY_ADMIN, TREASURY_RISK_MANAGER, HEDGE_ACCOUNTANT)
def list_instrument_postings(instrument_id):
    limit, offset = v.pagination()
    status = v.enum_filter("status", POSTING_STATUSES)
    origin = v.enum_filter("origin", POSTING_ORIGINS)

    instrument = fetch.instrument(instrument_id)
    rows = domain.instrument_postings(instrument["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if origin is not None:
        rows = [r for r in rows if r["origin"] == origin]
    page, total = v.paginate(rows, limit, offset)
    return ok_list([ser.posting(r) for r in page], limit, offset, total)
