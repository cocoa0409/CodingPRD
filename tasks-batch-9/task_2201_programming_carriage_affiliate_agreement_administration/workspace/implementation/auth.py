"""Authentication, RBAC and DistributorLiaison scoping (PRD section 2.1)."""
from flask import request

from constants import ROLES
from errors import ApiError
from store import db

HEADER_USER_ID = "X-User-ID"
HEADER_USER_ROLE = "X-User-Role"


class Caller(object):
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_liaison(self):
        return self.role == "DistributorLiaison"


def authenticate():
    user_id = request.headers.get(HEADER_USER_ID)
    role = request.headers.get(HEADER_USER_ROLE)
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "missing or invalid identity headers")
    return Caller(user_id, role)


def guard(allowed_roles):
    """Rule 1 then rule 2 of the validation gauntlet."""
    caller = authenticate()
    if caller.role not in allowed_roles:
        raise ApiError(
            "ERR_FORBIDDEN_ROLE",
            "role %s may not call this endpoint" % caller.role,
        )
    return caller


# ---------------------------------------------------------------------------
# distributor resolution for scope checks
# ---------------------------------------------------------------------------
def agreement_distributor_id(agreement):
    if not agreement:
        return None
    return agreement.get("distributor_id")


def resolve_distributor_for_agreement_id(agreement_id):
    agreement = db.agreements.get(agreement_id)
    return agreement_distributor_id(agreement)


def resolve_distributor_of(record, kind):
    """Resolve the operator a record belongs to, per PRD section 2.1."""
    if record is None:
        return None
    if kind == "distributor":
        return record.get("id")
    if kind == "invoice":
        return record.get("distributor_id")
    if kind == "agreement":
        return record.get("distributor_id")
    if kind == "title":
        return None
    if kind == "rate_card_entry":
        return None
    if kind == "finding":
        engagement = db.audit_engagements.get(record.get("engagement_id"))
        if not engagement:
            return None
        return resolve_distributor_for_agreement_id(engagement.get("agreement_id"))
    if kind == "mfn":
        return resolve_distributor_for_agreement_id(record.get("agreement_id"))
    # report, engagement, window, blackout, commitment, analysis
    return resolve_distributor_for_agreement_id(record.get("agreement_id"))


def enforce_scope(caller, distributor_id):
    """Rule 4: a DistributorLiaison may act only on its own operator."""
    if not caller.is_liaison:
        return
    if distributor_id is None or distributor_id != caller.user_id:
        raise ApiError(
            "ERR_DISTRIBUTOR_SCOPE_VIOLATION",
            "caller is scoped to a different operator",
        )


def scope_filter(caller, records, kind):
    """List endpoints show a liaison only its own operator's records."""
    if not caller.is_liaison:
        return records
    return [
        r for r in records if resolve_distributor_of(r, kind) == caller.user_id
    ]
