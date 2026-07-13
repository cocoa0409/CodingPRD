"""Pre-built role headers for every role in the PRD.

PRD §2.1 fixes what `X-User-ID` means per role:
  * PrincipalArchitect — an opaque operator identifier, never compared to any entity id.
  * ProjectManager     — the `id` of the acting StaffMember.
  * StaffArchitect     — the `id` of the acting StaffMember.
  * ConsultantRep      — the `id` of the acting ConsultantFirm.
  * ClientRep          — an opaque operator identifier, compared to Project.client_rep_user_id.

Roles whose identity is an entity id MUST use the per-instance builders below with the
real entity's id; the shared constants are only safe for calls that exercise no ownership.
"""
from prd_bench_local_runner.testing import build_user_headers

PRINCIPAL_A_USER_ID = "principal-alice"
PRINCIPAL_B_USER_ID = "principal-bob"
CLIENT_REP_USER_ID = "client-1"
OTHER_CLIENT_REP_USER_ID = "client-9"


# Shared constants — safe for the opaque roles, and for tests that do not exercise ownership.
TEST_USERS = {
    "principal_headers": build_user_headers(PRINCIPAL_A_USER_ID, "PrincipalArchitect"),
    "principal_b_headers": build_user_headers(PRINCIPAL_B_USER_ID, "PrincipalArchitect"),
    "client_rep_headers": build_user_headers(CLIENT_REP_USER_ID, "ClientRep"),
    "other_client_rep_headers": build_user_headers(OTHER_CLIENT_REP_USER_ID, "ClientRep"),
    # Fallbacks for non-ownership tests only (e.g. plain 403-role-denial checks).
    "project_manager_headers": build_user_headers("test-pm-unbound", "ProjectManager"),
    "staff_architect_headers": build_user_headers("test-arch-unbound", "StaffArchitect"),
    "consultant_rep_headers": build_user_headers("test-firm-unbound", "ConsultantRep"),
}


def make_principal_headers(user_id: str = PRINCIPAL_A_USER_ID) -> dict:
    """PrincipalArchitect (opaque identity)."""
    return build_user_headers(user_id, "PrincipalArchitect")


def make_project_manager_headers(staff_member_id: str) -> dict:
    """ProjectManager. Pass the acting StaffMember's id (PRD §2.1)."""
    return build_user_headers(staff_member_id, "ProjectManager")


def make_staff_architect_headers(staff_member_id: str) -> dict:
    """StaffArchitect. Pass the acting StaffMember's id (PRD §2.1)."""
    return build_user_headers(staff_member_id, "StaffArchitect")


def make_consultant_rep_headers(consultant_firm_id: str) -> dict:
    """ConsultantRep. Pass the acting ConsultantFirm's id (PRD §2.1)."""
    return build_user_headers(consultant_firm_id, "ConsultantRep")


def make_client_rep_headers(client_rep_user_id: str = CLIENT_REP_USER_ID) -> dict:
    """ClientRep (opaque identity, compared to Project.client_rep_user_id)."""
    return build_user_headers(client_rep_user_id, "ClientRep")
