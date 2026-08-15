from flask import Blueprint

from auth import user_context, require_role, forbidden, check_parent_owns_case
from db import store, base_fields, register, touch
from domain import (ser_questionnaire, provisional_score, reviewed_score,
                    case_age_band)
from envelope import ok, ok_list
from errors import ApiError
from validators import body, req_int, opt_str
from routes.cases import load_case

bp = Blueprint('questionnaires', __name__)

ANSWER_INT_KEYS = ('night_wakings', 'night_feeds', 'bedtime_resistance_minutes',
                   'nap_total_minutes')
ANSWER_BOOL_KEYS = ('medical_flags', 'preterm_birth')


def validate_answers(data):
    answers = data.get('answers')
    if not isinstance(answers, dict):
        raise ApiError('ERR_INVALID_REQUEST', 400,
                       'answers is required and must be an object')
    for k in ANSWER_INT_KEYS:
        v = answers.get(k)
        if not isinstance(v, int) or isinstance(v, bool) or v < 0:
            raise ApiError('ERR_INVALID_REQUEST', 400,
                           'answers.{} is required and must be an integer >= 0'.format(k))
    for k in ANSWER_BOOL_KEYS:
        v = answers.get(k)
        if not isinstance(v, bool):
            raise ApiError('ERR_INVALID_REQUEST', 400,
                           'answers.{} is required and must be a boolean'.format(k))
    return answers


@bp.post('/cases/<caseId>/questionnaire')
def submit_questionnaire(caseId):
    uid, role = user_context()
    require_role(role, 'Parent')
    data = body()
    answers = validate_answers(data)
    case = load_case(caseId)
    check_parent_owns_case(uid, role, case)
    # State (stage 5) enforces the one-questionnaire-per-case invariant
    # structurally: submission requires INTAKE and the first submission
    # moves the case out of INTAKE forever.
    if case['status'] != 'INTAKE':
        raise ApiError('ERR_CASE_INVALID_STATE', 409,
                       'Questionnaire submission requires the case to be in INTAKE')
    q = base_fields()
    q.update({
        'case_id': case['id'],
        'answers': answers,
        'provisional_severity_score': provisional_score(answers),
        'adjustment_points': None,
        'reviewed_severity_score': None,
        'review_note': None,
        'status': 'SUBMITTED',
    })
    register(store.questionnaires, q)
    case['status'] = 'ASSESSMENT'
    touch(case)
    return ok(ser_questionnaire(q), status=201)


@bp.get('/cases/<caseId>/questionnaire')
def get_case_questionnaire(caseId):
    uid, role = user_context()
    require_role(role, 'PracticeAdmin', 'Consultant', 'Parent')
    case = load_case(caseId)
    check_parent_owns_case(uid, role, case)
    rows = [q for q in store.questionnaires.values() if q['case_id'] == case['id']]
    rows.sort(key=lambda q: (q['created_at'], q['_seq']))
    items = [ser_questionnaire(q) for q in rows]
    # Array of length 0 or 1; carries pagination fields with defaults.
    return ok_list(items, len(items), 10, 0)


@bp.post('/questionnaires/<questionnaireId>/review')
def review_questionnaire(questionnaireId):
    uid, role = user_context()
    require_role(role, 'Consultant')
    data = body()
    adjustment_points = req_int(data, 'adjustment_points', min_v=-30, max_v=30)
    review_note = opt_str(data, 'review_note')
    q = store.questionnaires.get(questionnaireId)
    if q is None:
        raise ApiError('ERR_QUESTIONNAIRE_NOT_FOUND', 404, 'Questionnaire not found')
    case = store.cases.get(q['case_id'])
    if case is None:
        raise ApiError('ERR_CASE_NOT_FOUND', 404, 'Case not found')
    if case['consultant_id'] != uid:
        forbidden('Only the assigned consultant may review the questionnaire')
    if q['status'] != 'SUBMITTED':
        raise ApiError('ERR_QUESTIONNAIRE_ALREADY_REVIEWED', 409,
                       'Questionnaire has already been reviewed')
    if case['status'] != 'ASSESSMENT':
        raise ApiError('ERR_CASE_INVALID_STATE', 409,
                       'Questionnaire review requires the case to be in ASSESSMENT')
    q['adjustment_points'] = adjustment_points
    q['review_note'] = review_note
    q['reviewed_severity_score'] = reviewed_score(
        q['provisional_severity_score'], adjustment_points, case_age_band(case))
    q['status'] = 'REVIEWED'
    touch(q)
    case['status'] = 'PLANNING'
    touch(case)
    return ok(ser_questionnaire(q))
