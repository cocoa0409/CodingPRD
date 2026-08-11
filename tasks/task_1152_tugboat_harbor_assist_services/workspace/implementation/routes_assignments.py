"""Tug assignments: propose, confirm, release, list, get."""
from flask import Blueprint, request

from db import store, new_id, stamp_new, touch, now
from errors import ApiError
from util import (
    authenticate, require_roles, not_found, ok_object, ok_list,
    json_body, Check, get_dt, get_occ, half_open_overlap,
    parse_pagination, check_enum_filter, page_slice,
)
from calc import ser_assignment, latest_inspection_overall

bp = Blueprint('assignments', __name__)

ASSIGNMENT_STATUSES = {'PROPOSED', 'CONFIRMED', 'ACTIVE', 'RELEASED', 'SUPERSEDED'}
ASSIGNMENT_TERMINAL = {'RELEASED', 'SUPERSEDED'}
OPEN_STATUSES = {'PROPOSED', 'CONFIRMED', 'ACTIVE'}


def _load_assignment(aid):
    a = store.tug_assignments.get(aid)
    if a is None:
        not_found('tug assignment')
    return a


@bp.route('/api/tug-assignments', methods=['POST'])
def create_assignment():
    _, role = authenticate()
    require_roles(role, ('PortDispatcher',))
    body = json_body()
    c = Check()
    # Existence (stage 4), left to right: job_order_id, then tug_id.
    raw_job = body.get('job_order_id')
    job = None
    if raw_job is None or not isinstance(raw_job, str):
        c.bad_request = True
    else:
        job = store.job_orders.get(raw_job)
        if job is None:
            not_found('job order')
    raw_tug = body.get('tug_id')
    tug = None
    if raw_tug is None or not isinstance(raw_tug, str):
        c.bad_request = True
    else:
        tug = store.tugs.get(raw_tug)
        if tug is None:
            not_found('tug')
    # OCC (stage 5) on the owning job.
    if job is not None:
        get_occ(body, 'expected_job_order_version', job['version'], c)
    # From-state (stage 7): job must admit a new assignment.
    if job is not None and job['status'] not in ('REQUESTED', 'CONFIRMED'):
        raise ApiError('ERR_INVALID_STATE', 409,
                       f"Cannot propose an assignment for a job in state {job['status']}")
    # Business safety (10): tug must be AVAILABLE.
    if tug is not None and tug['operational_status'] != 'AVAILABLE':
        raise ApiError('ERR_TUG_UNAVAILABLE', 409,
                       'Tug is not AVAILABLE')
    ws = get_dt(body, 'window_start', c)
    we = get_dt(body, 'window_end', c)
    # Temporal (13): half-open tug-calendar conflict.
    if ws is not None and we is not None and tug is not None:
        for a in store.tug_assignments.values():
            if (a['tug_id'] == tug['id'] and a['status'] in OPEN_STATUSES
                    and half_open_overlap(ws, we, a['window_start'], a['window_end'])):
                raise ApiError('ERR_TUG_WINDOW_CONFLICT', 409,
                               'Window overlaps an existing assignment of this tug')
    # Constraint (19): no duplicate tug on the job.
    if job is not None and tug is not None:
        for a in store.tug_assignments.values():
            if (a['job_order_id'] == job['id'] and a['tug_id'] == tug['id']
                    and a['status'] in OPEN_STATUSES):
                raise ApiError('ERR_DUPLICATE_TUG_ASSIGNMENT', 409,
                               'Job already has an open assignment for this tug')
    if ws is not None and we is not None and we <= ws:
        c.bad_request = True
    c.raise_deferred()
    rec = {
        'id': new_id(), 'job_order_id': raw_job, 'tug_id': raw_tug,
        'window_start': ws, 'window_end': we,
        'participated': False, 'status': 'PROPOSED',
    }
    stamp_new(rec)
    store.tug_assignments[rec['id']] = rec
    # A successful proposal advances the owning job's version (PRD §3.3).
    touch(job)
    return ok_object(ser_assignment(rec), 201)


@bp.route('/api/tug-assignments', methods=['GET'])
def list_assignments():
    authenticate()
    c = Check()
    limit, offset = parse_pagination(c)
    status = check_enum_filter('status', ASSIGNMENT_STATUSES, c)
    job_id = request.args.get('job_order_id')
    tug_id = request.args.get('tug_id')
    c.raise_deferred()
    recs = [a for a in store.tug_assignments.values()
            if (status is None or a['status'] == status)
            and (job_id is None or a['job_order_id'] == job_id)
            and (tug_id is None or a['tug_id'] == tug_id)]
    page, total = page_slice(recs, limit, offset)
    return ok_list([ser_assignment(a) for a in page], limit, offset, total)


@bp.route('/api/tug-assignments/<aid>', methods=['GET'])
def get_assignment(aid):
    authenticate()
    return ok_object(ser_assignment(_load_assignment(aid)))


@bp.route('/api/tug-assignments/<aid>/confirm', methods=['POST'])
def confirm_assignment(aid):
    uid, role = authenticate()
    require_roles(role, ('TugCaptain',))
    a = _load_assignment(aid)
    if a['tug_id'] != uid:
        raise ApiError('ERR_ASSIGNMENT_NOT_OWNED', 403,
                       'TugCaptain may only confirm assignments of their own tug')
    if a['status'] in ASSIGNMENT_TERMINAL:
        raise ApiError('ERR_ALREADY_TERMINAL', 409,
                       f"Assignment is in terminal state {a['status']}")
    if a['status'] != 'PROPOSED':
        raise ApiError('ERR_INVALID_STATE', 409,
                       f"Cannot confirm an assignment in state {a['status']}")
    tug = store.tugs[a['tug_id']]
    if tug['operational_status'] != 'AVAILABLE':
        raise ApiError('ERR_TUG_UNAVAILABLE', 409, 'Tug is not AVAILABLE')
    latest = latest_inspection_overall(tug['id'])
    if (latest is None or latest['outcome'] != 'PASSED'
            or not (latest['next_due_at'] > now())):
        raise ApiError('ERR_GEAR_INSPECTION_OVERDUE', 409,
                       'Latest gear inspection is not current and PASSED')
    a['status'] = 'CONFIRMED'
    touch(a)
    return ok_object(ser_assignment(a))


@bp.route('/api/tug-assignments/<aid>/release', methods=['POST'])
def release_assignment(aid):
    _, role = authenticate()
    require_roles(role, ('PortDispatcher',))
    a = _load_assignment(aid)
    if a['status'] in ASSIGNMENT_TERMINAL:
        raise ApiError('ERR_ALREADY_TERMINAL', 409,
                       f"Assignment is in terminal state {a['status']}")
    if a['status'] != 'CONFIRMED':
        raise ApiError('ERR_INVALID_STATE', 409,
                       f"Cannot release an assignment in state {a['status']}")
    a['status'] = 'RELEASED'
    touch(a)
    return ok_object(ser_assignment(a))
