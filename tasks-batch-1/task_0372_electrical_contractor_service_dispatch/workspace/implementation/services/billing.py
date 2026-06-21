"""Invoice calculation (PRD §3.7, SCAFFOLD invoice_total).

Chronological / actual billing built from realized usages, the accepted
estimate, the snapshotted membership, and the job's priority. Component fields
are computed in a pinned order; rounding is applied independently at each step
(round-then-sum, NOT sum-then-round, PRD §2.8).
"""
from decimal import Decimal, ROUND_HALF_UP

import db
from helpers import round_half_up
from services import domain


def _round_pct(base_cents, fraction):
    """round_half_up(base_cents * fraction) at integer cents."""
    result = (Decimal(str(base_cents)) * Decimal(str(fraction))).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    return int(result)


def compute_invoice(job, accepted_estimate, technician):
    """Return a dict of the invoice component fields for the job.

    technician: the technician whose hourly_rate_cents applies to TIME_MATERIALS
    labor, or None for FLAT_RATE jobs (where labor ignores the rate).
    """
    # Step 1: labor subtotal.
    if accepted_estimate["pricing_mode"] == "FLAT_RATE":
        labor_subtotal_cents = accepted_estimate["flat_rate_cents"]
    else:  # TIME_MATERIALS
        actual_hours = job.get("actual_labor_hours", 0) or 0
        rate = technician["hourly_rate_cents"] if technician is not None else 0
        labor_subtotal_cents = round_half_up(Decimal(str(actual_hours)) * Decimal(str(rate)))

    # Step 2: material subtotal — sum of non-voided line_total_cents,
    # accumulated in ascending created_at order for a deterministic running sum.
    usages = [
        u for u in db.material_usages.values()
        if u["job_id"] == job["id"] and not u["voided"]
    ]
    usages.sort(key=lambda u: (u["created_at"], u["_seq"]))
    material_subtotal_cents = 0
    for u in usages:
        material_subtotal_cents += u["line_total_cents"]

    # Step 3: dispatch fee — waived when the plan waives it.
    plan = domain.plan_for_job(db, job)
    if job.get("membership_id") is not None and plan is not None and plan["waives_dispatch_fee"]:
        dispatch_fee_cents = 0
    else:
        dispatch_fee_cents = domain.DISPATCH_FEE_CENTS

    # Step 4: emergency surcharge.
    emergency_surcharge_cents = (
        domain.EMERGENCY_SURCHARGE_CENTS if job["priority"] == "EMERGENCY" else 0
    )

    # Step 5: discount — membership labor discount, rounded half up.
    if job.get("membership_id") is not None and plan is not None:
        discount_cents = _round_pct(labor_subtotal_cents, plan["labor_discount_pct"])
    else:
        discount_cents = 0

    # Step 6: tax — taxable material base * TAX_RATE, rounded half up.
    taxable_base = 0
    for u in usages:
        sku = db.material_skus.get(u["sku_id"])
        if sku is not None and sku["taxable"]:
            taxable_base += u["line_total_cents"]
    tax_cents = _round_pct(taxable_base, domain.TAX_RATE)

    # Step 7: grand total.
    total_cents = (
        (labor_subtotal_cents - discount_cents)
        + material_subtotal_cents
        + dispatch_fee_cents
        + emergency_surcharge_cents
        + tax_cents
    )

    return {
        "labor_subtotal_cents": labor_subtotal_cents,
        "material_subtotal_cents": material_subtotal_cents,
        "dispatch_fee_cents": dispatch_fee_cents,
        "emergency_surcharge_cents": emergency_surcharge_cents,
        "discount_cents": discount_cents,
        "tax_cents": tax_cents,
        "total_cents": total_cents,
    }
