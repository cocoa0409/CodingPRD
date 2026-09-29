"""Authentication, RBAC and ownership (PRD 2.1, priorities 1, 2 and 5)."""

from flask import request

from errors import fail

ROLES = ("ProgramAdmin", "StateRegulator", "Trainer", "EmployerAdmin", "AlcoholServer")

PROGRAM_ADMIN = "ProgramAdmin"
STATE_REGULATOR = "StateRegulator"
TRAINER = "Trainer"
EMPLOYER_ADMIN = "EmployerAdmin"
ALCOHOL_SERVER = "AlcoholServer"


class Caller(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_program_admin(self):
        return self.role == PROGRAM_ADMIN

    @property
    def is_trainer(self):
        return self.role == TRAINER

    @property
    def is_employer_admin(self):
        return self.role == EMPLOYER_ADMIN

    @property
    def is_alcohol_server(self):
        return self.role == ALCOHOL_SERVER


def authenticate(allowed_roles):
    """Priority 1 then priority 2."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "Missing or unrecognised authentication headers.")
    if role not in allowed_roles:
        fail("ERR_ROLE_NOT_PERMITTED", "Role '%s' may not call this endpoint." % role)
    return Caller(user_id, role)


def deny_ownership():
    fail("ERR_NOT_RESOURCE_OWNER", "The caller does not own the target resource.")


def require_match(caller, expected_id):
    """Entity-backed ownership: ProgramAdmin passes by construction."""
    if caller.is_program_admin or caller.role == STATE_REGULATOR:
        return
    if expected_id is None or caller.user_id != expected_id:
        deny_ownership()
