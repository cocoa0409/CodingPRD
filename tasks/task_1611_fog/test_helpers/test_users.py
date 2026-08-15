"""Pre-built role headers for every role in the PRD.

ProgramAdmin, Inspector, and ComplianceOfficer are opaque identities: the
X-User-ID is not tied to any persisted entity. FseContact is entity-backed by
Establishment (X-User-ID is the acting establishment's id) and HaulerAdmin is
entity-backed by Hauler (X-User-ID is the acting hauler's id). Ownership-gated
calls MUST use the per-instance builders with the real entity id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership (400-on-bad-payload, 404-on-missing-resource, wrong-role checks).
TEST_USERS = {
    "program_admin_headers": build_user_headers("test-admin-1", "ProgramAdmin"),
    "inspector_headers": build_user_headers("test-inspector-1", "Inspector"),
    "compliance_officer_headers": build_user_headers("test-officer-1",
                                                     "ComplianceOfficer"),
    # entity_backed roles: shared constants are fallbacks for non-ownership
    # tests only.
    "fse_contact_headers": build_user_headers("test-fse-1", "FseContact"),
    "hauler_admin_headers": build_user_headers("test-hauler-1", "HaulerAdmin"),
}


def make_program_admin_headers(user_id: str = "test-admin-1") -> dict:
    return build_user_headers(user_id, "ProgramAdmin")


def make_inspector_headers(user_id: str = "test-inspector-1") -> dict:
    return build_user_headers(user_id, "Inspector")


def make_compliance_officer_headers(user_id: str = "test-officer-1") -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")


def make_fse_contact_headers(establishment_id: str) -> dict:
    """For FseContact (entity_backed:Establishment). Pass the acting
    Establishment.id whenever the call is ownership-gated."""
    return build_user_headers(establishment_id, "FseContact")


def make_hauler_admin_headers(hauler_id: str) -> dict:
    """For HaulerAdmin (entity_backed:Hauler). Pass the acting Hauler.id
    whenever the call is ownership-gated."""
    return build_user_headers(hauler_id, "HaulerAdmin")
