"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise ownership.
TEST_USERS = {
    # Opaque roles: canonical shared form.
    "reporter_headers": build_user_headers("reporter-opaque-1", "HotlineReporter"),
    "admin_headers": build_user_headers("test-admin-1", "EthicsPlatformAdmin"),
    "acm_headers": build_user_headers("test-acm-1", "AuditCommitteeMember"),
    # entity_backed roles: shared constants are a fallback for non-ownership tests only.
    "intake_headers": build_user_headers("test-intake-1", "IntakeSpecialist"),
    "investigator_headers": build_user_headers("test-investigator-1", "Investigator"),
    "officer_headers": build_user_headers("test-officer-1", "ComplianceOfficer"),
}


# Per-instance builders — required for entity_backed roles whenever the call is
# ownership-gated (X-User-ID must equal the StaffMember.id).
def make_intake_headers(user_id: str) -> dict:
    """IntakeSpecialist (entity_backed:StaffMember)."""
    return build_user_headers(user_id, "IntakeSpecialist")


def make_investigator_headers(user_id: str) -> dict:
    """Investigator (entity_backed:StaffMember)."""
    return build_user_headers(user_id, "Investigator")


def make_officer_headers(user_id: str) -> dict:
    """ComplianceOfficer (entity_backed:StaffMember)."""
    return build_user_headers(user_id, "ComplianceOfficer")


def make_reporter_headers(reporter_access_key: str) -> dict:
    """HotlineReporter (opaque): X-User-ID must equal the case's reporter_access_key."""
    return build_user_headers(reporter_access_key, "HotlineReporter")


def make_admin_headers(user_id: str = "test-admin-1") -> dict:
    return build_user_headers(user_id, "EthicsPlatformAdmin")


def make_acm_headers(user_id: str = "test-acm-1") -> dict:
    return build_user_headers(user_id, "AuditCommitteeMember")
