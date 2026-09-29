"""Pre-built identity headers for every role the PRD declares.

Every request carries `X-User-ID` and `X-User-Role`. Two roles are entity backed —
a Rebuilder acts only on its own applications and an Inspector only on inspections
assigned to it — so ownership-gated calls MUST use the per-instance builders below
with the real entity id, never a shared constant.
"""

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# --- canonical opaque user ids --------------------------------------------
ADMIN_USER_ID = "admin-01"
SECOND_ADMIN_USER_ID = "admin-02"
CLERK_USER_ID = "clerk-01"
SECOND_CLERK_USER_ID = "clerk-02"
ADJUSTER_USER_ID = "adj-01"
HEARING_OFFICER_USER_ID = "ho-01"
SECOND_HEARING_OFFICER_USER_ID = "ho-02"
FRAUD_INVESTIGATOR_USER_ID = "fi-01"
SECOND_FRAUD_INVESTIGATOR_USER_ID = "fi-02"

# Fallback ids for the entity-backed roles. Only safe for tests that never reach
# an ownership check (malformed payloads, unknown ids, role-permission checks).
UNBOUND_REBUILDER_USER_ID = "rebuilder-unbound-01"
UNBOUND_INSPECTOR_USER_ID = "inspector-unbound-01"


TEST_USERS = {
    "program_admin_headers": build_user_headers(
        ADMIN_USER_ID, UserRole.PROGRAM_ADMIN.value
    ),
    "second_program_admin_headers": build_user_headers(
        SECOND_ADMIN_USER_ID, UserRole.PROGRAM_ADMIN.value
    ),
    "state_title_clerk_headers": build_user_headers(
        CLERK_USER_ID, UserRole.STATE_TITLE_CLERK.value
    ),
    "second_state_title_clerk_headers": build_user_headers(
        SECOND_CLERK_USER_ID, UserRole.STATE_TITLE_CLERK.value
    ),
    "insurer_adjuster_headers": build_user_headers(
        ADJUSTER_USER_ID, UserRole.INSURER_ADJUSTER.value
    ),
    "hearing_officer_headers": build_user_headers(
        HEARING_OFFICER_USER_ID, UserRole.HEARING_OFFICER.value
    ),
    "second_hearing_officer_headers": build_user_headers(
        SECOND_HEARING_OFFICER_USER_ID, UserRole.HEARING_OFFICER.value
    ),
    "fraud_investigator_headers": build_user_headers(
        FRAUD_INVESTIGATOR_USER_ID, UserRole.FRAUD_INVESTIGATOR.value
    ),
    "second_fraud_investigator_headers": build_user_headers(
        SECOND_FRAUD_INVESTIGATOR_USER_ID, UserRole.FRAUD_INVESTIGATOR.value
    ),
    # Entity-backed roles: fallbacks for non-ownership tests only.
    "rebuilder_headers": build_user_headers(
        UNBOUND_REBUILDER_USER_ID, UserRole.REBUILDER.value
    ),
    "inspector_headers": build_user_headers(
        UNBOUND_INSPECTOR_USER_ID, UserRole.INSPECTOR.value
    ),
}


def make_rebuilder_headers(rebuilder_id: str) -> dict:
    """Identity headers for the Rebuilder role.

    Pass the real rebuilder id: a Rebuilder acts only on its own applications, so
    every ownership-gated call must present that id as `X-User-ID`.
    """
    return build_user_headers(rebuilder_id, UserRole.REBUILDER.value)


def make_inspector_headers(inspector_id: str) -> dict:
    """Identity headers for the Inspector role.

    Pass the real inspector id: an Inspector acts only on inspections assigned to
    it, so every ownership-gated call must present that id as `X-User-ID`.
    """
    return build_user_headers(inspector_id, UserRole.INSPECTOR.value)


def make_program_admin_headers(user_id: str = ADMIN_USER_ID) -> dict:
    """Identity headers for a named ProgramAdmin operator."""
    return build_user_headers(user_id, UserRole.PROGRAM_ADMIN.value)


def make_state_title_clerk_headers(user_id: str = CLERK_USER_ID) -> dict:
    """Identity headers for a named StateTitleClerk operator."""
    return build_user_headers(user_id, UserRole.STATE_TITLE_CLERK.value)


def make_insurer_adjuster_headers(user_id: str = ADJUSTER_USER_ID) -> dict:
    """Identity headers for a named InsurerAdjuster operator."""
    return build_user_headers(user_id, UserRole.INSURER_ADJUSTER.value)


def make_hearing_officer_headers(user_id: str = HEARING_OFFICER_USER_ID) -> dict:
    """Identity headers for a named HearingOfficer operator."""
    return build_user_headers(user_id, UserRole.HEARING_OFFICER.value)


def make_fraud_investigator_headers(user_id: str = FRAUD_INVESTIGATOR_USER_ID) -> dict:
    """Identity headers for a named FraudInvestigator operator."""
    return build_user_headers(user_id, UserRole.FRAUD_INVESTIGATOR.value)


def headers_for_role(role: str, user_id: str = None) -> dict:
    """Identity headers for any role, defaulting to that role's canonical user id."""
    defaults = {
        UserRole.PROGRAM_ADMIN.value: ADMIN_USER_ID,
        UserRole.STATE_TITLE_CLERK.value: CLERK_USER_ID,
        UserRole.INSURER_ADJUSTER.value: ADJUSTER_USER_ID,
        UserRole.HEARING_OFFICER.value: HEARING_OFFICER_USER_ID,
        UserRole.FRAUD_INVESTIGATOR.value: FRAUD_INVESTIGATOR_USER_ID,
        UserRole.REBUILDER.value: UNBOUND_REBUILDER_USER_ID,
        UserRole.INSPECTOR.value: UNBOUND_INSPECTOR_USER_ID,
    }
    return build_user_headers(user_id or defaults[role], role)
