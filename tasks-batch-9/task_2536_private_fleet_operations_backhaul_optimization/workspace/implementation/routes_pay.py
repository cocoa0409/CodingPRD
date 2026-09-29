"""Driver pay statements -- PRD §3.8."""

from flask import Blueprint

from core import apply_filters, auth, bump, fail, must_exist, out, page, respond, db
import validate as v

bp = Blueprint("pay", __name__)

READ_ROLES = ["PayrollAnalyst", "TransportManager", "Driver"]
STATEMENT_STATUSES = ("ACCRUED", "SETTLED", "REVERSED")
# §3.8 declares the pay engine's two variants; both are declared values of the
# `variant` vocabulary, so both are accepted as a filter even though only
# FINAL_SETTLEMENT is ever persisted on a statement.
VARIANTS = ("PLANNED_ACCRUAL", "FINAL_SETTLEMENT")


def _unwind_ledgers(statement, sign):
    """Move Driver.ytd_gross_cents and Domicile.accrued_pay_cents together."""
    driver = db.drivers.get(statement.get("driver_id")) if statement.get("driver_id") else None
    if driver is None:
        return
    driver["ytd_gross_cents"] = int(driver["ytd_gross_cents"]) + sign * int(
        statement["gross_cents"]
    )
    bump(driver)
    domicile = db.domiciles.get(driver["domicile_id"])
    if domicile is not None:
        domicile["accrued_pay_cents"] = int(domicile["accrued_pay_cents"]) + sign * int(
            statement["gross_cents"]
        )
        bump(domicile)


@bp.get("/pay-statements/<statement_id>")
def get_statement(statement_id):
    auth(READ_ROLES)
    return respond(out(must_exist("statements", statement_id)))


@bp.get("/pay-statements")
def list_statements():
    auth(READ_ROLES)
    limit, offset = v.page_window()
    rows = apply_filters(list(db.statements.values()), [
        ("driver_id", v.qstr("driver_id")),
        ("trip_id", v.qstr("trip_id")),
        ("pay_plan_id", v.qstr("pay_plan_id")),
        ("status", v.qenum("status", STATEMENT_STATUSES)),
        ("variant", v.qenum("variant", VARIANTS)),
    ])
    return page(rows, limit, offset)


@bp.post("/pay-statements/<statement_id>/settle")
def settle_statement(statement_id):
    auth(["PayrollAnalyst"])
    statement = must_exist("statements", statement_id)
    data = v.body()
    reference = v.rstr(data, "settlement_reference")
    # level 8: the statement's own state
    if statement["status"] != "ACCRUED":
        fail("ERR_STATEMENT_NOT_ACCRUED")
    # level 10: the trip's payroll dimension
    trip = db.trips.get(statement["trip_id"])
    if trip is None or trip["settlement_status"] != "ACCRUED":
        fail("ERR_INVALID_STATE_TRANSITION")
    # level 16: a zero-gross statement cannot be paid at all
    if int(statement["gross_cents"]) == 0:
        fail("ERR_ZERO_PAY_SETTLEMENT")
    statement["settlement_reference"] = reference
    statement["status"] = "SETTLED"
    bump(statement)
    # Domicile.accrued_pay_cents does NOT move: both statuses sit in the filter.
    trip["settlement_status"] = "SETTLED"
    bump(trip)
    return respond(out(statement))


@bp.post("/pay-statements/<statement_id>/reverse")
def reverse_statement(statement_id):
    auth(["PayrollAnalyst"])
    statement = must_exist("statements", statement_id)
    data = v.body()
    reason = v.ostr(data, "reason_code")
    if statement["status"] not in ("ACCRUED", "SETTLED"):
        fail("ERR_STATEMENT_NOT_ACCRUED")
    statement["status"] = "REVERSED"
    statement["_reason_code"] = reason
    bump(statement)
    _unwind_ledgers(statement, -1)
    trip = db.trips.get(statement["trip_id"])
    if trip is not None:
        trip["settlement_status"] = "ADJUSTED"
        trip["driver_pay_cents"] = 0
        bump(trip)
    return respond(out(statement))
