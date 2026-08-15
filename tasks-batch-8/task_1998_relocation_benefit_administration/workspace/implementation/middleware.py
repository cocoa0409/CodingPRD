"""Auth middleware and role checking.

Per PRD §2.1 and scaffold validations[]:
  - Headers: X-User-ID and X-User-Role must both be present.
  - Role must be one of the five declared roles.
  - ERR_UNAUTHENTICATED (401) when missing/invalid.
  - ERR_FORBIDDEN (403) when role not allowed on the endpoint, or ownership check fails.
"""

from flask import request

from errors import err_unauthenticated, err_forbidden

ROLES = {"Employee", "MobilityCoordinator", "Vendor", "FinanceSpecialist", "ProgramManager"}


class Actor:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    def __repr__(self):
        return f"Actor(role={self.role!r}, user_id={self.user_id!r})"


def get_actor():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise err_unauthenticated("Missing or invalid X-User-ID / X-User-Role headers")
    return Actor(user_id=user_id, role=role)


def require_role(actor, allowed_roles):
    if actor.role not in allowed_roles:
        raise err_forbidden(f"Role {actor.role} not permitted for this endpoint")


def check_employee_owns_case(actor, case):
    """Employee may only act on resources whose case.employee_id == X-User-ID."""
    if actor.role == "Employee":
        if case is None or case.get("employee_id") != actor.user_id:
            raise err_forbidden("Employee does not own this case")


def check_vendor_owns_assignment(actor, assignment):
    """Vendor may only act on assignments with vendor_id == X-User-ID."""
    if actor.role == "Vendor":
        if assignment is None or assignment.get("vendor_id") != actor.user_id:
            raise err_forbidden("Vendor does not own this assignment")
