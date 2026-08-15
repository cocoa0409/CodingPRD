from flask import request

from errors import ApiError

DECLARED_ROLES = {
    'PlatformAdmin', 'StoreManager', 'SalesAssociate', 'InstitutionalBidOfficer',
    'ComplianceOfficer', 'ServiceCoordinator', 'FinanceOfficer', 'Customer', 'Consignor',
}


def auth(*allowed_roles):
    """Priority 1: headers present and role declared -> 401.
    Priority 2: role on the endpoint's authorized list -> 403."""
    uid = request.headers.get('X-User-ID')
    role = request.headers.get('X-User-Role')
    if not uid or not role or role not in DECLARED_ROLES:
        raise ApiError('ERR_UNAUTHENTICATED', 401,
                       'missing or unknown X-User-ID / X-User-Role header')
    if allowed_roles and role not in allowed_roles:
        raise ApiError('ERR_UNAUTHORIZED_ROLE', 403,
                       'role %s is not permitted for this endpoint' % role)
    return uid, role
