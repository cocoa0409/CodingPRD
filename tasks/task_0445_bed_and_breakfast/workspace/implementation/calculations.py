"""Money & time calculations (PRD §2.6, §3.2-§3.5, §3.9; SCAFFOLD §1.3).

All money is integer cents. Two rounding disciplines (PRD §2.6):
  - per-night room charge: FLOOR to whole cents per night, then sum (round-then-sum).
  - lodging tax + percentage deposit/refund: ROUND HALF UP to whole cents.
Where a rounding and a floor/cap both apply, rounding happens first.
"""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR

BPS_DENOM = 10000
DEFAULT_MULTIPLIER_BPS = 10000
DIRECT_DEPOSIT_BPS = 3000  # 30%

# cancellation_refund tiers (SCAFFOLD §1.3 / PRD §3.5)
TIER_FULL_DAYS = 14
TIER_HALF_DAYS = 7
TIER_TOKEN_DAYS = 1
FULL_BPS = 10000
HALF_BPS = 5000
TOKEN_BPS = 1000


def parse_date(s):
    return datetime.strptime(s, "%Y-%m-%d").date()


def date_diff_days(later_s, earlier_s):
    return (parse_date(later_s) - parse_date(earlier_s)).days


def floor_bps(cents, multiplier_bps):
    """floor(cents * multiplier_bps / 10000) — per-night room charge step."""
    val = (Decimal(cents) * Decimal(multiplier_bps) / Decimal(BPS_DENOM)).to_integral_value(
        rounding=ROUND_FLOOR
    )
    return int(val)


def round_half_up_bps(cents, rate_bps):
    """round_half_up(cents * rate_bps / 10000) — tax / deposit / refund percentage."""
    val = (Decimal(cents) * Decimal(rate_bps) / Decimal(BPS_DENOM)).to_integral_value(
        rounding=ROUND_HALF_UP
    )
    return int(val)


def occupied_nights(checkin_date, checkout_date):
    """Half-open [checkin_date, checkout_date): the checkout date itself is not occupied."""
    start = parse_date(checkin_date)
    end = parse_date(checkout_date)
    out = []
    d = start
    while d < end:
        out.append(d)
        d = d + timedelta(days=1)
    return out


def select_period_for_night(night, rate_periods):
    """Pick the RatePeriod whose inclusive [start_date, end_date] window contains
    `night`. When several contain it, choose the HIGHEST rate_multiplier_bps, tie
    broken toward the earlier created_at (then insertion seq). Returns the period
    dict, or None if no period contains the night.
    (PRD §3.2 / SCAFFOLD calc room_charge.)
    """
    candidates = []
    for rp in rate_periods:
        start = parse_date(rp["start_date"])
        end = parse_date(rp["end_date"])
        if start <= night <= end:
            candidates.append(rp)
    if not candidates:
        return None
    # Highest multiplier; tie -> earliest created_at, then earliest insertion seq.
    candidates.sort(key=lambda rp: (-rp["rate_multiplier_bps"], rp["created_at"], rp["_seq"]))
    return candidates[0]


def per_night_charges(room, checkin_date, checkout_date, rate_periods):
    """List of floored per-night charges in ascending date order (ORDER PINNED)."""
    base = room["base_rate_cents"]
    charges = []
    for night in occupied_nights(checkin_date, checkout_date):
        period = select_period_for_night(night, rate_periods)
        mult = period["rate_multiplier_bps"] if period else DEFAULT_MULTIPLIER_BPS
        charges.append(floor_bps(base, mult))
    return charges


def compute_room_charge(room, checkin_date, checkout_date, rate_periods):
    return sum(per_night_charges(room, checkin_date, checkout_date, rate_periods))


def compute_package_charge(package, nights):
    if package is None:
        return 0
    return package["flat_add_cents"] + package["per_night_add_cents"] * nights


def compute_taxable_base(room, room_charge, package, package_charge):
    base = 0
    if room["is_taxable"]:
        base += room_charge
    if package is not None and package["is_taxable"]:
        base += package_charge
    return base


def compute_lodging_tax(taxable_base, lodging_tax_rate_bps):
    return round_half_up_bps(taxable_base, lodging_tax_rate_bps)


def compute_deposit_due(channel, total_cents, first_night_cents):
    """PRD §3.3:
       DIRECT: round_half_up(total * 30%), then max with first-night floor.
       OTA: full total (first-night floor is inert).
    """
    if channel == "DIRECT":
        amount = round_half_up_bps(total_cents, DIRECT_DEPOSIT_BPS)
    else:  # OTA
        amount = total_cents
    # First-night floor applied AFTER rounding.
    return max(amount, first_night_cents)


def refund_tier_bps(days_before):
    """SCAFFOLD §1.3 cancellation_refund tier table; >= comparisons."""
    if days_before >= TIER_FULL_DAYS:
        return FULL_BPS
    if days_before >= TIER_HALF_DAYS:
        return HALF_BPS
    if days_before >= TIER_TOKEN_DAYS:
        return TOKEN_BPS
    return 0  # days_before == 0


def compute_cancellation_refund(channel, deposit_paid_cents, days_before):
    """PRD §3.5: gross = round_half_up(deposit_paid * tier%); OTA override:
       an OTA booking cancelled with < 14 days before arrival refunds nothing.
       days_before is clamped to >= 0 by caller.
    """
    if days_before < 0:
        days_before = 0
    pct_bps = refund_tier_bps(days_before)
    gross = round_half_up_bps(deposit_paid_cents, pct_bps)
    if channel == "OTA" and days_before < TIER_FULL_DAYS:
        gross = 0
    return gross
