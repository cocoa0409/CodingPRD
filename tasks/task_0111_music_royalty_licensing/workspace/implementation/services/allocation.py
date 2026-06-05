"""Shared allocation machinery for usage allocate and sync execute.

Both operations distribute a rounded pool to holders, write one EARNING
LedgerEntry per holder onto that holder's open DRAFT statement, recompute each
affected statement's gross, and bump each affected statement's version.

The open-statement precondition is checked atomically: ALL target holders must
have a covering DRAFT statement before ANY ledger row is written (PRD §3.3/§3.4).
"""
import db
from errors import fail, ERR_NO_OPEN_STATEMENT
from services.common import parse_dt, touch


def find_open_statement(rightsholder_id, instant_dt):
    """Return the holder's DRAFT statement whose half-open [period_start,
    period_end) contains instant_dt, or None."""
    ts = instant_dt.timestamp()
    for stmt in db.statements.values():
        if stmt["rightsholder_id"] != rightsholder_id:
            continue
        if stmt["status"] != "DRAFT":
            continue
        start = parse_dt(stmt["period_start"]).timestamp()
        end = parse_dt(stmt["period_end"]).timestamp()
        if start <= ts < end:
            return stmt
    return None


def recompute_statement_gross(stmt):
    """Recompute a statement's gross_earnings_cents from its EARNING entries."""
    total = 0
    for entry in db.ledger_entries.values():
        if entry["statement_id"] == stmt["id"] and entry["entry_type"] == "EARNING":
            total += entry["amount_cents"]
    stmt["gross_earnings_cents"] = total


def distribute_earnings(allocations, instant_dt, source_type, source_id):
    """allocations: list of (rightsholder_id, amount_cents).

    Validates that every distinct target holder has an open DRAFT statement
    covering instant_dt (else ERR_NO_OPEN_STATEMENT, nothing written), then:
      - appends one EARNING LedgerEntry per allocation to the holder's statement
      - recomputes each affected statement's gross_earnings_cents
      - bumps each affected DRAFT statement's version once

    Returns the count of distinct holders that received an entry.
    """
    # Resolve statements for all distinct holders first (atomic precondition).
    holder_statement = {}
    for rh_id, _amount in allocations:
        if rh_id in holder_statement:
            continue
        stmt = find_open_statement(rh_id, instant_dt)
        if stmt is None:
            fail(ERR_NO_OPEN_STATEMENT,
                 "A distribution-target holder has no open DRAFT statement for the period")
        holder_statement[rh_id] = stmt

    # All preconditions satisfied — write ledger rows.
    affected = set()
    distinct_holders = set()
    for rh_id, amount in allocations:
        stmt = holder_statement[rh_id]
        entry = {
            "id": db.new_id(),
            "created_at": db.now_iso(),
            "statement_id": stmt["id"],
            "rightsholder_id": stmt["rightsholder_id"],
            "entry_type": "EARNING",
            "source_type": source_type,
            "source_id": source_id,
            "amount_cents": amount,
            "_seq": db.next_seq(),
        }
        db.ledger_entries[entry["id"]] = entry
        affected.add(stmt["id"])
        distinct_holders.add(rh_id)

    for stmt_id in affected:
        stmt = db.statements[stmt_id]
        recompute_statement_gross(stmt)
        touch(stmt)

    return len(distinct_holders)
