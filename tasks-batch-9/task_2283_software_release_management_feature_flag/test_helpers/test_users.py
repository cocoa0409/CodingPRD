"""Pre-built authentication headers for the six roles of PRD §2.1.

PRD §2.1 declares ``X-User-ID`` an opaque operator identifier that is never
compared against any resource ``id``.  Ownership and authorship checks compare
it against stored opaque fields (``owner_user_id``, ``author_user_id``), so the
right shape for the helpers is "a role plus a stable opaque id", not "a role
plus an entity id".

The named header dicts below give every test a stable cast of operators; the
``as_*`` builders exist for the cases where a test needs a *different* opaque id
in the same role (a non-owner engineer, a second approver, an author who also
holds the approver role).
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import Role

# ---------------------------------------------------------------------------
# Opaque operator identifiers used throughout the suite
# ---------------------------------------------------------------------------

PLATFORM_ADMIN_USER_ID = "u-pa-1"
RELEASE_MANAGER_USER_ID = "u-rm-1"
ENGINEER_USER_ID = "u-eng-1"
OTHER_ENGINEER_USER_ID = "u-eng-2"
THIRD_ENGINEER_USER_ID = "u-eng-9"
APPROVER_USER_ID = "u-appr-1"
SECOND_APPROVER_USER_ID = "u-appr-2"
COMPLIANCE_USER_ID = "u-comp-1"
SRE_USER_ID = "u-sre-1"
#: An operator who authors a change and also holds an approver role, used to
#: exercise the segregation-of-duties rule of PRD §2.12.
DUAL_ROLE_USER_ID = "u-dual-1"

# ---------------------------------------------------------------------------
# Ready-made header dicts
# ---------------------------------------------------------------------------

PLATFORM_ADMIN = build_user_headers(PLATFORM_ADMIN_USER_ID, Role.PLATFORM_ADMIN)
RELEASE_MANAGER = build_user_headers(RELEASE_MANAGER_USER_ID, Role.RELEASE_MANAGER)
ENGINEER = build_user_headers(ENGINEER_USER_ID, Role.ENGINEER)
OTHER_ENGINEER = build_user_headers(OTHER_ENGINEER_USER_ID, Role.ENGINEER)
THIRD_ENGINEER = build_user_headers(THIRD_ENGINEER_USER_ID, Role.ENGINEER)
CHANGE_APPROVER = build_user_headers(APPROVER_USER_ID, Role.CHANGE_APPROVER)
SECOND_CHANGE_APPROVER = build_user_headers(SECOND_APPROVER_USER_ID, Role.CHANGE_APPROVER)
COMPLIANCE_OFFICER = build_user_headers(COMPLIANCE_USER_ID, Role.COMPLIANCE_OFFICER)
SRE = build_user_headers(SRE_USER_ID, Role.SRE)

#: Same opaque id in two roles: authors changes as an Engineer, then attempts to
#: approve them as a ChangeApprover.
DUAL_ROLE_ENGINEER = build_user_headers(DUAL_ROLE_USER_ID, Role.ENGINEER)
DUAL_ROLE_APPROVER = build_user_headers(DUAL_ROLE_USER_ID, Role.CHANGE_APPROVER)


# ---------------------------------------------------------------------------
# Builders for ad-hoc identities
# ---------------------------------------------------------------------------


def as_platform_admin(user_id: str = PLATFORM_ADMIN_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, Role.PLATFORM_ADMIN)


def as_release_manager(user_id: str = RELEASE_MANAGER_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, Role.RELEASE_MANAGER)


def as_engineer(user_id: str = ENGINEER_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, Role.ENGINEER)


def as_change_approver(user_id: str = APPROVER_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, Role.CHANGE_APPROVER)


def as_compliance_officer(user_id: str = COMPLIANCE_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, Role.COMPLIANCE_OFFICER)


def as_sre(user_id: str = SRE_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, Role.SRE)


def headers_without_user_id(role: str = Role.RELEASE_MANAGER) -> Dict[str, str]:
    """Headers carrying a role but no ``X-User-ID`` at all (PRD §2.1: 401)."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_without_role(user_id: str = ENGINEER_USER_ID) -> Dict[str, str]:
    """Headers carrying an operator id but no role (PRD §2.1: 401)."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


#: Role -> default header dict, for parametrized authorization sweeps.
ROLE_HEADERS = {
    Role.PLATFORM_ADMIN: PLATFORM_ADMIN,
    Role.RELEASE_MANAGER: RELEASE_MANAGER,
    Role.ENGINEER: ENGINEER,
    Role.CHANGE_APPROVER: CHANGE_APPROVER,
    Role.COMPLIANCE_OFFICER: COMPLIANCE_OFFICER,
    Role.SRE: SRE,
}
