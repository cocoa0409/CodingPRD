"""Calculation rules (SCAFFOLD §1.3, PRD §2.8 & §3).

All monetary amounts are integer cents. Fractional cents are resolved with
ROUND_HALF_UP (PRD §2.8). Loyalty points are integers produced with floor.
Order-of-operations is pinned where the PRD pins it.
"""

from decimal import Decimal, ROUND_HALF_UP


# ---- constants (SCAFFOLD §1.3) ----------------------------------------------
BAND_MULT = {"TWILIGHT": Decimal("0.80"), "OFFPEAK": Decimal("1.00"), "PEAK": Decimal("1.60")}
DAY_FACTOR = {"WEEKDAY": Decimal("1.00"), "WEEKEND": Decimal("1.25")}
MULT_FLOOR = Decimal("0.80")
MULT_CEIL = Decimal("2.00")
TIER_DISCOUNT = {"STANDARD": Decimal("0.00"), "GOLD": Decimal("0.10"), "PLATINUM": Decimal("0.15")}

GRATUITY_PCT = Decimal("0.18")
TAX_PCT = Decimal("0.0825")

POINTS_PER_CENT_DIVISOR = 100
TIER_MULT = {"STANDARD": Decimal("1.0"), "GOLD": Decimal("1.25"), "PLATINUM": Decimal("1.5")}

NO_SHOW_PCT = Decimal("0.50")

HOLD_TTL_MINUTES = 30
LATE_CANCEL_WINDOW_MINUTES = 120
QUEUE_TTL_MINUTES = 60

STREAK_LEN = 5
STREAK_MIN_POINTS = 10
STREAK_BONUS = 25


def _round_half_up(dec_value):
    """Round a Decimal to a whole integer using ROUND_HALF_UP, return int."""
    return int(dec_value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def dynamic_bay_price(base_rate_cents, num_segments, time_band, day_type,
                      peak_demand_factor, member_tier):
    """DYNAMIC_BAY_PRICE (SCAFFOLD §1.3 / PRD §3.3).

    ROUND_TOTAL is pinned: the whole base*segments*eff_mult product is rounded
    once, never per segment. Then a tier discount is rounded once and subtracted.
    """
    band = BAND_MULT[time_band]
    day = DAY_FACTOR[day_type]
    raw_mult = band * day * Decimal(str(peak_demand_factor))
    eff_mult = max(MULT_FLOOR, min(MULT_CEIL, raw_mult))

    gross = _round_half_up(Decimal(base_rate_cents) * Decimal(num_segments) * eff_mult)

    discount_pct = TIER_DISCOUNT[member_tier]
    discount = _round_half_up(Decimal(gross) * discount_pct)

    quoted = gross - discount
    if quoted < 0:
        quoted = 0
    return quoted


def fb_tab_totals(line_items):
    """FB_TAB_TOTAL (SCAFFOLD §1.3 / PRD §3.9).

    Nested rounding order is pinned: gratuity is rounded on the full subtotal
    BEFORE tax is computed on (subtotal + rounded gratuity).
    """
    subtotal = sum(item["unit_price_cents"] * item["qty"] for item in line_items)
    gratuity = _round_half_up(Decimal(subtotal) * GRATUITY_PCT)
    tax = _round_half_up(Decimal(subtotal + gratuity) * TAX_PCT)
    total = subtotal + gratuity + tax
    return subtotal, gratuity, tax, total


def event_estimated_total(headcount_estimate, per_head_package_cents, bay_block_cents):
    """EVENT_PRICING provisional variant (integer arithmetic, no rounding)."""
    return headcount_estimate * per_head_package_cents + bay_block_cents


def event_final_total(actual_attendee_count, per_head_package_cents, bay_block_cents,
                      event_fb_total_cents):
    """EVENT_PRICING settled variant (integer arithmetic, no rounding)."""
    return (actual_attendee_count * per_head_package_cents
            + bay_block_cents + event_fb_total_cents)


def deposit_waterfall(deposit_cents, bay_block_cents, per_head_total_cents,
                      event_fb_total_cents):
    """DEPOSIT_WATERFALL (SCAFFOLD §1.3 / PRD §3.10).

    Buckets filled in pinned order [bay_block, per-head, F&B]; the leftover
    remaining deposit is the refund. Returns (deposit_applied, deposit_refund).
    """
    remaining = deposit_cents
    for bucket in (bay_block_cents, per_head_total_cents, event_fb_total_cents):
        applied = min(remaining, bucket)
        remaining -= applied
    deposit_applied = deposit_cents - remaining
    deposit_refund = remaining
    return deposit_applied, deposit_refund


def earn_provisional(net_cents):
    """EARN_PROVISIONAL: floor(net / 100), tier-agnostic."""
    return net_cents // POINTS_PER_CENT_DIVISOR


def earn_final(net_cents, member_tier):
    """EARN_FINAL: floor((net / 100) * tier_multiplier)."""
    value = (Decimal(net_cents) / Decimal(POINTS_PER_CENT_DIVISOR)) * TIER_MULT[member_tier]
    return int(value.to_integral_value(rounding="ROUND_FLOOR"))


def no_show_fee(quoted_price_cents):
    """NO_SHOW_FEE: round_half_up(quote * 0.50)."""
    return _round_half_up(Decimal(quoted_price_cents) * NO_SHOW_PCT)


def scoring(shots):
    """SCORING (SCAFFOLD §1.3 / PRD §3.6).

    base = sum of points; +STREAK_BONUS once if any run of >= STREAK_LEN
    consecutive shots (in seq order) each with points >= STREAK_MIN_POINTS.
    """
    base = sum(s["points"] for s in shots)
    run = 0
    has_streak = False
    for s in sorted(shots, key=lambda x: x["seq"]):
        if s["points"] >= STREAK_MIN_POINTS:
            run += 1
            if run >= STREAK_LEN:
                has_streak = True
        else:
            run = 0
    bonus = STREAK_BONUS if has_streak else 0
    return base + bonus, len(shots)
