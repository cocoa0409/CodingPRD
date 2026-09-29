"""Actor identities and request headers.

The PRD authorises endpoints by the role carried in ``X-User-Role`` and
identifies the acting user by ``X-User-ID``.  Several rules turn on the acting
user rather than the role — an observation may not be validated by the user who
recorded it, a report may not be certified by the user who compiled it, and a
fee credit application may only be resubmitted by the account that filed it.
Tests therefore need more than one distinct user per role.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# --------------------------------------------------------------------------
# Distinct actors per role.  Where a rule keys on the acting user, two actors
# holding the same role are needed so that "a different user" is expressible.
# --------------------------------------------------------------------------

MANAGER_ONE = "mgr-01"
MANAGER_TWO = "mgr-02"
IDDE_ONE = "idde-01"
IDDE_TWO = "idde-02"
INSPECTOR_ONE = "insp-01"
INSPECTOR_TWO = "insp-02"
OFFICER_ONE = "enf-01"
OFFICER_TWO = "enf-02"
OPERATIONS_ONE = "ops-01"
OPERATIONS_TWO = "ops-02"
CLERK_ONE = "clerk-01"
CLERK_TWO = "clerk-02"


TEST_USERS: Dict[str, Dict[str, str]] = {
    "manager": {
        "user_id": MANAGER_ONE,
        "role": UserRole.STORMWATER_PROGRAM_MANAGER.value,
    },
    "manager_two": {
        "user_id": MANAGER_TWO,
        "role": UserRole.STORMWATER_PROGRAM_MANAGER.value,
    },
    "idde": {
        "user_id": IDDE_ONE,
        "role": UserRole.IDDE_INVESTIGATOR.value,
    },
    "idde_two": {
        "user_id": IDDE_TWO,
        "role": UserRole.IDDE_INVESTIGATOR.value,
    },
    "inspector": {
        "user_id": INSPECTOR_ONE,
        "role": UserRole.CONSTRUCTION_INSPECTOR.value,
    },
    "inspector_two": {
        "user_id": INSPECTOR_TWO,
        "role": UserRole.CONSTRUCTION_INSPECTOR.value,
    },
    "officer": {
        "user_id": OFFICER_ONE,
        "role": UserRole.ENFORCEMENT_OFFICER.value,
    },
    "officer_two": {
        "user_id": OFFICER_TWO,
        "role": UserRole.ENFORCEMENT_OFFICER.value,
    },
    "operations": {
        "user_id": OPERATIONS_ONE,
        "role": UserRole.MUNICIPAL_OPERATIONS_SUPERVISOR.value,
    },
    "operations_two": {
        "user_id": OPERATIONS_TWO,
        "role": UserRole.MUNICIPAL_OPERATIONS_SUPERVISOR.value,
    },
    "clerk": {
        "user_id": CLERK_ONE,
        "role": UserRole.UTILITY_BILLING_CLERK.value,
    },
    "clerk_two": {
        "user_id": CLERK_TWO,
        "role": UserRole.UTILITY_BILLING_CLERK.value,
    },
}


def headers_for(key: str) -> Dict[str, str]:
    """Headers for one of the fixed actors above."""
    user = TEST_USERS[key]
    return build_user_headers(user["user_id"], user["role"])


MANAGER_HEADERS = headers_for("manager")
MANAGER_TWO_HEADERS = headers_for("manager_two")
IDDE_HEADERS = headers_for("idde")
IDDE_TWO_HEADERS = headers_for("idde_two")
INSPECTOR_HEADERS = headers_for("inspector")
INSPECTOR_TWO_HEADERS = headers_for("inspector_two")
OFFICER_HEADERS = headers_for("officer")
OFFICER_TWO_HEADERS = headers_for("officer_two")
OPERATIONS_HEADERS = headers_for("operations")
OPERATIONS_TWO_HEADERS = headers_for("operations_two")
CLERK_HEADERS = headers_for("clerk")
CLERK_TWO_HEADERS = headers_for("clerk_two")


# --------------------------------------------------------------------------
# PropertyOwner is not a fixed actor.  The PRD says that when ``X-User-Role``
# is ``PropertyOwner``, ``X-User-ID`` is the ``id`` of the acting
# ``StormwaterAccount``, so the header must be built from an account created
# by the test itself.  There is deliberately no shared PropertyOwner constant.
# --------------------------------------------------------------------------


def make_property_owner_headers(account_id: str) -> Dict[str, str]:
    """Headers for the property owner acting as the given account."""
    return build_user_headers(account_id, UserRole.PROPERTY_OWNER.value)


def role_only_headers(role: str) -> Dict[str, str]:
    """Headers that carry a role but deliberately omit ``X-User-ID``.

    ``build_user_headers`` always emits ``X-User-ID``, so the missing-header
    case has to be constructed by hand.
    """
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_with_unknown_actor(role: str) -> Dict[str, str]:
    """Headers naming an actor the server has never heard of."""
    return build_user_headers("nobody-at-all", role)
