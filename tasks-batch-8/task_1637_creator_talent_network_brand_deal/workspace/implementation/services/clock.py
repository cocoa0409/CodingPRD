"""Logical-clock sweep: each clock set expires OPEN briefs past their
submission_window_end and marks ISSUED invoices past due_date OVERDUE."""

import db
from services import helpers as H
from services import lifecycle


def sweep():
    now = db.get_clock()

    for brief in list(db.briefs.values()):
        if brief["status"] != "OPEN":
            continue
        end = db.parse_iso(brief["submission_window_end"])
        if end is not None and now > end:
            brief["status"] = "EXPIRED"
            H.touch(brief)
            lifecycle.withdraw_open_pitches_of_brief(brief["id"])

    for inv in list(db.invoices.values()):
        if inv["status"] != "ISSUED":
            continue
        due = db.parse_iso(inv["due_date"]) if inv.get("due_date") else None
        if due is not None and now > due:
            inv["status"] = "OVERDUE"
            H.touch(inv)
