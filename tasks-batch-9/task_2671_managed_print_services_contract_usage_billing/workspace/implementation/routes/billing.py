"""Billing periods and the two statement variants (PRD 3.7)."""
from flask import Blueprint

import calc
import derive
import serialize
import validation as v
from auth import require
from envelope import created, ok, ok_list
from errors import fail
from resolve import get_contract, get_period, get_statement
from store import db, new_row, touch
from util import overlaps

bp = Blueprint("billing", __name__)


@bp.post("/billing-periods")
def create_period():
    require("BillingAnalyst")
    body = v.body()
    contract_id = v.id_field(body, "contract_id")
    period_start = v.dt_field(body, "period_start")
    period_end = v.dt_field(body, "period_end")
    contract = get_contract(contract_id)

    if period_start >= period_end:
        fail("ERR_PERIOD_WINDOW_OVERLAP",
             "period_start must be strictly earlier than period_end.")
    for other in derive.contract_periods(contract["id"]):
        if overlaps(period_start, period_end, other["period_start"], other["period_end"]):
            fail("ERR_PERIOD_WINDOW_OVERLAP",
                 "The window intersects an existing period of this contract.")

    row = new_row()
    row.update({
        "contract_id": contract["id"],
        "period_start": period_start,
        "period_end": period_end,
        "status": "OPEN",
        "sweep_run_count": 0,
        "provisional_total_cents": None,
        "final_total_cents": None,
    })
    db.periods[row["id"]] = row
    return created(serialize.period(row))


@bp.get("/billing-periods/<period_id>")
def read_period(period_id):
    require("BillingAnalyst", "AccountManager", "FleetOpsController")
    period = get_period(period_id)
    return ok(serialize.period(period))


@bp.get("/billing-periods")
def list_periods():
    require("BillingAnalyst", "AccountManager", "FleetOpsController")
    rows = db.sorted_rows("periods")
    for field in ("contract_id", "status"):
        value = v.query_filter(field)
        if value is not None:
            rows = [p for p in rows if p[field] == value]
    data, meta = v.paginate(rows, serialize.period)
    return ok_list(data, meta)


def _write_statement(period, contract, variant, figures, line_specs):
    statement = new_row()
    statement.update({
        "billing_period_id": period["id"],
        "variant": variant,
        "projection_basis": "PROJECTED" if variant == "PROVISIONAL" else "ACTUAL",
        "generated_at": db.clock,
    })
    statement.update(figures)
    db.statements[statement["id"]] = statement
    for spec in line_specs:
        line = new_row(with_common=False)
        line.update(spec)
        line["statement_id"] = statement["id"]
        db.lines[line["id"]] = line
    return statement


@bp.post("/billing-periods/<period_id>/provisional-statement")
def provisional_statement(period_id):
    require("BillingAnalyst")
    period = get_period(period_id)
    body = v.body()
    expected = v.int_field(body, "expected_billing_period_version")

    if expected != period["version"]:
        fail("ERR_STALE_PERIOD_VERSION",
             "expected_billing_period_version %d does not match the period's current version %d."
             % (expected, period["version"]))
    if period["status"] not in ("OPEN", "SWEPT", "PROVISIONAL"):
        fail("ERR_PERIOD_INVALID_STATE",
             "A period in %s cannot receive a provisional statement." % period["status"])
    contract = db.contracts.get(period["contract_id"])
    if contract is None or contract["status"] != "ACTIVE":
        fail("ERR_CONTRACT_NOT_ACTIVE", "The governing contract is not ACTIVE.")

    figures, line_specs = calc.price_statement(period, contract, "PROVISIONAL", db.clock)

    prior = derive.period_statement(period["id"], "PROVISIONAL")
    if prior is not None:
        for line in derive.statement_lines(prior["id"]):
            db.lines.pop(line["id"], None)
        db.statements.pop(prior["id"], None)

    statement = _write_statement(period, contract, "PROVISIONAL", figures, line_specs)
    period["status"] = "PROVISIONAL"
    period["provisional_total_cents"] = statement["total_cents"]
    touch(period)
    return created(serialize.statement(statement))


@bp.post("/billing-periods/<period_id>/close")
def close_period(period_id):
    require("BillingAnalyst")
    period = get_period(period_id)
    v.body()

    if period["status"] not in ("SWEPT", "PROVISIONAL"):
        fail("ERR_PERIOD_INVALID_STATE",
             "A period in %s cannot be closed." % period["status"])
    contract = db.contracts.get(period["contract_id"])
    if contract is None or contract["status"] not in ("ACTIVE", "TERMINATING"):
        fail("ERR_CONTRACT_NOT_ACTIVE",
             "Closing requires a contract in ACTIVE or TERMINATING.")
    if db.clock < period["period_end"]:
        fail("ERR_PERIOD_NOT_ENDED", "The logical clock has not reached period_end.")
    if derive.exception_open_count(period["id"]) > 0:
        fail("ERR_PERIOD_HAS_OPEN_EXCEPTIONS",
             "The period still has open meter-read exceptions.")

    figures, line_specs = calc.price_statement(period, contract, "FINAL", db.clock)
    statement = _write_statement(period, contract, "FINAL", figures, line_specs)

    provisional_total = period["provisional_total_cents"]
    period["status"] = "CLOSED"
    period["final_total_cents"] = statement["total_cents"]
    touch(period)

    contract["lifetime_billed_cents"] += statement["total_cents"]
    if provisional_total is not None:
        contract["true_up_balance_cents"] += statement["total_cents"] - provisional_total
    touch(contract)
    return created(serialize.statement(statement))


@bp.get("/billing-statements/<statement_id>")
def read_statement(statement_id):
    require("BillingAnalyst", "AccountManager", "CustomerAdmin")
    statement = get_statement(statement_id)
    return ok(serialize.statement(statement))


@bp.get("/billing-statements")
def list_statements():
    require("BillingAnalyst", "AccountManager", "CustomerAdmin")
    rows = db.sorted_rows("statements")
    for field in ("billing_period_id", "variant"):
        value = v.query_filter(field)
        if value is not None:
            rows = [s for s in rows if s[field] == value]
    data, meta = v.paginate(rows, serialize.statement)
    return ok_list(data, meta)


@bp.get("/billing-statements/<statement_id>/lines")
def list_statement_lines(statement_id):
    require("BillingAnalyst", "AccountManager", "CustomerAdmin")
    statement = get_statement(statement_id)
    rows = derive.statement_lines(statement["id"])
    page_class = v.query_filter("page_class")
    if page_class is not None:
        rows = [l for l in rows if l["page_class"] == page_class]
    data, meta = v.paginate(rows, serialize.statement_line)
    return ok_list(data, meta)
