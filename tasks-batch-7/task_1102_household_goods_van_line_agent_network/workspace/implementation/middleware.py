from flask import request

from db import db
from errors import ApiError

ROLES = {
    'VanLineAdmin', 'BookingAgent', 'OriginAgent', 'HaulingAgent',
    'DestinationAgent', 'Customer', 'ClaimsAdjuster', 'Arbitrator',
}
AGENT_ROLE_MAP = {
    'BookingAgent': 'BOOKING',
    'OriginAgent': 'ORIGIN',
    'HaulingAgent': 'HAULING',
    'DestinationAgent': 'DESTINATION',
}
OPAQUE_ROLES = {'VanLineAdmin', 'ClaimsAdjuster', 'Arbitrator'}
ALL_ROLES = sorted(ROLES)


class Auth:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate():
    uid = request.headers.get('X-User-ID')
    role = request.headers.get('X-User-Role')
    if not uid or not role or role not in ROLES:
        raise ApiError('ERR_UNAUTHENTICATED', 401,
                       'X-User-ID and X-User-Role headers are required and the role must be one of the eight declared roles')
    return Auth(uid, role)


def authorize(auth, allowed_roles):
    if auth.role not in allowed_roles:
        raise ApiError('ERR_FORBIDDEN_ROLE', 403, 'role is not authorized for this endpoint')
    # entity-backed roles: X-User-ID must resolve to an existing backing entity
    if auth.role in AGENT_ROLE_MAP:
        if auth.user_id not in db.agents:
            raise ApiError('ERR_FORBIDDEN_ROLE', 403, 'X-User-ID does not resolve to an existing Agent')
    elif auth.role == 'Customer':
        if auth.user_id not in db.customers:
            raise ApiError('ERR_FORBIDDEN_ROLE', 403, 'X-User-ID does not resolve to an existing Customer')


def check_order_scope(auth, order_id):
    """Ownership scoping (pipeline stage 3) for order-scoped mutations.

    The agent must hold an assignment on the target order with agent_id == X-User-ID
    and role matching the caller's agent role. The assignment's lifecycle status is
    intentionally not re-filtered here: §3 gives every action endpoint its own
    documented from-state error (e.g. deliver from DELIVERED -> ERR_TRANSITION_NOT_ALLOWED),
    and those state gates must stay reachable for the legitimate role holder whose
    assignment has by then advanced to COMPLETED or RELEASED. The operative ownership
    question — is this agent the one holding this role on this order — is stable
    across the assignment lifecycle."""
    if auth.role in OPAQUE_ROLES:
        return
    if auth.role == 'Customer':
        o = db.orders.get(order_id)
        if not o or o['customer_id'] != auth.user_id:
            raise ApiError('ERR_FORBIDDEN_ROLE', 403, 'customer does not own the target order')
        return
    want = AGENT_ROLE_MAP[auth.role]
    for a in db.assignments.values():
        if (a['order_id'] == order_id and a['agent_id'] == auth.user_id
                and a['role'] == want):
            return
    raise ApiError('ERR_FORBIDDEN_ROLE', 403,
                   'agent does not hold a matching assignment on the target order')
