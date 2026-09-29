"""Every arithmetic rule of the system (PRD 2.5, 2.11, 3.1, 3.3, 3.5, 3.6, 3.9).

All money is an integer number of cents; all rates are integer basis points.
Division is exact integer arithmetic -- never float -- and rounds half up
(away from zero).  The pinned rounding locations are documented per function.
"""
from store import db

CABIN_UPLIFT_BP = {'ECONOMY': 0, 'PREMIUM': 1500, 'BUSINESS': 3000}
ZONE_MULTIPLIER_BP = {'FWD': 13000, 'MID': 10000, 'AFT': 9000,
                      'EXIT_ROW': 16000, 'BULKHEAD': 14000}
DEMAND_TIER_MULTIPLIER_BP = {'LOW': 10000, 'MID': 11000, 'HIGH': 12500}
TOUCHPOINT_MULTIPLIER_BP = {'BOOKING': 10000, 'CHECKIN': 11000, 'INFLIGHT': 12500}
TAX_RATE_BP = {'TAXABLE_TRANSPORT': 750, 'TAXABLE_SERVICE': 400, 'EXEMPT': 0}
CATEGORY_PRIORITY_ORDER = ['BAGGAGE', 'SEAT', 'CHANGE', 'BOARDING', 'ONBOARD',
                           'AIR_TRANSPORT']
BASE_WTP_BP = 10000
WTP_LF_SLOPE_BP = 40
WTP_SCARCITY_SLOPE_BP = 60
WTP_MIN_BP = 6000
WTP_MAX_BP = 16000
PRICE_FLOOR_BP = 7000
PRICE_CAP_BP = 18000
MAX_OFFERS_PER_SESSION = 3
OFFER_TTL_MINUTES = 60
OFFER_COOLOFF_MINUTES = 30
IROPS_CHANGE_WAIVER_MIN_DELAY_MINUTES = 180


def rhu(num, den):
    """Round half up: nearest integer, exact halves away from zero."""
    if den < 0:
        num, den = -num, -den
    if num >= 0:
        return (2 * num + den) // (2 * den)
    return -((-2 * num + den) // (2 * den))


def row_band_adjust_cents(row_start):
    if row_start <= 5:
        return 1500
    if row_start <= 15:
        return 500
    return 0


def demand_tier(booked_load_factor_pct):
    if booked_load_factor_pct >= 80:
        return 'HIGH'
    if booked_load_factor_pct >= 60:
        return 'MID'
    return 'LOW'


# --------------------------------------------------------------------------
# fare_family_fee_fingerprint
# --------------------------------------------------------------------------
def active_attributes(family_id):
    rows = [a for a in db.attributes.values()
            if a['fare_family_id'] == family_id and a['attribute_state'] == 'ACTIVE']
    return sorted(rows, key=lambda a: db.products[a['ancillary_product_id']]['sku'])


def fee_fingerprint(family):
    parts = []
    for attr in active_attributes(family['id']):
        product = db.products[attr['ancillary_product_id']]
        parts.append('%s:%s:%d:%d' % (product['sku'], attr['inclusion'],
                                      attr['included_quantity'],
                                      attr['effective_unit_cents']))
    return '%s|%d|%s' % (family['code'], family['revision_no'], ';'.join(parts))


# --------------------------------------------------------------------------
# fare_family_bundle_valuation -- override_basis and list_basis
# --------------------------------------------------------------------------
def effective_unit_cents(attr):
    """override_price_cents when not null, else the product's list price."""
    if attr.get('override_price_cents') is not None:
        return attr['override_price_cents']
    return db.products[attr['ancillary_product_id']]['list_price_cents']


def attr_value(unit_cents, quantity, cabin_class):
    """One rounding per attribute -- never sum the un-rounded products."""
    uplift = CABIN_UPLIFT_BP[cabin_class]
    return rhu(unit_cents * quantity * (10000 + uplift), 10000)


def bundle_valuation(family, basis='override_basis'):
    """Returns (unbundled_value_cents, {attribute_id: attr_value_cents})."""
    total = 0
    per_attr = {}
    for attr in active_attributes(family['id']):
        if basis == 'list_basis':
            unit = db.products[attr['ancillary_product_id']]['list_price_cents']
        else:
            unit = effective_unit_cents(attr)
        value = attr_value(unit, attr['included_quantity'], family['cabin_class'])
        per_attr[attr['id']] = value
        total += value
    return total, per_attr


def bundle_discount_bp(a_la_carte_total_cents, bundle_price_cents,
                       unbundled_value_cents):
    if unbundled_value_cents == 0:
        return 0
    return rhu((a_la_carte_total_cents - bundle_price_cents) * 10000,
               a_la_carte_total_cents)


# --------------------------------------------------------------------------
# seat_segment_effective_price -- exactly one rounding, at the very end
# --------------------------------------------------------------------------
def seat_segment_effective_price(segment, tier):
    zone_base = segment['base_price_cents'] + row_band_adjust_cents(segment['row_start'])
    zone_mult = ZONE_MULTIPLIER_BP[segment['zone']]
    demand_mult = DEMAND_TIER_MULTIPLIER_BP[tier]
    return rhu(zone_base * zone_mult * demand_mult, 100000000)


# --------------------------------------------------------------------------
# tax (PRD 2.11)
# --------------------------------------------------------------------------
def tax_cents(gross_cents, tax_treatment):
    rate = TAX_RATE_BP[tax_treatment]
    magnitude = rhu(abs(gross_cents) * rate, 10000)
    return -magnitude if gross_cents < 0 else magnitude


# --------------------------------------------------------------------------
# ancillary_offer_dynamic_price -- three sequential roundings, then a clamp
# --------------------------------------------------------------------------
def wtp_residual_inventory(open_segments):
    """RESIDUAL_INVENTORY variant: physical seat scarcity, ignoring the feed."""
    basis_total = sum(s['total_seats'] for s in open_segments)
    basis_available = sum(s['available_seats'] for s in open_segments)
    sold_pct = rhu((basis_total - basis_available) * 100, basis_total)
    return BASE_WTP_BP + WTP_SCARCITY_SLOPE_BP * (sold_pct - 50)


def wtp_elastic(flight):
    """WTP_ELASTIC variant: the revenue-management demand feed."""
    score = BASE_WTP_BP + WTP_LF_SLOPE_BP * (flight['booked_load_factor_pct'] - 50)
    score += rhu(flight['demand_index_bp'] * WTP_SCARCITY_SLOPE_BP, 10000)
    return score


def clamp_wtp(raw_score):
    if raw_score < WTP_MIN_BP:
        return WTP_MIN_BP
    if raw_score > WTP_MAX_BP:
        return WTP_MAX_BP
    return raw_score


def dynamic_price(list_price_cents, wtp_score_bp, touchpoint, markup_bp):
    first = rhu(list_price_cents * wtp_score_bp, 10000)
    second = rhu(first * TOUCHPOINT_MULTIPLIER_BP[touchpoint], 10000)
    third = rhu(second * (10000 + markup_bp), 10000)
    floor = rhu(list_price_cents * PRICE_FLOOR_BP, 10000)
    cap = rhu(list_price_cents * PRICE_CAP_BP, 10000)
    if third < floor:
        return floor
    if third > cap:
        return cap
    return third


def expected_value(offered_price_cents, wtp_score_bp):
    return rhu(offered_price_cents * wtp_score_bp, 10000)


# --------------------------------------------------------------------------
# channel_settlement_total -- the pinned seven-step sequence (PRD 3.9)
# --------------------------------------------------------------------------
def settlement(fare_component_cents, ancillary_gross_cents, commission_bp):
    """Returns (commission_cents, incentive_credit_cents, total_cents)."""
    if fare_component_cents is None:
        return 0, 0, 0
    subtotal = fare_component_cents + ancillary_gross_cents
    commission_cents = rhu(subtotal * commission_bp, 10000)
    provisional = subtotal + commission_cents
    if provisional >= 50000:
        tier_bp = 300
    elif provisional >= 30000:
        tier_bp = 150
    else:
        tier_bp = 0
    incentive_credit_cents = rhu(provisional * tier_bp, 10000)
    return commission_cents, incentive_credit_cents, provisional - incentive_credit_cents


# --------------------------------------------------------------------------
# ancillary_revenue_split -- the ticketing allocation (PRD 3.5)
# --------------------------------------------------------------------------
def allocation_buckets(family, amount_cents):
    """Floor pass, one-cent remainder pass, then tax.  Returns a list of dicts
    in category-priority order, each carrying category, gross_cents and the
    contributing attribute (None for AIR_TRANSPORT)."""
    weights = {}
    contributors = {}
    for attr in active_attributes(family['id']):
        if attr['inclusion'] != 'INCLUDED':
            continue
        product = db.products[attr['ancillary_product_id']]
        category = product['category']
        weights[category] = weights.get(category, 0) + attr['attr_value_cents']
        current = contributors.get(category)
        if current is None or product['sku'] < db.products[current['ancillary_product_id']]['sku']:
            contributors[category] = attr
    weights['AIR_TRANSPORT'] = family['base_fare_cents']
    total_weight = family['a_la_carte_total_cents']

    buckets = []
    for category in CATEGORY_PRIORITY_ORDER:
        weight = weights.get(category, 0)
        if weight > 0:
            buckets.append({'category': category, 'weight': weight,
                            'attr': contributors.get(category),
                            'gross_cents': 0})
    if not buckets or total_weight <= 0:
        return []
    # pass one: floor
    for bucket in buckets:
        bucket['gross_cents'] = (amount_cents * bucket['weight']) // total_weight
    remainder = amount_cents - sum(b['gross_cents'] for b in buckets)
    # pass two: one cent at a time, weight DESC then category-priority index ASC
    order = sorted(buckets,
                   key=lambda b: (-b['weight'],
                                  CATEGORY_PRIORITY_ORDER.index(b['category'])))
    index = 0
    while remainder > 0 and order:
        order[index % len(order)]['gross_cents'] += 1
        remainder -= 1
        index += 1
    return buckets
