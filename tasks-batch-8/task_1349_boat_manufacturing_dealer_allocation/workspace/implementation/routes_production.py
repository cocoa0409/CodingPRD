"""Production planning: runs, the season close checkpoint, and build slots."""
from datetime import datetime, timedelta, timezone

from flask import Blueprint, request

from store import DB, CLOCK, fmt_dt, new_rec, serialize, touch
from services import carrying_for_hull
from store import recount_allocation
from util import (ApiError, respond, list_response, auth_context, require_roles,
                  json_body, need, present, as_str, as_int, as_enum, as_date,
                  as_datetime, invalid, get_or_404)

bp = Blueprint('production', __name__)

SEASONS = {'PEAK', 'SHOULDER', 'OFF_PEAK'}


# ---------------------------------------------------------------- runs
@bp.post('/production-runs')
def create_run():
    uid, role = auth_context()
    require_roles(role, 'ProductionPlanner')
    data = json_body()
    line = as_str(need(data, 'plant_line_code'), 'plant_line_code')
    season = as_enum(need(data, 'season'), 'season', SEASONS)
    start = as_date(need(data, 'build_week_start'), 'build_week_start')
    end = as_date(need(data, 'build_week_end'), 'build_week_end')
    if end != start + timedelta(days=7):
        invalid('build_week_end must equal build_week_start + 7 days exactly')
    cutoff = as_datetime(need(data, 'option_change_cutoff_at'),
                         'option_change_cutoff_at')
    # PRD §3.3: cutoff no later than the end of the final build day; the run
    # occupies [start, end) so the final build day ends at end 00:00 UTC.
    final_day_end = datetime(end.year, end.month, end.day, tzinfo=timezone.utc)
    if cutoff > final_day_end:
        invalid('option_change_cutoff_at must be <= end of the final build day')
    # family 10: half-open windows on the same line may not overlap;
    # adjacent end == start is permitted.
    for o in DB['runs'].values():
        if o['plant_line_code'] == line and start < o['_end'] and o['_start'] < end:
            raise ApiError(409, 'ERR_LINE_WINDOW_OVERLAP',
                           'Overlapping half-open run window on the same plant line')
    rec = new_rec({
        'plant_line_code': line,
        'season': season,
        'build_week_start': start.isoformat(),
        'build_week_end': end.isoformat(),
        'option_change_cutoff_at': fmt_dt(cutoff),
        'status': 'OPEN',
        'total_carrying_actual_cents': 0,
        'total_carrying_seasonal_cents': 0,
        'closed_at': None,
    })
    rec['_start'] = start
    rec['_end'] = end
    rec['_cutoff'] = cutoff
    DB['runs'][rec['id']] = rec
    return respond(serialize(rec), 201)


@bp.get('/production-runs')
def list_runs():
    auth_context()
    items = list(DB['runs'].values())
    line = request.args.get('plant_line_code')
    if line is not None:
        items = [r for r in items if r['plant_line_code'] == line]
    status = request.args.get('status')
    if status is not None:
        items = [r for r in items if r['status'] == status]
    return list_response(items, serialize)


@bp.get('/production-runs/<rid>')
def get_run(rid):
    auth_context()
    rec = get_or_404(DB['runs'], rid, 'ERR_RUN_NOT_FOUND', 'ProductionRun')
    return respond(serialize(rec), 200)


@bp.post('/production-runs/<rid>/close')
def close_run(rid):
    uid, role = auth_context()
    require_roles(role, 'ProductionPlanner')
    run = get_or_404(DB['runs'], rid, 'ERR_RUN_NOT_FOUND', 'ProductionRun')
    if run['status'] != 'OPEN':
        raise ApiError(409, 'ERR_RUN_NOT_OPEN', 'Run is not OPEN')
    slot_ids = {s['id'] for s in DB['slots'].values() if s['run_id'] == rid}

    # Act 1: carrying accrual over AT_PLANT hulls on this run's slots.
    total_actual = 0
    total_seasonal = 0
    for hull in DB['hulls'].values():
        if hull['slot_id'] in slot_ids and hull['delivery_status'] == 'AT_PLANT':
            actual, seasonal = carrying_for_hull(hull, run)
            hull['carrying_cost_cents'] += seasonal
            touch(hull)
            total_actual += actual
            total_seasonal += seasonal
    run['total_carrying_actual_cents'] = total_actual
    run['total_carrying_seasonal_cents'] = total_seasonal

    # Act 2: every slot -> RELEASED (terminal).
    for s in DB['slots'].values():
        if s['run_id'] == rid:
            s['status'] = 'RELEASED'
            touch(s)

    # Act 3: ALLOCATED orders on this run's slots -> CANCELLED, fee waived,
    # full refund; NO waitlist promotion fires at close. COMMITTED orders
    # persist untouched.
    for o in list(DB['orders'].values()):
        if o['status'] == 'ALLOCATED' and o['slot_id'] in slot_ids:
            o['status'] = 'CANCELLED'
            o['cancel_fee_cents'] = 0
            o['refund_cents'] = o['deposit_paid_cents']
            touch(o)
            dealer = DB['dealers'][o['dealer_id']]
            dealer['allocation_used'] = recount_allocation(dealer['id'])
            touch(dealer)

    # Act 4: run closes.
    run['status'] = 'CLOSED'
    run['closed_at'] = fmt_dt(CLOCK.now())
    touch(run)
    return respond(serialize(run), 200)


# ---------------------------------------------------------------- slots
@bp.post('/build-slots')
def create_slot():
    uid, role = auth_context()
    require_roles(role, 'ProductionPlanner')
    data = json_body()
    run_id = as_str(need(data, 'run_id'), 'run_id')
    slot_code = as_str(need(data, 'slot_code'), 'slot_code')
    capacity = as_int(need(data, 'capacity_hours'), 'capacity_hours')
    if capacity <= 0:
        invalid('capacity_hours must be > 0')
    run = get_or_404(DB['runs'], run_id, 'ERR_RUN_NOT_FOUND', 'ProductionRun')
    if run['status'] != 'OPEN':
        raise ApiError(409, 'ERR_RUN_NOT_OPEN',
                       'Slots may only be added to an OPEN run')
    if any(s['run_id'] == run_id and s['slot_code'] == slot_code
           for s in DB['slots'].values()):
        invalid('slot_code must be unique within a run')
    rec = new_rec({
        'run_id': run_id,
        'slot_code': slot_code,
        'capacity_hours': capacity,
        'reserved_hours': 0,
        'status': 'OPEN',
    })
    DB['slots'][rec['id']] = rec
    return respond(serialize(rec), 201)


@bp.get('/build-slots')
def list_slots():
    auth_context()
    items = list(DB['slots'].values())
    run_id = request.args.get('run_id')
    if run_id is not None:
        items = [s for s in items if s['run_id'] == run_id]
    return list_response(items, serialize)


@bp.get('/build-slots/<sid>')
def get_slot(sid):
    auth_context()
    rec = get_or_404(DB['slots'], sid, 'ERR_SLOT_NOT_FOUND', 'BuildSlot')
    return respond(serialize(rec), 200)
