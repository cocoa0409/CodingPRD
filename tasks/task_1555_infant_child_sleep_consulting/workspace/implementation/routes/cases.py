from flask import Blueprint, request

from auth import user_context, require_role, forbidden, check_parent_owns_case
from db import store, base_fields, register, touch, now
from domain import (ser_case, ser_enrollment, consultant_active_case_count,
                    current_plan)
from envelope import ok, paginate
from errors import ApiError
from validators import body, req_str, req_int, req_enum, req_date

bp = Blueprint('cases', __name__)

DELIVERY_MODES = ('ONE_ON_ONE', 'GROUP_COURSE')


def load_case(case_id):
    case = store.cases.get(case_id)
    if case is None:
        raise ApiError('ERR_CASE_NOT_FOUND', 404, 'Case not found')
    return case


@bp.post('/cases')
def create_case():
    uid, role = user_context()
    require_role(role, 'Parent', 'PracticeAdmin')
    data = body()
    family_id = req_str(data, 'family_id')
    consultant_id = req_str(data, 'consultant_id')
    birth = req_date(data, 'child_birth_date')
    mode = req_enum(data, 'delivery_mode', DELIVERY_MODES)
    goal = req_int(data, 'guarantee_goal_night_wakings', min_v=0)
    if role == 'Parent' and family_id != uid:
        forbidden('Parent may open cases only for their own family')
    if family_id not in store.families:
        raise ApiError('ERR_FAMILY_NOT_FOUND', 404, 'family_id does not exist')
    consultant = store.consultants.get(consultant_id)
    if consultant is None:
        raise ApiError('ERR_CONSULTANT_NOT_FOUND', 404, 'consultant_id does not exist')
    # Quota (pipeline stage 9): reject when the consultant is already at capacity.
    if consultant_active_case_count(consultant_id) >= consultant['max_active_cases']:
        raise ApiError('ERR_CONSULTANT_AT_CAPACITY', 409,
                       'Consultant has reached max_active_cases')
    c = base_fields()
    c.update({
        'family_id': family_id,
        'consultant_id': consultant_id,
        'child_birth_date': birth,
        'delivery_mode': mode,
        'guarantee_goal_night_wakings': goal,
        'status': 'INTAKE',
        'completed_at': None,
    })
    register(store.cases, c)
    return ok(ser_case(c), status=201)


@bp.get('/cases')
def list_cases():
    uid, role = user_context()
    require_role(role, 'PracticeAdmin', 'Consultant', 'Parent')
    rows = list(store.cases.values())
    if role == 'Parent':
        rows = [c for c in rows if c['family_id'] == uid]
    family_id = request.args.get('family_id')
    if family_id is not None:
        rows = [c for c in rows if c['family_id'] == family_id]
    consultant_id = request.args.get('consultant_id')
    if consultant_id is not None:
        rows = [c for c in rows if c['consultant_id'] == consultant_id]
    status = request.args.get('status')
    if status is not None:
        rows = [c for c in rows if c['status'] == status]
    return paginate(rows, ser_case)


@bp.get('/cases/<caseId>')
def get_case(caseId):
    uid, role = user_context()
    require_role(role, 'PracticeAdmin', 'Consultant', 'Parent')
    case = load_case(caseId)
    check_parent_owns_case(uid, role, case)
    return ok(ser_case(case))


@bp.post('/cases/<caseId>/complete')
def complete_case(caseId):
    uid, role = user_context()
    require_role(role, 'Consultant')
    case = load_case(caseId)
    if case['consultant_id'] != uid:
        forbidden('Only the assigned consultant may complete the case')
    if case['status'] != 'ACTIVE_SUPPORT':
        raise ApiError('ERR_CASE_INVALID_STATE', 409,
                       'Completion requires the case to be in ACTIVE_SUPPORT')
    if any(p['case_id'] == case['id'] and p['status'] == 'ACTIVE'
           for p in store.packages.values()):
        raise ApiError('ERR_CASE_INVALID_STATE', 409,
                       'Case has a package in ACTIVE status')
    if any(s['case_id'] == case['id'] and s['status'] == 'SCHEDULED'
           for s in store.sessions.values()):
        raise ApiError('ERR_CASE_INVALID_STATE', 409,
                       'Case has a troubleshooting session in SCHEDULED status')
    if any(r['case_id'] == case['id'] and r['status'] in ('REQUESTED', 'APPROVED')
           for r in store.refunds.values()):
        raise ApiError('ERR_CASE_INVALID_STATE', 409,
                       'Case has a refund request in REQUESTED or APPROVED status')
    if not any(p['case_id'] == case['id'] for p in store.plans.values()):
        raise ApiError('ERR_CASE_INVALID_STATE', 409,
                       'Case has no sleep plan')
    plan = current_plan(case['id'])
    if plan is not None and plan['status'] == 'ACTIVE':
        plan['status'] = 'COMPLETED'
        touch(plan)
    case['status'] = 'COMPLETED'
    case['completed_at'] = now()
    touch(case)
    return ok(ser_case(case))


@bp.get('/cases/<caseId>/enrollments')
def list_case_enrollments(caseId):
    uid, role = user_context()
    require_role(role, 'PracticeAdmin', 'Consultant', 'Parent')
    case = load_case(caseId)
    check_parent_owns_case(uid, role, case)
    rows = [e for e in store.enrollments.values() if e['case_id'] == case['id']]
    return paginate(rows, ser_enrollment)
