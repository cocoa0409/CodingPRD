"""All monetary calculations, implemented exactly per PRD §3 / SCAFFOLD §1.3.

All money is rounded to 2dp, round-half-up, via util.round2 (Decimal). Per-
component rounding order is pinned where the formula pins it.
"""
from decimal import Decimal, ROUND_HALF_UP
from util import round2, parse_iso_date

# Per-day ticket prices. NOTE: SCAFFOLD/PRD reference PER_DAY_PRICE[ticket_type]
# for face_value but do not state the dollar values in prose. The design YAMLs
# (test ground truth) imply GA=80/day (240=80*3, 160=80*2) and VIP=200/day
# (400=200*2). These are used here.
PER_DAY_PRICE = {"GA": 80.00, "VIP": 200.00}

# booth_fee_calc constants (SCAFFOLD §1.3)
TIER_RATE = {"STANDARD": 150.00, "PREMIUM": 300.00, "FOOD": 450.00}
ZONE_SURCHARGE = {"A": 0.20, "B": 0.10, "C": 0.00}
POWER_DAILY = 40.00


def ticket_face_value(ticket_type, day_count):
    return round2(PER_DAY_PRICE[ticket_type] * day_count)


def booth_fee_calc(booth_tier, day_count, zone_code, power_addon):
    """location_fee rounded FIRST, then power_fee added and rounded again."""
    base = TIER_RATE[booth_tier] * day_count
    surcharge = base * ZONE_SURCHARGE[zone_code]
    location_fee = round2(base + surcharge)
    power_fee = round2(POWER_DAILY * day_count) if power_addon else 0.00
    return round2(location_fee + power_fee)


def weather_prorata_refund(face_value, current_festival_day, total_days):
    """Forward-looking: refund = face * (remaining / total_days). No fee."""
    elapsed = current_festival_day
    remaining = max(0, total_days - elapsed)
    amount = round2(face_value * (remaining / total_days))
    return amount, 0.00


def voluntary_tiered_refund(face_value, today_date, start_date):
    """Fee tiered by whole days between today and start_date (>= thresholds)."""
    days_before = (start_date - today_date).days
    if days_before >= 14:
        fee_pct = 0.00
    elif days_before >= 7:
        fee_pct = 0.25
    elif days_before >= 1:
        fee_pct = 0.50
    else:
        fee_pct = 1.00
    fee_withheld = round2(face_value * fee_pct)
    refund_amount = round2(face_value - fee_withheld)
    return refund_amount, fee_withheld


def wristband_cashout(pre_balance, cashout_pct):
    fee = round2(pre_balance * cashout_pct)
    refund_amount = round2(pre_balance - fee)
    return refund_amount, fee


def vendor_settlement_payout(spend_amounts, commission_pct, booth_fee, fee_paid):
    """gross = round2(SUM(spend)); commission on summed gross; sum-then-round."""
    gross = round2(sum(spend_amounts)) if spend_amounts else 0.00
    commission = round2(gross * commission_pct)
    net = round2(gross - commission)
    outstanding = max(0.0, round2((booth_fee or 0.0) - (fee_paid or 0.0)))
    payout = round2(net - outstanding)
    return payout
