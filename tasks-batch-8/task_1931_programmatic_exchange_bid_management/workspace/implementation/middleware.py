"""Auth header extraction and role checking (PRD §2.1).

Every request must carry X-User-ID and X-User-Role. The four declared roles
are ExchangeAdmin, PublisherManager, DemandSide, FinanceOfficer.

Identity anchoring (PRD §2.1):
- PublisherManager is entity-backed: X-User-ID is the id of the acting
  Publisher; ownership checks compare a resource's publisher FK against it.
- ExchangeAdmin, DemandSide and FinanceOfficer are opaque operator
  identifiers, never compared to entity ids (FinanceOfficer's id is persisted
  on payout batches for segregation of duties).
"""

from flask import request

from errors import unauthenticated, unauthorized

ROLE_EXCHANGE_ADMIN = "ExchangeAdmin"
ROLE_PUBLISHER_MANAGER = "PublisherManager"
ROLE_DEMAND_SIDE = "DemandSide"
ROLE_FINANCE_OFFICER = "FinanceOfficer"

ROLES = {
    ROLE_EXCHANGE_ADMIN,
    ROLE_PUBLISHER_MANAGER,
    ROLE_DEMAND_SIDE,
    ROLE_FINANCE_OFFICER,
}

ALL_ROLES = [
    ROLE_EXCHANGE_ADMIN,
    ROLE_PUBLISHER_MANAGER,
    ROLE_DEMAND_SIDE,
    ROLE_FINANCE_OFFICER,
]


def authenticate():
    """Validation pipeline stage 1: both identity headers present and
    well-formed (a role outside the four declared roles is malformed)."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if not role or not isinstance(role, str) or role not in ROLES:
        raise unauthenticated()
    if not user_id or not isinstance(user_id, str):
        raise unauthenticated()
    return role, user_id


def require_roles(allowed):
    """Pipeline stages 1-2: authentication, then role authorization."""
    role, user_id = authenticate()
    if role not in allowed:
        raise unauthorized()
    return role, user_id
