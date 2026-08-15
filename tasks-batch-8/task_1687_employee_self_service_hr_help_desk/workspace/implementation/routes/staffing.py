"""Seasonal staffing windows and agent shifts."""
from flask import Blueprint

import db
from db import bump
from errors import ApiError
from middleware import authenticate, require_roles
from response import ok_list, ok_object
from serializers import ser_agent_shift, ser_staffing_window
from services.coverage import compute_coverage
from validate import (enum_filter, get_body, opt_number, parse_pagination,
                      req_datetime, req_number, req_str, str_filter, paginate,
                      MISSING)

bp = Blueprint('staffing', __name__)

WINDOW_STATUSES = ('PLANNED', 'ACTIVE', 'COMPLETED', 'CANCELLED')
SHIFT_STATUSES = ('SCHEDULED', 'CANCELLED')
_WINDOW_READ_ROLES = ('WorkforcePlanner', 'HRServicesAdmin', 'HelpDeskAgent',
                      'SpecialistAgent', 'SensitiveCaseManager')
_SHIFT_READ_ROLES = ('WorkforcePlanner', 'HRServicesAdmin')


def _ser_window(w):
    c1, c2, posture = compute_coverage(w)
    return ser_staffing_window(w, c1, c2, posture)


@bp.post('/staffing-windows')
def create_window():
    ctx = authenticate()
    require_roles(ctx, 'WorkforcePlanner')
    body = get_body()
    team_id = req_str(body, 'team_id')
    name = req_str(body, 'name')
    window_start = req_datetime(body, 'window_start')
    window_end = req_datetime(body, 'window_end')
    req_t1 = req_number(body, 'required_t1_hours', minimum=0)
    req_t2 = req_number(body, 'required_t2_hours', minimum=0)
    multiplier = opt_number(body, 'sla_multiplier', default=1.0, minimum=1.0)
    if team_id not in db.teams:
        raise ApiError('ERR_TEAM_NOT_FOUND', 404, 'team_id references no team')
    # Closed-interval overlap per team among PLANNED/ACTIVE windows; touching
    # endpoints conflict (tier 8, ahead of the temporal bounds check).
    for w in db.staffing_windows.values():
        if w['team_id'] != team_id or w['status'] not in ('PLANNED', 'ACTIVE'):
            continue
        if window_start <= w['window_end'] and w['window_start'] <= window_end:
            raise ApiError('ERR_WINDOW_OVERLAP', 409,
                           'window overlaps an existing window of the team')
    if window_end < window_start:
        raise ApiError('ERR_INVALID_TIME_RANGE', 422,
                       'window_end must not precede window_start')
    now = db.now()
    status = 'ACTIVE' if window_start <= now <= window_end else 'PLANNED'
    rec = {
        'team_id': team_id,
        'name': name,
        'window_start': window_start,
        'window_end': window_end,
        'required_t1_hours': req_t1,
        'required_t2_hours': req_t2,
        'sla_multiplier': multiplier,
        'status': status,
    }
    db.stamp_common(rec)
    db.staffing_windows[rec['id']] = rec
    return ok_object(_ser_window(rec), status=201)


@bp.get('/staffing-windows')
def list_windows():
    ctx = authenticate()
    require_roles(ctx, *_WINDOW_READ_ROLES)
    team_f = str_filter('team_id')
    status_f = enum_filter('status', WINDOW_STATUSES)
    limit, offset = parse_pagination()
    rows = list(db.staffing_windows.values())
    if team_f is not MISSING:
        rows = [w for w in rows if w['team_id'] == team_f]
    if status_f is not MISSING:
        rows = [w for w in rows if w['status'] == status_f]
    rows.sort(key=lambda w: (w['created_at'], w['_seq']))
    page, total = paginate(rows, limit, offset)
    return ok_list([_ser_window(w) for w in page], limit, offset, total)


@bp.get('/staffing-windows/<window_id>')
def get_window(window_id):
    ctx = authenticate()
    require_roles(ctx, *_WINDOW_READ_ROLES)
    w = db.staffing_windows.get(window_id)
    if w is None:
        raise ApiError('ERR_WINDOW_NOT_FOUND', 404, 'no such staffing window')
    return ok_object(_ser_window(w))


@bp.post('/staffing-windows/<window_id>/cancel')
def cancel_window(window_id):
    ctx = authenticate()
    require_roles(ctx, 'WorkforcePlanner')
    w = db.staffing_windows.get(window_id)
    if w is None:
        raise ApiError('ERR_WINDOW_NOT_FOUND', 404, 'no such staffing window')
    if w['status'] not in ('PLANNED', 'ACTIVE'):
        raise ApiError('ERR_WINDOW_INVALID_STATE', 409,
                       'only PLANNED or ACTIVE windows may be cancelled')
    # Shifts remain on record; the window stops applying its sla_multiplier.
    w['status'] = 'CANCELLED'
    bump(w)
    return ok_object(_ser_window(w))


# ---- Agent shifts ------------------------------------------------------------

@bp.post('/agent-shifts')
def create_shift():
    ctx = authenticate()
    require_roles(ctx, 'WorkforcePlanner')
    body = get_body()
    agent_id = req_str(body, 'agent_id')
    window_id = req_str(body, 'staffing_window_id')
    shift_start = req_datetime(body, 'shift_start')
    shift_end = req_datetime(body, 'shift_end')
    agent = db.agents.get(agent_id)
    if agent is None:
        raise ApiError('ERR_AGENT_NOT_FOUND', 404, 'agent_id references no agent')
    window = db.staffing_windows.get(window_id)
    if window is None:
        raise ApiError('ERR_WINDOW_NOT_FOUND', 404,
                       'staffing_window_id references no window')
    # Half-open overlap against the agent's other SCHEDULED shifts (tier 8):
    # strictly overlapping conflicts; back-to-back touching is allowed.
    for s in db.agent_shifts.values():
        if s['agent_id'] != agent_id or s['status'] != 'SCHEDULED':
            continue
        if shift_start < s['shift_end'] and s['shift_start'] < shift_end:
            raise ApiError('ERR_SHIFT_OVERLAP', 409,
                           'shift overlaps another scheduled shift of the agent')
    # Temporal bounds (tier 9).
    if shift_end <= shift_start:
        raise ApiError('ERR_INVALID_TIME_RANGE', 422,
                       'shift_end must fall strictly after shift_start')
    if shift_start < window['window_start'] or shift_end > window['window_end']:
        raise ApiError('ERR_SHIFT_OUTSIDE_WINDOW', 422,
                       'shift must lie within the window bounds')
    # Referential usability (tier 10): the window must still accept shifts.
    if window['status'] not in ('PLANNED', 'ACTIVE'):
        raise ApiError('ERR_WINDOW_INVALID_STATE', 409,
                       'the window is not accepting shifts')
    rec = {
        'agent_id': agent_id,
        'staffing_window_id': window_id,
        'shift_start': shift_start,
        'shift_end': shift_end,
        'status': 'SCHEDULED',
    }
    db.stamp_common(rec)
    db.agent_shifts[rec['id']] = rec
    return ok_object(ser_agent_shift(rec), status=201)


@bp.get('/agent-shifts')
def list_shifts():
    ctx = authenticate()
    require_roles(ctx, *_SHIFT_READ_ROLES)
    agent_f = str_filter('agent_id')
    window_f = str_filter('staffing_window_id')
    status_f = enum_filter('status', SHIFT_STATUSES)
    limit, offset = parse_pagination()
    rows = list(db.agent_shifts.values())
    if agent_f is not MISSING:
        rows = [s for s in rows if s['agent_id'] == agent_f]
    if window_f is not MISSING:
        rows = [s for s in rows if s['staffing_window_id'] == window_f]
    if status_f is not MISSING:
        rows = [s for s in rows if s['status'] == status_f]
    rows.sort(key=lambda s: (s['created_at'], s['_seq']))
    page, total = paginate(rows, limit, offset)
    return ok_list([ser_agent_shift(s) for s in page], limit, offset, total)


@bp.get('/agent-shifts/<shift_id>')
def get_shift(shift_id):
    ctx = authenticate()
    require_roles(ctx, *_SHIFT_READ_ROLES)
    s = db.agent_shifts.get(shift_id)
    if s is None:
        raise ApiError('ERR_SHIFT_NOT_FOUND', 404, 'no such shift')
    return ok_object(ser_agent_shift(s))


@bp.post('/agent-shifts/<shift_id>/cancel')
def cancel_shift(shift_id):
    ctx = authenticate()
    require_roles(ctx, 'WorkforcePlanner')
    s = db.agent_shifts.get(shift_id)
    if s is None:
        raise ApiError('ERR_SHIFT_NOT_FOUND', 404, 'no such shift')
    if s['status'] != 'SCHEDULED':
        raise ApiError('ERR_SHIFT_INVALID_STATE', 409, 'shift is not SCHEDULED')
    s['status'] = 'CANCELLED'
    bump(s)
    return ok_object(ser_agent_shift(s))
