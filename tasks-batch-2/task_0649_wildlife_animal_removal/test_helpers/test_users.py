"""Pre-built role headers for every role in the PRD (§2.1).

Dispatcher and ComplianceOfficer are opaque operator identities — the shared
constant is the canonical form. PropertyOwner is entity_backed:ServiceAccount and
FieldTechnician is entity_backed:Technician — for ownership-gated calls use the
per-instance builders with the real entity id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise ownership
# (400/404/403 paths, or reads).
TEST_USERS = {
    # opaque
    "dispatcher_headers": build_user_headers("test-dispatcher-1", "Dispatcher"),
    "compliance_officer_headers": build_user_headers("test-compliance-1", "ComplianceOfficer"),
    # entity_backed — shared constant is a fallback for non-ownership tests only.
    "property_owner_headers": build_user_headers("test-owner-1", "PropertyOwner"),
    "field_technician_headers": build_user_headers("test-tech-1", "FieldTechnician"),
}


def make_dispatcher_headers(user_id: str = "test-dispatcher-1") -> dict:
    """Dispatcher is opaque; X-User-ID is not compared to any entity."""
    return build_user_headers(user_id, "Dispatcher")


def make_compliance_officer_headers(user_id: str = "test-compliance-1") -> dict:
    """ComplianceOfficer is opaque; X-User-ID is not compared to any entity."""
    return build_user_headers(user_id, "ComplianceOfficer")


def make_property_owner_headers(account_id: str) -> dict:
    """For PropertyOwner (entity_backed:ServiceAccount). Pass the owning ServiceAccount.id
    whenever the call (accept/decline/request-revision/warranty-claim) is ownership-gated."""
    return build_user_headers(account_id, "PropertyOwner")


def make_field_technician_headers(technician_id: str) -> dict:
    """For FieldTechnician (entity_backed:Technician). Pass the acting Technician.id."""
    return build_user_headers(technician_id, "FieldTechnician")
