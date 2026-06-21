"""Business logic: calculations, derived-field recomputes, and cascades.

Money is integer cents throughout. The single rounding point is the per-line
G703 retainage (round-half-up at the cent), implemented with Decimal
(PRD §2.9). All other money arithmetic is exact integer cents.
"""
from decimal import Decimal, ROUND_HALF_UP

import db


# ---------------------------------------------------------------------------
# §3 calculations
# ---------------------------------------------------------------------------

def round_half_up_cents(amount):
    """Round a Decimal amount to a whole cent, half-up (PRD §2.9)."""
    return int(Decimal(amount).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def line_retainage_cents(retainage_pct, billed_this_app):
    """g703_line_retainage: round_half_up(retainage_pct * billed_this_app).

    retainage_pct is a fraction (e.g. 0.10). Done in Decimal to avoid float
    error before the half-up rounding.
    """
    product = Decimal(str(retainage_pct)) * Decimal(billed_this_app)
    return round_half_up_cents(product)


def active_sov_lines(project_id):
    return [s for s in db.sov_lines.values()
            if s["project_id"] == project_id and s["status"] == "ACTIVE"]


def project_sov_lines(project_id):
    return [s for s in db.sov_lines.values() if s["project_id"] == project_id]


def recompute_revised_contract_sum(project):
    """revised_contract_sum_cents = original + sum(APPROVED CO amounts)."""
    total = project["original_contract_sum_cents"]
    for co in db.change_orders.values():
        if co["project_id"] == project["id"] and co["status"] == "APPROVED":
            total += co["change_order_amount_cents"]
    project["revised_contract_sum_cents"] = total


def recompute_completed_and_stored(project):
    """total_completed_and_stored_cents = sum over SovLines of
    (work_completed_to_date_cents + materials_stored_cents)."""
    total = 0
    for s in project_sov_lines(project["id"]):
        total += s["work_completed_to_date_cents"] + s["materials_stored_cents"]
    project["total_completed_and_stored_cents"] = total


def recompute_retainage_held(project):
    """retainage_held_cents = sum over SovLines of retainage_withheld_to_date_cents.

    The roll-up reads every SovLine (active and deleted retain whatever they
    hold), but the waterfall and the project invariant operate on ACTIVE lines;
    deleted lines are not produced by any declared endpoint, so in practice this
    sums the held retainage that exists on the project's lines.
    """
    total = 0
    for s in project_sov_lines(project["id"]):
        total += s["retainage_withheld_to_date_cents"]
    project["retainage_held_cents"] = total


def pay_app_line_for(pay_app_id):
    lines = [ln for ln in db.pay_app_lines.values() if ln["pay_app_id"] == pay_app_id]
    return sorted(lines, key=lambda r: (r.get("created_at", ""), r.get("_seq", 0)))


def compute_g702_totals(pay_app):
    """g702_current_payment_due — computes lines 4, 5, 6.

    line 4: total_completed_and_stored = sum over lines of
            (previous + this_period + materials_stored)
    line 5: total_retainage = sum over lines of line_retainage_cents
            (round-per-line already done at line creation)
    line 6: current_payment_due = line4 - line5 - prior_certificates
            prior_certificates = sum of current_payment_due over the project's
            CERTIFIED applications.
    """
    lines = pay_app_line_for(pay_app["id"])
    total_completed = 0
    total_retainage = 0
    for ln in lines:
        total_completed += (ln["work_completed_previous_cents"]
                            + ln["work_completed_this_period_cents"]
                            + ln["materials_stored_cents"])
        total_retainage += ln["line_retainage_cents"]

    prior_certificates = 0
    for pa in db.pay_applications.values():
        if pa["project_id"] == pay_app["project_id"] and pa["status"] == "CERTIFIED":
            prior_certificates += pa["current_payment_due_cents"]

    pay_app["total_completed_and_stored_cents"] = total_completed
    pay_app["total_retainage_cents"] = total_retainage
    pay_app["current_payment_due_cents"] = (
        total_completed - total_retainage - prior_certificates
    )


def retention_waterfall(project, amount_cents):
    """retention_release_waterfall — distribute amount_cents across ACTIVE
    SovLines holding retainage, ascending (item_no, created_at)."""
    candidates = [s for s in active_sov_lines(project["id"])
                  if s["retainage_withheld_to_date_cents"] > 0]
    candidates.sort(key=lambda s: (s["item_no"], s.get("created_at", ""), s.get("_seq", 0)))
    remaining = amount_cents
    for line in candidates:
        if remaining == 0:
            break
        take = min(remaining, line["retainage_withheld_to_date_cents"])
        line["retainage_withheld_to_date_cents"] -= take
        remaining -= take
        db.touch(line)
    recompute_retainage_held(project)


def commitment_invoice_sweep(project_id, waiver_amount_cents):
    """commitment_invoice_sweep — credit exactly one OPEN commitment with
    remaining balance, ranked by largest remaining balance, tie-break earliest
    created_at. Credit = min(waiver_amount, remaining). No-op if none eligible.
    """
    eligible = [c for c in db.subcontractor_commitments.values()
                if c["project_id"] == project_id
                and c["status"] == "OPEN"
                and c["invoiced_to_date_cents"] < c["committed_amount_cents"]]
    if not eligible:
        return
    def remaining(c):
        return c["committed_amount_cents"] - c["invoiced_to_date_cents"]
    # Largest remaining balance first; tie-break earliest created_at.
    eligible.sort(key=lambda c: (-remaining(c), c.get("created_at", ""), c.get("_seq", 0)))
    chosen = eligible[0]
    credit = min(waiver_amount_cents, remaining(chosen))
    chosen["invoiced_to_date_cents"] += credit
    db.touch(chosen)
