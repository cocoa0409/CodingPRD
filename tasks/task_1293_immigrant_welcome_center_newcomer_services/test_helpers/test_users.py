"""Pre-built role headers for every role in the PRD (§2.1).

Staff roles (CenterAdmin / CaseManager / IntakeSpecialist) are entity-backed by
StaffMember, PartnerOrg by Organization, and Client by Client: whenever a call is
ownership- or authorship-gated, build headers with the real entity id via the
make_*_headers builders below. The shared TEST_USERS constants are safe for calls
whose success does not depend on the caller owning the subject resource (pure
role checks, admin operations, opaque FunderAuditor).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "center_admin_headers": build_user_headers("test-center-admin-1", "CenterAdmin"),
    "case_manager_headers": build_user_headers("test-case-manager-1", "CaseManager"),
    "intake_specialist_headers": build_user_headers("test-intake-specialist-1", "IntakeSpecialist"),
    "partner_org_headers": build_user_headers("test-partner-org-1", "PartnerOrg"),
    "client_headers": build_user_headers("test-client-1", "Client"),
    "funder_auditor_headers": build_user_headers("test-funder-auditor-1", "FunderAuditor"),
}


def make_center_admin_headers(user_id: str) -> dict:
    """CenterAdmin acting as a specific StaffMember (entity-backed)."""
    return build_user_headers(user_id, "CenterAdmin")


def make_case_manager_headers(user_id: str) -> dict:
    """CaseManager acting as a specific StaffMember (entity-backed)."""
    return build_user_headers(user_id, "CaseManager")


def make_intake_specialist_headers(user_id: str) -> dict:
    """IntakeSpecialist acting as a specific StaffMember (entity-backed)."""
    return build_user_headers(user_id, "IntakeSpecialist")


def make_partner_org_headers(organization_id: str) -> dict:
    """PartnerOrg acting as a specific Organization (entity-backed)."""
    return build_user_headers(organization_id, "PartnerOrg")


def make_client_headers(client_id: str) -> dict:
    """Client acting as itself (entity-backed)."""
    return build_user_headers(client_id, "Client")


def make_funder_auditor_headers(operator_id: str = "auditor-1") -> dict:
    """FunderAuditor is opaque — its id is never compared to an entity id."""
    return build_user_headers(operator_id, "FunderAuditor")
