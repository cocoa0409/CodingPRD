"""Equipment stocks and reservations (selector, dispatch, return, billing)."""
from datetime import timedelta
from flask import Blueprint, request

from auth import auth, own_or_403, REVIEW_ROLES
from calc import (RATE, DISPATCH_HOURS, RETURN_GRACE_HOURS, LATE_MULTIPLIER,
                  SHORTAGE_MULTIPLIER, WAIVER_MAX_INVOICE_CENTS, get_application,
                  get_stock, get_reservation, find_deposit, select_stock,
                  stock_counters, post_charge)
from envelope import ok, created, ok_list
from errors import ApiError
from store import db, entity, now, touch
from validate import body, req, as_str, as_int, as_enum

bp = Blueprint('equipment', __name__)

KINDS = ['BARRICADE', 'CONE', 'SIGN']
STOCK_ROLES = ['Organizer', 'TrafficReviewer', 'SafetyReviewer', 'PermitOfficer',
               'DepotOfficer', 'CityAdmin']
RES_READ = ['Organizer', 'PermitOfficer', 'DepotOfficer', 'CityAdmin']


def _pub_stock(s):
    reserved, out, available = stock_counters(s)
    d = dict(s)
    d['reserved_units'] = reserved
    d['out_units'] = out
    d['available_units'] = available
    return d


@bp.route('/equipment-stocks', methods=['POST'])
def create_stock():
    auth(['CityAdmin'])
    b = body()
    total = as_int(req(b, 'total_units'), 'total_units')
    if total <= 0:
        raise ApiError('ERR_INVALID_REQUEST', 'total_units must be > 0', 400)
    s = entity(
        depot_name=as_str(req(b, 'depot_name'), 'depot_name'),
        equipment_kind=as_enum(req(b, 'equipment_kind'), 'equipment_kind', KINDS),
        total_units=total,
    )
    db.stocks[s['id']] = s
    return created(_pub_stock(s))


@bp.route('/equipment-stocks', methods=['GET'])
def list_stocks():
    auth(STOCK_ROLES)
    rows = list(db.stocks.values())
    kind = request.args.get('equipment_kind')
    if kind is not None:
        if kind not in KINDS:
            raise ApiError('ERR_INVALID_REQUEST', 'Unknown equipment_kind filter', 400)
        rows = [s for s in rows if s['equipment_kind'] == kind]
    return ok_list([_pub_stock(s) for s in rows])


@bp.route('/equipment-stocks/<sid>', methods=['GET'])
def get_one_stock(sid):
    auth(STOCK_ROLES)
    return ok(_pub_stock(get_stock(sid)))


@bp.route('/equipment-stocks/<sid>/equipment-reservations', methods=['GET'])
def stock_reservations(sid):
    auth(['PermitOfficer', 'DepotOfficer', 'CityAdmin'])
    s = get_stock(sid)
    return ok_list([r for r in db.reservations.values() if r['stock_id'] == s['id']])


@bp.route('/permit-applications/<aid>/equipment-reservations', methods=['POST'])
def create_reservation(aid):
    uid, role = auth(['Organizer'])
    app = get_application(aid)
    own_or_403(role, uid, app['organizer_id'])
    if app['status'] not in ('UNDER_REVIEW', 'SUSPENDED', 'APPROVED'):
        raise ApiError('ERR_INVALID_STATE',
                       'Application state %s does not permit reservations' % app['status'], 409)
    b = body()
    kind = as_enum(req(b, 'equipment_kind'), 'equipment_kind', KINDS)
    units = as_int(req(b, 'units'), 'units')
    if units <= 0:
        raise ApiError('ERR_INVALID_REQUEST', 'units must be > 0', 400)
    stock = select_stock(kind, units, app)
    r = entity(
        application_id=aid,
        stock_id=stock['id'],
        equipment_kind=kind,
        units=units,
        reservation_status='HELD',
        billing_status='UNBILLED',
        invoice_cents=None,
        dispatched_by=None,
        dispatched_at=None,
        return_due_at=None,
        returned_at=None,
        returned_units=None,
        late_days=None,
        return_verified_by=None,
    )
    db.reservations[r['id']] = r
    return created(r)


@bp.route('/permit-applications/<aid>/equipment-reservations', methods=['GET'])
def list_reservations(aid):
    uid, role = auth(RES_READ)
    app = get_application(aid)
    own_or_403(role, uid, app['organizer_id'])
    return ok_list([r for r in db.reservations.values() if r['application_id'] == aid])


@bp.route('/equipment-reservations/<rid>', methods=['GET'])
def get_one_reservation(rid):
    uid, role = auth(RES_READ)
    r = get_reservation(rid)
    app = get_application(r['application_id'])
    own_or_403(role, uid, app['organizer_id'])
    return ok(r)


@bp.route('/equipment-reservations/<rid>/cancel', methods=['POST'])
def cancel_reservation(rid):
    uid, role = auth(['Organizer'])
    r = get_reservation(rid)
    app = get_application(r['application_id'])
    own_or_403(role, uid, app['organizer_id'])
    if r['reservation_status'] != 'HELD':
        raise ApiError('ERR_INVALID_STATE', 'Reservation is not HELD', 409)
    if app['status'] not in ('UNDER_REVIEW', 'SUSPENDED', 'APPROVED'):
        raise ApiError('ERR_INVALID_STATE',
                       'Application state %s does not permit reservation cancel' % app['status'], 409)
    r['reservation_status'] = 'CANCELLED'
    touch(r)
    return ok(r)


@bp.route('/equipment-reservations/<rid>/pay', methods=['POST'])
def pay_reservation(rid):
    uid, role = auth(['Organizer'])
    r = get_reservation(rid)
    app = get_application(r['application_id'])
    own_or_403(role, uid, app['organizer_id'])
    if r['billing_status'] != 'INVOICED':
        raise ApiError('ERR_INVALID_STATE', 'Reservation billing is not INVOICED', 409)
    r['billing_status'] = 'PAID'
    touch(r)
    return ok(r)


@bp.route('/equipment-reservations/<rid>/waive', methods=['POST'])
def waive_reservation(rid):
    auth(['PermitOfficer'])
    r = get_reservation(rid)
    if r['billing_status'] != 'INVOICED':
        raise ApiError('ERR_INVALID_STATE', 'Reservation billing is not INVOICED', 409)
    if r['invoice_cents'] > WAIVER_MAX_INVOICE_CENTS:
        raise ApiError('ERR_WAIVER_AMOUNT_TOO_LARGE',
                       'Invoice exceeds the 500-cent waiver cap', 422)
    r['billing_status'] = 'WAIVED'
    touch(r)
    return ok(r)


@bp.route('/equipment-reservations/<rid>/dispatch', methods=['POST'])
def dispatch_reservation(rid):
    uid, role = auth(['DepotOfficer'])
    r = get_reservation(rid)
    app = get_application(r['application_id'])
    if r['reservation_status'] != 'CONFIRMED':
        raise ApiError('ERR_INVALID_STATE', 'Reservation is not CONFIRMED', 409)
    if app['status'] != 'ISSUED':
        raise ApiError('ERR_INVALID_STATE', 'Application is not ISSUED', 409)
    t = now()
    if not (app['event_start_at'] - timedelta(hours=DISPATCH_HOURS)
            <= t <= app['event_start_at']):
        raise ApiError('ERR_DISPATCH_WINDOW_VIOLATION',
                       'Dispatch is outside [event_start_at - 48h, event_start_at]', 422)
    r['reservation_status'] = 'DISPATCHED'
    r['dispatched_by'] = uid
    r['dispatched_at'] = t
    r['return_due_at'] = app['event_end_at'] + timedelta(hours=RETURN_GRACE_HOURS)
    touch(r)
    return ok(r)


@bp.route('/equipment-reservations/<rid>/return', methods=['POST'])
def return_reservation(rid):
    auth(['DepotOfficer'])
    r = get_reservation(rid)
    b = body()
    returned = as_int(req(b, 'returned_units'), 'returned_units')
    if r['reservation_status'] != 'DISPATCHED':
        raise ApiError('ERR_INVALID_STATE', 'Reservation is not DISPATCHED', 409)
    if returned < 0 or returned > r['units']:
        raise ApiError('ERR_INVALID_REQUEST',
                       'returned_units must be between 0 and %d' % r['units'], 400)
    t = now()
    r['reservation_status'] = 'RETURNED'
    r['returned_at'] = t
    r['returned_units'] = returned
    delta = t - r['return_due_at']
    if delta.total_seconds() <= 0:
        late_days = 0
    else:
        late_days = delta.days + (1 if (delta.seconds or delta.microseconds) else 0)
    r['late_days'] = late_days
    touch(r)
    dep = find_deposit(r['application_id'])
    if dep is not None and dep['status'] == 'HELD':
        rate = RATE[r['equipment_kind']]
        if late_days > 0:
            post_charge(dep, 'LATE_EQUIPMENT',
                        returned * rate * LATE_MULTIPLIER * late_days,
                        'Late equipment return (%d day(s))' % late_days,
                        source_reservation_id=r['id'])
        shortage = r['units'] - returned
        if shortage > 0:
            post_charge(dep, 'SHORTAGE',
                        shortage * rate * SHORTAGE_MULTIPLIER,
                        'Equipment shortage (%d unit(s))' % shortage,
                        source_reservation_id=r['id'])
    return ok(r)


@bp.route('/equipment-reservations/<rid>/verify-return', methods=['POST'])
def verify_return(rid):
    uid, role = auth(['DepotOfficer'])
    r = get_reservation(rid)
    if r['reservation_status'] != 'RETURNED':
        raise ApiError('ERR_INVALID_STATE', 'Reservation is not RETURNED', 409)
    if uid == r['dispatched_by']:
        raise ApiError('ERR_SOD_SAME_OFFICER',
                       'Return verification must be performed by a different officer', 403)
    if r['billing_status'] not in ('PAID', 'WAIVED'):
        raise ApiError('ERR_BILLING_UNSETTLED',
                       'Billing must be PAID or WAIVED before verification', 409)
    r['reservation_status'] = 'CLOSED'
    r['return_verified_by'] = uid
    touch(r)
    return ok(r)
