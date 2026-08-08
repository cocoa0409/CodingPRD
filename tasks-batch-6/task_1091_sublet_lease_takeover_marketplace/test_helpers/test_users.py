"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque operator roles, and for tests that do NOT
# exercise ownership (400-on-bad-payload, 404-on-missing-resource, role-denied).
TEST_USERS = {
    # entity_backed roles: shared constant is a fallback for non-ownership tests only.
    "landlord_headers": build_user_headers("test-landlord-1", "Landlord"),
    "leaseholder_headers": build_user_headers("test-leaseholder-1", "Leaseholder"),
    "applicant_headers": build_user_headers("test-applicant-1", "Applicant"),
    # opaque operator roles: shared constant is the canonical form.
    "compliance_headers": build_user_headers("test-compliance-1", "ComplianceOfficer"),
    "admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
}


# --- Per-instance builders — required for every entity_backed role. ---

def make_landlord_headers(user_id: str) -> dict:
    """For Landlord (entity_backed:Landlord). Pass the actual Landlord.id when
    the call is ownership-gated (lease.landlord_id / appointment.landlord_id)."""
    return build_user_headers(user_id, "Landlord")


def make_leaseholder_headers(user_id: str) -> dict:
    """For Leaseholder (entity_backed:Leaseholder). Pass the actual Leaseholder.id
    when the call is ownership-gated (lease.leaseholder_id and everything downstream)."""
    return build_user_headers(user_id, "Leaseholder")


def make_applicant_headers(user_id: str) -> dict:
    """For Applicant (entity_backed:Applicant). Pass the actual Applicant.id when
    the call is ownership-gated (application.applicant_id)."""
    return build_user_headers(user_id, "Applicant")


def make_compliance_headers(user_id: str = "test-compliance-1") -> dict:
    """ComplianceOfficer is an opaque operator; id is never an ownership subject."""
    return build_user_headers(user_id, "ComplianceOfficer")


def make_admin_headers(user_id: str = "test-admin-1") -> dict:
    """PlatformAdmin is an opaque operator; id is never an ownership subject."""
    return build_user_headers(user_id, "PlatformAdmin")
