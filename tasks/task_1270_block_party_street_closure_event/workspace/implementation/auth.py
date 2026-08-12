"""Auth header extraction, role gating, and Organizer ownership checks.

Every request must carry X-User-ID and X-User-Role. The Organizer role is
entity-backed (X-User-ID is an Organizer.id); all other roles are opaque.
"""
from flask import request

from errors import ApiError

ROLES = {
    'Anonymous', 'Organizer', 'Neighbor', 'TrafficReviewer', 'SafetyReviewer',
    'PermitOfficer', 'DepotOfficer', 'CityAdmin',
}
ALL_ROLES = ['Organizer', 'Neighbor', 'TrafficReviewer', 'SafetyReviewer',
             'PermitOfficer', 'DepotOfficer', 'CityAdmin']
REVIEW_ROLES = ['Organizer', 'TrafficReviewer', 'SafetyReviewer',
                'PermitOfficer', 'DepotOfficer', 'CityAdmin']


def auth(allowed):
    uid = request.headers.get('X-User-ID')
    role = request.headers.get('X-User-Role')
    if not uid or not role or role not in ROLES:
        raise ApiError('ERR_UNAUTHENTICATED',
                       'X-User-ID and X-User-Role headers are required and the role must be recognized',
                       401)
    if role not in allowed:
        raise ApiError('ERR_UNAUTHORIZED',
                       'Role %s is not permitted for this endpoint' % role, 403)
    return uid, role


def own_or_403(role, uid, organizer_id):
    """Entity-backed Organizer ownership check against a resource's owner."""
    if role == 'Organizer' and uid != organizer_id:
        raise ApiError('ERR_NOT_RESOURCE_OWNER',
                       'Caller does not own the target resource', 403)
