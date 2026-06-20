"""Invoice line sweep + totals (PRD §3.8, §3.9, scaffold calculations.invoice_total).

Eligible unbilled lines (invoiced == false) across the owner's horses:
  COMPLETED / NO_SHOW Lesson.billed_fee_cents
  COMPLETED ServiceVisit.fee_cents
  CONFIRMED / SCRATCHED ShowEntry.entry_fee_cents
  ENDED BoardingAgreement.final_charge_cents

Pinned three-step order:
  STEP 1 gross = sum over lines of round_half_up(line_value)  (round EACH line FIRST, THEN sum)
  STEP 2 discount: n = distinct Horse ids contributing an ENDED boarding line
           pct = 0.00 (n<=1), 0.05 (n==2), 0.10 (n>=3)
           multi_horse_discount = round_half_up(gross * pct)  (once, after summation)
  STEP 3 net = gross - discount; deposit_applied = min(deposit_held, net);
           amount_due = max(0, net - deposit_applied)
"""
from decimal import Decimal

from db import db
from services.common import round_half_up, pct

DISCOUNT_TIER_2_PCT = Decimal("0.05")
DISCOUNT_TIER_3_PCT = Decimal("0.10")


def _owner_horse_ids(owner_id):
    return {h["id"] for h in db.horses.values() if h["owner_id"] == owner_id}


def collect_lines(owner):
    """Return (lines, boarding_horse_ids) for the owner's unbilled billable work.
    lines is a list of (value_cents, ref_dict). boarding_horse_ids is the set of
    distinct Horse ids contributing an ENDED boarding-agreement line."""
    horse_ids = _owner_horse_ids(owner["id"])
    lines = []
    boarding_horse_ids = set()

    for l in db.lessons.values():
        if l["horse_id"] in horse_ids and not l["invoiced"] and l["status"] in ("COMPLETED", "NO_SHOW"):
            lines.append((l["billed_fee_cents"], l))
    for v in db.visits.values():
        if v["horse_id"] in horse_ids and not v["invoiced"] and v["status"] == "COMPLETED":
            lines.append((v["fee_cents"], v))
    for e in db.entries.values():
        if e["horse_id"] in horse_ids and not e["invoiced"] and e["status"] in ("CONFIRMED", "SCRATCHED"):
            lines.append((e["entry_fee_cents"], e))
    for a in db.agreements.values():
        if a["horse_id"] in horse_ids and not a["invoiced"] and a["status"] == "ENDED":
            lines.append((a["final_charge_cents"], a))
            boarding_horse_ids.add(a["horse_id"])

    return lines, boarding_horse_ids


def _discount_pct(n):
    if n <= 1:
        return Decimal("0.00")
    if n == 2:
        return DISCOUNT_TIER_2_PCT
    return DISCOUNT_TIER_3_PCT


def compute_totals(owner, lines, boarding_horse_ids):
    """Pinned-order totals. Returns dict with gross/discount/deposit_applied/amount_due."""
    # STEP 1 — round each line first, then sum
    gross = sum(round_half_up(value) for value, _ in lines)
    # STEP 2 — tiered multi-horse discount (rounded once after summation)
    n = len(boarding_horse_ids)
    discount = pct(gross, _discount_pct(n))
    # STEP 3 — deposit waterfall
    net = gross - discount
    deposit_applied = min(owner["deposit_held_cents"], net)
    amount_due = max(0, net - deposit_applied)
    return {
        "gross_amount_cents": gross,
        "multi_horse_discount_cents": discount,
        "deposit_applied_cents": deposit_applied,
        "amount_due_cents": amount_due,
    }


def project_open_invoice_amount_due(owner, invoice):
    """Projected amount_due of an OPEN invoice, used by provisional standing (PRD §3.9).
    Computed with the same total rule against the owner's currently-unbilled lines."""
    lines, boarding_horse_ids = collect_lines(owner)
    totals = compute_totals(owner, lines, boarding_horse_ids)
    return totals["amount_due_cents"]
