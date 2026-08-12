"""Calculations (section 1.3 of the scaffold) and cross-entity cascades."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from errors import ApiError
from store import db, now, entity, touch

RATE = {'BARRICADE': 250, 'CONE': 25, 'SIGN': 100}
LEAD_DAYS = {'CITY': 14, 'COUNTY': 28, 'STATE_ROUTE': 45}
DISPATCH_HOURS = 48
RETURN_GRACE_HOURS = 48
REPORT_WINDOW_HOURS = 72
LATE_MULTIPLIER = 2
SHORTAGE_MULTIPLIER = 5
MIN_COVERAGE_CENTS = 100000000
WAIVER_MAX_INVOICE_CENTS = 500
WAIVER_MAX_ATTENDANCE = 75

APP_STATUSES = ['DRAFT', 'UNDER_REVIEW', 'SUSPENDED', 'APPROVED', 'DENIED',
                'ISSUED', 'COMPLETED', 'CANCELLED', 'REVOKED', 'EXPIRED']


# ---------------------------------------------------------------- getters ---
def _get(table, rid, label):
    e = table.get(rid)
    if e is None:
        raise ApiError('ERR_NOT_FOUND', '%s not found' % label, 404)
    return e


def get_organizer(oid):
    return _get(db.organizers, oid, 'Organizer')


def get_segment(sid):
    return _get(db.segments, sid, 'StreetSegment')


def get_petition(pid):
    return _get(db.petitions, pid, 'Petition')


def get_application(aid):
    a = db.applications.get(aid)
    if a is None:
        raise ApiError('ERR_NOT_FOUND', 'PermitApplication not found', 404)
    ensure_fresh(a)
    return a


def get_tcp(tid):
    return _get(db.tcps, tid, 'TrafficControlPlan')


def get_sound(sid):
    return _get(db.sound_plans, sid, 'SoundPlan')


def get_insurance(iid):
    return _get(db.insurance, iid, 'InsuranceCertificate')


def get_stock(sid):
    return _get(db.stocks, sid, 'EquipmentStock')


def get_reservation(rid):
    return _get(db.reservations, rid, 'EquipmentReservation')


def get_pool(pid):
    return _get(db.pools, pid, 'CostSharePool')


def get_deposit(did):
    return _get(db.deposits, did, 'Deposit')


def get_report(rid):
    return _get(db.reports, rid, 'PostEventReport')


def find_tcp(app_id):
    return next((t for t in db.tcps.values() if t['application_id'] == app_id), None)


def find_sound(app_id):
    return next((s for s in db.sound_plans.values() if s['application_id'] == app_id), None)


def find_pool(app_id):
    return next((p for p in db.pools.values() if p['application_id'] == app_id), None)


def find_deposit(app_id):
    return next((d for d in db.deposits.values() if d['application_id'] == app_id), None)


def find_report(app_id):
    rows = [r for r in db.reports.values() if r['application_id'] == app_id]
    rows.sort(key=lambda r: (r['created_at'], r['_seq']))
    return rows[-1] if rows else None


def app_reservations(app_id):
    return [r for r in db.reservations.values() if r['application_id'] == app_id]


# ------------------------------------------------------------ calculations ---
def ceil_div(a, b):
    return -(-a // b)


def petition_threshold(seg):
    """calculations.petition_required_signatures; integer ceil, minimum 1."""
    if seg['segment_kind'] == 'RESIDENTIAL':
        required = ceil_div(60 * seg['household_count'], 100)
        mode = 'DISTINCT_HOUSEHOLD'
    else:  # MIXED_USE
        required = ceil_div(6 * seg['household_count'] + 5 * seg['business_count'], 10)
        mode = 'SIGNATURE_COUNT'
    return max(1, required), mode


def recompute_petition(p):
    sigs = [s for s in db.signatures.values()
            if s['petition_id'] == p['id'] and s['status'] == 'ACTIVE']
    p['valid_signature_count'] = len(sigs)
    p['distinct_household_count'] = len({s['household_address'] for s in sigs})


def support_metric(p):
    if p['support_mode'] == 'DISTINCT_HOUSEHOLD':
        return p['distinct_household_count']
    return p['valid_signature_count']


def fee_subtotal(app, seg):
    sub = 5000
    att = app['expected_attendance']
    if att > 150:
        sub += 9000
    elif att > 50:
        sub += 4000
    if app['alcohol_served']:
        sub += 7500
    if app['amplified_sound']:
        sub += 2500
    if seg['jurisdiction'] == 'STATE_ROUTE':
        sub += 10000
    return sub


def deposit_required(app):
    d = 10000
    if app['expected_attendance'] > 150:
        d += 15000
    if app['alcohol_served']:
        d += 20000
    return d


def rhu(dec):
    return int(dec.quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def invoice_line(units, kind):
    """calculations.equipment_rental_totals, per line: pretax + per-line tax."""
    pretax = units * RATE[kind]
    tax = rhu(Decimal(pretax) * Decimal('0.0825'))
    return pretax + tax


def provisional_fee(app, seg, tcp):
    estimate = 0
    if tcp is not None:
        estimate = (tcp['barricade_count'] * RATE['BARRICADE']
                    + tcp['cone_count'] * RATE['CONE']
                    + tcp['sign_count'] * RATE['SIGN'])
    return fee_subtotal(app, seg) + estimate


def final_fee(app, seg, equipment_total):
    """calculations.permit_fee_final, pinned evaluation order."""
    sub = fee_subtotal(app, seg)
    dep = deposit_required(app)
    if sub + dep > 20000:
        discounted = rhu(Decimal(sub) * Decimal('0.9'))
    else:
        discounted = sub
    surcharge = rhu(Decimal(discounted) * Decimal('0.03'))
    return discounted + surcharge + equipment_total


def buffered_window(app):
    return (app['event_start_at'] - timedelta(hours=24),
            app['event_end_at'] + timedelta(hours=24))


def overlaps_closed(a, b):
    return a[0] <= b[1] and b[0] <= a[1]


def stock_counters(stock):
    """Computed reserved/out/available counters against the logical clock."""
    t = now()
    reserved = 0
    out = 0
    for r in db.reservations.values():
        if r['stock_id'] != stock['id']:
            continue
        if r['reservation_status'] in ('HELD', 'CONFIRMED'):
            app = db.applications.get(r['application_id'])
            if app is None:
                continue
            ws, we = buffered_window(app)
            if ws <= t <= we:
                reserved += r['units']
        elif r['reservation_status'] == 'DISPATCHED':
            out += r['units'] - (r['returned_units'] or 0)
    available = stock['total_units'] - reserved - out
    return reserved, out, available


def window_available(stock, w):
    committed = 0
    for r in db.reservations.values():
        if r['stock_id'] != stock['id']:
            continue
        if r['reservation_status'] not in ('HELD', 'CONFIRMED', 'DISPATCHED'):
            continue
        app = db.applications.get(r['application_id'])
        if app is None:
            continue
        ensure_fresh(app)
        if overlaps_closed(buffered_window(app), w):
            committed += r['units']
    return stock['total_units'] - committed


def select_stock(kind, units, app):
    """calculations.equipment_stock_selector: availability desc, created_at asc."""
    w = buffered_window(app)
    cands = []
    for s in db.stocks.values():
        if s['equipment_kind'] != kind:
            continue
        avail = window_available(s, w)
        if avail >= units:
            cands.append((avail, s))
    if not cands:
        raise ApiError('ERR_EQUIPMENT_UNAVAILABLE',
                       'No stock of kind %s has %d window-available units' % (kind, units),
                       409)
    cands.sort(key=lambda x: (-x[0], x[1]['created_at'], x[1]['_seq']))
    return cands[0][1]


def segment_conflict(app):
    """calculations.segment_window_conflict: half-open overlap, self excluded."""
    for e in db.applications.values():
        if e['id'] == app['id']:
            continue
        if e['segment_id'] != app['segment_id']:
            continue
        if e['status'] not in ('UNDER_REVIEW', 'SUSPENDED', 'APPROVED', 'ISSUED'):
            continue
        if e['event_start_at'] < app['event_end_at'] and \
                app['event_start_at'] < e['event_end_at']:
            return True
    return False


def check_event_window(start, end):
    """end > start and duration <= 12h."""
    from datetime import timedelta as _td
    if end <= start or (end - start) > _td(hours=12):
        raise ApiError('ERR_EVENT_WINDOW_INVALID',
                       'event_end_at must be after event_start_at and the duration must be <= 12h',
                       400)


# ---------------------------------------------------------------- cascades ---
def demote_organizer(org):
    org['forfeiture_count'] += 1
    if org['forfeiture_count'] == 1:
        org['standing'] = 'FLAGGED'
    elif org['forfeiture_count'] >= 2:
        org['standing'] = 'SUSPENDED'
    touch(org)


def post_charge(dep, kind, amount, note, source_reservation_id=None):
    """Post a ChargeEntry; a charge reaching held_cents forfeits the deposit."""
    if amount <= 0:
        return None
    ch = entity(deposit_id=dep['id'], kind=kind, amount_cents=amount, note=note,
                source_reservation_id=source_reservation_id)
    # ChargeEntry carries only id + created_at (no updated_at / version).
    ch.pop('updated_at', None)
    ch.pop('version', None)
    db.charges[ch['id']] = ch
    dep['charges_cents'] += amount
    if dep['status'] == 'HELD' and dep['charges_cents'] >= dep['held_cents']:
        dep['status'] = 'FORFEITED'
        dep['refund_cents'] = 0
        app = db.applications.get(dep['application_id'])
        org = db.organizers.get(app['organizer_id']) if app else None
        if org is not None:
            demote_organizer(org)
    touch(dep)
    return ch


def deposit_auto_settle(app):
    dep = find_deposit(app['id'])
    if dep is not None and dep['status'] == 'HELD':
        dep['status'] = 'SETTLED'
        dep['refund_cents'] = dep['held_cents'] - dep['charges_cents']
        touch(dep)


def pool_refund_chain(app):
    pool = find_pool(app['id'])
    if pool is None or pool['status'] not in ('OPEN', 'FUNDED'):
        return
    pool['status'] = 'REFUNDING'
    touch(pool)
    t = now()
    for c in db.contributions.values():
        if c['pool_id'] == pool['id'] and c['status'] == 'PAID':
            c['status'] = 'REFUNDED'
            c['refunded_at'] = t
            pool['refunded_cents'] += c['amount_cents']
            pool['collected_cents'] -= c['amount_cents']
            touch(c)
    pool['status'] = 'REFUNDED'
    touch(pool)


def release_reservations(app, recall=False):
    """Cancel/recall live reservations, releasing stock; INVOICED billing waives
    only when a CONFIRMED reservation is cancelled or recalled."""
    for r in app_reservations(app['id']):
        if r['reservation_status'] == 'HELD':
            r['reservation_status'] = 'CANCELLED'
            touch(r)
        elif r['reservation_status'] == 'CONFIRMED':
            r['reservation_status'] = 'RECALLED' if recall else 'CANCELLED'
            if r['billing_status'] == 'INVOICED':
                r['billing_status'] = 'WAIVED'
            touch(r)


def unwind_pre_issuance(app):
    release_reservations(app)
    deposit_auto_settle(app)
    pool_refund_chain(app)


def ensure_fresh(app):
    """Lazy expiry: DRAFT/UNDER_REVIEW/SUSPENDED/APPROVED past event_end_at
    collapses to EXPIRED with the pre-issuance unwind."""
    if app['status'] in ('DRAFT', 'UNDER_REVIEW', 'SUSPENDED', 'APPROVED') \
            and now() > app['event_end_at']:
        app['status'] = 'EXPIRED'
        touch(app)
        unwind_pre_issuance(app)


def petition_deficient(p, note):
    p['status'] = 'DEFICIENT'
    p['deficiency_note'] = note
    touch(p)
    for a in db.applications.values():
        if a['petition_id'] == p['id'] and a['status'] in ('UNDER_REVIEW', 'APPROVED'):
            a['status'] = 'SUSPENDED'
            a['decision_reason'] = 'petition deficient'
            touch(a)
