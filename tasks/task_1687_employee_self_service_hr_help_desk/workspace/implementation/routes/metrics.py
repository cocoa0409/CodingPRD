"""Computed read-only metrics: deflection, SLA attainment, CSAT."""
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

import db
from errors import ApiError
from middleware import authenticate, require_roles
from response import ok_object
from services.csat import CSAT_WINDOW_DAYS, compute_csat
from services.deflection import DEFLECTION_WINDOW_DAYS, deflection_rate

bp = Blueprint('metrics', __name__)


def _required_param(name):
    v = request.args.get(name)
    if v is None or v == '':
        raise ApiError('ERR_VALIDATION', 400, 'query parameter %s is required' % name)
    return v


@bp.get('/metrics/deflection')
def metrics_deflection():
    ctx = authenticate()
    require_roles(ctx, 'HRServicesAdmin', 'KnowledgeManager', 'WorkforcePlanner')
    category_id = _required_param('category_id')
    if category_id not in db.categories:
        raise ApiError('ERR_CATEGORY_NOT_FOUND', 404, 'no such category')
    views, created, rate = deflection_rate(category_id)
    return ok_object({
        'category_id': category_id,
        'window_days': DEFLECTION_WINDOW_DAYS,
        'view_count': views,
        'ticket_created_count': created,
        'deflection_rate': float(rate),
    })


@bp.get('/metrics/sla-attainment')
def metrics_sla_attainment():
    ctx = authenticate()
    require_roles(ctx, 'HRServicesAdmin', 'WorkforcePlanner', 'HelpDeskAgent',
                  'SpecialistAgent', 'SensitiveCaseManager')
    category_id = _required_param('category_id')
    if category_id not in db.categories:
        raise ApiError('ERR_CATEGORY_NOT_FOUND', 404, 'no such category')
    met = 0
    breached = 0
    for t in db.tickets.values():
        if t['category_id'] != category_id or t['resolved_at'] is None:
            continue
        if t['workflow_status'] not in ('RESOLVED', 'REOPENED', 'CLOSED'):
            continue
        if t['sla_status'] == 'MET':
            met += 1
        elif t['sla_status'] == 'BREACHED_RESOLUTION':
            breached += 1
    total = met + breached
    if total == 0:
        pct = Decimal('0.0')
    else:
        pct = (Decimal(100) * Decimal(met) / Decimal(total)).quantize(
            Decimal('0.1'), rounding=ROUND_HALF_UP)
    return ok_object({
        'category_id': category_id,
        'met_count': met,
        'breached_count': breached,
        'attainment_pct': float(pct),
    })


@bp.get('/metrics/csat')
def metrics_csat():
    ctx = authenticate()
    require_roles(ctx, 'HRServicesAdmin', 'WorkforcePlanner', 'HelpDeskAgent',
                  'SpecialistAgent', 'SensitiveCaseManager')
    agent_id = _required_param('agent_id')
    if agent_id not in db.agents:
        raise ApiError('ERR_AGENT_NOT_FOUND', 404, 'no such agent')
    count, simple, weighted = compute_csat(agent_id)
    return ok_object({
        'agent_id': agent_id,
        'window_days': CSAT_WINDOW_DAYS,
        'survey_count': count,
        'simple_mean': float(simple) if simple is not None else None,
        'recency_weighted_mean': float(weighted) if weighted is not None else None,
    })
