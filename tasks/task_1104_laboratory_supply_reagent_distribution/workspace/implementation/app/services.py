"""Business logic: allocation, pricing, freight, cascades, clock sweeps."""
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from .db import db, fmt_logical
from .errors import ApiError
from . import serializers as S

# --- constants ---
COLDNESS = {'AMBIENT': 0, 'REFRIGERATED_2_8': 1, 'FROZEN_MINUS_20': 2,
            'ULTRACOLD_MINUS_80': 3}
BANDS = {'AMBIENT': (15, 25), 'REFRIGERATED_2_8': (2, 8),
         'FROZEN_MINUS_20': (-25, -15), 'ULTRACOLD_MINUS_80': (-90, -70)}
BASE_FREIGHT = {'STANDARD': 800, 'EXPRESS': 1500, 'PRIORITY_OVERNIGHT': 2500}
COOLANT_RATE = {'NONE': 0, 'GEL_PACK': 150, 'DRY_ICE': 400}
HAZ_CLASS_CAP = {'FLAMMABLE': 30, 'CORROSIVE': 30, 'TOXIC': 10, 'OXIDIZER': 10}
TOTAL_HAZ_CAP = 50
DRY_ICE_CAP = 20
MIN_FREIGHT_CENTS = 500
FREE_FREIGHT_THRESHOLD_CENTS = 250000
ENDORSEMENT_COVERS = {
    'NONE': {'NON_HAZARDOUS'},
    'LIMITED': {'NON_HAZARDOUS', 'FLAMMABLE', 'CORROSIVE'},
    'FULL': {'NON_HAZARDOUS', 'FLAMMABLE', 'CORROSIVE', 'TOXIC', 'OXIDIZER'},
}


def rhu(value):
    """round half up to integer cents."""
    return int(Decimal(value).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def line_total(quantity, unit_price_cents, discount_pct):
    return rhu(Decimal(quantity) * Decimal(unit_price_cents)
               * (Decimal('1') - Decimal(str(discount_pct))))


def logical_date():
    return db.clock.date()


# ---------------------------------------------------------------- allocations

def eligible_lots(product, warehouse_id, requested_ship_date):
    ship = date.fromisoformat(requested_ship_date)
    out = []
    for l in db.lots.values():
        if l['status'] != 'AVAILABLE':
            continue
        if l['product_id'] != product['id'] or l['warehouse_id'] != warehouse_id:
            continue
        zone = db.zones[l['storage_zone_id']]
        if COLDNESS[zone['zone_class']] < COLDNESS[product['storage_requirement']]:
            continue
        if (date.fromisoformat(l['expiry_date']) - ship).days < \
                product['min_remaining_shelf_life_days']:
            continue
        out.append(l)
    return out


def rank_lots(lots):
    fefo, fifo = [], []
    for l in lots:
        zone = db.zones[l['storage_zone_id']]
        (fefo if zone['rotation_policy'] == 'FEFO' else fifo).append(l)
    fefo.sort(key=lambda l: (l['expiry_date'], l['_received_dt'],
                             l['lot_sequence_number']))
    fifo.sort(key=lambda l: (l['_received_dt'], l['lot_sequence_number']))
    return fefo + fifo


def _create_reservation(line, lot, qty, touched):
    r = db.new_common()
    r.update({'order_line_id': line['id'], 'lot_id': lot['id'],
              'quantity': qty, 'status': 'HELD'})
    db.reservations[r['id']] = r
    lot['quantity_on_hand'] -= qty
    lot['quantity_reserved'] += qty
    db.touch('lots', lot['id'], touched)
    if lot['quantity_on_hand'] == 0 and lot['status'] == 'AVAILABLE':
        lot['status'] = 'DEPLETED'


def allocate_any(order, line, needed, touched):
    product = db.products[line['product_id']]
    remaining = needed
    for lot in rank_lots(eligible_lots(product, order['warehouse_id'],
                                       order['requested_ship_date'])):
        if remaining <= 0:
            break
        if lot['quantity_on_hand'] <= 0:
            continue
        take = min(remaining, lot['quantity_on_hand'])
        _create_reservation(line, lot, take, touched)
        remaining -= take


def allocate_sequential(order, line, needed, touched):
    product = db.products[line['product_id']]
    cands = sorted(eligible_lots(product, order['warehouse_id'],
                                 order['requested_ship_date']),
                   key=lambda l: l['lot_sequence_number'])
    # maximal consecutive runs
    runs, cur = [], []
    for l in cands:
        if cur and l['lot_sequence_number'] != cur[-1]['lot_sequence_number'] + 1:
            runs.append(cur)
            cur = []
        cur.append(l)
    if cur:
        runs.append(cur)
    best = None
    for run in runs:
        for i in range(len(run)):
            total = 0
            for j in range(i, len(run)):
                total += run[j]['quantity_on_hand']
                if total >= needed:
                    cand = run[i:j + 1]
                    key = (len(cand), cand[0]['lot_sequence_number'],
                           cand[0]['expiry_date'])
                    if best is None or key < best[0]:
                        best = (key, cand)
                    break  # longer runs from same start are dominated
    if best is None:
        return  # sequential lines never partially allocate
    remaining = needed
    for lot in best[1]:
        if remaining <= 0:
            break
        take = min(remaining, lot['quantity_on_hand'])
        _create_reservation(line, lot, take, touched)
        remaining -= take


def set_line_status_from_allocation(line, touched):
    alloc = S.allocated_quantity(line['id'])
    if alloc >= line['quantity']:
        new = 'ALLOCATED'
    elif alloc > 0:
        new = 'PARTIALLY_ALLOCATED'
    else:
        new = 'PENDING'
    if line['status'] != new:
        line['status'] = new
    db.touch('order_lines', line['id'], touched)


# ---------------------------------------------------------------- pricing

def price_order(order, customer, touched):
    lines = S.lines_of_order(order['id'])
    total = 0
    for line in lines:
        product = db.products[line['product_id']]
        line['unit_price_cents'] = product['unit_price_cents']
        line['line_total_cents'] = line_total(line['quantity'],
                                              product['unit_price_cents'],
                                              customer['volume_discount_pct'])
        total += line['line_total_cents']
        db.touch('order_lines', line['id'], touched)
    order['product_total_cents'] = total
    return total


def projected_product_total(order, customer):
    total = 0
    for line in S.lines_of_order(order['id']):
        product = db.products[line['product_id']]
        total += line_total(line['quantity'], product['unit_price_cents'],
                            customer['volume_discount_pct'])
    return total


def freight_cost(service, weight_grams, coolant_type, coolant_units,
                 hazmat_present, product_total_cents):
    """freight_cost — both variants differ only in the weight input."""
    if product_total_cents is not None and \
            product_total_cents >= FREE_FREIGHT_THRESHOLD_CENTS:
        return 0
    base = BASE_FREIGHT[service]
    extra = 0
    if weight_grams > 5000:
        extra = ((weight_grams - 5000 + 999) // 1000) * 120
    coolant = COOLANT_RATE[coolant_type] * coolant_units
    subtotal = base + extra + coolant
    surcharge = rhu(Decimal(subtotal) * Decimal('0.25')) if hazmat_present else 0
    return max(subtotal + surcharge, MIN_FREIGHT_CENTS)


def credit_precheck(order, customer):
    """outstanding + projected product total + projected freight estimate
    (base rate, zero weight, coolant NONE, no surcharge, floor applies,
    free-freight threshold evaluated against the projected product total)."""
    projected = projected_product_total(order, customer)
    estimate = 0 if projected >= FREE_FREIGHT_THRESHOLD_CENTS \
        else max(BASE_FREIGHT[order['shipping_service']], MIN_FREIGHT_CENTS)
    if S.outstanding_balance(customer['id']) + projected + estimate \
            > customer['credit_limit_cents']:
        raise ApiError('ERR_CREDIT_LIMIT_EXCEEDED',
                       'Credit limit would be exceeded by this order')


# ---------------------------------------------------------------- recall cover

def recall_covers_lot(recall, lot):
    if recall['product_id'] != lot['product_id']:
        return False
    if recall['scope_type'] == 'PRODUCT_ALL':
        return True
    return recall['scope_lot_seq_min'] <= lot['lot_sequence_number'] \
        <= recall['scope_lot_seq_max']


def issued_recall_for_product(product_id):
    for r in db.recalls.values():
        if r['status'] == 'ISSUED' and r['product_id'] == product_id:
            return r
    return None


def issued_recall_covers_lot(lot):
    for r in db.recalls.values():
        if r['status'] == 'ISSUED' and recall_covers_lot(r, lot):
            return r
    return None


# ------------------------------------------------------------- cascades

def _release_held_reservation(res, touched):
    lot = db.lots[res['lot_id']]
    lot['quantity_reserved'] -= res['quantity']
    lot['quantity_on_hand'] += res['quantity']
    res['status'] = 'RELEASED'
    db.touch('reservations', res['id'], touched)
    db.touch('lots', lot['id'], touched)


def cascade_demotions(affected_line_ids, touched, zero_only):
    """Line/order demotion after reservation loss.

    zero_only=False (quarantine / expiry / manual release): a line demotes to
    PENDING whenever allocated_quantity falls below its quantity.
    zero_only=True (recall issue): a line demotes to PENDING only when the
    recomputed amount reaches zero.
    Orders in ALLOCATED demote to BACKORDERED when any line fell short.
    """
    order_ids = set()
    for lid in affected_line_ids:
        line = db.order_lines[lid]
        if line['status'] not in ('ALLOCATED', 'PARTIALLY_ALLOCATED'):
            continue
        alloc = S.allocated_quantity(lid)
        fell_short = alloc < line['quantity']
        demote = (alloc == 0) if zero_only else fell_short
        if demote:
            line['status'] = 'PENDING'
        db.touch('order_lines', lid, touched)
        if fell_short:
            order_ids.add(line['order_id'])
    for oid in order_ids:
        order = db.orders[oid]
        if order['status'] == 'ALLOCATED':
            order['status'] = 'BACKORDERED'
            db.touch('orders', oid, touched)


def quarantine_cascade(lot, touched, zero_only=False):
    """Release every HELD reservation on the lot with compensation, then demote."""
    affected = []
    for res in db.reservations.values():
        if res['lot_id'] == lot['id'] and res['status'] == 'HELD':
            _release_held_reservation(res, touched)
            affected.append(res['order_line_id'])
    cascade_demotions(affected, touched, zero_only=zero_only)


# ------------------------------------------------------------- submit / runs

def submit_order(order, touched):
    """Full submit path. Raises ApiError on any validation failure."""
    if order['status'] != 'DRAFT':
        raise ApiError('ERR_ORDER_NOT_SUBMITTABLE', 'Order is not DRAFT')
    customer = db.customers[order['customer_id']]
    if customer['status'] != 'ACTIVE':
        raise ApiError('ERR_CUSTOMER_NOT_ACTIVE', 'Customer account is not ACTIVE')
    lines = S.lines_of_order(order['id'])
    if not lines:
        raise ApiError('ERR_ORDER_HAS_NO_LINES', 'Order has no lines')

    products = [db.products[l['product_id']] for l in lines]
    # hazmat endorsement ladder
    covered = ENDORSEMENT_COVERS[customer['hazmat_endorsement']]
    for p in products:
        if p['hazard_class'] not in covered:
            raise ApiError('ERR_HAZMAT_ENDORSEMENT_INSUFFICIENT',
                           'Customer hazmat endorsement does not cover %s'
                           % p['hazard_class'])
    # cold chain certification
    if any(p['requires_cold_chain'] for p in products) \
            and not customer['cold_chain_certified']:
        raise ApiError('ERR_COLD_CHAIN_NOT_CERTIFIED',
                       'Customer is not cold-chain certified')
    # recall block
    for p in products:
        if issued_recall_for_product(p['id']):
            raise ApiError('ERR_PRODUCT_UNDER_RECALL',
                           'Product %s is covered by an issued recall' % p['id'])
    # shelf-life hard edge
    for line in lines:
        p = db.products[line['product_id']]
        ship = date.fromisoformat(order['requested_ship_date'])
        pool = [l for l in db.lots.values()
                if l['status'] == 'AVAILABLE' and l['product_id'] == p['id']
                and l['warehouse_id'] == order['warehouse_id']
                and l['quantity_on_hand'] > 0]
        if pool and all(
                (date.fromisoformat(l['expiry_date']) - ship).days
                < p['min_remaining_shelf_life_days'] for l in pool):
            raise ApiError('ERR_SHELF_LIFE_TOO_SHORT',
                           'All available lots fail the shelf-life gate')
    # listing
    for p in products:
        if p['status'] != 'LISTED':
            raise ApiError('ERR_PRODUCT_NOT_LISTED',
                           'Product %s is not LISTED' % p['id'])
    # credit pre-check
    credit_precheck(order, customer)

    # pricing then allocation
    price_order(order, customer, touched)
    for line in lines:
        need = line['quantity'] - S.allocated_quantity(line['id'])
        if need <= 0:
            continue
        if line['fulfillment_mode'] == 'SEQUENTIAL':
            allocate_sequential(order, line, need, touched)
        else:
            allocate_any(order, line, need, touched)
    all_full = True
    for line in lines:
        set_line_status_from_allocation(line, touched)
        if S.allocated_quantity(line['id']) < line['quantity']:
            all_full = False
    order['status'] = 'ALLOCATED' if all_full else 'BACKORDERED'
    order['submission_seq'] = db.next_submission_seq()
    db.touch('orders', order['id'], touched)


def waitlist_retry(touched):
    """After lot receipt: BACKORDERED orders in submission_seq ASC get topped up."""
    backs = sorted([o for o in db.orders.values() if o['status'] == 'BACKORDERED'],
                   key=lambda o: o['submission_seq'])
    for order in backs:
        lines = S.lines_of_order(order['id'])
        for line in lines:
            need = line['quantity'] - S.allocated_quantity(line['id'])
            if need <= 0:
                continue
            if line['fulfillment_mode'] == 'SEQUENTIAL':
                allocate_sequential(order, line, need, touched)
            else:
                allocate_any(order, line, need, touched)
            set_line_status_from_allocation(line, touched)
        if all(S.allocated_quantity(l['id']) >= l['quantity'] for l in lines):
            order['status'] = 'ALLOCATED'
            db.touch('orders', order['id'], touched)


# ------------------------------------------------------------- clock sweeps

def expiry_sweep(touched):
    """Lots whose expiry_date is strictly before the new current date expire."""
    today = logical_date()
    expired = 0
    for lot in sorted(db.lots.values(), key=lambda l: l['_seq']):
        if lot['status'] != 'AVAILABLE':
            continue
        if today > date.fromisoformat(lot['expiry_date']):
            lot['status'] = 'EXPIRED'
            db.touch('lots', lot['id'], touched)
            expired += 1
            quarantine_cascade(lot, touched, zero_only=False)
    return expired


def create_order_record(customer_id, warehouse_id, shipping_service,
                        requested_ship_date, line_specs):
    o = db.new_common()
    o.update({'customer_id': customer_id, 'warehouse_id': warehouse_id,
              'shipping_service': shipping_service,
              'requested_ship_date': requested_ship_date,
              'product_total_cents': None, 'submission_seq': None,
              'status': 'DRAFT'})
    db.orders[o['id']] = o
    for spec in line_specs:
        l = db.new_common()
        l.update({'order_id': o['id'], 'product_id': spec['product_id'],
                  'quantity': spec['quantity'],
                  'fulfillment_mode': spec.get('fulfillment_mode', 'ANY'),
                  'unit_price_cents': None, 'line_total_cents': None,
                  'status': 'PENDING'})
        db.order_lines[l['id']] = l
    return o


def standing_order_sweep(touched):
    """standing_order_run_generation over the logical clock."""
    today = logical_date()
    run_count = 0
    orders_generated = 0
    sos = sorted([s for s in db.standing_orders.values() if s['status'] == 'ACTIVE'],
                 key=lambda s: s['_seq'])
    for so in sos:
        ran = False
        while so['status'] == 'ACTIVE' \
                and date.fromisoformat(so['next_run_date']) <= today \
                and date.fromisoformat(so['next_run_date']) <= \
                date.fromisoformat(so['effective_until']):
            ran = True
            order = create_order_record(
                so['customer_id'], so['warehouse_id'], 'STANDARD',
                so['next_run_date'],
                [{'product_id': so['product_id'],
                  'quantity': so['quantity_per_run'],
                  'fulfillment_mode': 'ANY'}])
            try:
                submit_order(order, touched)
            except ApiError:
                # generated order stays DRAFT; standing order pauses
                so['status'] = 'PAUSED'
                db.touch('standing_orders', so['id'], touched)
                break
            so['generated_order_count'] += 1
            so['next_run_date'] = (
                date.fromisoformat(so['next_run_date'])
                + timedelta(days=so['interval_days'])).isoformat()
            db.touch('standing_orders', so['id'], touched)
            orders_generated += 1
        if ran:
            run_count += 1
    return run_count, orders_generated


def auto_suspend_check(customer, touched):
    """outstanding * 10 > credit_limit * 12 -> SUSPENDED (strictly greater)."""
    if customer['status'] != 'ACTIVE':
        return
    if S.outstanding_balance(customer['id']) * 10 > customer['credit_limit_cents'] * 12:
        customer['status'] = 'SUSPENDED'
        db.touch('customers', customer['id'], touched)
