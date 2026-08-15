from flask import Blueprint

from auth import user_context, require_role, forbidden, check_parent_owns_case
from db import store, base_fields, register, touch, now
from domain import (ser_session, select_consumable_package,
                    has_scheduling_conflict, reeval_depleted)
from envelope import ok, paginate
from errors import ApiError
from validators import body, req_int, req_enum, req_datetime
from routes.cases import load_case

bp = Blueprint('sessions', __name__)

SESSION_TYPES = ('REGRESSION', 'TRAVEL')
MIN_DURATION_S = 15 * 60
MAX_DURATION_S = 120 * 60


@bp.post('/cases/<caseId>/troubleshooting-sessions')
def book_session(caseId):
    uid, role = user_context()
    require_role(role, 'Parent', 'Consultant')
    data = body()
    session_type = req_enum(data, 'session_type', SESSION_TYPES)
    start = req_datetime(data, 'scheduled_start')
    end = req_datetime(data, 'scheduled_end')
    expected_pkg_version = req_int(data, 'expected_package_version')
    # scheduled_start must be strictly after the logical clock; the session
    # must last 15..120 minutes inclusive with end after start.
    if start <= now():
        raise ApiError('ERR_INVALID_REQUEST', 400,
                       'scheduled_start must be strictly after the logical clock')
    if end <= start:
        raise ApiError('ERR_INVALID_REQUEST', 400,
                       'scheduled_end must be after scheduled_start')
    duration_s = (end - start).total_seconds()
    if duration_s < MIN_DURATION_S or duration_s > MAX_DURATION_S:
        raise ApiError('ERR_INVALID_REQUEST', 400,
                       'Session duration must be between 15 and 120 minutes inclusive')
    case = load_case(caseId)
    if role == 'Parent':
        check_parent_owns_case(uid, role, case)
    # Consumable package selection (state stage).
    pkg = select_consumable_package(case['id'])
    if pkg is None:
        raise ApiError('ERR_PACKAGE_NOT_ACTIVE', 409,
                       'No ACTIVE in-window package available for this case')
    # OCC guard on SupportPackage.version (PRD §2.7).
    if expected_pkg_version != pkg['version']:
        raise ApiError('ERR_STALE_VERSION', 412,
                       'expected_package_version does not match the package version')
    # Temporal (stage 7): 15-minute buffer against the consultant's calendar.
    if has_scheduling_conflict(case['consultant_id'], start, end):
        raise ApiError('ERR_SCHEDULING_CONFLICT', 409,
                       'Session violates the 15-minute buffer on the consultant calendar')
    # Quota (stage 9).
    if pkg['remaining_calls'] <= 0:
        raise ApiError('ERR_ENTITLEMENT_EXHAUSTED', 422,
                       'No remaining call entitlement on the selected package')
    session = base_fields()
    session.update({
        'case_id': case['id'],
        'package_id': pkg['id'],
        'session_type': session_type,
        'scheduled_start': start,
        'scheduled_end': end,
        'status': 'SCHEDULED',
    })
    register(store.sessions, session)
    pkg['remaining_calls'] -= 1
    touch(pkg)
    reeval_depleted(pkg)
    return ok(ser_session(session), status=201)


@bp.get('/cases/<caseId>/troubleshooting-sessions')
def list_case_sessions(caseId):
    uid, role = user_context()
    require_role(role, 'PracticeAdmin', 'Consultant', 'Parent')
    case = load_case(caseId)
    check_parent_owns_case(uid, role, case)
    rows = [s for s in store.sessions.values() if s['case_id'] == case['id']]
    return paginate(rows, ser_session)


def load_session(session_id):
    s = store.sessions.get(session_id)
    if s is None:
        raise ApiError('ERR_SESSION_NOT_FOUND', 404, 'Session not found')
    return s


@bp.post('/troubleshooting-sessions/<sessionId>/complete')
def complete_session(sessionId):
    uid, role = user_context()
    require_role(role, 'Consultant')
    session = load_session(sessionId)
    case = store.cases.get(session['case_id'])
    if case is None:
        raise ApiError('ERR_CASE_NOT_FOUND', 404, 'Case not found')
    if case['consultant_id'] != uid:
        forbidden('Only the assigned consultant may complete the session')
    if session['status'] != 'SCHEDULED':
        raise ApiError('ERR_SESSION_INVALID_STATE', 409,
                       'Completion requires the session to be SCHEDULED')
    session['status'] = 'COMPLETED'
    touch(session)
    # Entitlement stays consumed — no release on completion.
    return ok(ser_session(session))


@bp.post('/troubleshooting-sessions/<sessionId>/cancel')
def cancel_session(sessionId):
    uid, role = user_context()
    require_role(role, 'Parent', 'Consultant')
    session = load_session(sessionId)
    case = store.cases.get(session['case_id'])
    if case is None:
        raise ApiError('ERR_CASE_NOT_FOUND', 404, 'Case not found')
    if role == 'Parent':
        check_parent_owns_case(uid, role, case)
    if session['status'] != 'SCHEDULED':
        raise ApiError('ERR_SESSION_INVALID_STATE', 409,
                       'Cancellation requires the session to be SCHEDULED')
    if now() >= session['scheduled_start']:
        raise ApiError('ERR_SESSION_INVALID_STATE', 409,
                       'Cancellation requires the clock to be strictly before '
                       'scheduled_start')
    session['status'] = 'CANCELLED'
    touch(session)
    # Compensating release only while the charged package is still ACTIVE.
    pkg = store.packages.get(session['package_id'])
    if pkg is not None and pkg['status'] == 'ACTIVE':
        pkg['remaining_calls'] += 1
        touch(pkg)
    return ok(ser_session(session))
