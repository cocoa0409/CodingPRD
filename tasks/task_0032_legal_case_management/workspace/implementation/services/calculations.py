"""Calculation rules per PRD §3.6 and SCAFFOLD §1.3.

All money math uses Decimal with ROUND_HALF_UP; never float.
"""

from decimal import Decimal

import db
import helpers


CRIMINAL_FLAT_CENTS = 50000
ADMIN_FLAT_CENTS = 30000

# (lower_cents, upper_cents, rate_bps)
TIER_LADDER = [
    (0, 1_000_000, 500),
    (1_000_000, 10_000_000, 300),
    (10_000_000, 100_000_000, 200),
    (100_000_000, 9_999_999_999, 100),
]


def compute_court_fee(case_type, claim_amount_cents):
    """Tiered court fee per PRD §3.6.

    For CIVIL/ARBITRATION:
      - walk brackets ascending; per-bracket subtotal = round_half_up(slice * rate / 10000)
      - ROUND PER BRACKET BEFORE summing.
      - For ARBITRATION, after summing, apply 50% discount: total = round_half_up(total * 0.5)
    For CRIMINAL: flat 50000. For ADMINISTRATIVE: flat 30000.
    """
    if case_type == "CRIMINAL":
        return CRIMINAL_FLAT_CENTS
    if case_type == "ADMINISTRATIVE":
        return ADMIN_FLAT_CENTS

    remaining = int(claim_amount_cents)
    total = 0
    for lower, upper, rate_bps in TIER_LADDER:
        if remaining <= 0:
            break
        bracket_width = upper - lower
        slice_cents = max(0, min(remaining, bracket_width))
        if slice_cents == 0:
            continue
        per_bracket = helpers.round_half_up(
            Decimal(slice_cents) * Decimal(rate_bps) / Decimal(10000)
        )
        total += per_bracket
        remaining -= slice_cents

    if case_type == "ARBITRATION":
        total = helpers.round_half_up(Decimal(total) * Decimal("0.5"))
    return total


def compute_attorney_fee_hourly(case_id):
    """Sum of per-entry rounded fee for billable TimeEntries with status in
    {ADJUSTED, BILLED}, using hourly_rate_cents_pinned."""
    total = 0
    for te in db.time_entries.values():
        if te["case_id"] != case_id:
            continue
        if not te["billable"]:
            continue
        if te["status"] not in {"ADJUSTED", "BILLED"}:
            continue
        billable_minutes = max(0, te["minutes"] + te["adjustment_minutes"])
        per_entry = helpers.round_half_up(
            Decimal(billable_minutes) * Decimal(te["hourly_rate_cents_pinned"]) / Decimal(60)
        )
        total += per_entry
    return total


def compute_attorney_fee(bill, case):
    mode = bill["billing_mode"]
    if mode == "HOURLY":
        return compute_attorney_fee_hourly(case["id"])
    if mode == "FIXED":
        return int(bill["fixed_fee_cents"])
    if mode == "CONTINGENT":
        recovered = int(bill.get("recovered_amount_cents") or 0)
        rate_bps = int(bill["contingent_rate_bps"])
        return helpers.round_half_up(
            Decimal(recovered) * Decimal(rate_bps) / Decimal(10000)
        )
    return 0


def compute_total_due(court_fee, attorney_fee, expense_reimbursement, cost_recovery):
    return max(
        0,
        int(court_fee) + int(attorney_fee) + int(expense_reimbursement) - int(cost_recovery),
    )


def compute_provisional_running_cost(case_id):
    """PROVISIONAL view per PRD §3.6: includes ALL TimeEntry rows where
    billable=true regardless of status, using current Lawyer.hourly_rate_cents.
    """
    total = 0
    for te in db.time_entries.values():
        if te["case_id"] != case_id:
            continue
        if not te["billable"]:
            continue
        lawyer = db.lawyers.get(te["lawyer_id"])
        if lawyer is None:
            continue
        billable_minutes = max(0, te["minutes"] + te["adjustment_minutes"])
        rate = lawyer["hourly_rate_cents"]
        per_entry = helpers.round_half_up(
            Decimal(billable_minutes) * Decimal(rate) / Decimal(60)
        )
        total += per_entry
    return total


def compute_final_settlement(case, bill):
    """Chronological replay per PRD §3.6:
       - Iterate TimeEntry rows with status=BILLED in created_at order; add per-entry fee.
       - Then add Bill.expense_reimbursement_cents (one event).
       - Then apply Bill.cost_recovery_cents (interim balance clamped at zero).
       - Finally add court_fee_cents at close.

    The PRD treats expense and recovery as single events sourced from the bill;
    they are added/subtracted in that fixed order after time entries have been
    chronologically replayed.
    """
    balance = 0

    billed_entries = sorted(
        (te for te in db.time_entries.values()
         if te["case_id"] == case["id"] and te["status"] == "BILLED"),
        key=lambda te: te["created_at"],
    )
    for te in billed_entries:
        billable_minutes = max(0, te["minutes"] + te["adjustment_minutes"])
        per_entry = helpers.round_half_up(
            Decimal(billable_minutes) * Decimal(te["hourly_rate_cents_pinned"]) / Decimal(60)
        )
        balance += per_entry

    expense = int(bill.get("expense_reimbursement_cents") or 0)
    if expense:
        balance += expense

    recovery = int(bill.get("cost_recovery_cents") or 0)
    if recovery:
        balance = max(0, balance - recovery)

    balance += int(bill.get("court_fee_cents") or 0)

    return balance


def compute_prep_tasks(case):
    """Hearing prep-task checklist per PRD §3.4 / SCAFFOLD calc hearing_prep_tasks."""
    case_id = case["id"]
    tasks = []
    tasks.append("Confirm court_room and arrival time")
    tasks.append("Brief all Party rows with party_role in {PLAINTIFF, DEFENDANT}")
    if case["case_type"] == "CIVIL":
        tasks.append("Prepare civil witness list")
    elif case["case_type"] == "CRIMINAL":
        tasks.append("Coordinate with prosecution discovery")
    elif case["case_type"] == "ADMINISTRATIVE":
        tasks.append("File administrative-law brief")
    elif case["case_type"] == "ARBITRATION":
        tasks.append("Confirm arbitrator panel composition")
    n_submitted = sum(
        1 for ev in db.evidence_rows.values()
        if ev["case_id"] == case_id and ev["status"] == "SUBMITTED"
    )
    tasks.append(f"Re-verify {n_submitted} submitted evidence custody chain")
    return tasks
