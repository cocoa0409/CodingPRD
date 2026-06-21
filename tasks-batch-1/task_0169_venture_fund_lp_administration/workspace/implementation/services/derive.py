"""Derived-field reconciliation (PRD §2.6).

These functions COMPUTE the derived totals from children at read/serialize
time and at write time. They never mutate stored state; mutating callers
recompute and store explicitly where the PRD requires it (e.g. drawn_cents on
a commitment is stored because recycling restorations reduce it).
"""
from decimal import Decimal, ROUND_HALF_UP

import db


def round_half_up(value):
    """Round a Decimal/number half-up to the nearest integer cent."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Fund-level derived totals
# ---------------------------------------------------------------------------
def fund_total_committed(fund_id):
    # Sum committed_cents over Commitments with status IN {ACTIVE, DEFAULTED}.
    total = 0
    for c in db.commitments.values():
        if c["fund_id"] == fund_id and c["status"] in ("ACTIVE", "DEFAULTED"):
            total += c["committed_cents"]
    return total


def fund_total_called(fund_id):
    # Sum called_amount_cents over CapitalCalls with status IN
    # {ISSUED, SETTLED, PARTIALLY_DEFAULTED}.
    total = 0
    for call in db.capital_calls.values():
        if call["fund_id"] == fund_id and call["status"] in (
            "ISSUED",
            "SETTLED",
            "PARTIALLY_DEFAULTED",
        ):
            total += call["called_amount_cents"]
    return total


def fund_total_distributed(fund_id):
    # Sum gross_amount_cents over DistributionEvents with status IN
    # {DECLARED, PAID}.
    total = 0
    for e in db.distribution_events.values():
        if e["fund_id"] == fund_id and e["status"] in ("DECLARED", "PAID"):
            total += e["gross_amount_cents"]
    return total


def fund_recycled_to_date(fund_id):
    # Sum recycled_amount_cents over DistributionEvents with status = RECALLED.
    total = 0
    for e in db.distribution_events.values():
        if e["fund_id"] == fund_id and e["status"] == "RECALLED":
            total += e["recycled_amount_cents"]
    return total


def fund_nav(fund_id):
    # Sum current_mark_cents over Investments with status IN {ACTIVE, IMPAIRED}.
    total = 0
    for inv in db.investments.values():
        if inv["fund_id"] == fund_id and inv["status"] in ("ACTIVE", "IMPAIRED"):
            total += investment_current_mark(inv)
    return total


# ---------------------------------------------------------------------------
# Commitment-level derived totals
# ---------------------------------------------------------------------------
def commitment_drawn(commitment):
    """drawn_cents = sum of PAID allocation paid_amount_cents minus recycling
    restorations applied to this commitment.

    Recycling restorations are tracked on the commitment as a stored
    'recycled_restored_cents' offset so reductions persist.
    """
    paid = 0
    cid = commitment["id"]
    for a in db.capital_call_allocations.values():
        if a["commitment_id"] == cid and a["status"] == "PAID":
            paid += a["paid_amount_cents"]
    restored = commitment.get("recycled_restored_cents", 0)
    return paid - restored


def commitment_distributed(commitment):
    # Sum amount_cents over DistributionAllocations whose parent event status
    # IN {DECLARED, PAID}.
    cid = commitment["id"]
    total = 0
    for a in db.distribution_allocations.values():
        if a["commitment_id"] != cid:
            continue
        event = db.distribution_events.get(a["distribution_event_id"])
        if event and event["status"] in ("DECLARED", "PAID"):
            total += a["amount_cents"]
    return total


def commitment_unfunded(commitment):
    # committed_cents - drawn_cents, floored at 0.
    drawn = commitment_drawn(commitment)
    return max(0, commitment["committed_cents"] - drawn)


# ---------------------------------------------------------------------------
# CapitalCall / LP / Investment derived
# ---------------------------------------------------------------------------
def call_funded_amount(call):
    # Sum paid_amount_cents over PAID allocations of this call.
    total = 0
    for a in db.capital_call_allocations.values():
        if a["capital_call_id"] == call["id"] and a["status"] == "PAID":
            total += a["paid_amount_cents"]
    return total


def lp_default_strike_count(lp_id):
    # Count of that LP's allocations (across all its commitments) with status
    # DEFAULTED.
    commitment_ids = {c["id"] for c in db.commitments.values() if c["lp_id"] == lp_id}
    count = 0
    for a in db.capital_call_allocations.values():
        if a["commitment_id"] in commitment_ids and a["status"] == "DEFAULTED":
            count += 1
    return count


def investment_current_mark(inv):
    # current_mark_cents from latest FINAL mark; equals cost_basis_cents until
    # the first FINAL mark exists. "Latest" = greatest as_of_date among FINAL.
    finals = [
        m
        for m in db.valuation_marks.values()
        if m["investment_id"] == inv["id"] and m["status"] == "FINAL"
    ]
    if not finals:
        return inv["cost_basis_cents"]
    latest = max(finals, key=lambda m: (m["as_of_date"], m["created_at"]))
    return latest["fair_value_cents"]
