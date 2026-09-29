"""Shots, their five stage tasks and the earned-value read."""
from flask import Blueprint

from calc import (D, STAGES, STAGE_WEIGHT_PCT, by_created, iso, ratio4, shot_bcws_cents,
                  shot_bcwp_hours_progress, shot_bcwp_stage_weight, shot_labor_cost_cents,
                  shot_out, shot_tasks, task_out, num, recompute_shot)
from flows import (approve_task, enter_retake, fk_lookup, get_production, get_shot,
                  get_task, reconcile_production, reconcile_tasks, require_phase)
from helpers import (ALL_READ, ARTIST, ApiError, DIRECTOR, PARTNER_REP, PM,
                     READ_WITH_PARTNER, SUPERVISOR, arg, authenticate, body_json,
                     get_datetime, get_enum, get_int, get_number, get_str, paginate,
                     success, validation_error)
from store import base_row, db, now, touch

bp = Blueprint('shots', __name__)

SHOT_STATUSES = ('BLOCKED_PREPROD', 'READY', 'IN_PRODUCTION', 'COMPLETE')
TASK_STATUSES = ('NOT_STARTED', 'IN_PROGRESS', 'SUBMITTED', 'IN_REVIEW', 'RETAKE',
                 'APPROVED')
CREATE_PHASES = ('PRE_PRODUCTION', 'PRODUCTION_ACTIVE')


def new_task(shot, stage, stage_order, budgeted_hours):
    row = base_row()
    row.update({
        'shot_id': shot['id'],
        'outsource_package_id': None,
        'stage': stage,
        'stage_order': stage_order,
        'stage_weight_pct': STAGE_WEIGHT_PCT[stage],
        'status': 'NOT_STARTED',
        'budgeted_hours': budgeted_hours,
        'actual_hours': D('0.00'),
        'revision_count': 0,
        'escalated': False,
        'assigned_artist_user_id': None,
        'submitted_by_user_id': None,
        'reviewed_by_user_id': None,
        'submitted_at': None,
        'approved_at': None,
    })
    db.tasks[row['id']] = row
    return row


def task_owner_check(task, user_id, role):
    if role == ARTIST:
        if task['assigned_artist_user_id'] != user_id:
            raise ApiError('ERR_NOT_TASK_OWNER', 403, 'the task is assigned to another artist')
        return
    if role == PARTNER_REP:
        package = db.packages.get(task['outsource_package_id'])
        if package is None or package['partner_id'] != user_id:
            raise ApiError('ERR_NOT_TASK_OWNER', 403,
                           'the task is not inside a package of this partner')
        return
    raise ApiError('ERR_NOT_TASK_OWNER', 403, 'this role may not act on the task')


@bp.route('/studio/shots', methods=['POST'])
def create_shot():
    authenticate((PM,))
    body = body_json()
    production = fk_lookup(body, 'production_id', get_production)
    production_id = get_str(body, 'production_id', min_len=1)
    shot_code = get_str(body, 'shot_code', min_len=1)
    sequence_code = get_str(body, 'sequence_code', min_len=1)
    frame_count = get_int(body, 'frame_count', minimum=1)
    budget_cents = get_int(body, 'budget_cents', minimum=0)
    planned_start_at = get_datetime(body, 'planned_start_at')
    planned_finish_at = get_datetime(body, 'planned_finish_at')
    difficulty_factor = get_number(body, 'difficulty_factor', required=False, default=1.0,
                                   minimum=0.5, maximum=3.0, places=2)
    stage_budget_hours = body.get('stage_budget_hours')
    hours_map = {}
    if stage_budget_hours is not None:
        if not isinstance(stage_budget_hours, dict):
            raise validation_error('stage_budget_hours must be an object')
        for stage in STAGES:
            if stage in stage_budget_hours and stage_budget_hours[stage] is not None:
                value = get_number(stage_budget_hours, stage, exclusive_min=0, places=2)
                hours_map[stage] = D(value).quantize(D('0.01'))
    if production is None:
        production = get_production(production_id)
    require_phase(production, CREATE_PHASES)
    if not planned_start_at < planned_finish_at:
        raise ApiError('ERR_INVALID_WINDOW', 422,
                       'planned_finish_at must be strictly after planned_start_at')
    for row in db.shots.values():
        if row['production_id'] == production['id'] and row['shot_code'] == shot_code:
            raise ApiError('ERR_DUPLICATE_CODE', 409,
                           'shot_code is already in use in this production')

    shot = base_row()
    shot.update({
        'production_id': production['id'],
        'shot_code': shot_code,
        'sequence_code': sequence_code,
        'frame_count': frame_count,
        'difficulty_factor': D(difficulty_factor).quantize(D('0.01')),
        'budget_cents': budget_cents,
        'planned_start_at': planned_start_at,
        'planned_finish_at': planned_finish_at,
        'status': 'BLOCKED_PREPROD',
        'current_stage': 'LAYOUT',
        'retake_count': 0,
        'escalation_flag': False,
        'labor_cost_cents': 0,
        'render_cost_committed_cents': 0,
        'render_cost_actual_cents': 0,
        'bcwp_cents': 0,
        'acwp_cents': 0,
        'cpi': None,
    })
    db.shots[shot['id']] = shot
    for index, stage in enumerate(STAGES, start=1):
        new_task(shot, stage, index, hours_map.get(stage, D('10.00')))
    recompute_shot(shot, production)
    reconcile_production(production)
    return success(shot_out(shot), 201)


@bp.route('/studio/shots', methods=['GET'])
def list_shots():
    authenticate(ALL_READ)
    rows = list(db.shots.values())
    production_id = arg('production_id')
    if production_id is not None:
        rows = [r for r in rows if r['production_id'] == production_id]
    status = arg('status')
    if status is not None:
        rows = [r for r in rows if r['status'] == status]
    rows.sort(key=lambda s: (s['shot_code'], s['created_at'], s['_seq']))
    return paginate(rows, shot_out)


@bp.route('/studio/shots/<shot_id>', methods=['GET'])
def read_shot(shot_id):
    authenticate(ALL_READ)
    return success(shot_out(get_shot(shot_id)))


@bp.route('/studio/shots/<shot_id>/earned-value', methods=['GET'])
def shot_earned_value(shot_id):
    authenticate((PM, SUPERVISOR, DIRECTOR))
    shot = get_shot(shot_id)
    variant = arg('variant')
    if variant is None:
        variant = 'STAGE_WEIGHT'
    if variant not in ('STAGE_WEIGHT', 'HOURS_PROGRESS'):
        raise validation_error('variant must be STAGE_WEIGHT or HOURS_PROGRESS')
    tasks = shot_tasks(shot)
    bcws = shot_bcws_cents(shot)
    acwp = shot_labor_cost_cents(tasks) + shot['render_cost_actual_cents']
    if variant == 'STAGE_WEIGHT':
        bcwp = shot_bcwp_stage_weight(shot, tasks)
    else:
        bcwp = shot_bcwp_hours_progress(shot, tasks)
    return success({
        'shot_id': shot['id'],
        'variant': variant,
        'bcws_cents': bcws,
        'bcwp_cents': bcwp,
        'acwp_cents': acwp,
        'cpi': num(ratio4(bcwp, acwp)),
        'spi': num(ratio4(bcwp, bcws)),
        'computed_at': iso(now()),
    })


# ------------------------------------------------------------------ stage tasks
@bp.route('/studio/stage-tasks', methods=['GET'])
def list_stage_tasks():
    authenticate(READ_WITH_PARTNER)
    rows = list(db.tasks.values())
    shot_id = arg('shot_id')
    if shot_id is not None:
        rows = [r for r in rows if r['shot_id'] == shot_id]
    package_id = arg('outsource_package_id')
    if package_id is not None:
        rows = [r for r in rows if r['outsource_package_id'] == package_id]
    stage = arg('stage')
    if stage is not None:
        rows = [r for r in rows if r['stage'] == stage]
    status = arg('status')
    if status is not None:
        rows = [r for r in rows if r['status'] == status]
    rows.sort(key=lambda t: (t['stage_order'], t['created_at'], t['_seq']))
    return paginate(rows, task_out)


@bp.route('/studio/stage-tasks/<task_id>', methods=['GET'])
def read_stage_task(task_id):
    authenticate(READ_WITH_PARTNER)
    return success(task_out(get_task(task_id)))


@bp.route('/studio/stage-tasks/<task_id>/assign', methods=['POST'])
def assign_stage_task(task_id):
    authenticate((PM,))
    task = get_task(task_id)
    body = body_json()
    artist_user_id = get_str(body, 'assigned_artist_user_id', min_len=1)
    budgeted_hours = get_number(body, 'budgeted_hours', required=False, default=None,
                                exclusive_min=0, places=2)
    shot = db.shots.get(task['shot_id'])
    production = db.productions.get(shot['production_id']) if shot else None
    require_phase(production, ('PRODUCTION_ACTIVE',))
    if task['status'] != 'NOT_STARTED':
        raise ApiError('ERR_TASK_STATE_INVALID', 409,
                       'a task in %s may not be assigned' % task['status'])
    if task['stage_order'] > 1:
        previous = None
        for sibling in shot_tasks(shot):
            if sibling['stage_order'] == task['stage_order'] - 1:
                previous = sibling
        if previous is None or previous['status'] != 'APPROVED':
            raise ApiError('ERR_PREVIOUS_STAGE_NOT_APPROVED', 409,
                           'the previous stage of this shot is not APPROVED')
    task['status'] = 'IN_PROGRESS'
    task['assigned_artist_user_id'] = artist_user_id
    if budgeted_hours is not None:
        task['budgeted_hours'] = D(budgeted_hours).quantize(D('0.01'))
    touch(task)
    reconcile_tasks([task])
    return success(task_out(task))


@bp.route('/studio/stage-tasks/<task_id>/log-hours', methods=['POST'])
def log_hours(task_id):
    user_id, role = authenticate((ARTIST, PARTNER_REP))
    task = get_task(task_id)
    body = body_json()
    hours = get_number(body, 'hours', exclusive_min=0, places=2)
    task_owner_check(task, user_id, role)
    shot = db.shots.get(task['shot_id'])
    production = db.productions.get(shot['production_id']) if shot else None
    require_phase(production, ('PRODUCTION_ACTIVE',))
    task['actual_hours'] = (D(task['actual_hours']) + D(hours)).quantize(D('0.01'))
    touch(task)
    reconcile_tasks([task])
    return success(task_out(task))


@bp.route('/studio/stage-tasks/<task_id>/submit', methods=['POST'])
def submit_stage_task(task_id):
    user_id, role = authenticate((ARTIST, PARTNER_REP))
    task = get_task(task_id)
    body = body_json()
    hours = get_number(body, 'hours', required=False, default=None, exclusive_min=0,
                       places=2)
    task_owner_check(task, user_id, role)
    shot = db.shots.get(task['shot_id'])
    production = db.productions.get(shot['production_id']) if shot else None
    require_phase(production, ('PRODUCTION_ACTIVE',))
    if task['status'] not in ('IN_PROGRESS', 'RETAKE'):
        raise ApiError('ERR_TASK_STATE_INVALID', 409,
                       'a task in %s may not be submitted' % task['status'])
    if task['outsource_package_id'] is not None:
        package = db.packages.get(task['outsource_package_id'])
        if package is None or package['status'] != 'IN_PROGRESS':
            raise ApiError('ERR_PACKAGE_STATE_INVALID', 409,
                           'the owning outsourcing package is not IN_PROGRESS')
    if hours is not None:
        task['actual_hours'] = (D(task['actual_hours']) + D(hours)).quantize(D('0.01'))
    task['status'] = 'SUBMITTED'
    task['submitted_by_user_id'] = user_id
    task['submitted_at'] = now()
    touch(task)
    reconcile_tasks([task])
    return success(task_out(task))


@bp.route('/studio/stage-tasks/<task_id>/review-decision', methods=['POST'])
def review_stage_task(task_id):
    user_id, _role = authenticate((SUPERVISOR,))
    task = get_task(task_id)
    body = body_json()
    decision = get_enum(body, 'decision', ('APPROVED', 'RETAKE'))
    get_str(body, 'note', required=False)
    if task['submitted_by_user_id'] is not None and task['submitted_by_user_id'] == user_id:
        raise ApiError('ERR_SEGREGATION_OF_DUTIES', 403,
                       'the submitter may not decide this stage')
    shot = db.shots.get(task['shot_id'])
    production = db.productions.get(shot['production_id']) if shot else None
    require_phase(production, ('PRODUCTION_ACTIVE',))
    if task['status'] not in ('SUBMITTED', 'IN_REVIEW'):
        raise ApiError('ERR_TASK_STATE_INVALID', 409,
                       'a task in %s may not be decided' % task['status'])
    if decision == 'APPROVED':
        approve_task(task, user_id)
    else:
        task['reviewed_by_user_id'] = user_id
        enter_retake(task)
    reconcile_tasks([task])
    return success(task_out(task))
