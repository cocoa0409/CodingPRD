from datetime import timedelta, datetime, timezone
from decimal import Decimal

from db import db
from util import now_iso_string, add_common_fields, bump, round_half_up, parse_iso


TAX_RATE = Decimal("0.0825")
LATE_FEE_WEEKLY_RATE = Decimal("0.015")


def _today_period_bounds(now: datetime):
    """Return (period_start_date, period_end_date) as 'YYYY-MM-DD' for the month containing 'now'."""
    first = now.date().replace(day=1)
    # Compute last day of month: go to next month first-day minus 1
    if first.month == 12:
        nxt = first.replace(year=first.year + 1, month=1)
    else:
        nxt = first.replace(month=first.month + 1)
    last = nxt - timedelta(days=1)
    return first.isoformat(), last.isoformat()


def get_or_create_draft_bill(tenant_id: str) -> dict:
    now = db.now()
    period_start, period_end = _today_period_bounds(now)
    # Find existing DRAFT bill for this tenant and period
    for b in db.bills.values():
        if (b["tenant_id"] == tenant_id and b["status"] == "DRAFT"
                and b["period_start_date"] == period_start
                and b["period_end_date"] == period_end):
            return b
    # Also accept any DRAFT bill if period matches structurally; PRD says one DRAFT per tenant/period.
    # Create a new DRAFT bill.
    bill = {
        "tenant_id": tenant_id,
        "period_start_date": period_start,
        "period_end_date": period_end,
        "status": "DRAFT",
        "subtotal_cents": 0,
        "tax_cents": 0,
        "late_fee_cents": 0,
        "total_due_cents": 0,
        "issued_at": None,
        "due_at": None,
        "paid_at": None,
    }
    add_common_fields(bill, now, db.new_id())
    db.bills[bill["id"]] = bill
    return bill


def append_line(bill: dict, line_kind: str, source_entity_id: str, amount_cents: int):
    now = db.now()
    line = {
        "bill_id": bill["id"],
        "line_kind": line_kind,
        "source_entity_id": source_entity_id,
        "amount_cents": amount_cents,
    }
    line["id"] = db.new_id()
    line["created_at"] = now_iso_string(now)
    db.bill_lines[line["id"]] = line


def recompute_bill_totals(bill: dict):
    """Recompute subtotal, tax, total for a bill from the line sources.
    subtotal = sum of final_fee_cents for its COMPLETED/NO_SHOW reservations
             + sum of overstay_fee_cents for its CHECKED_OUT visitors (with consolidated fee)
             + termination penalty lines
    """
    subtotal = 0
    # Reservations pointing at this bill
    for r in db.reservations.values():
        if r.get("bill_id") == bill["id"] and r["status"] in ("COMPLETED", "NO_SHOW"):
            subtotal += r.get("final_fee_cents", 0) or 0
    for v in db.visitors.values():
        if v.get("bill_id") == bill["id"] and v["status"] == "CHECKED_OUT":
            subtotal += v.get("overstay_fee_cents", 0) or 0
    # Termination penalty lines
    for line in db.bill_lines.values():
        if line["bill_id"] == bill["id"] and line["line_kind"] == "TERMINATION_PENALTY":
            subtotal += line["amount_cents"]

    bill["subtotal_cents"] = subtotal
    # Tax applied to subtotal (sum-then-round)
    tax = Decimal(subtotal) * TAX_RATE
    bill["tax_cents"] = round_half_up(tax)

    # Late fee recompute (if bill is overdue)
    if bill["status"] == "OVERDUE":
        recompute_late_fee(bill)
    # else late_fee_cents is managed separately (cleared at 0 by default)

    bill["total_due_cents"] = bill["subtotal_cents"] + bill["tax_cents"] + bill["late_fee_cents"]


def recompute_late_fee(bill: dict):
    """Late fee = principal * 0.015 * weeks_past_due, non-compounding, rewrites late_fee_cents."""
    if bill["status"] != "OVERDUE":
        bill["late_fee_cents"] = 0
        return
    if not bill.get("due_at"):
        bill["late_fee_cents"] = 0
        return
    due_at = parse_iso(bill["due_at"])
    now = db.now()
    delta = now - due_at
    seconds = int(delta.total_seconds())
    if seconds < 0:
        weeks = 0
    else:
        weeks = seconds // (7 * 24 * 3600)
    principal = bill["subtotal_cents"] + bill["tax_cents"]
    late_fee = Decimal(principal) * LATE_FEE_WEEKLY_RATE * Decimal(weeks)
    bill["late_fee_cents"] = round_half_up(late_fee)


def bill_view(bill: dict) -> dict:
    lines = [line_view(l) for l in db.bill_lines.values() if l["bill_id"] == bill["id"]]
    lines.sort(key=lambda x: x["created_at"])
    return {
        "id": bill["id"],
        "created_at": bill["created_at"],
        "updated_at": bill["updated_at"],
        "version": bill["version"],
        "tenant_id": bill["tenant_id"],
        "period_start_date": bill["period_start_date"],
        "period_end_date": bill["period_end_date"],
        "status": bill["status"],
        "subtotal_cents": bill["subtotal_cents"],
        "tax_cents": bill["tax_cents"],
        "late_fee_cents": bill["late_fee_cents"],
        "total_due_cents": bill["total_due_cents"],
        "issued_at": bill.get("issued_at"),
        "due_at": bill.get("due_at"),
        "paid_at": bill.get("paid_at"),
        "lines": lines,
    }


def line_view(line: dict) -> dict:
    return {
        "id": line["id"],
        "created_at": line["created_at"],
        "bill_id": line["bill_id"],
        "line_kind": line["line_kind"],
        "source_entity_id": line["source_entity_id"],
        "amount_cents": line["amount_cents"],
    }
