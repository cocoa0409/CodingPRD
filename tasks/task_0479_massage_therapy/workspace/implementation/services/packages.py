"""Package credit ledger and cycle math (PRD §3.10)."""
from datetime import timedelta

import db
import helpers as h
import util


def add_one_cycle(dt, cycle_anchor_day):
    """Advance an instant by one membership cycle.

    Cycles renew on cycle_anchor_day (1..28). We advance to the anchor day in
    the next month relative to dt, preserving the time-of-day.
    """
    year = dt.year
    month = dt.month
    # next month
    month += 1
    if month > 12:
        month = 1
        year += 1
    return dt.replace(year=year, month=month, day=cycle_anchor_day)


def write_ledger(package, reason, delta_sessions):
    """Append a CreditLedgerEntry, mutate package balance, record balance_after.

    A CreditLedgerEntry carries only id and created_at (PRD §2.4).
    """
    package["credit_balance_sessions"] += delta_sessions
    entry = h.new_entity({
        "package_id": package["id"],
        "delta_sessions": delta_sessions,
        "reason": reason,
        "balance_after": package["credit_balance_sessions"],
    }, versioned=False)
    db.ledger_entries[entry["id"]] = entry
    return entry


def refund_credit(package):
    """Write a REFUND ledger entry (delta +1) and recompute balance."""
    write_ledger(package, "REFUND", 1)
    h.touch(package)
