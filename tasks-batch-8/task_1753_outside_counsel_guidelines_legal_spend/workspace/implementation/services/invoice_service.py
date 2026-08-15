"""Invoice/line-item rule engine, aggregation, booking, and accrual matching.

Implements PRD §3.5, §3.6 and calculations:
  - invoice_payable_amount (per-line round-half-up pinned before aggregation)
  - block_billing_detection (regex L[0-9]{3}, case-sensitive, >= 2 distinct)
  - staffing_ratio_compliance (billed-hours basis for auto-review)
  - matter_forecast_reconciliation (billed -> wip -> variance)
"""

import re
from decimal import Decimal, ROUND_HALF_UP

import db

BLOCK_BILLING = "BLOCK_BILLING"
RATE_EXCEEDS_APPROVED = "RATE_EXCEEDS_APPROVED"
UNAPPROVED_TIMEKEEPER = "UNAPPROVED_TIMEKEEPER"
STAFFING_RATIO = "STAFFING_RATIO"
OVER_BUDGET = "OVER_BUDGET"

APPROVED_EQUIVALENT = {"APPROVED", "ADJUSTED_APPROVED", "REINSTATED"}
REJECTED_EQUIVALENT = {"REJECTED", "UPHELD"}

_NARRATIVE_RE = re.compile(r"L[0-9]{3}")


def round_half_up_cents(value: Decimal) -> int:
    """Round half-up to a whole cent (integer)."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def compute_line_amount_cents(hours, rate_cents) -> int:
    """Per-line amount: hours * rate_cents, round_half_up to whole cents."""
    h = Decimal(str(hours))
    r = Decimal(str(rate_cents))
    return round_half_up_cents(h * r)


def line_contribution(line: dict) -> int:
    """Contribution of a line to invoice.approved_total_cents."""
    status = line.get("review_status")
    if status == "ADJUSTED_APPROVED":
        adj = line.get("adjusted_amount_cents")
        return int(adj) if adj is not None else 0
    if status in ("APPROVED", "REINSTATED"):
        return int(line.get("amount_cents", 0))
    return 0


def lines_of_invoice(invoice_id):
    return [l for l in db.invoice_line_items.values() if l.get("invoice_id") == invoice_id]


def recompute_invoice_totals(invoice: dict):
    """Recompute approved_total_cents; final_payable_cents tracks it unless PAID."""
    total = sum(line_contribution(l) for l in lines_of_invoice(invoice["id"]))
    invoice["approved_total_cents"] = total
    if invoice.get("status") != "PAID":
        invoice["final_payable_cents"] = total
    return total


def derive_invoice_status(invoice: dict) -> str:
    """Aggregate status derivation (PRD §3.5):
    any PENDING -> UNDER_REVIEW;
    all in {APPROVED, ADJUSTED_APPROVED, REINSTATED} -> APPROVED;
    all in {REJECTED, UPHELD} -> REJECTED;
    otherwise PARTIALLY_APPROVED.
    """
    lines = lines_of_invoice(invoice["id"])
    statuses = [l.get("review_status") for l in lines]
    if any(s == "PENDING" for s in statuses):
        return "UNDER_REVIEW"
    if statuses and all(s in APPROVED_EQUIVALENT for s in statuses):
        return "APPROVED"
    if statuses and all(s in REJECTED_EQUIVALENT for s in statuses):
        return "REJECTED"
    return "PARTIALLY_APPROVED"


def billed_hours_ratio(matter_id: str):
    """Billed-hours partner share for a matter (4-decimal precision).

    Returns (ratio_pct: Decimal|None, per_invoice_line_hours).
    Per-line hours are quantized to 2 decimals before summation.
    """
    partner_hours = Decimal("0")
    total_hours = Decimal("0")
    matter_invoices = [
        inv for inv in db.invoices.values()
        if inv.get("matter_id") == matter_id and inv.get("status") != "VOID"
    ]
    inv_ids = {inv["id"] for inv in matter_invoices}
    for line in db.invoice_line_items.values():
        if line.get("invoice_id") not in inv_ids:
            continue
        if line.get("review_status") not in APPROVED_EQUIVALENT:
            continue
        h = Decimal(str(line.get("hours", 0))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        total_hours += h
        tk = db.timekeepers.get(line.get("timekeeper_id"))
        if tk and tk.get("tk_class") == "PARTNER":
            partner_hours += h
    if total_hours == 0:
        return None
    ratio = (partner_hours / total_hours * Decimal("100")).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP
    )
    return ratio


def firm_approved_rate_for_year(firm_id: str, timekeeper_id: str, year: int):
    """Find the timekeeper's approved_rate_cents on the firm's APPROVED card
    covering the given effective year. Returns the rate (int) or None when the
    timekeeper has no row on that card or no card exists."""
    card = approved_card_for_year(firm_id, year)
    if card is None:
        return None
    for r in db.timekeeper_rates.values():
        if r.get("rate_card_id") == card["id"] and r.get("timekeeper_id") == timekeeper_id:
            return r.get("approved_rate_cents")
    return None


def approved_card_for_year(firm_id: str, year: int):
    """The firm's APPROVED rate card covering `year`.

    Prefers an exact effective_year match; otherwise falls back to the most
    recent APPROVED card with effective_year <= year. Tie-break: effective_year
    DESC, created_at ASC (per calculations.annual_rate_increase_pct constants).
    """
    candidates = [
        c for c in db.rate_cards.values()
        if c.get("panel_firm_id") == firm_id and c.get("status") == "APPROVED"
    ]
    if not candidates:
        return None
    exact = [c for c in candidates if c.get("effective_year") == year]
    pool = exact if exact else [c for c in candidates if c.get("effective_year", 0) <= year]
    if not pool:
        return None
    pool.sort(key=lambda c: (-int(c.get("effective_year", 0)), c.get("created_at", ""), c.get("_seq", 0)))
    return pool[0]


def rule_engine_line(line: dict, firm_id: str, year: int):
    """Run the auto-review rule engine on a single line (PRD §3.5 order):
    (a) block-billing, (b) rate exceeds approved, (c) unapproved timekeeper,
    (d) rate-not-on-card -> leave PENDING, (e) approve.
    Sets review_status / rejection_reason_code on the line dict.
    """
    narrative = line.get("narrative") or ""
    distinct = set(_NARRATIVE_RE.findall(narrative))
    if len(distinct) >= 2:
        line["review_status"] = "REJECTED"
        line["rejection_reason_code"] = BLOCK_BILLING
        return

    tk = db.timekeepers.get(line.get("timekeeper_id"))
    approved_rate = firm_approved_rate_for_year(firm_id, line.get("timekeeper_id"), year)
    rate_cents = int(line.get("rate_cents", 0))

    if approved_rate is not None and rate_cents > int(approved_rate):
        line["review_status"] = "REJECTED"
        line["rejection_reason_code"] = RATE_EXCEEDS_APPROVED
        return

    if tk is None or tk.get("qualification_status") != "QUALIFIED":
        line["review_status"] = "REJECTED"
        line["rejection_reason_code"] = UNAPPROVED_TIMEKEEPER
        return

    if approved_rate is not None and rate_cents != int(approved_rate):
        # Below the approved rate but not on the card -> manual review.
        line["review_status"] = "PENDING"
        line["rejection_reason_code"] = None
        return

    line["review_status"] = "APPROVED"
    line["rejection_reason_code"] = None


def match_accruals(invoice: dict, matter: dict):
    """Consume unmatched accruals whose (period_year, period_month) falls
    within [billing_period_start, billing_period_end)."""
    start = db.parse_iso(invoice.get("billing_period_start"))
    end = db.parse_iso(invoice.get("billing_period_end"))
    if start is None or end is None:
        return
    for acc in db.accruals.values():
        if acc.get("matter_id") != matter["id"]:
            continue
        if acc.get("matched_invoice_id") is not None:
            continue
        py = int(acc.get("period_year", 0))
        pm = int(acc.get("period_month", 0))
        # period instant = first day of (year, month) UTC
        from datetime import datetime, timezone
        try:
            period_dt = datetime(py, pm, 1, tzinfo=timezone.utc)
        except ValueError:
            continue
        if start <= period_dt < end:
            acc["matched_invoice_id"] = invoice["id"]
            db.touch(acc)
            matter["accrual_outstanding_cents"] = int(matter.get("accrual_outstanding_cents", 0)) - int(acc.get("amount_cents", 0))


def finalize_invoice_state(invoice: dict, matter: dict, old_status: str):
    """After line statuses change: recompute totals, derive new aggregate
    status, and book spend / match accruals when the invoice newly lands on
    APPROVED or PARTIALLY_APPROVED."""
    recompute_invoice_totals(invoice)
    new_status = derive_invoice_status(invoice)
    invoice["status"] = new_status
    booked_states = {"APPROVED", "PARTIALLY_APPROVED"}
    if new_status in booked_states and old_status not in booked_states:
        matter["billed_to_date_cents"] = int(matter.get("billed_to_date_cents", 0)) + int(invoice["approved_total_cents"])
        match_accruals(invoice, matter)
        refresh_forecast(matter["id"])
    return new_status


def refresh_forecast(matter_id: str):
    """Recompute wip/variance on the matter's forecast if one exists.
    Evaluation order pinned: billed -> wip -> variance."""
    forecast = db.matter_forecasts.get(matter_id)
    if forecast is None:
        return
    matter = db.matters.get(matter_id)
    if matter is None:
        return
    billed = int(matter.get("billed_to_date_cents", 0))
    wip = sum(
        int(a.get("amount_cents", 0))
        for a in db.accruals.values()
        if a.get("matter_id") == matter_id and a.get("matched_invoice_id") is None
    )
    forecast["wip_estimate_cents"] = wip
    forecast["variance_cents"] = int(forecast.get("lifecycle_estimate_cents", 0)) - (billed + wip)
    db.touch(forecast)


def sweep_overdue_acknowledgments():
    """Clock sweep: PENDING acks whose due date has passed -> OVERDUE.
    Due date = parent GuidelineVersion publication timestamp +
    LegalDepartment.acknowledgment_window_days. Strictly: logical clock must be
    greater than the due instant."""
    clock = db.get_clock()
    for ack in db.guideline_acknowledgments.values():
        if ack.get("status") != "PENDING":
            continue
        gv = db.guideline_versions.get(ack.get("guideline_version_id"))
        if gv is None:
            continue
        published_at = db.parse_iso(gv.get("published_at"))
        if published_at is None:
            continue
        dept = db.legal_departments.get(gv.get("legal_department_id"))
        window = int(dept.get("acknowledgment_window_days", 0)) if dept else 0
        from datetime import timedelta
        due = published_at + timedelta(days=window)
        if clock > due:
            ack["status"] = "OVERDUE"
            db.touch(ack)
