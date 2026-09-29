"""Authentication and role authorization.

Requests carry X-User-ID and X-User-Role; X-Role is accepted as a short-form
alias carrying the same value.  Authorization is settled before the payload
schema is examined and before the addressed resource is looked up.
"""

from flask import request

from errors import fail

ELECTIONS_DIRECTOR = "ElectionsDirector"
BALLOT_COORDINATOR = "BallotCoordinator"
LANGUAGE_ACCESS_COORDINATOR = "LanguageAccessCoordinator"
PRINT_VENDOR_REP = "PrintVendorRep"
WAREHOUSE_CUSTODIAN = "WarehouseCustodian"
VOTING_SYSTEM_TECHNICIAN = "VotingSystemTechnician"
PUBLIC_OBSERVER = "PublicObserver"

ALL_ROLES = (
    ELECTIONS_DIRECTOR,
    BALLOT_COORDINATOR,
    LANGUAGE_ACCESS_COORDINATOR,
    PRINT_VENDOR_REP,
    WAREHOUSE_CUSTODIAN,
    VOTING_SYSTEM_TECHNICIAN,
    PUBLIC_OBSERVER,
)


def role_header():
    value = request.headers.get("X-User-Role")
    if value is None or value == "":
        value = request.headers.get("X-Role")
    return value


def user_id():
    value = request.headers.get("X-User-ID")
    if value is None or value == "":
        value = request.headers.get("X-User-Id")
    return value


def require(*allowed_roles):
    """Authenticate the caller and check the operation's role list."""
    role = role_header()
    if role is None or role == "" or role not in ALL_ROLES:
        fail("ERR_UNAUTHENTICATED", "Missing or unrecognized X-Role header.")
    if allowed_roles and role not in allowed_roles:
        fail("ERR_UNAUTHORIZED", "Role %s may not perform this operation." % role)
    return role, user_id()


def require_any():
    """Every GET is open to any authenticated role."""
    return require(*ALL_ROLES)
