"""Calculation rules (scaffold §1.3 / PRD §3 & §2.6). All monetary values are
integer cents; the two non-money derived quantities (total-loss ratio and
comparative-negligence recovery) round half-up.
"""
import math

import db
from util import ratio_round4, pct_recovery

# Constants (scaffold §1.3).
TOTAL_LOSS_THRESHOLD = 0.75       # repair-to-ACV ratio at or above => total loss
TOTAL_LOSS_RENTAL_MAX_DAYS = 5    # on total loss, rental curtailed to <= 5 days


# ---- repair_total ----------------------------------------------------------
def repair_total(lines):
    """Sum over each line of (labor_cents + parts_cents). Exact integer cents."""
    total = 0
    for ln in lines:
        total += int(ln["labor_cents"]) + int(ln["parts_cents"])
    return total


# ---- repair_path_settlement ------------------------------------------------
def repair_path_settlement(gross_repair_total, deductible_cents, limit_cents):
    """settlement = min(max(0, gross - deductible), limit). No fault reduction."""
    after_deductible = max(0, gross_repair_total - deductible_cents)
    return min(after_deductible, limit_cents)


# ---- total_loss_decision ---------------------------------------------------
def total_loss_decision(repair_total_cents, acv_cents):
    """ratio = round(repair/acv, 4) half-up; is_total_loss = ratio >= TLT (>=)."""
    ratio = ratio_round4(repair_total_cents, acv_cents)
    is_total = ratio >= TOTAL_LOSS_THRESHOLD
    return ratio, is_total


# ---- total_loss_settlement -------------------------------------------------
def total_loss_settlement(acv_cents, salvage_value_cents, salvage_retained,
                          deductible_cents, limit_cents):
    """Order is fixed: salvage first, THEN deductible, THEN limit cap."""
    after_salvage = acv_cents - (salvage_value_cents if salvage_retained else 0)
    after_deductible = max(0, after_salvage - deductible_cents)
    return min(after_deductible, limit_cents)


# ---- rental_reimbursement --------------------------------------------------
def rental_requested_days(start_dt, end_dt):
    """ceil((end - start) / 86400s) over the half-open interval."""
    seconds = (end_dt - start_dt).total_seconds()
    return int(math.ceil(seconds / 86400.0))


def rental_reimbursement(requested_days, rental_max_days, daily_cap_cents,
                         daily_rate_cents, disposition):
    """day_cap = rental_max_days, lowered to min(.,5) when disposition==TOTAL_LOSS.
    per_day cap is applied BEFORE multiplying by days.
    Returns (reimbursable_days, reimbursement_cents).
    """
    day_cap = rental_max_days
    if disposition == "TOTAL_LOSS":
        day_cap = min(day_cap, TOTAL_LOSS_RENTAL_MAX_DAYS)
    reimbursable_days = min(requested_days, day_cap)
    per_day = min(daily_rate_cents, daily_cap_cents)
    reimbursement_cents = reimbursable_days * per_day
    return reimbursable_days, reimbursement_cents


# ---- subrogation_recovery --------------------------------------------------
def subrogation_recovery(demand_cents, insured_fault_pct, rule):
    """Comparative-negligence reduction of a third-party recovery.

    PURE        : always demand * (100-f)/100
    MODIFIED_50 : 0 if f >= 50 else reduced
    MODIFIED_51 : 0 if f >= 51 else reduced
    Round half-up to whole cents once at the end.
    """
    f = insured_fault_pct
    if rule == "PURE":
        return pct_recovery(demand_cents, f)
    if rule == "MODIFIED_50":
        return 0 if f >= 50 else pct_recovery(demand_cents, f)
    if rule == "MODIFIED_51":
        return 0 if f >= 51 else pct_recovery(demand_cents, f)
    # Defensive: unknown rule treated as no recovery; rule is validated upstream.
    return 0


# ---- claim_ledger_balance --------------------------------------------------
def claim_ledger_balance(claim_id):
    """Net sum of amount_cents over APPROVED disbursements for the claim,
    replayed in created_at (here _seq) ascending order. Returns
    (net_paid_cents, approved_count).
    """
    rows = [d for d in db.disbursements.values()
            if d["claim_id"] == claim_id and d["status"] == "APPROVED"]
    rows.sort(key=lambda r: r.get("_seq", 0))
    net = 0
    for d in rows:
        net += d["amount_cents"]
    return net, len(rows)


def refresh_claim_ledger(claim_rec):
    """Recompute and store Claim.total_disbursed_cents; refresh updated_at
    WITHOUT bumping version (a derived-field recompute per PRD §2.4)."""
    net, _count = claim_ledger_balance(claim_rec["id"])
    claim_rec["total_disbursed_cents"] = net
    db.touch_no_version(claim_rec)
    return net
