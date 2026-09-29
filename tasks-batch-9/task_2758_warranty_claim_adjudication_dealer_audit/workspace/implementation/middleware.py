"""Authentication, role authorisation and dealer scoping (PRD 2.1, 2.11 steps 1-3)."""

from flask import request

from errors import ApiError

WARRANTY_ADMIN = "WarrantyAdmin"
CLAIM_ADJUDICATOR = "ClaimAdjudicator"
ADJUDICATION_MANAGER = "AdjudicationManager"
FIELD_AUDITOR = "FieldAuditor"
AUDIT_MANAGER = "AuditManager"
APPEAL_REVIEWER = "AppealReviewer"
DEALER_WARRANTY_ADMIN = "DealerWarrantyAdmin"

ROLES = (
    WARRANTY_ADMIN,
    CLAIM_ADJUDICATOR,
    ADJUDICATION_MANAGER,
    FIELD_AUDITOR,
    AUDIT_MANAGER,
    APPEAL_REVIEWER,
    DEALER_WARRANTY_ADMIN,
)


class Actor(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_dealer(self):
        return self.role == DEALER_WARRANTY_ADMIN


def auth(*allowed_roles):
    """Step 1: header presence and role validity. Step 2: endpoint authorisation."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not str(user_id).strip():
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID header is required.")
    if not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role header must name one of the seven declared roles.")
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED", "Role %s is not authorised for this endpoint." % role)
    return Actor(str(user_id), role)


def scope(actor, dealer_id):
    """Step 3: a DealerWarrantyAdmin may only reach its own dealership."""
    if actor.is_dealer and dealer_id != actor.user_id:
        raise ApiError("ERR_DEALER_SCOPE_VIOLATION", "This resource does not belong to the acting dealership.")


def scope_body(actor, data, key):
    """Scope check against a body-declared dealer identifier, when one is legible."""
    if not actor.is_dealer:
        return
    value = data.get(key)
    if isinstance(value, str) and value != actor.user_id:
        raise ApiError("ERR_DEALER_SCOPE_VIOLATION", "The %s in the body must equal X-User-ID." % key)


def fetch(store, record_id, error_id):
    """Step 5/6: existence, returning the record or raising the entity's not-found code."""
    record = store.get(record_id)
    if record is None:
        raise ApiError(error_id)
    return record
