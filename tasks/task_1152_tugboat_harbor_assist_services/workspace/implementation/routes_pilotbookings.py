"""Pilot bookings: create, confirm, board, list, get."""
from datetime import timedelta

from flask import Blueprint, request

from db import store, new_id, stamp_new, touch
from errors import ApiError
from util import (
    authenticate, require_roles, not_found, ok_object, ok_list,
    json_body, Check, get_dt,
    parse_pagination, check_enum_filter, page_slice,
)
from calc import ser_booking

bp = Blueprint('pilot_bookings', __name__)

BOOKING_STATUSES = {'REQUESTED', 'CONFIRMED', 'BOARDED', 'COMPLETED',
                    'NO_SHOW', 'CANCELLED', 'SUPERSEDED'}
BOOKING_TERMINAL = {'COMPLETED', 'NO_SHOW', 'CANCELLED', 'SUPERSEDED'}
BUFFER_STATUSES = {'REQUESTED', 'CONFIRMED', 'BOARDED'}
TURNAROUND = timedelta(minutes=60)

LICENSE_RULES = {
    'TOWAGE': {'CLASS_I'},
    'ESCORT': {'CLASS_I'},
    'DOCKING': {'CLASS_I', 'CLASS_II'},
    'UNDOCKING': {'CLASS_I', 'CLASS_II'},
    'SHIFTING': {'CLASS_I', 'CLASS_II', 'CLASS_III'},
}


def _load_booking(bid):
    b = store.pilot_bookings.get(bid)
    if b is None:
        not_found('pilot booking')
    return b


@bp.route('/api/pilot-bookings', methods=['POST'])
def create_booking():
    _, role = authenticate()
    require_roles(role, ('PortDispatcher',))
    body = json_body()
    c = Check()
    # Existence (stage 4), left to right: job_order_id, then pilot_id.
    raw_job = body.get('job_order_id')
    job = None
    if raw_job is None or not isinstance(raw_job, str):
        c.bad_request = True
    else:
        job = store.job_orders.get(raw_job)
        if job is None:
            not_found('job order')
    raw_pilot = body.get('pilot_id')
    pilot = None
    if raw_pilot is None or not isinstance(raw_pilot, str):
        c.bad_request = True
    else:
        pilot = store.pilots.get(raw_pilot)
        if pilot is None:
            not_found('pilot')
    # From-state (stage 7): job must admit a new booking.
    if job is not None and job['status'] not in ('REQUESTED', 'CONFIRMED'):
        raise ApiError('ERR_INVALID_STATE', 409,
                       f"Cannot book a pilot for a job in state {job['status']}")
    ws = get_dt(body, 'window_start', c)
    we = get_dt(body, 'window_end', c)
    # Temporal (14): 60-minute pilot turnaround buffer.
    if ws is not None and we is not None and pilot is not None:
        for b in store.pilot_bookings.values():
            if b['pilot_id'] != pilot['id'] or b['status'] not in BUFFER_STATUSES:
                continue
            if ws >= b['window_end'] + TURNAROUND or we <= b['window_start'] - TURNAROUND:
                continue
            raise ApiError('ERR_PILOT_WINDOW_CONFLICT', 409,
                           'Booking violates the 60-minute pilot turnaround buffer')
    # Constraint (22): pilot license class must suffice for the maneuver.
    if job is not None and pilot is not None:
        if pilot['license_class'] not in LICENSE_RULES[job['maneuver_type']]:
            raise ApiError('ERR_PILOT_LICENSE_INSUFFICIENT', 422,
                           'Pilot license class is insufficient for the maneuver')
    if ws is not None and we is not None and we <= ws:
        c.bad_request = True
    c.raise_deferred()
    rec = {
        'id': new_id(), 'job_order_id': raw_job, 'pilot_id': raw_pilot,
        'window_start': ws, 'window_end': we, 'status': 'REQUESTED',
    }
    stamp_new(rec)
    store.pilot_bookings[rec['id']] = rec
    return ok_object(ser_booking(rec), 201)


@bp.route('/api/pilot-bookings', methods=['GET'])
def list_bookings():
    authenticate()
    c = Check()
    limit, offset = parse_pagination(c)
    status = check_enum_filter('status', BOOKING_STATUSES, c)
    job_id = request.args.get('job_order_id')
    pilot_id = request.args.get('pilot_id')
    c.raise_deferred()
    recs = [b for b in store.pilot_bookings.values()
            if (status is None or b['status'] == status)
            and (job_id is None or b['job_order_id'] == job_id)
            and (pilot_id is None or b['pilot_id'] == pilot_id)]
    page, total = page_slice(recs, limit, offset)
    return ok_list([ser_booking(b) for b in page], limit, offset, total)


@bp.route('/api/pilot-bookings/<bid>', methods=['GET'])
def get_booking(bid):
    authenticate()
    return ok_object(ser_booking(_load_booking(bid)))


@bp.route('/api/pilot-bookings/<bid>/confirm', methods=['POST'])
def confirm_booking(bid):
    uid, role = authenticate()
    require_roles(role, ('Pilot',))
    b = _load_booking(bid)
    if b['pilot_id'] != uid:
        raise ApiError('ERR_BOOKING_NOT_OWNED', 403,
                       'Pilot may only confirm their own booking')
    if b['status'] in BOOKING_TERMINAL:
        raise ApiError('ERR_ALREADY_TERMINAL', 409,
                       f"Booking is in terminal state {b['status']}")
    if b['status'] != 'REQUESTED':
        raise ApiError('ERR_INVALID_STATE', 409,
                       f"Cannot confirm a booking in state {b['status']}")
    b['status'] = 'CONFIRMED'
    touch(b)
    return ok_object(ser_booking(b))


@bp.route('/api/pilot-bookings/<bid>/board', methods=['POST'])
def board_booking(bid):
    uid, role = authenticate()
    require_roles(role, ('Pilot',))
    b = _load_booking(bid)
    if b['pilot_id'] != uid:
        raise ApiError('ERR_BOOKING_NOT_OWNED', 403,
                       'Pilot may only board their own booking')
    if b['status'] in BOOKING_TERMINAL:
        raise ApiError('ERR_ALREADY_TERMINAL', 409,
                       f"Booking is in terminal state {b['status']}")
    if b['status'] != 'CONFIRMED':
        raise ApiError('ERR_INVALID_STATE', 409,
                       f"Cannot board a booking in state {b['status']}")
    job = store.job_orders[b['job_order_id']]
    if job['status'] not in ('DISPATCHED', 'IN_PROGRESS'):
        raise ApiError('ERR_INVALID_STATE', 409,
                       f"Cannot board while the job is in state {job['status']}")
    b['status'] = 'BOARDED'
    touch(b)
    return ok_object(ser_booking(b))
