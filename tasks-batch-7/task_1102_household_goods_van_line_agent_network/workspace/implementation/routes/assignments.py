from flask import Blueprint, request

from db import db
from errors import ApiError
from middleware import authenticate, authorize, check_order_scope, ALL_ROLES, AGENT_ROLE_MAP
from response import ok
from services import calc
from services.store import new_entity, touch, assignment_view
from util import get_body, check_body, check_ref_exists, get_path, apply_list

bp = Blueprint('assignments', __name__)

PROPOSABLE_ROLES = ('ORIGIN', 'HAULING', 'DESTINATION')


@bp.post('/orders/<oid>/agent-assignments')
def create_assignment(oid):
    auth = authenticate()
    authorize(auth, ['BookingAgent', 'VanLineAdmin'])
    check_order_scope(auth, oid)
    order = get_path(db.orders, oid)
    body = get_body()
    check_ref_exists(body, 'agent_id', db.agents)
    vals = check_body(body, [
        ('agent_id', 'str', True, None),
        ('role', 'enum', True, PROPOSABLE_ROLES),
    ])
    if order['status'] != 'REGISTERED':
        raise ApiError('ERR_ORDER_NOT_REGISTERED', 409, 'order is not REGISTERED')
    agent = db.agents[vals['agent_id']]
    if agent['status'] != 'ACTIVE':
        raise ApiError('ERR_AGENT_SUSPENDED', 409, 'assigned agent is not ACTIVE')
    if vals['role'] not in agent['capabilities']:
        raise ApiError('ERR_AGENT_CAPABILITY_MISSING', 422,
                       'agent capabilities do not include the assigned role')
    asg = new_entity()
    asg.update({
        'order_id': oid,
        'agent_id': vals['agent_id'],
        'role': vals['role'],
        'split_pct': None,
        'split_amount_cents': None,
        'status': 'PROPOSED',
    })
    db.assignments[asg['id']] = asg
    return ok(assignment_view(asg), 201)


@bp.post('/order-agent-assignments/<aid>/confirm')
def confirm_assignment(aid):
    auth = authenticate()
    authorize(auth, ['OriginAgent', 'HaulingAgent', 'DestinationAgent'])
    asg = get_path(db.assignments, aid)
    # identity: the assigned agent confirms its own assignment, in its own role
    if asg['agent_id'] != auth.user_id or AGENT_ROLE_MAP[auth.role] != asg['role']:
        raise ApiError('ERR_FORBIDDEN_ROLE', 403,
                       'the acting agent must be the assignee acting in the assignment role')
    check_body(get_body(), [])
    if asg['status'] != 'PROPOSED':
        raise ApiError('ERR_TRANSITION_NOT_ALLOWED', 409, 'assignment is not PROPOSED')
    agent = db.agents[asg['agent_id']]
    if agent['status'] != 'ACTIVE':
        raise ApiError('ERR_AGENT_SUSPENDED', 409, 'agent is not ACTIVE')
    order = db.orders[asg['order_id']]
    if order['status'] != 'REGISTERED':
        raise ApiError('ERR_ORDER_NOT_REGISTERED', 409, 'order is not REGISTERED')
    asg['split_pct'] = float(calc.split_pct_for(asg['role'], agent['commission_tier']))
    asg['status'] = 'CONFIRMED'
    touch(asg)
    return ok(assignment_view(asg))


@bp.post('/order-agent-assignments/<aid>/release')
def release_assignment(aid):
    auth = authenticate()
    authorize(auth, ['BookingAgent', 'VanLineAdmin'])
    asg = get_path(db.assignments, aid)
    check_order_scope(auth, asg['order_id'])
    check_body(get_body(), [])
    if asg['status'] != 'PROPOSED':
        raise ApiError('ERR_TRANSITION_NOT_ALLOWED', 409, 'assignment is not PROPOSED')
    if asg['role'] == 'BOOKING':
        raise ApiError('ERR_TRANSITION_NOT_ALLOWED', 409,
                       'the BOOKING assignment cannot be released')
    order = db.orders[asg['order_id']]
    if order['status'] != 'REGISTERED':
        raise ApiError('ERR_ORDER_NOT_REGISTERED', 409, 'order is not REGISTERED')
    asg['status'] = 'RELEASED'
    touch(asg)
    return ok(assignment_view(asg))


@bp.get('/order-agent-assignments')
def list_assignments():
    auth = authenticate()
    authorize(auth, ALL_ROLES)
    filters = []
    for param in ('order_id', 'agent_id', 'role', 'status'):
        v = request.args.get(param)
        if v is not None:
            filters.append(lambda a, p=param, v=v: a[p] == v)
    return apply_list(db.assignments, filters, assignment_view)


@bp.get('/order-agent-assignments/<aid>')
def get_assignment(aid):
    auth = authenticate()
    authorize(auth, ALL_ROLES)
    return ok(assignment_view(get_path(db.assignments, aid)))
