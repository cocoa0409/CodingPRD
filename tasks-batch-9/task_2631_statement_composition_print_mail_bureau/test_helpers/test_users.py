"""Pre-built identity headers for the six operator roles.

Both ``X-User-ID`` and ``X-User-Role`` are mandatory on every request. Identity
is opaque: the user id is never compared against any entity's ``id``, and it is
recorded only where the contract says so — ``composed_by_user_id``,
``sealed_by_user_id`` and ``manifested_by_user_id`` — which is what the
segregation-of-duties rules key on. Tests that need two distinct actors in the
same authorised role use the numbered variants or ``headers_for()``.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import Role

# --------------------------------------------------------------------------
# Default actor per role
# --------------------------------------------------------------------------

ADMIN_USER_ID = "admin-1"
LIAISON_USER_ID = "liaison-1"
OPERATOR_USER_ID = "op-1"
SCHEDULER_USER_ID = "sched-1"
POSTAGE_USER_ID = "postage-1"
AUDITOR_USER_ID = "auditor-1"

#: Second actors, for the duty separations that compare user ids.
ADMIN_USER_ID_2 = "admin-2"
POSTAGE_USER_ID_2 = "postage-2"

BUREAU_ADMIN = build_user_headers(ADMIN_USER_ID, Role.BUREAU_ADMIN.value)
CLIENT_LIAISON = build_user_headers(LIAISON_USER_ID, Role.CLIENT_LIAISON.value)
COMPOSITION_OPERATOR = build_user_headers(
    OPERATOR_USER_ID, Role.COMPOSITION_OPERATOR.value
)
PRODUCTION_SCHEDULER = build_user_headers(
    SCHEDULER_USER_ID, Role.PRODUCTION_SCHEDULER.value
)
POSTAGE_CONTROLLER = build_user_headers(
    POSTAGE_USER_ID, Role.POSTAGE_CONTROLLER.value
)
INTEGRITY_AUDITOR = build_user_headers(AUDITOR_USER_ID, Role.INTEGRITY_AUDITOR.value)

#: A second bureau administrator, so the closing actor can differ from the
#: identity recorded as ``composed_by_user_id``.
BUREAU_ADMIN_2 = build_user_headers(ADMIN_USER_ID_2, Role.BUREAU_ADMIN.value)

#: A second postage controller, so the manifesting actor can differ from the
#: identity recorded as ``sealed_by_user_id``.
POSTAGE_CONTROLLER_2 = build_user_headers(
    POSTAGE_USER_ID_2, Role.POSTAGE_CONTROLLER.value
)

#: A composition operator acting under the administrator's user id, used where
#: a test needs the composing identity to collide with the closing identity.
COMPOSITION_OPERATOR_AS_ADMIN_1 = build_user_headers(
    ADMIN_USER_ID, Role.COMPOSITION_OPERATOR.value
)


ALL_ROLE_HEADERS: Dict[str, Dict[str, str]] = {
    Role.BUREAU_ADMIN.value: BUREAU_ADMIN,
    Role.CLIENT_LIAISON.value: CLIENT_LIAISON,
    Role.COMPOSITION_OPERATOR.value: COMPOSITION_OPERATOR,
    Role.PRODUCTION_SCHEDULER.value: PRODUCTION_SCHEDULER,
    Role.POSTAGE_CONTROLLER.value: POSTAGE_CONTROLLER,
    Role.INTEGRITY_AUDITOR.value: INTEGRITY_AUDITOR,
}


def headers_for(role: str, user_id: str) -> Dict[str, str]:
    """Identity headers for an arbitrary (role, user id) pair."""
    return build_user_headers(user_id, role)


# --------------------------------------------------------------------------
# Malformed identity, for the authentication gate
# --------------------------------------------------------------------------

#: A request that supplies a user id but no role.
NO_ROLE_HEADERS: Dict[str, str] = {
    "X-User-ID": ADMIN_USER_ID,
    "Content-Type": "application/json",
}

#: A request that supplies a role but no user id.
NO_USER_ID_HEADERS: Dict[str, str] = {
    "X-User-Role": Role.BUREAU_ADMIN.value,
    "Content-Type": "application/json",
}

#: A request that supplies neither identity header.
NO_AUTH_HEADERS: Dict[str, str] = {"Content-Type": "application/json"}

#: A request whose role is not one of the six the contract names.
UNKNOWN_ROLE_HEADERS: Dict[str, str] = build_user_headers(
    ADMIN_USER_ID, "WarehouseClerk"
)
