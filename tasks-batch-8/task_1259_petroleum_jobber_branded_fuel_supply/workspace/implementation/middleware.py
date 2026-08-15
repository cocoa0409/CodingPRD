"""Auth context extraction, role gating, and dealer ownership scoping."""
from flask import request

from errors import (ApiError, ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
                    ERR_UNAUTHORIZED_ROLE, ERR_STATION_OWNERSHIP_MISMATCH)

DECLARED_ROLES = {
    'JobberAdmin', 'PricingDesk', 'Dispatcher', 'CreditManager',
    'TaxAccountant', 'BrandInspector', 'DealerOperator',
}

# Roles allowed on every list/detail read (PRD §2.1: reads shared by all).
ALL_ROLES = sorted(DECLARED_ROLES)


def auth_context():
    """Pipeline stage 1: user context headers present, non-blank, role declared."""
    uid = request.headers.get('X-User-ID')
    role = request.headers.get('X-User-Role')
    if (uid is None or not uid.strip() or role is None or not role.strip()
            or role.strip() not in DECLARED_ROLES):
        raise ApiError(ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, 400,
                       'X-User-ID and a declared X-User-Role are required')
    return uid, role.strip()


def require_role(role, allowed):
    """Pipeline stage 2: acting role listed among the endpoint's roles."""
    if role not in allowed:
        raise ApiError(ERR_UNAUTHORIZED_ROLE, 403,
                       'Role {} not permitted on this endpoint'.format(role))


def dealer_scope_check(uid, role, station_id):
    """Pipeline stage 5: DealerOperator may only touch their own station."""
    if role == 'DealerOperator' and station_id != uid:
        raise ApiError(ERR_STATION_OWNERSHIP_MISMATCH, 403,
                       'DealerOperator may only act on their own station')


def scoped(items, uid, role, station_of):
    """Scope list reads for DealerOperator to their own station's resources."""
    if role != 'DealerOperator':
        return items
    return [r for r in items if station_of(r) == uid]
