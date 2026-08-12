"""Job orders and their lifecycle actions."""
from decimal import Decimal

from flask import Blueprint, request

from db import store, new_id, stamp_new, touch, now
from errors import ApiError
from util import (
    authenticate, require_roles, not_found, ok_object, ok_list,
    json_body, Check, get_str, get_enum, get_dt, get_occ,
    parse_pagination, check_enum_filter, page_slice,
)
from calc import (
    ser_job, required_bollard_pull, any_active_restriction_overlaps,
    release_assignments_on_cancel, cancel_bookings_on_cancel,
    supersede_on_amend_from_confirmed, activate_assignments_on_start,
    settle_on_complete,
)

bp = Blueprint('jobs', __name__)

MANEUVER_TYPES = {'DOCKING', 'UNDOCKING', 'SHIFTING', 'ESCORT', 'TOWAGE'}
JOB_STATUSES = {'REQUESTED', 'CONFIRMED', 'DISPATCHED', 'ON_HOLD',
                'IN_PROGRESS', 'COMPLETED', 'INVOICED', 'CANCELLED'}
JOB_TERMINAL = {'INVOICED', 'CANCELLED'}


def _load_job(jid):
    job = store.job_orders.get(jid)
    if job is None:
        not_found('job order')
    return job


def _guard_terminal(job):
    if job['status'] in JOB_TERMINAL:
        raise ApiError('ERR_ALREADY_TERMINAL', 409,
                       f"Job order is in terminal state {job['status']}")


def _tariff_effective(tariff, start):
    return tariff['effective_from'] <= start <= tariff['effective_to']


# ------------------------------------------------------------------ CRUD

@bp.route('/api/job-orders', methods=['POST'])
def create_job():
    uid, role = authenticate()
    require_roles(role, ('VesselAgent',))
    body = json_body()
    c = Check()
    # Ownership (stage 3) runs on the raw body vessel_id, before existence.
    raw_vessel = body.get('vessel_id')
    if raw_vessel is None:
        c.bad_request = True
    elif not isinstance(raw_vessel, str):
        c.bad_request = True
    elif raw_vessel != uid:
        raise ApiError('ERR_JOB_NOT_OWNED', 403,
                       'VesselAgent may only order for their own vessel')
    # Existence (stage 4), left to right: vessel_id, then tariff_rate_id.
    vessel = None
    if isinstance(raw_vessel, str):
        vessel = store.vessels.get(raw_vessel)
        if vessel is None:
            not_found('vessel')
    tariff = None
    raw_tariff = body.get('tariff_rate_id')
    if raw_tariff is None or not isinstance(raw_tariff, str):
        c.bad_request = True
    else:
        tariff = store.tariff_rates.get(raw_tariff)
        if tariff is None:
            not_found('tariff rate')
    maneuver = get_enum(body, 'maneuver_type', MANEUVER_TYPES, c)
    start = get_dt(body, 'scheduled_start', c)
    end = get_dt(body, 'scheduled_end', c)
    # Temporal (stage 9): window-in-past (16) before window-shape (17).
    if start is not None and start < now():
        raise ApiError('ERR_WINDOW_IN_PAST', 422,
                       'scheduled_start lies before the current logical clock')
    if start is not None and end is not None and end <= start:
        raise ApiError('ERR_JOB_WINDOW_INVALID', 422,
                       'scheduled_end must be strictly after scheduled_start')
    # Business referential (stage 10, rule 26): tariff effectiveness.
    if tariff is not None and start is not None and not _tariff_effective(tariff, start):
        raise ApiError('ERR_TARIFF_NOT_EFFECTIVE', 422,
                       'Tariff is not effective at scheduled_start')
    # Shape (stages 27/28) run deliberately last.
    c.raise_deferred()
    rec = {
        'id': new_id(), 'vessel_id': raw_vessel, 'tariff_rate_id': raw_tariff,
        'maneuver_type': maneuver, 'scheduled_start': start, 'scheduled_end': end,
        'required_bollard_pull_tons': required_bollard_pull(vessel, maneuver),
        'actual_start': None, 'actual_end': None,
        'had_weather_hold': False, 'needs_reassignment': False,
        'cancel_reason': None, 'status': 'REQUESTED',
    }
    stamp_new(rec)
    store.job_orders[rec['id']] = rec
    return ok_object(ser_job(rec), 201)


@bp.route('/api/job-orders', methods=['GET'])
def list_jobs():
    authenticate()
    c = Check()
    limit, offset = parse_pagination(c)
    status = check_enum_filter('status', JOB_STATUSES, c)
    vessel_id = request.args.get('vessel_id')
    tariff_id = request.args.get('tariff_rate_id')
    c.raise_deferred()
    recs = [j for j in store.job_orders.values()
            if (status is None or j['status'] == status)
            and (vessel_id is None or j['vessel_id'] == vessel_id)
            and (tariff_id is None or j['tariff_rate_id'] == tariff_id)]
    page, total = page_slice(recs, limit, offset)
    return ok_list([ser_job(j) for j in page], limit, offset, total)


@bp.route('/api/job-orders/<jid>', methods=['GET'])
def get_job(jid):
    authenticate()
    return ok_object(ser_job(_load_job(jid)))


# ------------------------------------------------------------------ actions

@bp.route('/api/job-orders/<jid>/amend', methods=['POST'])
def amend_job(jid):
    uid, role = authenticate()
    require_roles(role, ('VesselAgent',))
    job = _load_job(jid)
    if job['vessel_id'] != uid:
        raise ApiError('ERR_JOB_NOT_OWNED', 403,
                       'VesselAgent may only amend their own vessel\'s job')
    body = json_body()
    c = Check()
    # Existence of body FK before OCC (stage 4 < stage 5).
    new_tariff = None
    if 'tariff_rate_id' in body and body['tariff_rate_id'] is not None:
        if not isinstance(body['tariff_rate_id'], str):
            c.bad_request = True
        else:
            new_tariff = store.tariff_rates.get(body['tariff_rate_id'])
            if new_tariff is None:
                not_found('tariff rate')
    get_occ(body, 'expected_job_order_version', job['version'], c)
    _guard_terminal(job)
    if job['status'] not in ('REQUESTED', 'CONFIRMED'):
        raise ApiError('ERR_INVALID_STATE', 409,
                       f"Cannot amend a job in state {job['status']}")
    was_confirmed = job['status'] == 'CONFIRMED'
    start = get_dt(body, 'scheduled_start', c, required=False)
    end = get_dt(body, 'scheduled_end', c, required=False)
    maneuver = get_enum(body, 'maneuver_type', MANEUVER_TYPES, c, required=False)
    eff_start = start if start is not None else job['scheduled_start']
    eff_end = end if end is not None else job['scheduled_end']
    eff_maneuver = maneuver if maneuver is not None else job['maneuver_type']
    eff_tariff = new_tariff if new_tariff is not None else store.tariff_rates[job['tariff_rate_id']]
    if eff_end <= eff_start:
        raise ApiError('ERR_JOB_WINDOW_INVALID', 422,
                       'scheduled_end must be strictly after scheduled_start')
    if not _tariff_effective(eff_tariff, eff_start):
        raise ApiError('ERR_TARIFF_NOT_EFFECTIVE', 422,
                       'Tariff is not effective at scheduled_start')
    c.raise_deferred()
    job['scheduled_start'] = eff_start
    job['scheduled_end'] = eff_end
    job['maneuver_type'] = eff_maneuver
    if new_tariff is not None:
        job['tariff_rate_id'] = new_tariff['id']
    vessel = store.vessels[job['vessel_id']]
    job['required_bollard_pull_tons'] = required_bollard_pull(vessel, eff_maneuver)
    if was_confirmed:
        supersede_on_amend_from_confirmed(job)
    job['status'] = 'REQUESTED'
    touch(job)
    return ok_object(ser_job(job))


@bp.route('/api/job-orders/<jid>/confirm', methods=['POST'])
def confirm_job(jid):
    _, role = authenticate()
    require_roles(role, ('PortDispatcher',))
    job = _load_job(jid)
    _guard_terminal(job)
    if job['status'] != 'REQUESTED':
        raise ApiError('ERR_INVALID_STATE', 409,
                       f"Cannot confirm a job in state {job['status']}")
    if any_active_restriction_overlaps(job['scheduled_start'], job['scheduled_end']):
        raise ApiError('ERR_WEATHER_RESTRICTED', 409,
                       'An ACTIVE weather restriction overlaps the job window')
    tariff = store.tariff_rates[job['tariff_rate_id']]
    if not _tariff_effective(tariff, job['scheduled_start']):
        raise ApiError('ERR_TARIFF_NOT_EFFECTIVE', 422,
                       'Tariff is not effective at scheduled_start')
    job['status'] = 'CONFIRMED'
    touch(job)
    return ok_object(ser_job(job))


@bp.route('/api/job-orders/<jid>/dispatch', methods=['POST'])
def dispatch_job(jid):
    _, role = authenticate()
    require_roles(role, ('PortDispatcher',))
    job = _load_job(jid)
    _guard_terminal(job)
    if job['status'] != 'CONFIRMED':
        raise ApiError('ERR_INVALID_STATE', 409,
                       f"Cannot dispatch a job in state {job['status']}")
    # Business safety (12) weather before constraints (20, 21).
    if any_active_restriction_overlaps(job['scheduled_start'], job['scheduled_end']):
        raise ApiError('ERR_WEATHER_RESTRICTED', 409,
                       'An ACTIVE weather restriction overlaps the job window')
    total_pull = Decimal('0')
    for a in store.tug_assignments.values():
        if a['job_order_id'] == job['id'] and a['status'] == 'CONFIRMED':
            tug = store.tugs[a['tug_id']]
            total_pull += Decimal(str(tug['bollard_pull_tons']))
    if total_pull < Decimal(str(job['required_bollard_pull_tons'])):
        raise ApiError('ERR_INSUFFICIENT_BOLLARD_PULL', 422,
                       'Confirmed assignments do not meet required bollard pull')
    if not any(b['job_order_id'] == job['id'] and b['status'] == 'CONFIRMED'
               for b in store.pilot_bookings.values()):
        raise ApiError('ERR_PILOT_BOOKING_NOT_CONFIRMED', 409,
                       'No CONFIRMED pilot booking exists for the job')
    job['status'] = 'DISPATCHED'
    job['needs_reassignment'] = False
    touch(job)
    return ok_object(ser_job(job))


@bp.route('/api/job-orders/<jid>/start', methods=['POST'])
def start_job(jid):
    _, role = authenticate()
    require_roles(role, ('PortDispatcher',))
    job = _load_job(jid)
    _guard_terminal(job)
    if job['status'] != 'DISPATCHED':
        raise ApiError('ERR_INVALID_STATE', 409,
                       f"Cannot start a job in state {job['status']}")
    job['status'] = 'IN_PROGRESS'
    job['actual_start'] = now()
    activate_assignments_on_start(job)
    touch(job)
    return ok_object(ser_job(job))


@bp.route('/api/job-orders/<jid>/complete', methods=['POST'])
def complete_job(jid):
    _, role = authenticate()
    require_roles(role, ('PortDispatcher',))
    job = _load_job(jid)
    _guard_terminal(job)
    if job['status'] != 'IN_PROGRESS':
        raise ApiError('ERR_INVALID_STATE', 409,
                       f"Cannot complete a job in state {job['status']}")
    job['status'] = 'COMPLETED'
    job['actual_end'] = now()
    settle_on_complete(job)  # releases assignments, settles bookings, mints invoice, vessel balance
    touch(job)
    return ok_object(ser_job(job))


@bp.route('/api/job-orders/<jid>/cancel', methods=['POST'])
def cancel_job(jid):
    uid, role = authenticate()
    require_roles(role, ('VesselAgent', 'PortDispatcher'))
    job = _load_job(jid)
    if role == 'VesselAgent' and job['vessel_id'] != uid:
        raise ApiError('ERR_JOB_NOT_OWNED', 403,
                       'VesselAgent may only cancel their own vessel\'s job')
    body = json_body()
    c = Check()
    reason = get_str(body, 'cancel_reason', c, required=False)
    _guard_terminal(job)
    if job['status'] not in ('REQUESTED', 'CONFIRMED', 'DISPATCHED', 'ON_HOLD'):
        raise ApiError('ERR_INVALID_STATE', 409,
                       f"Cannot cancel a job in state {job['status']}")
    c.raise_deferred()
    if reason is not None:
        job['cancel_reason'] = reason
    release_assignments_on_cancel(job)
    cancel_bookings_on_cancel(job)
    job['status'] = 'CANCELLED'
    touch(job)
    return ok_object(ser_job(job))
