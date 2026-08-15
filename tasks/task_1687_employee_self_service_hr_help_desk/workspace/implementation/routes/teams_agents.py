"""Teams and Agents."""
from flask import Blueprint

import db
from errors import ApiError
from middleware import authenticate, require_roles
from response import ok_list, ok_object
from serializers import ser_agent, ser_team
from services.csat import compute_csat
from validate import (bool_filter, enum_filter, get_body, opt_bool, opt_enum,
                      opt_int, opt_str, parse_pagination, req_enum, req_str,
                      str_filter, paginate, MISSING)

bp = Blueprint('teams_agents', __name__)

TIERS = ('T1', 'T2')
CLEARANCES = ('STANDARD', 'SENSITIVE')
_TEAM_READ_ROLES = ('HRServicesAdmin', 'WorkforcePlanner', 'HelpDeskAgent',
                    'SpecialistAgent', 'SensitiveCaseManager')
_AGENT_READ_ROLES = _TEAM_READ_ROLES


@bp.post('/teams')
def create_team():
    ctx = authenticate()
    require_roles(ctx, 'HRServicesAdmin')
    body = get_body()
    name = req_str(body, 'name')
    description = opt_str(body, 'description')
    for t in db.teams.values():
        if t['name'] == name:
            raise ApiError('ERR_VALIDATION', 400, 'team name already exists')
    rec = {'name': name, 'description': description}
    db.stamp_common(rec)
    db.teams[rec['id']] = rec
    return ok_object(ser_team(rec), status=201)


@bp.get('/teams')
def list_teams():
    ctx = authenticate()
    require_roles(ctx, *_TEAM_READ_ROLES)
    limit, offset = parse_pagination()
    rows = sorted(db.teams.values(), key=lambda t: (t['created_at'], t['_seq']))
    page, total = paginate(rows, limit, offset)
    return ok_list([ser_team(t) for t in page], limit, offset, total)


@bp.get('/teams/<team_id>')
def get_team(team_id):
    ctx = authenticate()
    require_roles(ctx, *_TEAM_READ_ROLES)
    t = db.teams.get(team_id)
    if t is None:
        raise ApiError('ERR_TEAM_NOT_FOUND', 404, 'no such team')
    return ok_object(ser_team(t))


@bp.post('/agents')
def create_agent():
    ctx = authenticate()
    require_roles(ctx, 'HRServicesAdmin')
    body = get_body()
    display_name = req_str(body, 'display_name')
    email = req_str(body, 'email')
    tier = req_enum(body, 'tier', TIERS)
    team_id = req_str(body, 'team_id')
    clearance = opt_enum(body, 'clearance', CLEARANCES, default='STANDARD')
    capacity_max = opt_int(body, 'capacity_max', default=10, minimum=0)
    active = opt_bool(body, 'active', default=True)
    if team_id not in db.teams:
        raise ApiError('ERR_TEAM_NOT_FOUND', 404, 'team_id references no team')
    rec = {
        'display_name': display_name,
        'email': email,
        'tier': tier,
        'clearance': clearance,
        'team_id': team_id,
        'capacity_max': capacity_max,
        'active': active,
        'coaching_hold': False,
    }
    db.stamp_common(rec)
    db.agents[rec['id']] = rec
    _count, _simple, weighted = compute_csat(rec['id'])
    return ok_object(ser_agent(rec, rolling_csat=weighted), status=201)


@bp.get('/agents')
def list_agents():
    ctx = authenticate()
    require_roles(ctx, *_AGENT_READ_ROLES)
    team_f = str_filter('team_id')
    tier_f = enum_filter('tier', TIERS)
    clearance_f = enum_filter('clearance', CLEARANCES)
    active_f = bool_filter('active')
    limit, offset = parse_pagination()
    rows = list(db.agents.values())
    if team_f is not MISSING:
        rows = [a for a in rows if a['team_id'] == team_f]
    if tier_f is not MISSING:
        rows = [a for a in rows if a['tier'] == tier_f]
    if clearance_f is not MISSING:
        rows = [a for a in rows if a['clearance'] == clearance_f]
    if active_f is not MISSING:
        rows = [a for a in rows if a['active'] == active_f]
    rows.sort(key=lambda a: (a['created_at'], a['_seq']))
    page, total = paginate(rows, limit, offset)
    out = []
    for a in page:
        _c, _s, weighted = compute_csat(a['id'])
        out.append(ser_agent(a, rolling_csat=weighted))
    return ok_list(out, limit, offset, total)


@bp.get('/agents/<agent_id>')
def get_agent(agent_id):
    ctx = authenticate()
    require_roles(ctx, *_AGENT_READ_ROLES)
    a = db.agents.get(agent_id)
    if a is None:
        raise ApiError('ERR_AGENT_NOT_FOUND', 404, 'no such agent')
    _c, _s, weighted = compute_csat(a['id'])
    return ok_object(ser_agent(a, rolling_csat=weighted))
