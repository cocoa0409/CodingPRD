"""Auth middleware: X-User-ID / X-User-Role headers (PRD §2.1, §2.8 stages 1-3).
"""

from flask import request

from errors import unauthenticated, unauthorized, ownership

ROLES = {"Customer", "CustomerServiceRep", "EligibilitySpecialist",
         "ProgramAdmin", "FieldCrew"}


class Actor:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_customer(self):
        return self.role == "Customer"


def authenticate(allowed_roles):
    """Stages 1-2: header presence + role declared, then endpoint role check."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise unauthenticated()
    actor = Actor(user_id, role)
    if role not in allowed_roles:
        raise unauthorized()
    return actor


def check_ownership(actor, account_id):
    """Stage 3: Customer may only act on account whose id == X-User-ID."""
    if actor.is_customer and account_id is not None and account_id != actor.user_id:
        raise ownership()
