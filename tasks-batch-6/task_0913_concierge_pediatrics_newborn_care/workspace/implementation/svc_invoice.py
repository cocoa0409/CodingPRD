"""Invoice construction and DRAFT recomputation (PRD 3.3)."""
from datetime import date

from flask import g

import calc
from store import db, new_row, touch
from timeutil import days_in_month, last_day_of_month


def cycle_bounds(cycle_start):
    return last_day_of_month(cycle_start), days_in_month(cycle_start)


def cycle_start_for(day):
    return date(day.year, day.month, 1)


def find_invoice(family_id, cycle_start):
    for inv in db.invoices.values():
        if inv["family_id"] == family_id and inv["cycle_start_date"] == cycle_start:
            return inv
    return None


def compute_into(invoice, family):
    lines, subtotal, cap_adjustment, total = calc.build_invoice_lines(
        family,
        invoice["cycle_start_date"],
        invoice["cycle_end_date"],
        invoice["days_in_cycle"],
    )
    invoice["lines"] = lines
    invoice["subtotal_cents"] = subtotal
    invoice["cap_adjustment_cents"] = cap_adjustment
    invoice["total_cents"] = total


def create_invoice(family, cycle_start):
    cycle_end, days = cycle_bounds(cycle_start)
    invoice = new_row(
        db.invoices,
        {
            "family_id": family["id"],
            "cycle_start_date": cycle_start,
            "cycle_end_date": cycle_end,
            "days_in_cycle": days,
            "lines": [],
            "subtotal_cents": 0,
            "cap_adjustment_cents": 0,
            "total_cents": 0,
            "issued_date": None,
            "due_date": None,
            "paid_date": None,
            "amount_paid_cents": 0,
            "status": "DRAFT",
        },
    )
    compute_into(invoice, family)
    return invoice


def recompute_draft_invoices(family):
    """Only DRAFT invoices are ever recomputed; ISSUED and PAID are frozen."""
    for invoice in list(db.invoices.values()):
        if invoice["family_id"] != family["id"] or invoice["status"] != "DRAFT":
            continue
        compute_into(invoice, family)
        touch(invoice, g.touched)


def open_cycle_invoice_and_recompute(family, start_date):
    """Membership enrolment billing side effect: open the DRAFT invoice for the
    cycle containing start_date when the family has no invoice at all for that
    cycle, then recompute every DRAFT invoice of the family.  An existing
    ISSUED or PAID invoice for that cycle is left untouched and no replacement
    is created."""
    cycle_start = cycle_start_for(start_date)
    existing = find_invoice(family["id"], cycle_start)
    if existing is None:
        create_invoice(family, cycle_start)
    recompute_draft_invoices(family)
