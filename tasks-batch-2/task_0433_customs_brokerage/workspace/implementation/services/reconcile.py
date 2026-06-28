"""Bond / statement reconciliation and cascade helpers.

These functions mutate the in-memory store. Bond auto-transitions (ACTIVE <->
SATURATED) are system transitions: PRD §3.1 says they are NOT version-bumping
direct calls, so they only set status, not version.
"""
from db import db
from helpers import bump_version


def lines_for_entry(entry_id):
    return [l for l in db.entry_lines.values() if l["entry_id"] == entry_id]


# ---------------------------------------------------------------------------
# Bond saturation auto-transitions (system, no version bump on auto change).
# ---------------------------------------------------------------------------
def bond_apply_saturation(bond):
    """After a liability change, auto-flip bond between ACTIVE and SATURATED.

    ACTIVE -> SATURATED when outstanding >= limit.
    SATURATED -> ACTIVE when outstanding < limit.
    These are automatic (system) transitions and do not bump version.
    """
    if bond["status"] == "ACTIVE" and bond["outstanding_liability_cents"] >= bond["limit_cents"]:
        bond["status"] = "SATURATED"
    elif bond["status"] == "SATURATED" and bond["outstanding_liability_cents"] < bond["limit_cents"]:
        bond["status"] = "ACTIVE"


def bond_add_liability(bond, delta_cents):
    """Increase bond.outstanding_liability_cents by delta, then re-evaluate saturation."""
    bond["outstanding_liability_cents"] = bond["outstanding_liability_cents"] + delta_cents
    bond_apply_saturation(bond)


# ---------------------------------------------------------------------------
# Monthly statement scheduling and total reconciliation.
# ---------------------------------------------------------------------------
def period_month_of(dt):
    """YYYY-MM string for a datetime (the logical clock instant)."""
    return "%04d-%02d" % (dt.year, dt.month)


def recompute_statement_totals(statement):
    """statement_total_cents = sum of total_duties_owed_cents over entries whose
    statement_id == this statement and status in {RELEASED, LIQUIDATED}.
    entry_count = number of entries scheduled onto the statement.
    """
    scheduled = [e for e in db.entries.values() if e.get("statement_id") == statement["id"]]
    total = sum(
        e["total_duties_owed_cents"]
        for e in scheduled
        if e["status"] in ("RELEASED", "LIQUIDATED")
    )
    statement["statement_total_cents"] = total
    statement["entry_count"] = len(scheduled)


def schedule_entry_onto_statement(entry):
    """Schedule a just-released entry onto the OPEN monthly statement for its
    importer and the calendar month of the current logical clock; create one if
    none exists. Sets entry.statement_id and recomputes the statement totals.

    The created statement is a system-created OPEN statement (its own common
    fields are stamped). It does not carry a version-bumping call here.
    """
    from helpers import stamp_create  # local import to avoid cycle at import time

    importer_id = entry["importer_id"]
    period = period_month_of(db.now())
    statement = _find_open_statement(importer_id, period)
    if statement is None:
        statement = {
            "importer_id": importer_id,
            "period_month": period,
            "statement_total_cents": 0,
            "entry_count": 0,
            "status": "OPEN",
        }
        stamp_create(statement)
        db.monthly_statements[statement["id"]] = statement
    entry["statement_id"] = statement["id"]
    recompute_statement_totals(statement)
    return statement


def _find_open_statement(importer_id, period_month):
    for s in db.monthly_statements.values():
        if (
            s["importer_id"] == importer_id
            and s["period_month"] == period_month
            and s["status"] == "OPEN"
        ):
            return s
    return None
