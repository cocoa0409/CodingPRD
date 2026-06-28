"""Calculation rules (SCAFFOLD §1.3, PRD §3.4, §3.7, §3.8, §3.12, §3.13, §3.16).

All money is integer cents. round_half_up is applied per-line before summing,
as pinned per calculation. decimal.Decimal is used for precision-sensitive math.
"""
from decimal import Decimal, ROUND_HALF_UP

# Calculation constants (SCAFFOLD §1.3)
BRIDE_SURCHARGE_MULT = Decimal("1.5")
TIER1_CEIL_CENTS = 50000
TIER2_CEIL_CENTS = 200000
DEP_PCT_LOW = Decimal("0.25")
DEP_PCT_MID = Decimal("0.30")
DEP_PCT_HIGH = Decimal("0.40")
TOUCH_UP_FACTOR = Decimal("0.5")
EXTENDED_STAY_BLOCK_CENTS = 8000
FULL_REFUND_MIN_HOURS = Decimal("720")
DEPOSIT_FORFEIT_MIN_HOURS = Decimal("72")


def round_half_up(value):
    """Round a Decimal to a whole integer using round-half-up (PRD §2.6)."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def per_face_subtotal(faces, hair_rate, makeup_rate):
    """Sum per-face base, applying bride surcharge per-line with per-line rounding.

    PRD §3.4: per-face base = hair (HAIR/BOTH) + makeup (MAKEUP/BOTH); bride lines
    are multiplied by 1.5 and rounded half-up on that line before summing.
    """
    subtotal = 0
    for f in faces:
        base = 0
        st = f["service_type"]
        if st in ("HAIR", "BOTH"):
            base += hair_rate
        if st in ("MAKEUP", "BOTH"):
            base += makeup_rate
        if f.get("is_bride"):
            base = round_half_up(Decimal(base) * BRIDE_SURCHARGE_MULT)
        subtotal += base
    return subtotal


def travel_fee(travel_rate_per_km, distance_km):
    """Travel fee = travel_rate_per_km * venue_distance_km, round half-up (PRD §3.4)."""
    return round_half_up(Decimal(str(travel_rate_per_km)) * Decimal(str(distance_km)))


def quote_total(faces, artist, distance_km):
    """Forward-looking estimate over PENDING+CONFIRMED faces at selected artist rates."""
    sub = per_face_subtotal(faces, artist["hair_rate_per_face_cents"],
                            artist["makeup_rate_per_face_cents"])
    fee = travel_fee(artist["travel_rate_per_km_cents"], distance_km)
    return sub + fee


def contract_total(faces, contract, distance_km):
    """Final baseline over CONFIRMED faces priced at pinned rates (PRD §3.4)."""
    sub = per_face_subtotal(faces, contract["pinned_hair_rate_cents"],
                            contract["pinned_makeup_rate_cents"])
    fee = travel_fee(contract["pinned_travel_rate_per_km_cents"], distance_km)
    return sub + fee


def deposit_split(contracted_total):
    """Tiered deposit percentage (PRD §3.7). Half-open boundaries [lo, hi)."""
    t = contracted_total
    if t < TIER1_CEIL_CENTS:           # T < 50000
        pct = DEP_PCT_LOW
    elif t < TIER2_CEIL_CENTS:         # 50000 <= T < 200000
        pct = DEP_PCT_MID
    else:                              # T >= 200000
        pct = DEP_PCT_HIGH
    return round_half_up(Decimal(t) * pct)


def touch_up_amount(makeup_rate, quantity):
    """TOUCH_UP: round half-up per-unit (makeup_rate * 0.5) BEFORE multiplying by qty."""
    unit = round_half_up(Decimal(makeup_rate) * TOUCH_UP_FACTOR)
    return unit * quantity


def extended_stay_amount(quantity):
    """EXTENDED_STAY: flat 8000 cents per 30-min block * quantity (PRD §3.13)."""
    return EXTENDED_STAY_BLOCK_CENTS * quantity


def throughput_capacity(lead_cap, asst_cap, window_start, window_end):
    """floor((lead_cap + asst_cap) * window_hours) (PRD §3.12)."""
    window_hours = Decimal(str((window_end - window_start).total_seconds())) / Decimal("3600")
    capacity = (Decimal(lead_cap + asst_cap) * window_hours)
    # floor to whole faces
    return int(capacity.to_integral_value(rounding="ROUND_FLOOR"))


def hours_before(event_date_utc, clock_now):
    """Hours remaining, fractional (PRD §3.16)."""
    return Decimal(str((event_date_utc - clock_now).total_seconds())) / Decimal("3600")


def resolve_refund_tier(reason, hours):
    """Resolve refund tier from reason + hours (PRD §3.16). Lower bounds inclusive."""
    if reason == "WEATHER":
        return "FULL_REFUND"
    if hours >= FULL_REFUND_MIN_HOURS:        # >= 720
        return "FULL_REFUND"
    if hours >= DEPOSIT_FORFEIT_MIN_HOURS:    # >= 72, < 720
        return "DEPOSIT_FORFEIT"
    return "FULL_FORFEIT"                      # < 72
