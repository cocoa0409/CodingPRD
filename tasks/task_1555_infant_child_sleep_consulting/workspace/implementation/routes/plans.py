from flask import Blueprint

from auth import user_context, require_role, forbidden, check_parent_owns_case
from db import store, base_fields, register, touch
from domain import (ser_plan, case_age_band, ALLOWED_METHODS, current_plan)
from envelope import ok, paginate
from errors import ApiError
from validators import body, req_int, req_enum, opt_str
from routes.cases import load_case

bp = Blueprint('plans', __name__)

METHODS = ('GENTLE_NO_CRY', 'FERBER_GRADUATED', 'CHAIR_METHOD', 'EXTINCTION')
PLAN_CREATE_CASE_STATES = ('PLANNING', 'ACTIVE_SUPPORT', 'NEEDS_ATTENTION')


@bp.post('/cases/<caseId>/plans')
def create_plan(caseId):
    uid, role = user_context()
    require_role(role, 'Consultant')
    data = body()
    method = req_enum(data, 'method', METHODS)
    target_wakes = req_int(data, 'target_night_wake_count', min_v=0)
    target_stretch = req_int(data, 'target_longest_stretch_minutes', min_v=1)
    notes = opt_str(data, 'notes')
    expected_version = req_int(data, 'expected_case_version')
    case = load_case(caseId)
    if case['consultant_id'] != uid:
        forbidden('Only the assigned consultant may author plans')
    # Optimistic concurrency guard on ClientCase.version (PRD §2.7).
    if expected_version != case['version']:
        raise ApiError('ERR_STALE_VERSION', 412,
                       'expected_case_version does not match the case version')
    if case['status'] not in PLAN_CREATE_CASE_STATES:
        raise ApiError('ERR_CASE_INVALID_STATE', 409,
                       'Plan creation requires the case to be in PLANNING, '
                       'ACTIVE_SUPPORT or NEEDS_ATTENTION')
    # Method-age safety against the case's current age band (stage 6).
    band = case_age_band(case)
    if method not in ALLOWED_METHODS[band]:
        raise ApiError('ERR_METHOD_NOT_AGE_APPROPRIATE', 422,
                       'Method {} is not permitted for age band {}'.format(method, band))
    # Supersede the case's current ACTIVE / NEEDS_ADJUSTMENT plans.
    for p in store.plans.values():
        if p['case_id'] == case['id'] and p['status'] in ('ACTIVE', 'NEEDS_ADJUSTMENT'):
            p['status'] = 'SUPERSEDED'
            touch(p)
    existing_seq = [p['plan_sequence'] for p in store.plans.values()
                    if p['case_id'] == case['id']]
    plan = base_fields()
    plan.update({
        'case_id': case['id'],
        'plan_sequence': (max(existing_seq) + 1) if existing_seq else 1,
        'age_band': band,
        'method': method,
        'target_night_wake_count': target_wakes,
        'target_longest_stretch_minutes': target_stretch,
        'notes': notes,
        'status': 'ACTIVE',
    })
    register(store.plans, plan)
    if case['status'] in ('PLANNING', 'NEEDS_ATTENTION'):
        case['status'] = 'ACTIVE_SUPPORT'
    touch(case)
    return ok(ser_plan(plan), status=201)


@bp.get('/cases/<caseId>/plans')
def list_case_plans(caseId):
    uid, role = user_context()
    require_role(role, 'PracticeAdmin', 'Consultant', 'Parent')
    case = load_case(caseId)
    check_parent_owns_case(uid, role, case)
    rows = [p for p in store.plans.values() if p['case_id'] == case['id']]
    return paginate(rows, ser_plan)


@bp.post('/plans/<planId>/resume')
def resume_plan(planId):
    uid, role = user_context()
    require_role(role, 'Consultant')
    plan = store.plans.get(planId)
    if plan is None:
        raise ApiError('ERR_PLAN_NOT_FOUND', 404, 'Plan not found')
    case = store.cases.get(plan['case_id'])
    if case is None:
        raise ApiError('ERR_CASE_NOT_FOUND', 404, 'Case not found')
    if case['consultant_id'] != uid:
        forbidden('Only the assigned consultant may resume the plan')
    if plan['status'] != 'NEEDS_ADJUSTMENT':
        raise ApiError('ERR_PLAN_INVALID_STATE', 409,
                       'Resume requires the plan to be in NEEDS_ADJUSTMENT')
    plan['status'] = 'ACTIVE'
    touch(plan)
    latest = current_plan(case['id'])
    if case['status'] == 'NEEDS_ATTENTION' and latest is not None \
            and latest['id'] == plan['id']:
        case['status'] = 'ACTIVE_SUPPORT'
        touch(case)
    return ok(ser_plan(plan))
