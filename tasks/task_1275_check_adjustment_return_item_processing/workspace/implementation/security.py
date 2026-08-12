"""Auth header extraction, role authorization, and Customer ownership (PRD §2.1).

Headers: X-User-ID and X-User-Role. Six declared roles. The Customer role is
entity-backed: X-User-ID is the acting DepositorAccount's id and ownership
checks compare a resource's depositor_account_id against it.
"""
from flask import request

from errors import ApiError

ROLES = [
    'OperationsAdmin',
    'ItemProcessor',
    'AdjustmentAnalyst',
    'ComplianceOfficer',
    'CustomerService',
    'Customer',
]

ALL_ROLES = list(ROLES)
OPS_ROLES = ['OperationsAdmin', 'ItemProcessor', 'AdjustmentAnalyst',
             'ComplianceOfficer', 'CustomerService']


def auth_ctx():
    """Priority 1: both headers present and role is a declared role."""
    user_id = request.headers.get('X-User-ID')
    role = request.headers.get('X-User-Role')
    if not user_id or not role or role not in ROLES:
        raise ApiError('ERR_UNAUTHENTICATED', 401,
                       'Missing or invalid X-User-ID / X-User-Role headers')
    return {'user_id': user_id, 'role': role}


def require_roles(ctx, roles):
    """Priority 2: acting role must be in the endpoint's role list."""
    if ctx['role'] not in roles:
        raise ApiError('ERR_UNAUTHORIZED_ROLE', 403,
                       'Role %s is not authorized for this endpoint' % ctx['role'])


def customer_owns(ctx, account_id):
    """Priority 3: Customer may only touch resources of their own account."""
    if ctx['role'] == 'Customer' and ctx['user_id'] != account_id:
        raise ApiError('ERR_FORBIDDEN_OWNERSHIP', 403,
                       'Customer may only access resources of their own account')


def customer_list_scope(ctx, requested_account_id):
    """List scoping for Customer: forced to own depositor_account_id.

    An explicit mismatched depositor_account_id filter is a 403.
    """
    if ctx['role'] != 'Customer':
        return requested_account_id
    if requested_account_id is not None and requested_account_id != ctx['user_id']:
        raise ApiError('ERR_FORBIDDEN_OWNERSHIP', 403,
                       'Customer may only access resources of their own account')
    return ctx['user_id']
