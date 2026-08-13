"""Penalty accrual and mitigation credit calculations for ConsentOrders."""

import math
from datetime import timezone
from decimal import Decimal, ROUND_HALF_UP

import db


def _days_between(d1, d2):
    """Whole days from date d1 to date d2."""
    return (d2 - d1).days


def _gross_cents(co, end_date):
    """Capped gross assessment computed against end_date (a date)."""
    exc = db.exceedances.get(co["exceedance_id"])
    violation_date = exc["detected_at"].date() if exc else None
    if violation_date is None:
        return 0, 0
    accrued_days = max(1, _days_between(violation_date, end_date))
    base = int(co["base_penalty_cents"])
    cap = int(co["statutory_cap_cents"])
    if co["assessment_variant"] == "PER_DAY":
        gross = base + int(co.get("daily_accrual_cents") or 0) * accrued_days
    else:  # ECONOMIC_BENEFIT
        months = math.ceil(accrued_days / 30)
        avoided = int(co.get("avoided_cost_cents") or 0)
        gravity = Decimal(str(co.get("gravity_factor") or 0))
        product = Decimal(avoided) * Decimal(months) * gravity
        product = product.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        gross = base + int(product)
    gross_capped = min(cap, gross)
    return gross_capped, accrued_days


def compute_penalty(co):
    """Compute accrued_days + provisional_amount_cents against the current clock."""
    now_date = db.clock.now().date()
    if co["status"] in ("FINAL", "SATISFIED") and co.get("cure_date") is not None:
        end_date = co["cure_date"].date()
    else:
        end_date = now_date
    gross_capped, accrued_days = _gross_cents(co, end_date)

    # Provisional is always computed against current clock date
    provisional, _ = _gross_cents(co, now_date)

    return {
        "accrued_days": accrued_days,
        "provisional_amount_cents": provisional,
        "gross_capped_at_end": gross_capped,
    }


def compute_final_amount(co):
    """Three-step pinned finalize computation.

    Returns (final_amount_cents, cure_date_datetime).
    """
    from datetime import datetime

    exc = db.exceedances.get(co["exceedance_id"])
    ca = None
    if exc is not None and exc.get("corrective_action_id"):
        ca = db.corrective_actions.get(exc["corrective_action_id"])

    # Cure date: linked CA's resolved_at when VERIFIED at finalize time; else finalized_at
    finalized_at = db.clock.now()
    if ca is not None and ca["status"] == "VERIFIED" and ca.get("resolved_at") is not None:
        cure_date = ca["resolved_at"]
    else:
        cure_date = finalized_at

    # Step 1: capped gross at cure date (does NOT depend on credit)
    gross_capped, _ = _gross_cents(co, cure_date.date())

    # Step 2: mitigation credit = min(round_half_up(0.25 * gross_capped), verified_corrective_cost)
    verified_cost = 0
    if ca is not None and ca["status"] in ("VERIFIED", "CLOSED"):
        verified_cost = int(ca.get("actual_cost_cents") or 0)
    quarter = (Decimal(gross_capped) * Decimal("0.25")).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    credit = min(int(quarter), verified_cost)

    # Step 3: final = max(0, gross - credit)
    final_amount = max(0, gross_capped - credit)
    return final_amount, cure_date
