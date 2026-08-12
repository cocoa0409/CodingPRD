"""Calculation rules (scaffold Table 3). All money is integer cents, round-half-up."""
from datetime import timedelta

import db
from util import D, rhu, add_months, whole_months_between

# --- trade_in_valuation ---
BASE_VALUE_CENTS = {'GRAND': 2800000, 'UPRIGHT': 900000, 'DIGITAL': 250000, 'HYBRID': 600000}
WEAR_PCT = {'EXCELLENT': '0.0', 'GOOD': '0.05', 'FAIR': '0.15', 'POOR': '0.30'}
AGE_DEPRECIATION_PER_YEAR = D('0.03')
AGE_FACTOR_FLOOR = D('0.40')
MARKET_ADJ_CLAMP = D('0.15')
OFFER_TTL_DAYS = 14


def trade_in_provisional(category, year_built, condition_grade):
    age = db.now().year - year_built
    age_factor = max(AGE_FACTOR_FLOOR, D(1) - AGE_DEPRECIATION_PER_YEAR * age)
    return rhu(D(BASE_VALUE_CENTS[category]) * age_factor * (D(1) - D(WEAR_PCT[condition_grade])))


def clamp_market_adj(pct):
    a = D(pct)
    if a < -MARKET_ADJ_CLAMP:
        a = -MARKET_ADJ_CLAMP
    if a > MARKET_ADJ_CLAMP:
        a = MARKET_ADJ_CLAMP
    return a


def trade_in_final(provisional_value_cents, reconditioning_cost_cents, adj):
    # Pinned order: provisional, then subtract reconditioning, then multiply, single rounding.
    return rhu((D(provisional_value_cents) - D(reconditioning_cost_cents)) * (D(1) + adj))


# --- consignment_payout ---
def consignment_payout(line_total_cents, consignor, instrument):
    if consignor['split_mode'] == 'GROSS_SPLIT':
        return rhu(D(line_total_cents) * (D(1) - D(consignor['commission_pct'])))
    # NET_SPLIT: recoverable costs deducted before commission
    return rhu((D(line_total_cents) - D(instrument['recoverable_costs_cents']))
               * (D(1) - D(consignor['commission_pct'])))


# --- institutional_bid_price ---
INSTITUTION_MULTIPLIER = {
    'EDUCATION': D('0.95'), 'GOVERNMENT': D('0.93'),
    'NONPROFIT': D('0.97'), 'CORPORATE': D('1.00'),
}


def bid_pricing(lines, customer):
    # Pinned order: tier first, institution multiplier second, ceiling min last.
    quantity = len(lines)
    subtotal = sum(l['unit_price_cents'] for l in lines)
    if quantity >= 11:
        tier = D('0.15')
    elif quantity >= 6:
        tier = D('0.12')
    elif quantity >= 3:
        tier = D('0.08')
    else:
        tier = D('0.0')
    after_tier = rhu(D(subtotal) * (D(1) - tier))
    mult = INSTITUTION_MULTIPLIER[customer['institution_type']]
    after_mult = rhu(D(after_tier) * mult)
    ceiling = customer.get('state_contract_ceiling_cents')
    total = min(after_mult, ceiling) if ceiling is not None else after_mult
    return {
        'quantity': quantity,
        'subtotal_cents': subtotal,
        'tier_discount_pct': float(tier),
        'institution_multiplier': float(mult),
        'ceiling_cents': ceiling,
        'total_cents': total,
    }


# --- order_total + delivery_fee ---
TRADE_IN_CAP_PCT = D('0.40')
BASE_FEE_CENTS = 15000
PER_STAIR_CENTS = 2500
TIER2_FEE_CENTS = 12000
TIER3_FEE_CENTS = 24000
CLIMATE_SURCHARGE_CENTS = 20000


def delivery_fee(distance_miles, stairs_count, climate_controlled_required):
    fee = BASE_FEE_CENTS + PER_STAIR_CENTS * stairs_count
    if distance_miles <= 25:
        fee += 0
    elif distance_miles <= 60:
        fee += TIER2_FEE_CENTS
    else:
        fee += TIER3_FEE_CENTS
    if climate_controlled_required:
        fee += CLIMATE_SURCHARGE_CENTS
    return fee


def order_pricing(items, appraisal, tax_rate, distance_miles, stairs_count, climate):
    # Pinned order: round each line first, then sum.
    line_totals = [rhu(D(it['unit_price_cents']) * (D(1) - D(it['discount_pct']))) for it in items]
    subtotal = sum(line_totals)
    if appraisal is None:
        credit = 0
    else:
        credit = min(appraisal['final_value_cents'], rhu(TRADE_IN_CAP_PCT * D(subtotal)))
    taxable_base = subtotal - credit
    tax = 0 if D(tax_rate) == 0 else rhu(D(taxable_base) * D(tax_rate))
    fee = delivery_fee(distance_miles, stairs_count, climate)
    total = subtotal - credit + fee + tax
    return {
        'line_totals': line_totals,
        'subtotal_cents': subtotal,
        'trade_in_credit_cents': credit,
        'tax_cents': tax,
        'delivery_fee_cents': fee,
        'total_cents': total,
    }


# --- financing_schedule ---
RTO_MONTHLY_RATE = D('0.012')
RTO_CREDIT_PCT = D('0.60')
RTO_CREDIT_CAP_MONTHS = 24
DEFAULT_THRESHOLD_MISSED = 3


def monthly_amount(program, principal_cents, apr, term_months):
    if program == 'STANDARD':
        r = D(apr) / D(12)
        if r == 0:
            return rhu(D(principal_cents) / D(term_months))
        return rhu(D(principal_cents) * r / (D(1) - (D(1) + r) ** (-term_months)))
    # RENT_TO_OWN: flat 1.2% monthly rent
    return rhu(D(principal_cents) * RTO_MONTHLY_RATE)


def purchase_credit(agreement):
    return rhu(RTO_CREDIT_PCT * D(agreement['monthly_amount_cents'])
               * D(min(agreement['payments_made'], RTO_CREDIT_CAP_MONTHS)))


def missed_payments(agreement):
    activated = agreement.get('activated_at')
    if activated is None:
        return max(0, 0 - agreement['payments_made'])
    months = whole_months_between(activated, db.now())
    return max(0, months - agreement['payments_made'])


# --- service_plan_price ---
TIER_PRICE_CENTS = {'BASIC': 30000, 'STANDARD': 55000, 'PREMIUM': 85000}
TIER_VISITS = {'BASIC': 2, 'STANDARD': 4, 'PREMIUM': 6}
LOYALTY_PCT = D('0.10')


def plan_loyalty(customer_id):
    """True when the customer holds any other plan in EXHAUSTED or CANCELLED."""
    for plan in db.stores['plans'].values():
        order = db.stores['orders'].get(plan['order_id'])
        if order and order['customer_id'] == customer_id and plan['status'] in ('EXHAUSTED', 'CANCELLED'):
            return True
    return False


def plan_price(tier, customer_id):
    base = TIER_PRICE_CENTS[tier]
    if plan_loyalty(customer_id):
        return rhu(D(base) * (D(1) - LOYALTY_PCT))
    return base


# --- warranty_coverage_end ---
BASE_TERM_MONTHS = 24
EXTENSION_MONTHS = 12
EXTENSION_WINDOW_DAYS = 30
REGISTRATION_WINDOW_DAYS = 60


def coverage_end(delivered_at, registered_at):
    end = add_months(delivered_at, BASE_TERM_MONTHS)
    if registered_at <= delivered_at + timedelta(days=EXTENSION_WINDOW_DAYS):
        end = add_months(end, EXTENSION_MONTHS)
    return end


# --- artist_payout ---
def artist_payout(artist_guarantee_cents, split_pct, gross_cents):
    return max(artist_guarantee_cents, rhu(D(split_pct) * D(gross_cents)))
