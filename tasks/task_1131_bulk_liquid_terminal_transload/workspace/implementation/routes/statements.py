"""MonthlyStatement endpoints: create (OPEN), list, get, close, invoice."""
from datetime import datetime, timezone

from flask import Blueprint

from clock import CLOCK
from db import STORE, new_id
from errors import err
from middleware import require_roles, current_user
from response import success_object, success_list
from serializers import statement_view
from services.common import touch, get_lease_or_404
from services import lifecycle
from validation import get_body, req_period, sort_and_page

bp = Blueprint("statements", __name__)


def _period_bounds(period):
    year = int(period[0:4])
    month = int(period[5:7])
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    if month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    return start, end


@bp.post("/lease-agreements/<leaseId>/statements")
def create_statement(leaseId):
    require_roles("BillingClerk")
    body = get_body()
    period = req_period(body, "period")
    lease = get_lease_or_404(leaseId)
    if lease["status"] in ("EXPIRED", "TERMINATED"):
        raise err("ERR_LEASE_NOT_ACTIVE",
                  "Statements may not be created for an EXPIRED or TERMINATED lease")
    for s in STORE.statements.values():
        if s["lease_id"] == lease["id"] and s["period"] == period:
            raise err("ERR_STATEMENT_EXISTS",
                      "A statement already exists for this lease and period")
    start, end = _period_bounds(period)
    now = CLOCK.now()
    statement = {
        "id": new_id(),
        "lease_id": lease["id"],
        "period": period,
        "period_start": start,
        "period_end_exclusive": end,
        "total_throughput_bbl": 0,
        "throughput_fee_amount": 0.0,
        "shortfall_bbl": 0,
        "shortfall_fee_amount": 0.0,
        "total_excess_loss_bbl": 0,
        "excess_loss_amount": 0.0,
        "total_demurrage_amount": 0.0,
        "total_dwell_amount": 0.0,
        "statement_total_amount": 0.0,
        "status": "OPEN",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    STORE.statements[statement["id"]] = statement
    return success_object(statement_view(statement), status=201)


@bp.get("/lease-agreements/<leaseId>/statements")
def list_statements(leaseId):
    current_user()
    get_lease_or_404(leaseId)
    rows = [s for s in STORE.statements.values() if s["lease_id"] == leaseId]
    page, total, limit, offset = sort_and_page(rows)
    return success_list([statement_view(s) for s in page], total, limit, offset)


def _get_statement_or_404(statement_id):
    statement = STORE.statements.get(statement_id)
    if statement is None:
        raise err("ERR_STATEMENT_NOT_FOUND", "Statement %s not found" % statement_id)
    return statement


@bp.get("/monthly-statements/<statementId>")
def get_statement(statementId):
    current_user()
    statement = _get_statement_or_404(statementId)
    return success_object(statement_view(statement))


@bp.post("/monthly-statements/<statementId>/close")
def close_statement(statementId):
    require_roles("BillingClerk")
    statement = _get_statement_or_404(statementId)
    if statement["status"] != "OPEN":
        raise err("ERR_INVALID_STATE",
                  "Statement %s is %s; close requires OPEN"
                  % (statementId, statement["status"]))
    if CLOCK.now() < statement["period_end_exclusive"]:
        raise err("ERR_STATEMENT_PERIOD_NOT_ENDED",
                  "Statement close requires the logical clock to have reached period end")
    # Full deterministic recompute over the pinned input set.
    lifecycle.recompute_statement(statement)
    statement["status"] = "CLOSED"
    touch(statement)
    # Sweep period COMPLETED movements of this lease: UNBILLED -> ACCRUED.
    for m in lifecycle._statement_period_movements(statement):
        if m["billing_status"] == "UNBILLED":
            m["billing_status"] = "ACCRUED"
            touch(m)
    return success_object(statement_view(statement))


@bp.post("/monthly-statements/<statementId>/invoice")
def invoice_statement(statementId):
    require_roles("BillingClerk")
    statement = _get_statement_or_404(statementId)
    if statement["status"] != "CLOSED":
        raise err("ERR_INVALID_STATE",
                  "Statement %s is %s; invoice requires CLOSED"
                  % (statementId, statement["status"]))
    statement["status"] = "INVOICED"
    touch(statement)
    for m in lifecycle._statement_period_movements(statement):
        if m["billing_status"] == "ACCRUED":
            m["billing_status"] = "INVOICED"
            touch(m)
    return success_object(statement_view(statement))
