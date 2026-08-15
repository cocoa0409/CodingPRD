"""Ticket categories and SLA policies."""
from flask import Blueprint

import db
from errors import ApiError
from middleware import authenticate, require_roles
from response import ok_list, ok_object
from serializers import ser_category, ser_sla_policy
from services.sla import find_policy
from validate import (bool_filter, enum_filter, get_body, opt_bool, opt_enum,
                      parse_pagination, req_enum, req_int, req_str, str_filter,
                      paginate, MISSING)

bp = Blueprint('categories', __name__)

PRIORITIES = ('P1', 'P2', 'P3', 'P4')
CLOCK_MODES = ('WALL_CLOCK', 'BUSINESS_HOURS')
_CAT_READ_ROLES = ('Employee', 'HRServicesAdmin', 'HRDataSteward',
                   'HelpDeskAgent', 'SpecialistAgent', 'SensitiveCaseManager',
                   'KnowledgeManager', 'WorkforcePlanner')
_SLA_READ_ROLES = ('HRServicesAdmin', 'WorkforcePlanner', 'HelpDeskAgent',
                   'SpecialistAgent', 'SensitiveCaseManager')


@bp.post('/ticket-categories')
def create_category():
    ctx = authenticate()
    require_roles(ctx, 'HRServicesAdmin')
    body = get_body()
    code = req_str(body, 'code')
    name = req_str(body, 'name')
    specialist_team_id = req_str(body, 'specialist_team_id')
    is_sensitive = opt_bool(body, 'is_sensitive', default=False)
    active = opt_bool(body, 'active', default=True)
    if specialist_team_id not in db.teams:
        raise ApiError('ERR_TEAM_NOT_FOUND', 404, 'specialist_team_id references no team')
    for c in db.categories.values():
        if c['code'] == code:
            raise ApiError('ERR_DUPLICATE_CATEGORY_CODE', 409, 'category code already exists')
    rec = {
        'code': code,
        'name': name,
        'is_sensitive': is_sensitive,
        'specialist_team_id': specialist_team_id,
        'active': active,
    }
    db.stamp_common(rec)
    db.categories[rec['id']] = rec
    return ok_object(ser_category(rec), status=201)


@bp.get('/ticket-categories')
def list_categories():
    ctx = authenticate()
    require_roles(ctx, *_CAT_READ_ROLES)
    active_f = bool_filter('active')
    team_f = str_filter('specialist_team_id')
    limit, offset = parse_pagination()
    rows = list(db.categories.values())
    if active_f is not MISSING:
        rows = [c for c in rows if c['active'] == active_f]
    if team_f is not MISSING:
        rows = [c for c in rows if c['specialist_team_id'] == team_f]
    rows.sort(key=lambda c: (c['created_at'], c['_seq']))
    page, total = paginate(rows, limit, offset)
    return ok_list([ser_category(c) for c in page], limit, offset, total)


@bp.get('/ticket-categories/<cat_id>')
def get_category(cat_id):
    ctx = authenticate()
    require_roles(ctx, *_CAT_READ_ROLES)
    c = db.categories.get(cat_id)
    if c is None:
        raise ApiError('ERR_CATEGORY_NOT_FOUND', 404, 'no such category')
    return ok_object(ser_category(c))


@bp.get('/ticket-categories/<cat_id>/sla-policies')
def category_sla_policies(cat_id):
    ctx = authenticate()
    require_roles(ctx, *_SLA_READ_ROLES)
    c = db.categories.get(cat_id)
    if c is None:
        raise ApiError('ERR_CATEGORY_NOT_FOUND', 404, 'no such category')
    limit, offset = parse_pagination()
    rows = [p for p in db.sla_policies.values() if p['category_id'] == cat_id]
    rows.sort(key=lambda p: (p['created_at'], p['_seq']))
    page, total = paginate(rows, limit, offset)
    return ok_list([ser_sla_policy(p) for p in page], limit, offset, total)


@bp.post('/sla-policies')
def create_sla_policy():
    ctx = authenticate()
    require_roles(ctx, 'HRServicesAdmin')
    body = get_body()
    category_id = req_str(body, 'category_id')
    priority = req_enum(body, 'priority', PRIORITIES)
    first_response_minutes = req_int(body, 'first_response_minutes', minimum=1)
    resolution_minutes = req_int(body, 'resolution_minutes', minimum=1)
    clock_mode = opt_enum(body, 'clock_mode', CLOCK_MODES, default='WALL_CLOCK')
    if category_id not in db.categories:
        raise ApiError('ERR_CATEGORY_NOT_FOUND', 404, 'category_id references no category')
    if find_policy(category_id, priority) is not None:
        raise ApiError('ERR_SLA_POLICY_DUPLICATE', 409,
                       'policy already exists for (category_id, priority)')
    rec = {
        'category_id': category_id,
        'priority': priority,
        'first_response_minutes': first_response_minutes,
        'resolution_minutes': resolution_minutes,
        'clock_mode': clock_mode,
    }
    db.stamp_common(rec)
    db.sla_policies[rec['id']] = rec
    return ok_object(ser_sla_policy(rec), status=201)


@bp.get('/sla-policies')
def list_sla_policies():
    ctx = authenticate()
    require_roles(ctx, *_SLA_READ_ROLES)
    cat_f = str_filter('category_id')
    prio_f = enum_filter('priority', PRIORITIES)
    limit, offset = parse_pagination()
    rows = list(db.sla_policies.values())
    if cat_f is not MISSING:
        rows = [p for p in rows if p['category_id'] == cat_f]
    if prio_f is not MISSING:
        rows = [p for p in rows if p['priority'] == prio_f]
    rows.sort(key=lambda p: (p['created_at'], p['_seq']))
    page, total = paginate(rows, limit, offset)
    return ok_list([ser_sla_policy(p) for p in page], limit, offset, total)
