"""Authentication, role authorisation, actor identity and firm isolation (PRD 2.1).

Bands 1-3 and bands 9-10 of the global request-evaluation order (PRD 2.5) live here.
"""

from flask import request

import store
from errors import ApiError

SYSTEM_ADMIN = "SystemAdmin"
FIRM_MANAGING_PARTNER = "FirmManagingPartner"
ENGAGEMENT_PARTNER = "EngagementPartner"
QUALITY_CONTROL_DIRECTOR = "QualityControlDirector"
ENGAGEMENT_QUALITY_REVIEWER = "EngagementQualityReviewer"
PEER_REVIEWER = "PeerReviewer"
PEER_REVIEW_COMMITTEE = "PeerReviewCommittee"

ALL_ROLES = (
    SYSTEM_ADMIN, FIRM_MANAGING_PARTNER, ENGAGEMENT_PARTNER, QUALITY_CONTROL_DIRECTOR,
    ENGAGEMENT_QUALITY_REVIEWER, PEER_REVIEWER, PEER_REVIEW_COMMITTEE,
)

# The four roles whose X-User-ID must resolve to a Partner row of some firm.
PARTNER_ROLES = (
    FIRM_MANAGING_PARTNER, ENGAGEMENT_PARTNER, QUALITY_CONTROL_DIRECTOR,
    ENGAGEMENT_QUALITY_REVIEWER,
)

# Roles whose X-User-ID is opaque: the server never compares it to any entity id.
OPAQUE_ROLES = (SYSTEM_ADMIN, PEER_REVIEW_COMMITTEE)


class Actor(object):
    __slots__ = ("role", "user_id", "partner", "reviewer")

    def __init__(self, role, user_id, partner=None, reviewer=None):
        self.role = role
        self.user_id = user_id
        self.partner = partner
        self.reviewer = reviewer

    @property
    def is_partner_backed(self):
        return self.partner is not None

    @property
    def firm_id(self):
        return self.partner["firm_id"] if self.partner else None


def authenticate(allowed_roles, require_headers=True):
    """Bands 1-3: header presence and role vocabulary, endpoint role authorisation, then
    actor identity resolution for the five entity-backed roles."""
    role = (request.headers.get("X-User-Role") or "").strip()
    user_id = (request.headers.get("X-User-ID") or "").strip()

    if require_headers:
        if not role or not user_id or role not in ALL_ROLES:
            raise ApiError("ERR_UNAUTHENTICATED")

    if role not in allowed_roles:
        raise ApiError("ERR_ROLE_NOT_PERMITTED")

    partner = None
    reviewer = None
    if role in PARTNER_ROLES:
        partner = store.get(store.PARTNERS, user_id)
        if partner is None:
            raise ApiError("ERR_ROLE_IDENTITY_UNKNOWN")
    elif role == PEER_REVIEWER:
        reviewer = store.get(store.PEER_REVIEWERS, user_id)
        if reviewer is None:
            raise ApiError("ERR_ROLE_IDENTITY_UNKNOWN")

    return Actor(role, user_id, partner, reviewer)


def require_owner(actor, owner_id, roles=None):
    """Band 9: ERR_NOT_RESOURCE_OWNER.

    Opaque-identity roles (SystemAdmin, PeerReviewCommittee) are never subject to an
    ownership comparison.  When ``roles`` is given the check only applies to an actor
    holding one of those roles.
    """
    if actor.role in OPAQUE_ROLES:
        return
    if roles is not None and actor.role not in roles:
        return
    if owner_id is None or actor.user_id != owner_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")


def require_same_firm(actor, firm_id):
    """Band 10: a Partner-backed actor may only touch resources of their own firm."""
    if not actor.is_partner_backed:
        return
    if firm_id is None or actor.firm_id != firm_id:
        raise ApiError("ERR_CROSS_FIRM_ACCESS_DENIED")
