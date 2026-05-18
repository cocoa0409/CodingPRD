"""High-level orchestration: compute pipeline, cascades, invalidations.

This sits above `calculations.py` (pure math) and `db.py` (storage).
It owns the bookkeeping of timestamps, version bumps, parent reverts,
and cascade side effects (PRD §2.7).
"""
from __future__ import annotations

from config import (
    AMEND_STATUS_DRAFT,
    AMEND_STATUS_SUBMITTED,
    PAYMENT_CANCELLED,
    PAYMENT_SCHEDULED,
    RETURN_STATUS_DRAFT,
    RETURN_STATUS_READY_TO_FILE,
)
from db import store
from utils import iso_now
from services import calculations as calc


# ── Timestamp / version bookkeeping ─────────────────────────────────────


def stamp_create(entity: dict) -> dict:
    now = store.now()
    iso = iso_now(now)
    entity["created_at"] = iso
    entity["updated_at"] = iso
    entity["version"] = 1
    return entity


def stamp_update(entity: dict) -> dict:
    now = store.now()
    entity["updated_at"] = iso_now(now)
    entity["version"] = (entity.get("version") or 0) + 1
    return entity


def bump_parent_return(tax_return: dict) -> None:
    """Bump the parent TaxReturn's updated_at + version (§2.7)."""
    stamp_update(tax_return)


# ── Child mutation cascade: READY_TO_FILE → DRAFT (§2.7) ────────────────


def invalidate_computed_fields(tax_return: dict) -> None:
    """Reset computed numeric fields to zero per §2.7."""
    tax_return["agi_cents"] = 0
    tax_return["total_income_cents"] = 0
    tax_return["taxable_income_cents"] = 0
    tax_return["regular_tax_cents"] = 0
    tax_return["amt_cents"] = 0
    tax_return["total_credits_cents"] = 0
    tax_return["total_withholding_cents"] = 0
    tax_return["estimated_payments_applied_cents"] = 0
    tax_return["balance_due_or_refund_cents"] = 0
    # Reset every TaxCredit row on this return back to PENDING.
    for c in store.tax_credits.values():
        if c["tax_return_id"] == tax_return["id"]:
            c["eligibility_status"] = "PENDING"
            c["approved_amount_cents"] = 0
            c["refundable_portion_cents"] = 0
            c["ineligibility_reason"] = None
            stamp_update(c)


def cascade_child_mutation(tax_return: dict) -> None:
    """If parent is READY_TO_FILE, revert to DRAFT and invalidate computed fields."""
    if tax_return["status"] == RETURN_STATUS_READY_TO_FILE:
        tax_return["status"] = RETURN_STATUS_DRAFT
        invalidate_computed_fields(tax_return)
    bump_parent_return(tax_return)


# ── Compute pipeline (§3.5–§3.7) ────────────────────────────────────────


def _children_of_return(return_id: str):
    """Helper: list (income_docs, schedules, credits) belonging to a return."""
    docs = [d for d in store.income_documents.values() if d["tax_return_id"] == return_id]
    schedules = [s for s in store.schedules.values() if s["tax_return_id"] == return_id]
    credits = [c for c in store.tax_credits.values() if c["tax_return_id"] == return_id]
    # Stable order: by created_at.
    docs.sort(key=lambda x: x["created_at"])
    schedules.sort(key=lambda x: x["created_at"])
    credits.sort(key=lambda x: x["created_at"])
    return docs, schedules, credits


def _confirmed_estimated_payments_for(taxpayer_id: str, tax_year: int) -> int:
    total = 0
    for p in store.estimated_payments.values():
        if (
            p["taxpayer_id"] == taxpayer_id
            and p["tax_year"] == tax_year
            and p["status"] == "CONFIRMED"
        ):
            total += p.get("amount_cents", 0) or 0
    return total


def run_compute_pipeline(tax_return: dict, taxpayer: dict) -> None:
    """Run the full DRAFT → READY_TO_FILE compute against a return.

    Mutates the return + its schedules + its credits in place.
    Caller must hold store.lock and have validated state preconditions.
    """
    return_id = tax_return["id"]
    docs, schedules, credits = _children_of_return(return_id)

    # Step 0: refresh Schedule B / Schedule D aggregates from income docs.
    calc.refresh_schedule_aggregates(tax_return, docs, schedules)

    # Step 1: AGI.
    total_income, agi, schedule_c_net = calc.calc_agi(tax_return, docs, schedules)

    # Step 1.5: refresh Schedule C net_profit (and bump those schedules).
    for s in schedules:
        if s["schedule_type"] == "C":
            s_net = max(
                0,
                (s.get("schedule_c_gross_receipts_cents", 0) or 0)
                - (s.get("schedule_c_expenses_cents", 0) or 0),
            )
            s["schedule_c_net_profit_cents"] = s_net

    # Step 2: Taxable income.
    taxable, itemized_total = calc.calc_taxable_income(tax_return, taxpayer, schedules, agi)
    # Write itemized total back into Schedule A (if it exists).
    for s in schedules:
        if s["schedule_type"] == "A":
            s["total_itemized_deduction_cents"] = itemized_total

    # Step 3: Regular tax.
    regular_tax = calc.calc_regular_tax(taxable, tax_return["filing_status"])

    # Step 4: AMT.
    amt = calc.calc_amt(agi, tax_return["filing_status"], regular_tax)

    # Step 5: Credits.
    total_credits, applied_nonref, refundable_pool = calc.compute_credits(
        tax_return, credits, agi, regular_tax, amt
    )
    # Stamp each mutated credit row.
    for c in credits:
        stamp_update(c)
    # Stamp each mutated schedule.
    for s in schedules:
        stamp_update(s)

    # Step 6: Balance / payments.
    total_withholding = sum(d.get("federal_withholding_cents", 0) or 0 for d in docs)
    est_payments = _confirmed_estimated_payments_for(
        tax_return["taxpayer_id"], tax_return["tax_year"]
    )
    balance, net_tax = calc.calc_balance(
        regular_tax,
        amt,
        applied_nonref,
        refundable_pool,
        total_withholding,
        est_payments,
    )

    # Write back to the return.
    tax_return["total_income_cents"] = total_income
    tax_return["agi_cents"] = agi
    tax_return["taxable_income_cents"] = taxable
    tax_return["regular_tax_cents"] = regular_tax
    tax_return["amt_cents"] = amt
    tax_return["total_credits_cents"] = total_credits
    tax_return["total_withholding_cents"] = total_withholding
    tax_return["estimated_payments_applied_cents"] = est_payments
    tax_return["balance_due_or_refund_cents"] = balance

    tax_return["status"] = RETURN_STATUS_READY_TO_FILE


# ── Amendment compute (§3.9) ────────────────────────────────────────────


def run_amendment_compute(amendment: dict, original_return: dict, taxpayer: dict) -> dict:
    """Re-run the compute pipeline using restated inputs to produce a snapshot.

    Returns a snapshot dict with keys:
      agi_cents, total_income_cents, taxable_income_cents,
      regular_tax_cents, amt_cents, total_credits_cents,
      total_withholding_cents, estimated_payments_applied_cents,
      balance_due_or_refund_cents, filing_status, deduction_method,
      dependents_count, qualifying_children_under_17
    """
    # Build a shadow return reflecting restated inputs (do not mutate original).
    shadow_return = dict(original_return)
    if amendment.get("restated_filing_status") is not None:
        shadow_return["filing_status"] = amendment["restated_filing_status"]
    if amendment.get("restated_dependents_count") is not None:
        shadow_return["dependents_count"] = amendment["restated_dependents_count"]
    if amendment.get("restated_qualifying_children_under_17") is not None:
        shadow_return["qualifying_children_under_17"] = amendment[
            "restated_qualifying_children_under_17"
        ]
    if amendment.get("restated_deduction_method") is not None:
        shadow_return["deduction_method"] = amendment["restated_deduction_method"]

    return_id = original_return["id"]
    docs = [d for d in store.income_documents.values() if d["tax_return_id"] == return_id]
    schedules_raw = [
        s for s in store.schedules.values() if s["tax_return_id"] == return_id
    ]
    credits_raw = [
        c for c in store.tax_credits.values() if c["tax_return_id"] == return_id
    ]
    docs.sort(key=lambda x: x["created_at"])
    schedules_raw.sort(key=lambda x: x["created_at"])
    credits_raw.sort(key=lambda x: x["created_at"])

    # Deep copy schedules and credits so the amendment compute does not
    # mutate the originals.
    schedules = [dict(s) for s in schedules_raw]
    credits = [dict(c) for c in credits_raw]

    calc.refresh_schedule_aggregates(shadow_return, docs, schedules)
    total_income, agi, _ = calc.calc_agi(shadow_return, docs, schedules)
    for s in schedules:
        if s["schedule_type"] == "C":
            s["schedule_c_net_profit_cents"] = max(
                0,
                (s.get("schedule_c_gross_receipts_cents", 0) or 0)
                - (s.get("schedule_c_expenses_cents", 0) or 0),
            )
    taxable, itemized_total = calc.calc_taxable_income(
        shadow_return, taxpayer, schedules, agi
    )
    regular_tax = calc.calc_regular_tax(taxable, shadow_return["filing_status"])
    amt = calc.calc_amt(agi, shadow_return["filing_status"], regular_tax)
    total_credits, applied_nonref, refundable_pool = calc.compute_credits(
        shadow_return, credits, agi, regular_tax, amt
    )
    total_withholding = sum(d.get("federal_withholding_cents", 0) or 0 for d in docs)
    est_payments = _confirmed_estimated_payments_for(
        original_return["taxpayer_id"], original_return["tax_year"]
    )
    balance, _ = calc.calc_balance(
        regular_tax,
        amt,
        applied_nonref,
        refundable_pool,
        total_withholding,
        est_payments,
    )

    return {
        "filing_status": shadow_return["filing_status"],
        "deduction_method": shadow_return["deduction_method"],
        "dependents_count": shadow_return.get("dependents_count", 0),
        "qualifying_children_under_17": shadow_return.get("qualifying_children_under_17", 0),
        "total_income_cents": total_income,
        "agi_cents": agi,
        "taxable_income_cents": taxable,
        "regular_tax_cents": regular_tax,
        "amt_cents": amt,
        "total_credits_cents": total_credits,
        "total_withholding_cents": total_withholding,
        "estimated_payments_applied_cents": est_payments,
        "balance_due_or_refund_cents": balance,
    }


# ── Compliance lock cascade (§2.7 + §3.11) ──────────────────────────────


def cascade_compliance_lock(taxpayer: dict) -> list[dict]:
    """Cancel all SCHEDULED payments for this taxpayer.

    Returns the list of payment dicts that were transitioned. Caller
    must hold store.lock.
    """
    now_iso = iso_now(store.clock_now())
    cancelled = []
    for p in store.estimated_payments.values():
        if p["taxpayer_id"] == taxpayer["id"] and p["status"] == PAYMENT_SCHEDULED:
            p["status"] = PAYMENT_CANCELLED
            p["cancelled_at"] = now_iso
            stamp_update(p)
            cancelled.append(p)
    return cancelled


# ── Active-amendment lookup (§3.9 / validation priority 9) ──────────────


def has_active_amendment(original_return_id: str, exclude_id: str | None = None) -> bool:
    for a in store.amendments.values():
        if a["original_return_id"] != original_return_id:
            continue
        if exclude_id is not None and a["id"] == exclude_id:
            continue
        if a["status"] in (AMEND_STATUS_DRAFT, AMEND_STATUS_SUBMITTED):
            return True
    return False


# ── Prior-year return lookup for safe-harbor ────────────────────────────


def find_prior_year_return(taxpayer_id: str, current_tax_year: int):
    target_year = current_tax_year - 1
    candidates = [
        r
        for r in store.tax_returns.values()
        if r["taxpayer_id"] == taxpayer_id
        and r["tax_year"] == target_year
        and r["status"] in ("ACCEPTED", "SUPERSEDED")
    ]
    if not candidates:
        return None
    # Return the most recently updated one.
    return max(candidates, key=lambda r: r["updated_at"])
