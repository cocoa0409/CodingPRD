"""Statement & repayment cascade logic (PRD §3.6, §2.6, §2.7)."""
from db import db, stamp_create, touch
from services.common import (
    STATEMENT_DUE_DAYS, recompute_available_credit, add_days_iso, to_dt,
)


def open_new_statement(company, cycle_index):
    """Create a fresh OPEN statement for the company at the given cycle index.

    opened_at = company.clock_utc (may be null if the clock is not yet set).
    """
    stmt = {
        "company_id": company["id"],
        "cycle_index": cycle_index,
        "opened_at": company.get("clock_utc"),
        "closed_at": None,
        "due_at": None,
        "closing_balance_cents": 0,
        "minimum_due_cents": 0,
        "amount_repaid_cents": 0,
        "status": "OPEN",
    }
    stamp_create(stmt)
    db.statements[stmt["id"]] = stmt
    return stmt


def max_cycle_index(company_id):
    idx = 0
    for s in db.statements.values():
        if s["company_id"] == company_id:
            idx = max(idx, s["cycle_index"])
    return idx


def evaluate_past_due_for_company(company):
    """DUE -> PAST_DUE sweep when clock_utc > due_at and amount_repaid < minimum_due."""
    clock = company.get("clock_utc")
    if clock is None:
        return
    clock_dt = to_dt(clock)
    for stmt in db.statements.values():
        if (stmt["company_id"] == company["id"]
                and stmt["status"] == "DUE"
                and stmt.get("due_at") is not None):
            due_dt = to_dt(stmt["due_at"])
            if clock_dt > due_dt and stmt["amount_repaid_cents"] < stmt["minimum_due_cents"]:
                stmt["status"] = "PAST_DUE"
                touch(stmt)


def set_due_at(stmt, closed_at_iso):
    return add_days_iso(closed_at_iso, STATEMENT_DUE_DAYS)
