"""Render pools, capacity admission with CRITICAL preemption, and job settlement."""
from flask import Blueprint

from calc import (D, PRIORITIES, by_created, committed_core_hours, cost_per_frame_cents,
                  job_out, plan_admission, pool_out, recompute_pool)
from flows import (fk_lookup, get_job, get_pool, get_task, reconcile_tasks, require_phase)
from helpers import (ALL_READ, ApiError, PM, arg, authenticate, body_json, get_datetime,
                     get_enum, get_int, get_number, get_str, paginate, success,
                     validation_error)
from store import base_row, db, now, touch

bp = Blueprint('render', __name__)

NOT_WRAPPED = ('PRE_PRODUCTION', 'PRODUCTION_ACTIVE', 'DELIVERY')


def _production_of_task(task):
    shot = db.shots.get(task['shot_id'])
    if shot is None:
        return None, None
    return shot, db.productions.get(shot['production_id'])


@bp.route('/studio/render-pools', methods=['POST'])
def create_pool():
    authenticate((PM,))
    body = body_json()
    name = get_str(body, 'name', min_len=1)
    total_cores = get_int(body, 'total_cores', minimum=1)
    rate = get_int(body, 'cost_per_core_hour_cents', minimum=1)
    pool = base_row()
    pool.update({
        'name': name,
        'total_cores': total_cores,
        'cost_per_core_hour_cents': rate,
        'committed_core_hours': D('0.00'),
        'reserved_job_count': 0,
    })
    db.pools[pool['id']] = pool
    return success(pool_out(pool), 201)


@bp.route('/studio/render-pools', methods=['GET'])
def list_pools():
    authenticate(ALL_READ)
    return paginate(by_created(list(db.pools.values())), pool_out)


@bp.route('/studio/render-pools/<pool_id>', methods=['GET'])
def read_pool(pool_id):
    authenticate(ALL_READ)
    return success(pool_out(get_pool(pool_id)))


# -------------------------------------------------------------------- render jobs
@bp.route('/studio/render-jobs', methods=['POST'])
def create_job():
    authenticate((PM,))
    body = body_json()
    pool = fk_lookup(body, 'render_pool_id', get_pool)
    task = fk_lookup(body, 'shot_stage_task_id', get_task)
    pool_id = get_str(body, 'render_pool_id', min_len=1)
    task_id = get_str(body, 'shot_stage_task_id', min_len=1)
    priority = get_enum(body, 'priority', PRIORITIES, required=False, default='NORMAL')
    requested_cores = get_int(body, 'requested_cores', minimum=1)
    window_start = get_datetime(body, 'window_start')
    window_end = get_datetime(body, 'window_end')
    frame_count = get_int(body, 'frame_count', minimum=1)
    seconds_per_frame = get_number(body, 'seconds_per_frame', exclusive_min=0, places=2)
    expected_version = get_int(body, 'expected_render_pool_version')
    if pool is None:
        pool = get_pool(pool_id)
    if task is None:
        task = get_task(task_id)
    if expected_version != pool['version']:
        raise ApiError('ERR_STALE_RENDER_POOL_VERSION', 412,
                       'expected_render_pool_version does not match the stored version')
    shot, production = _production_of_task(task)
    require_phase(production, ('PRODUCTION_ACTIVE',))
    if task['status'] not in ('IN_PROGRESS', 'SUBMITTED', 'IN_REVIEW', 'RETAKE'):
        raise ApiError('ERR_TASK_STATE_INVALID', 409,
                       'a task in %s may not hold farm capacity' % task['status'])
    if not window_start < window_end or window_start < now():
        raise ApiError('ERR_INVALID_WINDOW', 422,
                       'the reservation window is not a future half-open interval')
    admitted, victims = plan_admission(pool, priority, requested_cores, window_start,
                                       window_end)
    if not admitted:
        raise ApiError('ERR_RENDER_CAPACITY_EXCEEDED', 409,
                       'the pool cannot admit the requested cores over that window')
    per_frame = cost_per_frame_cents(pool, requested_cores, seconds_per_frame, priority)
    estimated = per_frame * frame_count
    if production is not None:
        exposure = (production['render_committed_cents'] + production['render_actual_cents']
                    + estimated)
        if exposure > production['render_allowance_cents']:
            raise ApiError('ERR_RENDER_BUDGET_EXCEEDED', 402,
                           'the reservation would exceed the render allowance')

    job = base_row()
    job.update({
        'render_pool_id': pool['id'],
        'shot_stage_task_id': task['id'],
        'priority': priority,
        'requested_cores': requested_cores,
        'window_start': window_start,
        'window_end': window_end,
        'frame_count': frame_count,
        'seconds_per_frame': D(seconds_per_frame).quantize(D('0.01')),
        'actual_seconds_per_frame': None,
        'frames_completed': None,
        'status': 'RESERVED',
        'cost_per_frame_cents': per_frame,
        'estimated_cost_cents': estimated,
        'final_cost_cents': None,
        'committed_core_hours': committed_core_hours(requested_cores, window_start,
                                                     window_end),
        'preempted_by_render_job_id': None,
    })
    touched_tasks = [task]
    for victim in victims:
        victim['status'] = 'PREEMPTED'
        victim['preempted_by_render_job_id'] = job['id']
        victim['final_cost_cents'] = None
        touch(victim)
        victim_task = db.tasks.get(victim['shot_stage_task_id'])
        if victim_task is not None:
            touched_tasks.append(victim_task)
    db.jobs[job['id']] = job
    recompute_pool(pool)
    touch(pool)
    reconcile_tasks(touched_tasks)
    return success(job_out(job), 201)


@bp.route('/studio/render-jobs', methods=['GET'])
def list_jobs():
    authenticate(ALL_READ)
    rows = list(db.jobs.values())
    pool_id = arg('render_pool_id')
    if pool_id is not None:
        rows = [r for r in rows if r['render_pool_id'] == pool_id]
    task_id = arg('shot_stage_task_id')
    if task_id is not None:
        rows = [r for r in rows if r['shot_stage_task_id'] == task_id]
    preempted_by = arg('preempted_by_render_job_id')
    if preempted_by is not None:
        rows = [r for r in rows if r['preempted_by_render_job_id'] == preempted_by]
    priority = arg('priority')
    if priority is not None:
        rows = [r for r in rows if r['priority'] == priority]
    status = arg('status')
    if status is not None:
        rows = [r for r in rows if r['status'] == status]
    return paginate(by_created(rows), job_out)


@bp.route('/studio/render-jobs/<job_id>', methods=['GET'])
def read_job(job_id):
    authenticate(ALL_READ)
    return success(job_out(get_job(job_id)))


@bp.route('/studio/render-jobs/<job_id>/complete', methods=['POST'])
def complete_job(job_id):
    authenticate((PM,))
    job = get_job(job_id)
    body = body_json()
    outcome = get_enum(body, 'outcome', ('COMPLETED', 'FAILED'))
    actual_seconds = get_number(body, 'actual_seconds_per_frame', exclusive_min=0,
                                places=2)
    frames_completed = get_int(body, 'frames_completed', minimum=0)
    task = db.tasks.get(job['shot_stage_task_id'])
    production = None
    if task is not None:
        _shot, production = _production_of_task(task)
    require_phase(production, NOT_WRAPPED)
    if job['status'] != 'RESERVED':
        raise ApiError('ERR_RENDER_JOB_STATE_INVALID', 409,
                       'a job in %s may not be settled' % job['status'])
    if outcome == 'COMPLETED' and frames_completed != job['frame_count']:
        raise validation_error('COMPLETED requires frames_completed to equal frame_count')
    if outcome == 'FAILED' and frames_completed >= job['frame_count']:
        raise validation_error('FAILED requires frames_completed below frame_count')
    pool = db.pools.get(job['render_pool_id'])
    per_frame = cost_per_frame_cents(pool, job['requested_cores'], actual_seconds,
                                    job['priority'])
    job['status'] = outcome
    job['actual_seconds_per_frame'] = D(actual_seconds).quantize(D('0.01'))
    job['frames_completed'] = frames_completed
    job['cost_per_frame_cents'] = per_frame
    job['final_cost_cents'] = per_frame * frames_completed
    touch(job)
    if pool is not None:
        recompute_pool(pool)
        touch(pool)
    if task is not None:
        reconcile_tasks([task])
    return success(job_out(job))


@bp.route('/studio/render-jobs/<job_id>/cancel', methods=['POST'])
def cancel_job(job_id):
    authenticate((PM,))
    job = get_job(job_id)
    task = db.tasks.get(job['shot_stage_task_id'])
    production = None
    if task is not None:
        _shot, production = _production_of_task(task)
    require_phase(production, NOT_WRAPPED)
    if job['status'] != 'RESERVED':
        raise ApiError('ERR_RENDER_JOB_STATE_INVALID', 409,
                       'a job in %s may not be cancelled' % job['status'])
    job['status'] = 'CANCELLED'
    job['frames_completed'] = 0
    job['final_cost_cents'] = None
    touch(job)
    pool = db.pools.get(job['render_pool_id'])
    if pool is not None:
        recompute_pool(pool)
        touch(pool)
    if task is not None:
        reconcile_tasks([task])
    return success(job_out(job))
