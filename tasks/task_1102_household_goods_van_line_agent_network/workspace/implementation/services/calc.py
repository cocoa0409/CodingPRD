from datetime import timedelta
from decimal import Decimal

from util import D, rhu, to_cwt

CWT_LBS = 100
ESTIMATE_VALIDITY_DAYS = 30
NON_BINDING_CAP_PCT = Decimal('1.10')
SIT_MAX_DAYS = 180
OT_THRESHOLD_HOURS = 8
OT_MULTIPLIER = Decimal('1.5')
RELEASED_VALUE_CENTS_PER_LB = 60
FVP_RATE_PER_100_CENTS = 85
DEDUCTIBLE_FACTOR = {0: Decimal('1.00'), 25000: Decimal('0.85'), 50000: Decimal('0.70')}
ROLE_BASE_PCT = {
    'BOOKING': Decimal('0.10'),
    'ORIGIN': Decimal('0.20'),
    'HAULING': Decimal('0.54'),
    'DESTINATION': Decimal('0.10'),
}
TIER_BONUS = {
    'STANDARD': Decimal('0.00'),
    'PREFERRED': Decimal('0.01'),
    'PREMIER': Decimal('0.02'),
}
VAN_LINE_FLOOR_PCT = Decimal('0.04')
ARBITRATION_FILING_FEE_CENTS = 25000
MAX_CLAIM_ROUNDS = 3
CLAIM_WINDOW_DAYS = 270
MEDIATION_COOLING_OFF_DAYS = 14
CREW_WINDOW_EXTRA_DAYS = 30

SPREAD_TABLE = [
    (0, 500, 2, 2),
    (500, 1500, 4, 3),
    (1500, 2500, 6, 4),
    (2500, 999999, 8, 5),
]


def select_band(tariff, mileage):
    bands = sorted(tariff['mileage_bands'], key=lambda b: b['min_miles'])
    for i, b in enumerate(bands):
        last = i == len(bands) - 1
        if b['min_miles'] <= mileage < b['max_miles']:
            return b
        if last and mileage == b['max_miles']:
            return b
    return None


def linehaul_cents(tariff, mileage, weight_lbs):
    cwt = to_cwt(weight_lbs)
    band = select_band(tariff, mileage)
    if band is None:
        return 0
    return rhu(D(cwt) * D(tariff['base_rate_cents_per_cwt']) * D(band['rate_multiplier']))


def fuel_cents(linehaul, tariff):
    return rhu(D(linehaul) * D(tariff['fuel_surcharge_pct']))


def valuation_premium(coverage_type, declared_value_cents, deductible_cents):
    if coverage_type == 'RELEASED_VALUE':
        return 0
    units = -(-int(declared_value_cents) // 10000)
    return rhu(D(units) * D(FVP_RATE_PER_100_CENTS) * DEDUCTIBLE_FACTOR[deductible_cents])


def spread_window(mileage, pickup_date):
    for i, (lo, hi, transit, spread) in enumerate(SPREAD_TABLE):
        last = i == len(SPREAD_TABLE) - 1
        if lo <= mileage < hi or (last and mileage == hi):
            earliest = pickup_date + timedelta(days=transit)
            return earliest, earliest + timedelta(days=spread)
    return pickup_date, pickup_date


def sit_accrual(stored_weight_cwt, daily_rate, days_stored):
    billable = min(days_stored, SIT_MAX_DAYS)
    if billable < 0:
        billable = 0
    return stored_weight_cwt * daily_rate * billable


def sit_days(checked_in_at, end_dt):
    delta = (end_dt - checked_in_at).total_seconds()
    days = int(delta // 86400)
    return days


def crew_invoice(hourly_rate_cents, start_hour, end_hour, crew_size):
    labor_hours = end_hour - start_hour
    regular = min(labor_hours, OT_THRESHOLD_HOURS)
    overtime = max(0, labor_hours - OT_THRESHOLD_HOURS)
    per_worker = regular * hourly_rate_cents + rhu(D(overtime) * D(hourly_rate_cents) * OT_MULTIPLIER)
    return labor_hours, crew_size * per_worker


def split_pct_for(role, commission_tier):
    return ROLE_BASE_PCT[role] + TIER_BONUS[commission_tier]


def final_charges(order, tariff, accepted_estimate, locked_premium_cents):
    """Returns dict with linehaul, fuel, final, due, deferred."""
    if order['pricing_mode'] == 'BINDING':
        line = accepted_estimate['linehaul_cents']
        fuel = accepted_estimate['fuel_surcharge_cents']
        final = accepted_estimate['estimated_charges_cents']
        due = final
    else:
        line = linehaul_cents(tariff, order['mileage'], order['actual_weight_lbs'])
        fuel = fuel_cents(line, tariff)
        final = line + fuel + locked_premium_cents + accepted_estimate['packing_services_cents']
        cap = rhu(NON_BINDING_CAP_PCT * D(accepted_estimate['estimated_charges_cents']))
        due = min(final, cap)
    return {
        'linehaul_cents': line,
        'fuel_surcharge_cents': fuel,
        'final_charges_cents': final,
        'delivery_amount_due_cents': due,
        'deferred_balance_cents': final - due,
    }


def waterfall(linehaul_revenue_cents, split_pcts, locked_premium_cents):
    """split_pcts: dict role -> Decimal effective pct (frozen snapshot).
    Returns (shares dict, van_line_share_cents)."""
    L = linehaul_revenue_cents
    shares = {}
    for role in ('BOOKING', 'ORIGIN', 'HAULING', 'DESTINATION'):
        shares[role] = rhu(D(L) * split_pcts[role])
    van_line = L - (shares['BOOKING'] + shares['ORIGIN'] + shares['HAULING'] + shares['DESTINATION'])
    floor = rhu(D(L) * VAN_LINE_FLOOR_PCT)
    if van_line < floor:
        deficit = floor - van_line
        shares['HAULING'] -= deficit
        van_line = floor
    van_line += locked_premium_cents
    return shares, van_line


def claim_settlement_cap(claim, coverage):
    if coverage['coverage_type'] == 'RELEASED_VALUE':
        liability_cap = RELEASED_VALUE_CENTS_PER_LB * claim['claimed_item_weight_lbs']
    else:
        liability_cap = max(coverage['declared_value_cents'] - coverage['deductible_cents'], 0)
    return min(claim['claimed_amount_cents'], liability_cap)


def arbitration_fee_allocation(decision_amount_cents, subject_amount_cents):
    d = int(decision_amount_cents)
    s = int(subject_amount_cents)
    if d * 5 >= s * 4:
        return 'RESPONDENT'
    if d * 5 <= s * 1:
        return 'FILER'
    return 'SPLIT'


def quality_score_for(chargeback_total_cents):
    return max(0, 100 - (int(chargeback_total_cents) // 10000))
