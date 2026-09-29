"""Authentication, role authorisation, ownership and attorney standing.

Rungs 1, 2, 6 and 7 of the validation ladder (PRD 2.8). The header names and
role literals come from PRD 2.1.
"""
from functools import wraps

from flask import request

import errors
from enums import ROLES
from store import db
from timeutil import midnight, parse_date, parse_instant

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"

ENTITY_BACKED = {"Participant", "AlternatePayee", "Attorney"}


class Caller(object):
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_participant(self):
        return self.role == "Participant"

    @property
    def is_payee(self):
        return self.role == "AlternatePayee"

    @property
    def is_attorney(self):
        return self.role == "Attorney"


def authenticate():
    """Rung 1: both headers present and the role one of the five declared names."""
    user_id = request.headers.get(USER_ID_HEADER)
    role = request.headers.get(USER_ROLE_HEADER)
    if user_id is None or role is None or user_id == "" or role == "":
        errors.fail(errors.ERR_UNAUTHENTICATED, "Both X-User-ID and X-User-Role are required.")
    if role not in ROLES:
        errors.fail(errors.ERR_UNAUTHENTICATED, "X-User-Role is not a recognised role.")
    return Caller(user_id, role)


def require_roles(caller, allowed):
    """Rung 2: the presented role appears among the endpoint's authorised roles."""
    if caller.role not in allowed:
        errors.fail(errors.ERR_FORBIDDEN_ROLE,
                    "Role %s may not call this endpoint." % caller.role)


def endpoint(*allowed):
    """Wrap a view so rungs 1 and 2 run before anything else it does."""
    def decorate(view):
        @wraps(view)
        def wrapper(**kwargs):
            caller = authenticate()
            require_roles(caller, allowed)
            return view(caller, **kwargs)
        return wrapper
    return decorate


# --- ownership (rung 6) -----------------------------------------------------

def _not_owner():
    errors.fail(errors.ERR_NOT_RESOURCE_OWNER,
                "The presented X-User-ID does not own the resource reached.")


def acting_authorization(caller):
    return db.attorney_authorizations.get(caller.user_id)


def own_participant(caller, participant_id):
    if caller.is_participant and caller.user_id != participant_id:
        _not_owner()


def own_case(caller, case):
    """Ownership of any resource that resolves to a case."""
    if caller.is_participant:
        if caller.user_id != case["participant_id"]:
            _not_owner()
    elif caller.is_payee:
        account = db.ap_accounts.get(caller.user_id)
        if account is None or account["qdro_case_id"] != case["id"]:
            _not_owner()
    elif caller.is_attorney:
        authorization = acting_authorization(caller)
        if authorization is None or authorization["qdro_case_id"] != case["id"]:
            _not_owner()


def own_ap_account(caller, account):
    if caller.is_payee and caller.user_id != account["id"]:
        _not_owner()
    if caller.is_participant or caller.is_attorney:
        case = db.qdro_cases.get(account["qdro_case_id"])
        if case is None:
            _not_owner()
        own_case(caller, case)


def own_plan_account(caller, account):
    if caller.is_participant and caller.user_id != account["participant_id"]:
        _not_owner()


# --- attorney standing (rung 7) ---------------------------------------------

def attorney_standing(caller, supplied_authorization_id=None):
    """Rung 7: ACTIVE, inside the operative window, and citing itself."""
    if not caller.is_attorney:
        return None
    authorization = acting_authorization(caller)
    if authorization is None:
        errors.fail(errors.ERR_ATTORNEY_NOT_AUTHORIZED, "No such attorney authorization.")
    if authorization["status"] != "ACTIVE":
        errors.fail(errors.ERR_ATTORNEY_NOT_AUTHORIZED, "The attorney authorization is not ACTIVE.")
    now = db.now()
    effective_from = parse_date(authorization["effective_from"])
    if now < midnight(effective_from):
        errors.fail(errors.ERR_ATTORNEY_NOT_AUTHORIZED,
                    "The attorney authorization is not yet operative.")
    expires_at = parse_instant(authorization["expires_at"])
    if now > expires_at:
        errors.fail(errors.ERR_ATTORNEY_NOT_AUTHORIZED, "The attorney authorization has expired.")
    if supplied_authorization_id is not None and supplied_authorization_id != caller.user_id:
        errors.fail(errors.ERR_ATTORNEY_NOT_AUTHORIZED,
                    "attorney_authorization_id must equal the acting attorney's X-User-ID.")
    return authorization
