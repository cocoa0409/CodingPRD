"""Per-formula calculators from PRD §3 and SCAFFOLD §1.3.

The five formulas:

  * `provisional_refund_amount` (§3.4 forward-looking) — per-ticket
    half-up at the per-type per-ticket cents step, integer multiplication
    by the outstanding count, exact integer sum across types.

  * `final_refund_amount` (§3.4 chronological) — straight integer sum
    of the external system's per-type final cents; no further rounding.

  * `provisional_exposure_fulfilment_pct` (§3.6) — sum the projected
    contribution per allocation in exact Decimal arithmetic, divide by
    `contracted_units`, multiply by 100, round half-up to two decimals.

  * `actual_exposure_fulfilment_pct` (§3.6, §3.7) — sum the
    delivered-units across the tier's allocations, divide by
    `contracted_units`, multiply by 100, round half-up to two decimals.

  * `slot_priority_score` (§3.5) — weighted sum
    `tier_bonus + travel_buffer_minutes * 0.1 - conflicts * 20 +
    min(rider_count, 5) * 2`, then clamp at 0, then round half-up to
    two decimals.

  * `sponsor_payout_total` (§3.7) — sum the unrounded mills across all
    DELIVERED-or-REPORTED allocations of the tier (each line's
    contribution is integer units × integer mills/unit, no rounding),
    divide the integer total by 1000, round half-up to integer cents.
    The pinned single-final-rounding step makes the (1,1,1) units ×
    25 mills/unit canonical input produce 8 cents (not the alternative
    per-line-rounded 9 cents).

  * `festival_day_count` (§2.4 / §2.7) — integer ceil
    ``((end_time − start_time) / 86400)``.

  * `window_fraction_remaining` (§2.7) — clamped real number in
    `[0.0, 1.0]` equal to ``(end_time − max(now, start_time)) /
    max(1, end_time − start_time)``.

All money arithmetic stays in integer cents per §2.7 (CENT_PRECISION=0).
The half-up rule is `Decimal.quantize(..., ROUND_HALF_UP)` everywhere,
matching the IEEE 754 "round half away from zero" convention the PRD
pins for non-negative quantities.
"""
from __future__ import annotations

import math
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .constants import (
    HEADLINER_BONUS,
    MAIN_BONUS,
    MULTI_FESTIVAL_CONFLICT_PENALTY,
    OPENER_BONUS,
    PERCENT_PRECISION,
    RIDER_CAP,
    RIDER_WEIGHT,
    SPONSOR_PAYOUT_RATE_MILS_DEFAULT,
    SURPRISE_BONUS,
    TRAVEL_BUFFER_MAX_MINUTES,
    TRAVEL_WEIGHT,
    NON_NEGATIVE_FLOOR,
)


# ---------------------------------------------------------------------------
# Festival day-count and window fraction.
# ---------------------------------------------------------------------------


def festival_day_count(start_time: int, end_time: int) -> int:
    """Integer ceil of the window divided by 86400 seconds."""
    if end_time <= start_time:
        return 0
    duration = end_time - start_time
    days = -(-duration // 86400)  # ceil division
    return int(days)


def window_fraction_remaining(
    start_time: int, end_time: int, logical_now_seconds: int
) -> Decimal:
    """The §2.7 fraction in ``[0.0, 1.0]`` of the festival window that has not yet elapsed.

    Concretely::

        numerator = end_time - max(logical_now, start_time)
        denominator = max(1, end_time - start_time)
        clamp(numerator / denominator, 0.0, 1.0)
    """
    denom = max(1, end_time - start_time)
    numer = end_time - max(logical_now_seconds, start_time)
    if numer <= 0:
        return Decimal("0")
    frac = Decimal(numer) / Decimal(denom)
    if frac > 1:
        frac = Decimal("1")
    return frac


# ---------------------------------------------------------------------------
# Refund.
# ---------------------------------------------------------------------------


def per_ticket_provisional_cents(
    unit_price_cents: int, cancelled_days: int, festival_day_count_value: int
) -> int:
    """The half-up rounded per-ticket cents figure from §3.4.

    ``round_half_up(unit_price_cents * cancelled_days / festival_day_count)``.
    """
    if festival_day_count_value <= 0:
        return 0
    numer = Decimal(unit_price_cents) * Decimal(cancelled_days)
    denom = Decimal(festival_day_count_value)
    raw = numer / denom
    return int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def provisional_refund_for_change(
    affected_ticket_types: Sequence[Dict],
    cancelled_days: int,
    festival_day_count_value: int,
) -> Tuple[int, Dict[str, int]]:
    """Return ``(across_types_total_cents, per_type_attribution_cents_dict)``.

    The per-type attribution is the dict keyed by ticket_type_id that the
    refund-confirmed endpoint reads to decrement
    `provisional_refund_cents_outstanding` by the matching amount.
    """
    per_type: Dict[str, int] = {}
    total = 0
    for tt in affected_ticket_types:
        outstanding = int(tt["issued_count"]) - int(tt["refunded_count"])
        if outstanding <= 0:
            per_type[tt["id"]] = 0
            continue
        per_ticket = per_ticket_provisional_cents(
            int(tt["unit_price_cents"]), cancelled_days, festival_day_count_value
        )
        type_total = outstanding * per_ticket
        per_type[tt["id"]] = type_total
        total += type_total
    return total, per_type


# ---------------------------------------------------------------------------
# Fulfilment percentages.
# ---------------------------------------------------------------------------


def _round_half_up_to_decimals(value: Decimal, decimals: int) -> Decimal:
    """Round ``value`` half-up to ``decimals`` decimal places."""
    quant = Decimal("1").scaleb(-decimals)
    return value.quantize(quant, rounding=ROUND_HALF_UP)


def projected_fulfilment_pct(
    contracted_units: int,
    allocations: Iterable[Dict],
    program_item_lookup: Dict[str, Dict],
    festival_row: Dict,
    logical_now_seconds: int,
) -> Decimal:
    """The §3.6 forward-looking percentage.

    Sums the per-allocation projected contribution in exact Decimal, then
    divides by `contracted_units`, multiplies by 100, and rounds half-up
    to two decimal places per the §2.7 `PERCENT_PRECISION = 2` constant.
    """
    if contracted_units <= 0:
        return Decimal("0.00")
    scheduled_units = Decimal("0")
    f_start = int(festival_row["start_time"])
    f_end = int(festival_row["end_time"])
    for a in allocations:
        # Per §3.6 the basis is `actual_units` (the post-waterfall figure),
        # falling back to `requested_units` when the waterfall has not yet
        # been run for this allocation.  We use whichever is non-null.
        units = a.get("actual_units")
        if units is None:
            units = a.get("requested_units", 0)
        units = int(units)
        if a.get("status") in ("VOIDED",):
            # Voided allocations contribute zero to both projection and
            # actual; PRD §3.6 pins this when the cascade fires.
            projected = Decimal("0")
        elif a.get("program_item_id") is None:
            # Festival-wide: weight by the window-fraction-remaining.
            frac = window_fraction_remaining(f_start, f_end, logical_now_seconds)
            projected = (Decimal(units) * frac).quantize(
                Decimal("0.0001"), rounding=ROUND_HALF_UP
            )
        else:
            tied_item = program_item_lookup.get(a["program_item_id"])
            if tied_item is None:
                projected = Decimal("0")
            elif tied_item.get("status") in (
                "CONFIRMED",
                "ANNOUNCED",
                "ON_STAGE",
                "PERFORMED",
            ):
                projected = Decimal(units)
            else:
                # PROPOSED, CANCELLED — contribute zero.
                projected = Decimal("0")
        scheduled_units += projected
    pct = (scheduled_units / Decimal(contracted_units)) * Decimal(100)
    return _round_half_up_to_decimals(pct, PERCENT_PRECISION)


def delivered_units_for_allocation(
    allocation_id: str, fulfilment_logs: Iterable[Dict]
) -> int:
    """Sum DELIVERED units minus VOIDED-and-PROGRAM_VOIDED units.

    REPORTED rows carry ``units = 0`` and contribute nothing per §3.6.
    """
    delivered = 0
    voided = 0
    for row in fulfilment_logs:
        if row["exposure_allocation_id"] != allocation_id:
            continue
        et = row["event_type"]
        u = int(row.get("units", 0))
        if et == "DELIVERED":
            delivered += u
        elif et in ("VOIDED", "PROGRAM_VOIDED"):
            voided += u
        # REPORTED contributes zero.
    return delivered - voided


def actual_fulfilment_pct(
    contracted_units: int,
    tier_allocations: Sequence[Dict],
    fulfilment_logs: Iterable[Dict],
) -> Decimal:
    """The §3.7 post-close percentage from the immutable fulfilment-log stream."""
    if contracted_units <= 0:
        return Decimal("0.00")
    fl_list = list(fulfilment_logs)
    total_delivered = 0
    for a in tier_allocations:
        total_delivered += delivered_units_for_allocation(a["id"], fl_list)
    pct = (Decimal(total_delivered) / Decimal(contracted_units)) * Decimal(100)
    return _round_half_up_to_decimals(pct, PERCENT_PRECISION)


def tier_remaining_quota_from_logs(
    contracted_units: int,
    tier_allocations: Sequence[Dict],
    fulfilment_logs: Iterable[Dict],
) -> int:
    """The §3.6 conserved quota integer ``contracted_units - Σ delivered_units``."""
    fl_list = list(fulfilment_logs)
    total = 0
    for a in tier_allocations:
        total += delivered_units_for_allocation(a["id"], fl_list)
    return contracted_units - total


# ---------------------------------------------------------------------------
# Sponsor payout.
# ---------------------------------------------------------------------------


def sponsor_payout_total_cents(
    tier_allocations: Sequence[Dict],
    fulfilment_logs: Iterable[Dict],
) -> int:
    """§3.6 / §2.7 mills-summed-then-divided sponsor-payout total in
    the wire integer-cents unit the PRD's canonical worked example
    pins as the literal "8 cents" on a three-line × one-unit × 25-mill
    input.

    Each line's contribution is `delivered_units *
    pinned_rate_cents_per_unit` where the pinned rate's unit is mills
    (the §2.7 prose names it "thousandths of a cent") and defaults to
    `SPONSOR_PAYOUT_RATE_MILS_DEFAULT = 25` when the allocation's
    field is null.  Allocations whose `status` is not in the
    {DELIVERED, REPORTED} set or whose `delivered_units` is zero
    contribute nothing.

    The rounding-order is "sum the mills, divide once by 1000 at the
    end to get a Decimal in 'cents', quantize half-up to the two-
    decimal §2.7 precision, then multiply by 100 to render the wire
    integer".  The §2.7 worked example is verbatim "the unrounded
    `0.075` cents intermediate rounds half-up to `0.08` cents and ...
    the integer cents result ... is **8 cents**", with the alternative
    per-line ordering producing 9 (`0.025 → 0.03` per line, summing to
    0.09 → 9).  The wire-integer-cents convention's factor of 100 is
    what bridges "0.08 cents" and "8 integer cents" in the §2.7
    sentence's "on the integer-cents output convention the
    implementation reports this as 8 cents" clause.
    """
    fl_list = list(fulfilment_logs)
    total_mills = 0
    for a in tier_allocations:
        if a.get("status") not in ("DELIVERED", "REPORTED"):
            continue
        delivered = delivered_units_for_allocation(a["id"], fl_list)
        if delivered <= 0:
            continue
        rate = a.get("pinned_rate_cents_per_unit")
        if rate is None:
            rate = SPONSOR_PAYOUT_RATE_MILS_DEFAULT
        total_mills += int(delivered) * int(rate)
    if total_mills == 0:
        return 0
    # Single divide-once-by-1000 step from mills to fractional cents,
    # quantize half-up to the §2.7 two-decimal precision, then the
    # wire-integer convention multiplies by 100 so the canonical 0.08
    # cents renders as the wire literal 8.
    cents_fractional = Decimal(total_mills) / Decimal(1000)
    cents_two_dp = cents_fractional.quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    wire_integer = int(
        (cents_two_dp * Decimal(100)).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )
    return wire_integer


# ---------------------------------------------------------------------------
# Slot priority.
# ---------------------------------------------------------------------------


def _tier_bonus(tier: str) -> int:
    return {
        "HEADLINER": HEADLINER_BONUS,
        "MAIN": MAIN_BONUS,
        "OPENER": OPENER_BONUS,
        "SURPRISE": SURPRISE_BONUS,
    }.get(tier, 0)


def _latest_preceding_commitment_end(
    commitments: Sequence[Dict], candidate_start: int
) -> Optional[int]:
    best: Optional[int] = None
    for c in commitments:
        e = int(c.get("end_time", 0))
        if e <= candidate_start:
            if best is None or e > best:
                best = e
    return best


def _commitments_within_pm_24h(
    commitments: Sequence[Dict], candidate_start: int, candidate_end: int
) -> int:
    """Count commitments whose half-open window intersects the ±24h neighbourhood.

    The neighbourhood is ``[candidate_start - 86400, candidate_end + 86400)``.
    """
    lo = candidate_start - 86400
    hi = candidate_end + 86400
    count = 0
    for c in commitments:
        c_s = int(c.get("start_time", 0))
        c_e = int(c.get("end_time", 0))
        if c_s < hi and lo < c_e:
            count += 1
    return count


def slot_priority_score(
    artist_tier: str,
    artist_external_commitments: Sequence[Dict],
    candidate_start: int,
    candidate_end: int,
    rider_count: int,
) -> Decimal:
    """§3.5 weighted-sum formula, with the §2.7 half-up two-decimal rounding."""
    tier_bonus = Decimal(_tier_bonus(artist_tier))

    latest = _latest_preceding_commitment_end(
        artist_external_commitments, candidate_start
    )
    if latest is None:
        travel_minutes = Decimal(0)
    else:
        gap_seconds = max(0, candidate_start - latest)
        travel_minutes = Decimal(gap_seconds) / Decimal(60)
        # Clamp at TRAVEL_BUFFER_MAX_MINUTES (1440 minutes = 24 hours).
        if travel_minutes > Decimal(TRAVEL_BUFFER_MAX_MINUTES):
            travel_minutes = Decimal(TRAVEL_BUFFER_MAX_MINUTES)

    conflict_count = _commitments_within_pm_24h(
        artist_external_commitments, candidate_start, candidate_end
    )

    capped_rider_count = min(int(rider_count), RIDER_CAP)

    travel_term = travel_minutes * TRAVEL_WEIGHT
    conflict_term = Decimal(conflict_count) * Decimal(MULTI_FESTIVAL_CONFLICT_PENALTY)
    rider_term = Decimal(capped_rider_count) * Decimal(RIDER_WEIGHT)

    raw = tier_bonus + travel_term - conflict_term + rider_term
    floor = Decimal(NON_NEGATIVE_FLOOR)
    if raw < floor:
        raw = floor
    return _round_half_up_to_decimals(raw, 2)


def admin_fee_deducted_cents(provisional_cents: int) -> int:
    """The PRD §3.4 illustrative final-cents-after-admin-fee calculation.

    ``provisional - round_half_up(provisional * ADMIN_FEE_RATE_FINAL)``
    with ``ADMIN_FEE_RATE_FINAL = 0.05`` for the worked-example calibration
    (12000 provisional → 11400 final).
    """
    from .constants import ADMIN_FEE_RATE_FINAL

    fee_raw = Decimal(provisional_cents) * ADMIN_FEE_RATE_FINAL
    fee_cents = int(fee_raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return int(provisional_cents) - fee_cents
