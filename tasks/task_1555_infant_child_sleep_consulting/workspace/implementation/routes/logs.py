from flask import Blueprint, request

from auth import user_context, require_role, forbidden, check_parent_owns_case
from db import store, base_fields, register, touch, now, fmt_date
from domain import ser_log, regression_cascade
from envelope import ok, paginate
from errors import ApiError
from validators import body, req_date, req_int, req_enum, opt_str
from routes.cases import load_case

bp = Blueprint('logs', __name__)

OUTCOMES = ('ON_TRACK', 'REGRESSION')


@bp.post('/cases/<caseId>/logs')
def submit_log(caseId):
    uid, role = user_context()
    require_role(role, 'Parent')
    data = body()
    log_date = req_date(data, 'log_date')
    wake = req_int(data, 'night_wake_count', min_v=0)
    stretch = req_int(data, 'longest_stretch_minutes', min_v=0)
    nap_count = req_int(data, 'nap_count', min_v=0)
    nap_total = req_int(data, 'nap_total_minutes', min_v=0)
    notes = opt_str(data, 'notes')
    # A nightly log may not describe a future date (logical clock reference).
    if log_date > now().date():
        raise ApiError('ERR_INVALID_REQUEST', 400,
                       'log_date must not be later than the logical clock date')
    case = load_case(caseId)
    check_parent_owns_case(uid, role, case)
    if case['status'] not in ('ACTIVE_SUPPORT', 'NEEDS_ATTENTION'):
        raise ApiError('ERR_CASE_INVALID_STATE', 409,
                       'Log submission requires the case to be in ACTIVE_SUPPORT '
                       'or NEEDS_ATTENTION')
    if any(l['case_id'] == case['id'] and l['log_date'] == log_date
           for l in store.logs.values()):
        raise ApiError('ERR_DUPLICATE_LOG', 409,
                       'A log already exists for this case and log_date')
    log = base_fields()
    log.update({
        'case_id': case['id'],
        'log_date': log_date,
        'night_wake_count': wake,
        'longest_stretch_minutes': stretch,
        'nap_count': nap_count,
        'nap_total_minutes': nap_total,
        'notes': notes,
        'review_status': 'PENDING_REVIEW',
        'review_note': None,
    })
    register(store.logs, log)
    return ok(ser_log(log), status=201)


@bp.get('/cases/<caseId>/logs')
def list_case_logs(caseId):
    uid, role = user_context()
    require_role(role, 'PracticeAdmin', 'Consultant', 'Parent')
    case = load_case(caseId)
    check_parent_owns_case(uid, role, case)
    rows = [l for l in store.logs.values() if l['case_id'] == case['id']]
    log_date = request.args.get('log_date')
    if log_date is not None:
        rows = [l for l in rows if fmt_date(l['log_date']) == log_date]
    review_status = request.args.get('review_status')
    if review_status is not None:
        rows = [l for l in rows if l['review_status'] == review_status]
    return paginate(rows, ser_log)


@bp.post('/logs/<logId>/review')
def review_log(logId):
    uid, role = user_context()
    require_role(role, 'Consultant')
    data = body()
    outcome = req_enum(data, 'outcome', OUTCOMES)
    review_note = opt_str(data, 'review_note')
    log = store.logs.get(logId)
    if log is None:
        raise ApiError('ERR_LOG_NOT_FOUND', 404, 'Log not found')
    case = store.cases.get(log['case_id'])
    if case is None:
        raise ApiError('ERR_CASE_NOT_FOUND', 404, 'Case not found')
    if case['consultant_id'] != uid:
        forbidden('Only the assigned consultant may review logs')
    if log['review_status'] != 'PENDING_REVIEW':
        raise ApiError('ERR_LOG_ALREADY_REVIEWED', 409,
                       'Log has already been reviewed')
    log['review_note'] = review_note
    if outcome == 'ON_TRACK':
        log['review_status'] = 'REVIEWED_ON_TRACK'
        touch(log)
    else:
        log['review_status'] = 'REVIEWED_REGRESSION'
        touch(log)
        # Three-link regression cascade (each link conditional on state).
        regression_cascade(case)
    return ok(ser_log(log))
