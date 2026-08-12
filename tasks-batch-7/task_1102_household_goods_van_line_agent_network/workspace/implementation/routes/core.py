from flask import Blueprint, request

from db import db
from errors import ApiError, bad_request
from middleware import authenticate, authorize, ALL_ROLES
from response import ok
from services.lifecycle import reevaluate_all_lots
from services.store import (new_entity, touch, agent_view, customer_view,
                            tariff_view, warehouse_view)
from util import get_body, check_body, get_path, apply_list, fmt_ts

bp = Blueprint('core', __name__)

CAPABILITIES = ('BOOKING', 'ORIGIN', 'HAULING', 'DESTINATION')


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

@bp.post('/_clock/set_current_utc')
def set_clock():
    auth = authenticate()
    authorize(auth, ['VanLineAdmin'])
    vals = check_body(get_body(), [('to_iso8601', 'datetime', True, None)])
    db.clock = vals['to_iso8601']
    reevaluate_all_lots()
    return ok({'current_utc': fmt_ts(db.clock)})


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------

@bp.post('/agents')
def create_agent():
    auth = authenticate()
    authorize(auth, ['VanLineAdmin'])
    vals = check_body(get_body(), [
        ('legal_name', 'str', True, None),
        ('agent_code', 'str', True, None),
        ('capabilities', 'list', True, None),
        ('home_market', 'str', True, None),
        ('commission_tier', 'enum', False, ('STANDARD', 'PREFERRED', 'PREMIER')),
    ])
    caps = vals['capabilities']
    if not caps or any(not isinstance(c, str) or c not in CAPABILITIES for c in caps):
        bad_request('capabilities must be a non-empty subset of BOOKING, ORIGIN, HAULING, DESTINATION')
    if not (4 <= len(vals['agent_code']) <= 8):
        bad_request('agent_code must be 4-8 characters')
    for a in db.agents.values():
        if a['agent_code'] == vals['agent_code']:
            raise ApiError('ERR_DUPLICATE_AGENT_CODE', 409, 'agent_code already registered')
    agent = new_entity()
    agent.update({
        'legal_name': vals['legal_name'],
        'agent_code': vals['agent_code'],
        'capabilities': list(caps),
        'home_market': vals['home_market'],
        'commission_tier': vals.get('commission_tier', 'STANDARD'),
        'quality_score': 100,
        'ytd_linehaul_share_cents': 0,
        'status': 'ACTIVE',
    })
    db.agents[agent['id']] = agent
    return ok(agent_view(agent), 201)


@bp.get('/agents')
def list_agents():
    auth = authenticate()
    authorize(auth, ALL_ROLES)
    filters = []
    status = request.args.get('status')
    if status is not None:
        filters.append(lambda a: a['status'] == status)
    cap = request.args.get('capability')
    if cap is not None:
        filters.append(lambda a: cap in a['capabilities'])
    return apply_list(db.agents, filters, agent_view)


@bp.get('/agents/<aid>')
def get_agent(aid):
    auth = authenticate()
    authorize(auth, ALL_ROLES)
    return ok(agent_view(get_path(db.agents, aid)))


@bp.post('/agents/<aid>/suspend')
def suspend_agent(aid):
    auth = authenticate()
    authorize(auth, ['VanLineAdmin'])
    agent = get_path(db.agents, aid)
    body = check_body(get_body(), [('terminal', 'bool', False, None)])
    terminal = body.get('terminal', False)
    if terminal:
        if agent['status'] != 'SUSPENDED':
            raise ApiError('ERR_TRANSITION_NOT_ALLOWED', 409,
                           'termination requires the agent to be SUSPENDED')
        for a in db.assignments.values():
            if a['agent_id'] == aid and a['status'] in ('PROPOSED', 'CONFIRMED'):
                o = db.orders.get(a['order_id'])
                if o and o['status'] not in ('DELIVERED', 'SETTLED', 'CLOSED', 'CANCELLED'):
                    raise ApiError('ERR_AGENT_HAS_OPEN_WORK', 409,
                                   'agent holds PROPOSED/CONFIRMED assignments on non-terminal orders')
        agent['status'] = 'TERMINATED'
    else:
        if agent['status'] != 'ACTIVE':
            raise ApiError('ERR_TRANSITION_NOT_ALLOWED', 409,
                           'suspension requires the agent to be ACTIVE')
        agent['status'] = 'SUSPENDED'
    touch(agent)
    return ok(agent_view(agent))


@bp.post('/agents/<aid>/reactivate')
def reactivate_agent(aid):
    auth = authenticate()
    authorize(auth, ['VanLineAdmin'])
    agent = get_path(db.agents, aid)
    check_body(get_body(), [])
    if agent['status'] != 'SUSPENDED':
        raise ApiError('ERR_TRANSITION_NOT_ALLOWED', 409,
                       'reactivation requires the agent to be SUSPENDED')
    agent['status'] = 'ACTIVE'
    touch(agent)
    return ok(agent_view(agent))


# ---------------------------------------------------------------------------
# Customers
# ---------------------------------------------------------------------------

@bp.post('/customers')
def create_customer():
    auth = authenticate()
    authorize(auth, ['VanLineAdmin', 'BookingAgent'])
    vals = check_body(get_body(), [
        ('full_name', 'str', True, None),
        ('email', 'str', True, None),
        ('phone', 'str', True, None),
    ])
    for c in db.customers.values():
        if c['email'] == vals['email']:
            raise ApiError('ERR_DUPLICATE_CUSTOMER_EMAIL', 409, 'customer email already registered')
    cust = new_entity()
    cust.update({
        'full_name': vals['full_name'],
        'email': vals['email'],
        'phone': vals['phone'],
        'status': 'ACTIVE',
    })
    db.customers[cust['id']] = cust
    return ok(customer_view(cust), 201)


@bp.get('/customers')
def list_customers():
    auth = authenticate()
    authorize(auth, ALL_ROLES)
    return apply_list(db.customers, [], customer_view)


@bp.get('/customers/<cid>')
def get_customer(cid):
    auth = authenticate()
    authorize(auth, ALL_ROLES)
    return ok(customer_view(get_path(db.customers, cid)))


# ---------------------------------------------------------------------------
# Tariffs
# ---------------------------------------------------------------------------

def _validate_bands(bands):
    if not bands:
        bad_request('mileage_bands must be a non-empty array')
    for b in bands:
        if not isinstance(b, dict):
            bad_request('each mileage band must be an object')
        if set(b.keys()) != {'min_miles', 'max_miles', 'rate_multiplier'}:
            bad_request('mileage band keys must be exactly min_miles, max_miles, rate_multiplier')
        if isinstance(b['min_miles'], bool) or not isinstance(b['min_miles'], int):
            bad_request('min_miles must be an integer')
        if isinstance(b['max_miles'], bool) or not isinstance(b['max_miles'], int):
            bad_request('max_miles must be an integer')
        if isinstance(b['rate_multiplier'], bool) or not isinstance(b['rate_multiplier'], (int, float)):
            bad_request('rate_multiplier must be a number')
        if b['min_miles'] >= b['max_miles']:
            bad_request('each mileage band must have min_miles < max_miles')
    s = sorted(bands, key=lambda b: b['min_miles'])
    if s[0]['min_miles'] != 0:
        bad_request('mileage_bands must tile from 0')
    for i in range(1, len(s)):
        if s[i]['min_miles'] != s[i - 1]['max_miles']:
            bad_request('mileage_bands must tile without gaps or overlaps')


@bp.post('/tariffs')
def create_tariff():
    auth = authenticate()
    authorize(auth, ['VanLineAdmin'])
    vals = check_body(get_body(), [
        ('tariff_code', 'str', True, None),
        ('effective_start', 'datetime', True, None),
        ('effective_end', 'datetime', True, None),
        ('base_rate_cents_per_cwt', 'int', True, (0, None)),
        ('mileage_bands', 'list', True, None),
        ('fuel_surcharge_pct', 'num', True, None),
        ('sit_daily_rate_cents_per_cwt', 'int', True, (0, None)),
        ('hourly_labor_rate_cents', 'int', True, (0, None)),
    ])
    if vals['effective_end'] <= vals['effective_start']:
        bad_request('effective_end must be strictly later than effective_start')
    _validate_bands(vals['mileage_bands'])
    if vals['fuel_surcharge_pct'] < 0:
        bad_request('fuel_surcharge_pct must be >= 0')
    for t in db.tariffs.values():
        if t['tariff_code'] == vals['tariff_code']:
            raise ApiError('ERR_DUPLICATE_TARIFF_CODE', 409, 'tariff_code already registered')
    tariff = new_entity()
    tariff.update({
        'tariff_code': vals['tariff_code'],
        'effective_start': vals['effective_start'],
        'effective_end': vals['effective_end'],
        'base_rate_cents_per_cwt': vals['base_rate_cents_per_cwt'],
        'mileage_bands': [dict(b) for b in vals['mileage_bands']],
        'fuel_surcharge_pct': vals['fuel_surcharge_pct'],
        'sit_daily_rate_cents_per_cwt': vals['sit_daily_rate_cents_per_cwt'],
        'hourly_labor_rate_cents': vals['hourly_labor_rate_cents'],
        'status': 'DRAFT',
    })
    db.tariffs[tariff['id']] = tariff
    return ok(tariff_view(tariff), 201)


@bp.post('/tariffs/<tid>/publish')
def publish_tariff(tid):
    auth = authenticate()
    authorize(auth, ['VanLineAdmin'])
    tariff = get_path(db.tariffs, tid)
    check_body(get_body(), [])
    if tariff['status'] != 'DRAFT':
        raise ApiError('ERR_TRANSITION_NOT_ALLOWED', 409, 'only a DRAFT tariff may be published')
    for t in db.tariffs.values():
        if t['id'] == tid or t['status'] != 'PUBLISHED':
            continue
        # half-open windows; adjacency (other.end == this.start) allowed
        if not (t['effective_end'] <= tariff['effective_start'] or t['effective_start'] >= tariff['effective_end']):
            raise ApiError('ERR_TARIFF_WINDOW_OVERLAP', 409,
                           'window intersects another PUBLISHED tariff window')
    tariff['status'] = 'PUBLISHED'
    touch(tariff)
    return ok(tariff_view(tariff))


@bp.get('/tariffs')
def list_tariffs():
    auth = authenticate()
    authorize(auth, ALL_ROLES)
    filters = []
    status = request.args.get('status')
    if status is not None:
        filters.append(lambda t: t['status'] == status)
    return apply_list(db.tariffs, filters, tariff_view)


@bp.get('/tariffs/<tid>')
def get_tariff(tid):
    auth = authenticate()
    authorize(auth, ALL_ROLES)
    return ok(tariff_view(get_path(db.tariffs, tid)))


# ---------------------------------------------------------------------------
# Warehouses
# ---------------------------------------------------------------------------

@bp.post('/warehouses')
def create_warehouse():
    auth = authenticate()
    authorize(auth, ['VanLineAdmin'])
    vals = check_body(get_body(), [
        ('name', 'str', True, None),
        ('market', 'str', True, None),
        ('capacity_cwt', 'int', True, (1, None)),
    ])
    wh = new_entity()
    wh.update({
        'name': vals['name'],
        'market': vals['market'],
        'capacity_cwt': vals['capacity_cwt'],
        'occupied_cwt': 0,
        'status': 'ACTIVE',
    })
    db.warehouses[wh['id']] = wh
    return ok(warehouse_view(wh), 201)


@bp.post('/warehouses/<wid>/deactivate')
def deactivate_warehouse(wid):
    auth = authenticate()
    authorize(auth, ['VanLineAdmin'])
    wh = get_path(db.warehouses, wid)
    check_body(get_body(), [])
    if wh['status'] != 'ACTIVE':
        raise ApiError('ERR_TRANSITION_NOT_ALLOWED', 409, 'warehouse is not ACTIVE')
    wh['status'] = 'INACTIVE'
    touch(wh)
    return ok(warehouse_view(wh))


@bp.get('/warehouses')
def list_warehouses():
    auth = authenticate()
    authorize(auth, ALL_ROLES)
    filters = []
    status = request.args.get('status')
    if status is not None:
        filters.append(lambda w: w['status'] == status)
    return apply_list(db.warehouses, filters, warehouse_view)


@bp.get('/warehouses/<wid>')
def get_warehouse(wid):
    auth = authenticate()
    authorize(auth, ALL_ROLES)
    return ok(warehouse_view(get_path(db.warehouses, wid)))
