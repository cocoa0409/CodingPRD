"""Satisfaction surveys: list/read/submit with the coaching cascade."""
from flask import Blueprint

import db
from db import bump
from errors import ApiError
from middleware import authenticate, require_roles
from response import ok_list, ok_object
from serializers import ser_survey
from services.csat import recompute_agent_coaching
from validate import (enum_filter, get_body, opt_str, parse_pagination,
                      req_int, str_filter, paginate, MISSING)

bp = Blueprint('surveys', __name__)

SURVEY_STATUSES = ('ISSUED', 'SUBMITTED', 'EXPIRED')
_READ_ROLES = ('Employee', 'HelpDeskAgent', 'SpecialistAgent',
               'SensitiveCaseManager', 'HRServicesAdmin')


@bp.get('/surveys')
def list_surveys():
    ctx = authenticate()
    require_roles(ctx, *_READ_ROLES)
    emp_f = str_filter('employee_id')
    ticket_f = str_filter('ticket_id')
    agent_f = str_filter('agent_id')
    status_f = enum_filter('status', SURVEY_STATUSES)
    limit, offset = parse_pagination()
    rows = list(db.surveys.values())
    if ctx.role == 'Employee':
        rows = [s for s in rows if s['employee_id'] == ctx.user_id]
    elif emp_f is not MISSING:
        rows = [s for s in rows if s['employee_id'] == emp_f]
    if ticket_f is not MISSING:
        rows = [s for s in rows if s['ticket_id'] == ticket_f]
    if agent_f is not MISSING:
        rows = [s for s in rows if s['agent_id'] == agent_f]
    if status_f is not MISSING:
        rows = [s for s in rows if s['status'] == status_f]
    rows.sort(key=lambda s: (s['created_at'], s['_seq']))
    page, total = paginate(rows, limit, offset)
    return ok_list([ser_survey(s) for s in page], limit, offset, total)


@bp.get('/surveys/<survey_id>')
def get_survey(survey_id):
    ctx = authenticate()
    require_roles(ctx, *_READ_ROLES)
    s = db.surveys.get(survey_id)
    if s is None:
        raise ApiError('ERR_SURVEY_NOT_FOUND', 404, 'no such survey')
    if ctx.role == 'Employee' and ctx.user_id != s['employee_id']:
        raise ApiError('ERR_FORBIDDEN_ROLE', 403,
                       'employees may read only their own surveys')
    return ok_object(ser_survey(s))


@bp.post('/surveys/<survey_id>/submit')
def submit_survey(survey_id):
    ctx = authenticate()
    require_roles(ctx, 'Employee')
    body = get_body()
    score = req_int(body, 'score')
    comment = opt_str(body, 'comment')
    if score < 1 or score > 5:
        raise ApiError('ERR_VALIDATION', 400, 'score must be an integer in 1..5')
    s = db.surveys.get(survey_id)
    if s is None:
        raise ApiError('ERR_SURVEY_NOT_FOUND', 404, 'no such survey')
    if ctx.user_id != s['employee_id']:
        raise ApiError('ERR_FORBIDDEN_ROLE', 403,
                       'only the addressed employee may submit the survey')
    # State tier: already SUBMITTED, or flipped to EXPIRED by a clock sweep.
    if s['status'] != 'ISSUED':
        raise ApiError('ERR_SURVEY_INVALID_STATE', 409,
                       'survey is not in ISSUED state')
    # Temporal tier: lazy expiry when the stored status still reads ISSUED.
    if db.now() > s['expires_at']:
        raise ApiError('ERR_SURVEY_EXPIRED', 409, 'the survey has expired')
    s['status'] = 'SUBMITTED'
    s['score'] = score
    s['comment'] = comment
    s['submitted_at'] = db.now()
    bump(s)
    # Depth-3 cascade: survey -> agent rolling CSAT / coaching_hold ->
    # ticket reassignment with COACHING_RELEASE events.
    if s['agent_id'] is not None:
        agent = db.agents.get(s['agent_id'])
        if agent is not None:
            recompute_agent_coaching(agent, ctx.user_id)
    return ok_object(ser_survey(s))
