"""Deterministic calculations (PRD 2.6, 3.1, 3.3, 3.7, 3.8, 3.9).

All money is integer cents; every division keeps an exact rational intermediate
via ``Decimal`` and is rounded only where a rule names the rounding.
"""

from decimal import Decimal, ROUND_HALF_UP

import enums

ONE = Decimal(1)
HUNDRED = Decimal(100)


def round_half_up(value):
    """Half-up rounding to whole cents (PRD 2.6)."""
    return int(Decimal(value).quantize(ONE, rounding=ROUND_HALF_UP))


def floor_pct(numerator, denominator):
    """Floor to a whole percent; truncation toward zero for non-negatives."""
    if denominator == 0:
        return 0
    return (100 * numerator) // denominator


def patient_share_factor(plan):
    """(100 - coinsurance_pct) / 100 as an exact Decimal."""
    return (HUNDRED - Decimal(plan["coinsurance_pct"])) / HUNDRED


def rate_cents_per_day(plan, copay_tier):
    return plan[enums.TIER_RATE_FIELD[copay_tier]]


def raw_line_amount(plan, prescription, days_supply_filled):
    """Exact unrounded per-line amount, in cents."""
    rate = Decimal(rate_cents_per_day(plan, prescription["copay_tier"]))
    return rate * Decimal(days_supply_filled) * patient_share_factor(plan)


def line_copay_cents(plan, prescription, days_supply_filled):
    """Rounded-per-line provisional copay."""
    return round_half_up(raw_line_amount(plan, prescription, days_supply_filled))


def alignment(sync_mode, cycle_start_date, day_supply_days, last_dispensed_date,
              last_dispensed_days_supply):
    """The two irreconcilable synchronization policies (PRD 3.1).

    Returns (bridge_days, trim_days, days_supply_filled).
    """
    if last_dispensed_date is None:
        on_hand_through = cycle_start_date
    else:
        on_hand_through = last_dispensed_date + _days(last_dispensed_days_supply or 0)
    gap = max(0, (cycle_start_date - on_hand_through).days)
    overlap = max(0, (on_hand_through - cycle_start_date).days)
    if sync_mode == "BRIDGE_TO_START":
        return gap, 0, day_supply_days + gap
    return 0, overlap, max(0, day_supply_days - overlap)


def _days(count):
    from datetime import timedelta

    return timedelta(days=count)


def refill_pct_used(cycle_start_date, last_dispensed_date, last_dispensed_days_supply):
    """Percent of the previous day supply consumed by the cycle start."""
    if last_dispensed_date is None:
        return 100
    if not last_dispensed_days_supply or last_dispensed_days_supply <= 0:
        return 100
    elapsed = (cycle_start_date - last_dispensed_date).days
    return (100 * elapsed) // last_dispensed_days_supply


def allowance_days(plan, prescription, cycle_day_supply_days, bridge_days_applied,
                   approved_vacation_extra_days):
    """Four ceilings folded together with successive minima (PRD 3.3)."""
    value = min(
        plan["max_day_supply_days"],
        prescription["days_supply_written"] * (prescription["refills_remaining"] + 1),
        cycle_day_supply_days + bridge_days_applied + approved_vacation_extra_days,
    )
    if prescription["is_controlled"]:
        value = min(value, enums.CONTROLLED_DAY_SUPPLY_CAP)
    if prescription["refrigerated"]:
        value = min(value, enums.REFRIGERATED_DAY_SUPPLY_CAP)
    return value


def packable_route(prescription):
    if prescription["refrigerated"]:
        return "COLD_CHAIN"
    if prescription["packable"]:
        return "POUCH"
    return "LOOSE_SPLIT"


def quantity_dispensed(prescription, days_supply_filled):
    return (
        prescription["quantity_per_dose"]
        * len(prescription["dose_times"])
        * days_supply_filled
    )


def is_packable(form, refrigerated):
    return form in enums.POUCHABLE_FORMS and not refrigerated


def ship_cost_cents(shipment_kind, packaging, carrier_service):
    return (
        enums.SHIPMENT_KIND_BASE_CENTS[shipment_kind]
        + enums.PACKAGING_ADD_CENTS[packaging]
        + enums.CARRIER_ADD_CENTS[carrier_service]
    )


def reissue_fee_cents(tier_basis_cents):
    if tier_basis_cents >= 5000:
        return 0
    if tier_basis_cents >= 2000:
        return 250
    return 500


def line_reissue_credit_cents(copay_cents, unused_days, days_supply_filled):
    if days_supply_filled == 0:
        return 0
    return round_half_up(
        Decimal(copay_cents) * Decimal(unused_days) / Decimal(days_supply_filled)
    )


def imaging_result(image_confidence_pct, detected_pill_count, expected_pill_count):
    """Fixed precedence: unreadable, then match, then mismatch (PRD 3.6)."""
    if image_confidence_pct < enums.IMAGE_CONFIDENCE_MIN_PCT:
        return "UNREADABLE"
    if detected_pill_count == expected_pill_count:
        return "MATCH"
    return "MISMATCH_COUNT"
