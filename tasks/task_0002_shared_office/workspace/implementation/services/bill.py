"""Bill consolidation, line insertion, totals, tax, late fee."""
from datetime import date, timedelta
from decimal import Decimal

from clock import get_now, format_iso
from common import stamp_new, stamp_update
from db import db, new_id
from services.money import round_half_up_to_int

TAX_RATE = Decimal("0.0825")
LATE_FEE_RATE_PER_WEEK = Decimal("0.015")


def _current_period():
    """Current billing period: the current calendar month of virtual now."""
    now = get_now().date()
    start = date(now.year, now.month, 1)
    if now.month == 12:
        end = date(now.year, 12, 31)
    else:
        first_next = date(now.year, now.month + 1, 1)
        end = first_next - timedelta(days=1)
    return start.isoformat(), end.isoformat()


def get_or_create_draft_bill(tenant_id: str) -> dict:
    """Return the current DRAFT bill for the tenant (current period); create if missing."""
    period_start, period_end = _current_period()
    # Find existing DRAFT bill for this tenant
    for b in db.bills.values():
        if (b["tenant_id"] == tenant_id and b["status"] == "DRAFT"
                and b["period_start_date"] == period_start
                and b["period_end_date"] == period_end):
            return b
    bill = {
        "tenant_id": tenant_id,
        "period_start_date": period_start,
        "period_end_date": period_end,
        "subtotal_cents": 0,
        "tax_cents": 0,
        "late_fee_cents": 0,
        "total_due_cents": 0,
        "status": "DRAFT",
        "issued_at": None,
        "due_at": None,
        "paid_at": None,
    }
    stamp_new(bill)
    db.bills[bill["id"]] = bill
    return bill


def add_bill_line(bill: dict, line_kind: str, source_entity_id: str, amount_cents: int):
    line = {
        "id": new_id(),
        "bill_id": bill["id"],
        "line_kind": line_kind,
        "source_entity_id": source_entity_id,
        "amount_cents": amount_cents,
        "created_at": format_iso(get_now()),
    }
    db.bill_lines[line["id"]] = line
    return line


def recompute_bill_totals(bill: dict):
    # subtotal = sum of lines
    subtotal = 0
    for line in db.bill_lines.values():
        if line["bill_id"] == bill["id"]:
            subtotal += line["amount_cents"]
    bill["subtotal_cents"] = subtotal
    bill["tax_cents"] = round_half_up_to_int(Decimal(subtotal) * TAX_RATE)
    bill["total_due_cents"] = bill["subtotal_cents"] + bill["tax_cents"] + bill.get("late_fee_cents", 0)
    stamp_update(bill)


def compute_late_fee(bill: dict, now_dt) -> int:
    from clock import parse_iso
    if not bill.get("due_at"):
        return 0
    due_dt = parse_iso(bill["due_at"])
    delta_sec = (now_dt - due_dt).total_seconds()
    if delta_sec < 0:
        return 0
    weeks = int(delta_sec // (7 * 24 * 3600))
    if weeks <= 0:
        return 0
    principal = Decimal(bill.get("subtotal_cents", 0) + bill.get("tax_cents", 0))
    return round_half_up_to_int(principal * LATE_FEE_RATE_PER_WEEK * Decimal(weeks))


def update_overdue_late_fee(bill: dict, now_dt):
    new_fee = compute_late_fee(bill, now_dt)
    bill["late_fee_cents"] = new_fee
    bill["total_due_cents"] = bill.get("subtotal_cents", 0) + bill.get("tax_cents", 0) + new_fee
    stamp_update(bill)


def bill_to_public(bill: dict) -> dict:
    """Return a bill dict with lines[] embedded."""
    out = dict(bill)
    lines = [l for l in db.bill_lines.values() if l["bill_id"] == bill["id"]]
    lines.sort(key=lambda l: l["created_at"])
    out["lines"] = lines
    return out
