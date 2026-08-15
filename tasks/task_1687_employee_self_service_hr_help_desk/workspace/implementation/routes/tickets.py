"""Tickets: intake, queue workflow actions, escalation, resolution, events."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

import db
from db import bump
from errors import ApiError
from middleware import (AGENT_ROLES, authenticate, caller_sensitive_cleared,
                        require_roles, require_sensitive_write)
from response import ok_list, ok_object
from serializers import (agent_assigned_open_count, ser_ticket,
                         ser_ticket_event)
from services import deflection as deflection_svc
from services.sla import (append_event, compute_deadlines, eff_minutes,
                          add_minutes, evaluate_ticket_sla, find_policy,
                          surge_multiplier_at)
from validate import (enum_filter, get_body, opt_enum, opt_str, req_int,
                      req_str, str_filter, parse_pagination, paginate, MISSING)

bp = Blueprint('tickets', __name__)

PRIORITIES = ('P1', 'P2', 'P3', 'P4')
WORKFLOW_STATUSES = ('NEW', 'TRIAGED', 'IN_PROGRESS', 'PENDING_EMPLOYEE',
                     'ESCALATED', 'RESOLVED', 'REOPENED', 'CLOSED', 'CANCELLED')
SLA_STATUSES = ('ON_TRACK', 'AT_RISK', 'BREACHED_RESPONSE',
                'BREACHED_RESOLUTION', 'MET')
READ_ROLES = ('Employee', 'HelpDeskAgent', 'SpecialistAgent',
              'SensitiveCaseManager', 'HRServicesAdmin')
AGENT_WRITE_ROLES = ('HelpDeskAgent', 'SpecialistAgent', 'SensitiveCaseManager')

REOPEN_WINDOW_HOURS = 72
SURVEY_TTL_DAYS = 7


def _get_ticket(ticket_id):
    t = db.tickets.get(ticket_id)
    if t is None:
        raise ApiError('ERR_TICKET_NOT_FOUND', 404, 'no such ticket')
    return t


def _require_owner(ctx, ticket):
    if ctx.user_id != ticket['employee_id']:
        raise ApiError('ERR_FORBIDDEN_ROLE', 403,
                       'employees may act only on their own tickets')


def _masked_for(ctx, ticket):
    if not ticket['sensitive']:
        return False
    if ctx.role == 'Employee' and ctx.user_id == ticket['employee_id']:
        return False
    return not caller_sensitive_cleared(ctx)


def _read_ticket(ctx, ticket):
    evaluate_ticket_sla(ticket)
    return ser_ticket(ticket, masked=_masked_for(ctx, ticket))


# ---- Intake -----------------------------------------------------------------

@bp.post('/tickets')
def create_ticket():
    ctx = authenticate()
    require_roles(ctx, 'Employee')
    body = get_body()
    # Ownership scope (tier 2) is evaluated before the remaining shape checks
    # whenever employee_id is present and well-typed.
    raw_eid = body.get('employee_id')
    if isinstance(raw_eid, str) and raw_eid and raw_eid != ctx.user_id:
        raise ApiError('ERR_FORBIDDEN_ROLE', 403,
                       'employee_id must equal the caller X-User-ID')
    employee_id = req_str(body, 'employee_id')
    category_id = req_str(body, 'category_id')
    subject = req_str(body, 'subject')
    description = req_str(body, 'description')
    priority = opt_enum(body, 'priority', PRIORITIES, default='P3')
    if employee_id != ctx.user_id:
        raise ApiError('ERR_FORBIDDEN_ROLE', 403,
                       'employee_id must equal the caller X-User-ID')
    employee = db.employees.get(employee_id)
    if employee is None:
        raise ApiError('ERR_EMPLOYEE_NOT_FOUND', 404, 'no such employee')
    category = db.categories.get(category_id)
    if category is None:
        raise ApiError('ERR_CATEGORY_NOT_FOUND', 404, 'no such category')
    policy = find_policy(category_id, priority)
    if policy is None:
        raise ApiError('ERR_SLA_POLICY_NOT_FOUND', 404,
                       'no SLA policy for (category_id, priority)')
    if not category['active']:
        raise ApiError('ERR_CATEGORY_INACTIVE', 422,
                       'category is inactive for new intake')

    created = db.now()
    surge = surge_multiplier_at(category, created)
    fr_due, res_due = compute_deadlines(created, policy, surge)
    rec = {
        'employee_id': employee_id,
        'category_id': category_id,
        'subject': subject,
        'description': description,
        'priority': priority,
        'sensitive': bool(category['is_sensitive']),
        'tier': 'T1',
        'workflow_status': 'NEW',
        'sla_status': 'ON_TRACK',
        'assigned_agent_id': None,
        'source_article_id': None,
        'resolution_article_id': None,
        'resolution_summary': None,
        'first_response_due_at': fr_due,
        'resolution_due_at': res_due,
        'first_responded_at': None,
        'resolved_at': None,
        'closed_at': None,
        'escalation_count': 0,
        'reopen_count': 0,
        '_surge': surge,
    }
    db.stamp_common(rec)
    db.tickets[rec['id']] = rec
    # Deflection linkage, then sensitive-category auto-assignment.
    deflection_svc.link_deflection(rec)
    if rec['sensitive']:
        winner = _select_agent(clearance_required=True)
        if winner is not None:
            rec['assigned_agent_id'] = winner['id']
    append_event(rec, 'CREATED', ctx.user_id, None, 'NEW', note=None)
    return ok_object(ser_ticket(rec, masked=False), status=201)


def _select_agent(team_id=None, tier=None, clearance_required=False):
    """Shared selector: active, under capacity, optional team/tier/clearance;
    rank assigned_open_count ASC then agent created_at ASC."""
    pool = []
    for a in db.agents.values():
        if not a['active']:
            continue
        if team_id is not None and a['team_id'] != team_id:
            continue
        if tier is not None and a['tier'] != tier:
            continue
        if clearance_required and a['clearance'] != 'SENSITIVE':
            continue
        load = agent_assigned_open_count(a['id'])
        if load >= a['capacity_max']:
            continue
        pool.append((load, a))
    if not pool:
        return None
    pool.sort(key=lambda p: (p[0], p[1]['created_at'], p[1]['_seq']))
    return pool[0][1]


# ---- Reads ------------------------------------------------------------------

@bp.get('/tickets')
def list_tickets():
    ctx = authenticate()
    require_roles(ctx, *READ_ROLES)
    emp_f = str_filter('employee_id')
    agent_f = str_filter('assigned_agent_id')
    cat_f = str_filter('category_id')
    wf_f = enum_filter('workflow_status', WORKFLOW_STATUSES)
    sla_f = enum_filter('sla_status', SLA_STATUSES)
    prio_f = enum_filter('priority', PRIORITIES)
    src_f = str_filter('source_article_id')
    res_f = str_filter('resolution_article_id')
    limit, offset = parse_pagination()
    # Lazy SLA re-evaluation happens before filtering on sla_status.
    for t in db.tickets.values():
        evaluate_ticket_sla(t)
    rows = list(db.tickets.values())
    if ctx.role == 'Employee':
        rows = [t for t in rows if t['employee_id'] == ctx.user_id]
    elif emp_f is not MISSING:
        rows = [t for t in rows if t['employee_id'] == emp_f]
    if agent_f is not MISSING:
        rows = [t for t in rows if t['assigned_agent_id'] == agent_f]
    if cat_f is not MISSING:
        rows = [t for t in rows if t['category_id'] == cat_f]
    if wf_f is not MISSING:
        rows = [t for t in rows if t['workflow_status'] == wf_f]
    if sla_f is not MISSING:
        rows = [t for t in rows if t['sla_status'] == sla_f]
    if prio_f is not MISSING:
        rows = [t for t in rows if t['priority'] == prio_f]
    if src_f is not MISSING:
        rows = [t for t in rows if t['source_article_id'] == src_f]
    if res_f is not MISSING:
        rows = [t for t in rows if t['resolution_article_id'] == res_f]
    rows.sort(key=lambda t: (t['created_at'], t['_seq']))
    page, total = paginate(rows, limit, offset)
    return ok_list([ser_ticket(t, masked=_masked_for(ctx, t)) for t in page],
                   limit, offset, total)


@bp.get('/tickets/<ticket_id>')
def get_ticket(ticket_id):
    ctx = authenticate()
    require_roles(ctx, *READ_ROLES)
    t = _get_ticket(ticket_id)
    if ctx.role == 'Employee':
        _require_owner(ctx, t)
    return ok_object(_read_ticket(ctx, t))


@bp.get('/tickets/<ticket_id>/events')
def ticket_events(ticket_id):
    ctx = authenticate()
    require_roles(ctx, *READ_ROLES)
    t = _get_ticket(ticket_id)
    if ctx.role == 'Employee':
        _require_owner(ctx, t)
    limit, offset = parse_pagination()
    rows = [e for e in db.ticket_events.values() if e['ticket_id'] == t['id']]
    # Chronological, created_at ascending.
    rows.sort(key=lambda e: (e['created_at'], e['_seq']))
    page, total = paginate(rows, limit, offset)
    return ok_list([ser_ticket_event(e) for e in page], limit, offset, total)


# ---- Queue workflow ----------------------------------------------------------

@bp.post('/tickets/<ticket_id>/triage')
def triage_ticket(ticket_id):
    ctx = authenticate()
    require_roles(ctx, 'HelpDeskAgent', 'SensitiveCaseManager')
    body = get_body(required=False)
    new_priority = opt_enum(body, 'priority', PRIORITIES, default=None)
    t = _get_ticket(ticket_id)
    if t['workflow_status'] != 'NEW':
        raise ApiError('ERR_TICKET_INVALID_STATE', 409, 'ticket is not NEW')
    require_sensitive_write(ctx, t)
    if new_priority is not None:
        category = db.categories.get(t['category_id'])
        policy = find_policy(t['category_id'], new_priority)
        if policy is None:
            raise ApiError('ERR_SLA_POLICY_NOT_FOUND', 404,
                           'no SLA policy for (category_id, priority)')
        t['priority'] = new_priority
        # Recompute deadlines from created_at with the creation-time surge.
        fr_due, res_due = compute_deadlines(t['created_at'], policy, t['_surge'])
        t['first_response_due_at'] = fr_due
        t['resolution_due_at'] = res_due
    t['workflow_status'] = 'TRIAGED'
    append_event(t, 'TRIAGED', ctx.user_id, 'NEW', 'TRIAGED', note=None)
    bump(t)
    return ok_object(_read_ticket(ctx, t))


@bp.post('/tickets/<ticket_id>/assign')
def assign_ticket(ticket_id):
    ctx = authenticate()
    require_roles(ctx, 'HelpDeskAgent', 'SpecialistAgent', 'SensitiveCaseManager',
                  'HRServicesAdmin')
    body = get_body()
    raw_agent = body.get('agent_id')
    # Self-assignment scope for SpecialistAgent / SensitiveCaseManager.
    if ctx.role in ('SpecialistAgent', 'SensitiveCaseManager') \
            and isinstance(raw_agent, str) and raw_agent != ctx.user_id:
        raise ApiError('ERR_FORBIDDEN_ROLE', 403,
                       'this role may only self-assign')
    agent_id = req_str(body, 'agent_id')
    expected = req_int(body, 'expected_ticket_version')
    t = _get_ticket(ticket_id)
    agent = db.agents.get(agent_id)
    if agent is None:
        raise ApiError('ERR_AGENT_NOT_FOUND', 404, 'no such agent')
    if t['workflow_status'] not in ('NEW', 'TRIAGED', 'ESCALATED', 'REOPENED'):
        raise ApiError('ERR_TICKET_INVALID_STATE', 409,
                       'ticket is not assignable from its current state')
    require_sensitive_write(ctx, t)
    # Assignee clearance is business safety (tier 7); fit checks and OCC are
    # business constraints (tier 8), with OCC last per PRD §2.10's enumeration.
    if t['sensitive'] and agent['clearance'] != 'SENSITIVE':
        raise ApiError('ERR_CONFIDENTIALITY_CLEARANCE_REQUIRED', 403,
                       'sensitive ticket requires a SENSITIVE-cleared assignee')
    if not agent['active']:
        raise ApiError('ERR_AGENT_AT_CAPACITY', 409, 'assignee is inactive')
    if agent_assigned_open_count(agent['id']) >= agent['capacity_max']:
        raise ApiError('ERR_AGENT_AT_CAPACITY', 409, 'assignee is at capacity')
    if agent['tier'] != t['tier']:
        raise ApiError('ERR_AGENT_TIER_INSUFFICIENT', 409,
                       'assignee tier does not match ticket tier')
    if expected != t['version']:
        raise ApiError('ERR_STALE_TICKET_VERSION', 412,
                       'expected_ticket_version does not match current version')
    from_state = t['workflow_status']
    prior = t['assigned_agent_id']
    t['assigned_agent_id'] = agent_id
    t['workflow_status'] = 'IN_PROGRESS'
    if prior is not None and prior != agent_id:
        append_event(t, 'UNASSIGNED', ctx.user_id, from_state, 'IN_PROGRESS',
                     note=None)
    append_event(t, 'ASSIGNED', ctx.user_id, from_state, 'IN_PROGRESS', note=None)
    bump(t)
    return ok_object(_read_ticket(ctx, t))


@bp.post('/tickets/<ticket_id>/respond')
def respond_ticket(ticket_id):
    ctx = authenticate()
    require_roles(ctx, *AGENT_WRITE_ROLES)
    body = get_body()
    resp_body = req_str(body, 'body')
    t = _get_ticket(ticket_id)
    if t['workflow_status'] not in ('TRIAGED', 'IN_PROGRESS', 'ESCALATED'):
        raise ApiError('ERR_TICKET_INVALID_STATE', 409,
                       'respond is valid only from TRIAGED/IN_PROGRESS/ESCALATED')
    require_sensitive_write(ctx, t)
    if t['first_responded_at'] is None:
        t['first_responded_at'] = db.now()
    append_event(t, 'RESPONDED', ctx.user_id, t['workflow_status'],
                 t['workflow_status'], note=resp_body)
    bump(t)
    return ok_object(_read_ticket(ctx, t))


@bp.post('/tickets/<ticket_id>/request-info')
def request_info(ticket_id):
    ctx = authenticate()
    require_roles(ctx, *AGENT_WRITE_ROLES)
    body = get_body()
    info_body = req_str(body, 'body')
    t = _get_ticket(ticket_id)
    if t['workflow_status'] != 'IN_PROGRESS':
        raise ApiError('ERR_TICKET_INVALID_STATE', 409,
                       'ticket is not IN_PROGRESS')
    require_sensitive_write(ctx, t)
    t['workflow_status'] = 'PENDING_EMPLOYEE'
    append_event(t, 'INFO_REQUESTED', ctx.user_id, 'IN_PROGRESS',
                 'PENDING_EMPLOYEE', note=info_body)
    bump(t)
    return ok_object(_read_ticket(ctx, t))


@bp.post('/tickets/<ticket_id>/provide-info')
def provide_info(ticket_id):
    ctx = authenticate()
    require_roles(ctx, 'Employee')
    body = get_body()
    info_body = req_str(body, 'body')
    t = _get_ticket(ticket_id)
    _require_owner(ctx, t)
    if t['workflow_status'] != 'PENDING_EMPLOYEE':
        raise ApiError('ERR_TICKET_INVALID_STATE', 409,
                       'ticket is not PENDING_EMPLOYEE')
    t['workflow_status'] = 'IN_PROGRESS'
    append_event(t, 'INFO_PROVIDED', ctx.user_id, 'PENDING_EMPLOYEE',
                 'IN_PROGRESS', note=info_body)
    bump(t)
    return ok_object(_read_ticket(ctx, t))


@bp.post('/tickets/<ticket_id>/escalate')
def escalate_ticket(ticket_id):
    ctx = authenticate()
    require_roles(ctx, 'HelpDeskAgent')
    body = get_body(required=False)
    reason = opt_str(body, 'reason')
    t = _get_ticket(ticket_id)
    if t['workflow_status'] not in ('TRIAGED', 'IN_PROGRESS') or t['tier'] != 'T1':
        raise ApiError('ERR_TICKET_INVALID_STATE', 409,
                       'only a T1 ticket in TRIAGED/IN_PROGRESS may be escalated')
    require_sensitive_write(ctx, t)
    category = db.categories.get(t['category_id'])
    winner = _select_agent(team_id=category['specialist_team_id'], tier='T2',
                           clearance_required=bool(t['sensitive']))
    if winner is None:
        raise ApiError('ERR_NO_ELIGIBLE_SPECIALIST', 422,
                       'no eligible specialist in the category team')
    from_state = t['workflow_status']
    t['tier'] = 'T2'
    t['escalation_count'] += 1
    t['assigned_agent_id'] = winner['id']
    t['workflow_status'] = 'ESCALATED'
    # SLA clocks are deliberately NOT reset by escalation.
    append_event(t, 'ESCALATED', ctx.user_id, from_state, 'ESCALATED', note=reason)
    bump(t)
    return ok_object(_read_ticket(ctx, t))


@bp.post('/tickets/<ticket_id>/resolve')
def resolve_ticket(ticket_id):
    ctx = authenticate()
    require_roles(ctx, *AGENT_WRITE_ROLES)
    body = get_body()
    summary = req_str(body, 'resolution_summary')
    article_id = opt_str(body, 'resolution_article_id')
    t = _get_ticket(ticket_id)
    article = None
    if article_id is not None:
        article = db.articles.get(article_id)
        if article is None:
            raise ApiError('ERR_ARTICLE_NOT_FOUND', 404, 'no such article')
    if t['workflow_status'] not in ('IN_PROGRESS', 'REOPENED'):
        raise ApiError('ERR_TICKET_INVALID_STATE', 409,
                       'ticket is not IN_PROGRESS or REOPENED')
    require_sensitive_write(ctx, t)
    if article is not None and article['status'] != 'PUBLISHED':
        raise ApiError('ERR_RESOLUTION_ARTICLE_NOT_PUBLISHED', 422,
                       'resolution article must be PUBLISHED')
    now = db.now()
    first_resolution = t['resolved_at'] is None
    from_state = t['workflow_status']
    t['resolved_at'] = now
    t['resolution_summary'] = summary
    t['resolution_article_id'] = article_id
    t['sla_status'] = 'MET' if now <= t['resolution_due_at'] else 'BREACHED_RESOLUTION'
    t['workflow_status'] = 'RESOLVED'
    append_event(t, 'RESOLVED', ctx.user_id, from_state, 'RESOLVED', note=summary)
    if first_resolution:
        # Exactly one survey per ticket, issued on the first resolution.
        survey = {
            'ticket_id': t['id'],
            'employee_id': t['employee_id'],
            'agent_id': t['assigned_agent_id'],
            'status': 'ISSUED',
            'score': None,
            'comment': None,
            'issued_at': now,
            'expires_at': now + timedelta(days=SURVEY_TTL_DAYS),
            'submitted_at': None,
        }
        db.stamp_common(survey)
        db.surveys[survey['id']] = survey
    bump(t)
    return ok_object(_read_ticket(ctx, t))


# ---- Employee exits ----------------------------------------------------------

@bp.post('/tickets/<ticket_id>/reopen')
def reopen_ticket(ticket_id):
    ctx = authenticate()
    require_roles(ctx, 'Employee')
    body = get_body()
    reason = req_str(body, 'reason')
    t = _get_ticket(ticket_id)
    _require_owner(ctx, t)
    if t['workflow_status'] != 'RESOLVED':
        raise ApiError('ERR_TICKET_INVALID_STATE', 409, 'ticket is not RESOLVED')
    now = db.now()
    if now > t['resolved_at'] + timedelta(hours=REOPEN_WINDOW_HOURS):
        raise ApiError('ERR_REOPEN_WINDOW_PASSED', 409,
                       'the 72-hour reopen window has passed')
    policy = find_policy(t['category_id'], t['priority'])
    if policy is None:
        raise ApiError('ERR_SLA_POLICY_NOT_FOUND', 404,
                       'no SLA policy for (category_id, priority)')
    eff = eff_minutes(policy['resolution_minutes'], t['_surge'])
    t['reopen_count'] += 1
    t['sla_status'] = 'ON_TRACK'
    t['resolution_due_at'] = add_minutes(now, eff, policy['clock_mode'])
    t['workflow_status'] = 'REOPENED'
    # No new survey: a ticket issues only one ever.
    append_event(t, 'REOPENED', ctx.user_id, 'RESOLVED', 'REOPENED', note=reason)
    bump(t)
    return ok_object(_read_ticket(ctx, t))


@bp.post('/tickets/<ticket_id>/close')
def close_ticket(ticket_id):
    ctx = authenticate()
    require_roles(ctx, 'Employee')
    t = _get_ticket(ticket_id)
    _require_owner(ctx, t)
    if t['workflow_status'] != 'RESOLVED':
        raise ApiError('ERR_TICKET_INVALID_STATE', 409, 'ticket is not RESOLVED')
    t['workflow_status'] = 'CLOSED'
    t['closed_at'] = db.now()
    append_event(t, 'CLOSED', ctx.user_id, 'RESOLVED', 'CLOSED', note=None)
    bump(t)
    return ok_object(_read_ticket(ctx, t))


@bp.post('/tickets/<ticket_id>/cancel')
def cancel_ticket(ticket_id):
    ctx = authenticate()
    require_roles(ctx, 'Employee')
    body = get_body(required=False)
    reason = opt_str(body, 'reason')
    t = _get_ticket(ticket_id)
    _require_owner(ctx, t)
    if t['workflow_status'] not in ('NEW', 'TRIAGED'):
        raise ApiError('ERR_TICKET_INVALID_STATE', 409,
                       'only NEW or TRIAGED tickets may be cancelled')
    from_state = t['workflow_status']
    t['assigned_agent_id'] = None
    t['workflow_status'] = 'CANCELLED'
    append_event(t, 'CANCELLED', ctx.user_id, from_state, 'CANCELLED', note=reason)
    bump(t)
    return ok_object(_read_ticket(ctx, t))
