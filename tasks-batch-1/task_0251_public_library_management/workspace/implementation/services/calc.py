"""Calculation rules (SCAFFOLD §1.3 / PRD §3).

All money is whole cents; rounding is ROUND_HALF_UP applied at the points the PRD
pins. We use decimal.Decimal everywhere a fractional cent could arise — never
float.
"""

from decimal import Decimal, ROUND_HALF_UP

from timeutil import floor_days

# replacement_charge constants (SCAFFOLD §1.3)
ANNUAL_DEPRECIATION_PCT = Decimal("0.10")
MAX_DEPRECIATION_PCT = Decimal("0.80")
PROCESSING_FEE_PCT = Decimal("0.10")

# capped_account_balance constants
GOODWILL_TIER_CENTS = 2000
GOODWILL_WAIVER_CENTS = 200


def _round_half_up(value):
    """Round a Decimal to whole cents, half up."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def overdue_fine(branch, due_date, return_instant):
    """Final/estimate overdue fine in whole cents (overdue_fine_final / estimate).

    overdue_days   = max(0, floor_days(return_instant - due_date))
    chargeable_days= max(0, overdue_days - grace_days)
    raw            = chargeable_days * daily_fine_cents
    return min(raw, max_fine_cents)   (0 when branch.fine_free)

    Returns (amount_cents, overdue_days, chargeable_days).
    """
    if branch.get("fine_free"):
        # Still report day counts for transparency, but the assessed money is 0.
        overdue_days = max(0, floor_days(return_instant, due_date))
        chargeable_days = max(0, overdue_days - branch["grace_days"])
        return 0, overdue_days, chargeable_days

    overdue_days = max(0, floor_days(return_instant, due_date))
    chargeable_days = max(0, overdue_days - branch["grace_days"])
    raw = chargeable_days * branch["daily_fine_cents"]
    amount = min(raw, branch["max_fine_cents"])
    return amount, overdue_days, chargeable_days


def replacement_charge(branch, title, copy, lost_at, flat_replacement=False):
    """Lost-item replacement charge in whole cents (SCAFFOLD §1.3 replacement_charge).

    PINNED ORDER: round each component to whole cents independently, THEN sum.
    """
    default_cents = Decimal(title["default_replacement_cents"])

    # Component 2: flat processing fee (same in both variants), rounded on its own.
    processing_cents = _round_half_up(default_cents * PROCESSING_FEE_PCT)

    if flat_replacement:
        # DEFAULT variant: ignore depreciation and condition_factor entirely.
        item_value_cents = int(title["default_replacement_cents"])
    else:
        # DEPRECIATED variant.
        days = floor_days(lost_at, copy["acquired_on"])
        age_years = Decimal(days) / Decimal(365)
        depreciation = age_years * ANNUAL_DEPRECIATION_PCT
        if depreciation > MAX_DEPRECIATION_PCT:
            depreciation = MAX_DEPRECIATION_PCT
        condition = Decimal(str(copy.get("condition_factor", 1.0)))
        raw_value = default_cents * (Decimal(1) - depreciation) * condition
        item_value_cents = _round_half_up(raw_value)

    return item_value_cents + processing_cents


def account_summary(patron):
    """capped_account_balance (SCAFFOLD §1.3).

    PINNED ORDER:
      1. raw_total = sum of UNPAID fine amounts
      2. tier keyed on raw_total -> waiver
      3. net = max(0, raw_total - waiver)
    Returns dict with raw_total_cents, waiver_cents, net_owed_cents, unpaid_fine_count.
    """
    import db

    pid = patron["id"]
    unpaid = [
        f for f in db.fines.values()
        if f["patron_id"] == pid and f["settlement_status"] == "UNPAID"
    ]
    raw_total_cents = sum(f["amount_cents"] for f in unpaid)

    if raw_total_cents >= GOODWILL_TIER_CENTS:
        waiver_cents = GOODWILL_WAIVER_CENTS
    else:
        waiver_cents = 0

    net_owed_cents = max(0, raw_total_cents - waiver_cents)

    return {
        "raw_total_cents": raw_total_cents,
        "waiver_cents": waiver_cents,
        "net_owed_cents": net_owed_cents,
        "unpaid_fine_count": len(unpaid),
    }
