"""Business logic: pricing engine, credit posture, temporal rules.

All money is integer cents. The two steps that can produce a fractional cent
(per-line promo allowance, fuel surcharge) round half-up to integer cents.
"""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from db import STORE, touch, logical_now

CASE_PICK_FEE_CENTS = 12
SPLIT_PICK_FEE_CENTS = 45
MIN_DROP_THRESHOLD_CENTS = 50000
MIN_DROP_FEE_CENTS = 2500

SLOT_BASE_CENTS = 50000
SLOT_PER_UNIT_CENTS = 250
SLOT_CAP_CENTS = 150000

DAY_INDEX = {'MON': 0, 'TUE': 1, 'WED': 2, 'THU': 3, 'FRI': 4}
OPEN_INVOICE_STATUSES = ('OPEN', 'PARTIALLY_PAID', 'PAST_DUE')
PIPELINE_ORDER_STATUSES = ('SUBMITTED', 'ASSIGNED', 'CLOSED')

TERMS_DAYS = {'COD': 0, 'NET7': 7, 'NET14': 14}


def round_half_up_cents(value):
    return int(Decimal(value).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def parse_date(s):
    return datetime.strptime(s, '%Y-%m-%d').date()


# ---------------------------------------------------------------- clock/temporal

def next_delivery_date(delivery_day, now_dt):
    """Next occurrence of the retailer's delivery day on or after now (date)."""
    target = DAY_INDEX[delivery_day]
    d = now_dt.date()
    delta = (target - d.weekday()) % 7
    return d + timedelta(days=delta)


def cutoff_instant(delivery_date, cutoff_hours):
    """Midnight at the start of the delivery day minus cutoff_hours_before."""
    midnight = datetime(delivery_date.year, delivery_date.month, delivery_date.day,
                        tzinfo=timezone.utc)
    return midnight - timedelta(hours=cutoff_hours)


def promo_status(promo, now_dt=None):
    now_dt = now_dt or logical_now()
    d = now_dt.date()
    if d < parse_date(promo['start_date']):
        return 'SCHEDULED'
    if d > parse_date(promo['end_date']):
        return 'EXPIRED'
    return 'ACTIVE'


def find_off_invoice_promo(product_id, delivery_date):
    ds = delivery_date.isoformat() if isinstance(delivery_date, date) else delivery_date
    for p in STORE['promo_events'].values():
        if (p['product_id'] == product_id and p['promo_type'] == 'OFF_INVOICE'
                and p['start_date'] <= ds <= p['end_date']):
            return p
    return None


def find_fuel_rate_for_date(delivery_date):
    dd = parse_date(delivery_date) if isinstance(delivery_date, str) else delivery_date
    for r in STORE['fuel_surcharge_rates'].values():
        ws = parse_date(r['week_start_date'])
        if ws <= dd <= ws + timedelta(days=6):
            return r
    return None


def fuel_tier_rate(doe_index_usd):
    idx = Decimal(str(doe_index_usd))
    if idx < Decimal('3.50'):
        return Decimal('0')
    if idx < Decimal('4.00'):
        return Decimal('0.025')
    return Decimal('0.040')


# ---------------------------------------------------------------- orders/pricing

def order_lines(order_id):
    return [l for l in STORE['order_lines'].values() if l['order_id'] == order_id]


def tobacco_pack_count(lines, delivered=False):
    """Ordered (or delivered) tobacco packs: split eaches plus full cases
    contributing cases_qty * case_pack_units."""
    packs = 0
    for line in lines:
        product = STORE['products'][line['product_id']]
        if product['is_tobacco']:
            c = line['delivered_cases'] if delivered else line['cases_qty']
            s = line['delivered_split_units'] if delivered else line['split_units_qty']
            packs += s + c * product['case_pack_units']
    return packs


def tax_stamp_cost(supply, packs):
    """stamp charge = max(packs*rate, min_charge); rolls = ceil(packs/packs_per_roll);
    total = charge + rolls * handling fee."""
    stamp_charge = max(packs * supply['stamp_rate_cents_per_pack'],
                       supply['min_charge_cents'])
    ppr = supply['packs_per_roll']
    rolls = (packs + ppr - 1) // ppr if packs > 0 else 0
    return stamp_charge + rolls * supply['handling_fee_per_roll_cents'], rolls


def find_stamp_supply(jurisdiction_code):
    for s in STORE['tax_stamp_supplies'].values():
        if s['jurisdiction_code'] == jurisdiction_code:
            return s
    return None


def compute_pricing(lines, delivery_date, delivered=False):
    """Per-line merch + promo (round each line first, then sum), order-level
    merch subtotal, promo allowance, pick fee, and total case weight."""
    merch = 0
    promo = 0
    total_cases = 0
    total_splits = 0
    weight = 0
    line_values = {}
    for line in lines:
        product = STORE['products'][line['product_id']]
        c = line['delivered_cases'] if delivered else line['cases_qty']
        s = line['delivered_split_units'] if delivered else line['split_units_qty']
        lm = c * product['case_cost_cents'] + s * product['unit_cost_cents']
        pr = find_off_invoice_promo(line['product_id'], delivery_date)
        lp = 0
        if pr is not None:
            lp = round_half_up_cents(
                Decimal(lm) * Decimal(pr['discount_pct_bps']) / Decimal(10000))
        line_values[line['id']] = {'line_merch_cents': lm, 'line_promo_cents': lp}
        merch += lm
        promo += lp
        total_cases += c
        total_splits += s
        weight += c * product['weight_lbs_per_case']
    pick = total_cases * CASE_PICK_FEE_CENTS + total_splits * SPLIT_PICK_FEE_CENTS
    return {
        'merch': merch,
        'promo': promo,
        'pick': pick,
        'weight': weight,
        'line_values': line_values,
    }


def slotting_fee(product):
    raw = SLOT_BASE_CENTS + product['case_pack_units'] * SLOT_PER_UNIT_CENTS
    return min(raw, SLOT_CAP_CENTS)


# ---------------------------------------------------------------- credit posture

def compute_credit_status(retailer):
    if retailer['_manual_hold']:
        return 'CREDIT_HOLD'
    for inv in STORE['invoices'].values():
        if (inv['retailer_id'] == retailer['id'] and inv['status'] == 'PAST_DUE'
                and inv['balance_cents'] > 0):
            return 'CREDIT_HOLD'
    if retailer['exposure_forward_cents'] > retailer['credit_limit_cents']:
        return 'CREDIT_HOLD'
    return 'GOOD_STANDING'


def refresh_retailer(retailer):
    """Recompute ar_balance_cents and exposure_forward_cents from source records,
    then re-evaluate credit_status. Touches the retailer once if anything changed."""
    rid = retailer['id']
    ar = sum(inv['balance_cents'] for inv in STORE['invoices'].values()
             if inv['retailer_id'] == rid and inv['status'] in OPEN_INVOICE_STATUSES)
    fwd = ar + sum(o['provisional_total_cents'] for o in STORE['purchase_orders'].values()
                   if o['retailer_id'] == rid and o['status'] in PIPELINE_ORDER_STATUSES)
    changed = False
    if retailer['ar_balance_cents'] != ar:
        retailer['ar_balance_cents'] = ar
        changed = True
    if retailer['exposure_forward_cents'] != fwd:
        retailer['exposure_forward_cents'] = fwd
        changed = True
    status = compute_credit_status(retailer)
    if retailer['credit_status'] != status:
        retailer['credit_status'] = status
        changed = True
    if changed:
        touch(retailer)


def apply_past_due(now_dt):
    """Clock advance: OPEN invoices whose due_date has passed with a positive
    balance transition to PAST_DUE; affected retailers are re-evaluated."""
    today = now_dt.date()
    affected = set()
    for inv in STORE['invoices'].values():
        if (inv['status'] == 'OPEN' and inv['balance_cents'] > 0
                and parse_date(inv['due_date']) < today):
            inv['status'] = 'PAST_DUE'
            touch(inv)
            affected.add(inv['retailer_id'])
    for rid in affected:
        refresh_retailer(STORE['retailers'][rid])


def credit_summary(retailer):
    today = logical_now().date()
    current = 0
    due_1_7 = 0
    due_8_plus = 0
    for inv in STORE['invoices'].values():
        if inv['retailer_id'] != retailer['id'] or inv['status'] not in OPEN_INVOICE_STATUSES:
            continue
        days = (today - parse_date(inv['due_date'])).days
        if days <= 0:
            current += inv['balance_cents']
        elif days <= 7:
            due_1_7 += inv['balance_cents']
        else:
            due_8_plus += inv['balance_cents']
    return {
        'ar_balance_cents': retailer['ar_balance_cents'],
        'exposure_forward_cents': retailer['exposure_forward_cents'],
        'exposure_aging_current_cents': current,
        'exposure_aging_due_1_7_cents': due_1_7,
        'exposure_aging_due_8_plus_cents': due_8_plus,
        'credit_status': retailer['credit_status'],
    }


# ---------------------------------------------------------------- misc helpers

def find_invoice_for_order(order_id):
    for inv in STORE['invoices'].values():
        if inv['order_id'] == order_id:
            return inv
    return None


def maybe_complete_manifest(manifest):
    """Auto-transition CLOSED -> COMPLETED once every non-cancelled order in the
    manifest has reached DELIVERED or INVOICED."""
    if manifest['status'] != 'CLOSED':
        return
    orders = [o for o in STORE['purchase_orders'].values()
              if o.get('manifest_id') == manifest['id'] and o['status'] != 'CANCELLED']
    if orders and all(o['status'] in ('DELIVERED', 'INVOICED') for o in orders):
        manifest['status'] = 'COMPLETED'
        touch(manifest)
