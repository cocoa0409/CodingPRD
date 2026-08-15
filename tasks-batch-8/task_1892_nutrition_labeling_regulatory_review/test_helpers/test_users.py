"""Pre-built role headers for every role in the PRD.

PlatformAdmin, LabelAnalyst, RegulatoryReviewer, and ComplianceAuditor are
opaque identities: X-User-ID is not tied to any persisted entity. ClientRep
and QualityManager are entity-backed by Client (X-User-ID is the acting
Client's id); ownership-gated calls MUST use the per-instance builders with
the real client id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership (400-on-bad-payload, 404-on-missing-resource, wrong-role checks).
TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "label_analyst_headers": build_user_headers("analyst-1", "LabelAnalyst"),
    "regulatory_reviewer_headers": build_user_headers("reviewer-1", "RegulatoryReviewer"),
    "compliance_auditor_headers": build_user_headers("auditor-1", "ComplianceAuditor"),
    # entity_backed roles: shared constants are fallbacks for non-ownership tests only.
    "client_rep_headers": build_user_headers("test-client-rep-1", "ClientRep"),
    "quality_manager_headers": build_user_headers("test-qm-1", "QualityManager"),
}


def make_platform_admin_headers(user_id: str = "test-platform-admin-1") -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_label_analyst_headers(user_id: str = "analyst-1") -> dict:
    """For LabelAnalyst (opaque). The id is recorded as prepared_by on label
    versions the analyst creates."""
    return build_user_headers(user_id, "LabelAnalyst")


def make_regulatory_reviewer_headers(user_id: str = "reviewer-1") -> dict:
    """For RegulatoryReviewer (opaque). The id is recorded as reviewed_by /
    approved_by on resources the reviewer decides."""
    return build_user_headers(user_id, "RegulatoryReviewer")


def make_compliance_auditor_headers(user_id: str = "auditor-1") -> dict:
    return build_user_headers(user_id, "ComplianceAuditor")


def make_client_rep_headers(client_id: str) -> dict:
    """For ClientRep (entity_backed:Client). Pass the acting Client.id
    whenever the call is ownership-gated."""
    return build_user_headers(client_id, "ClientRep")


def make_quality_manager_headers(client_id: str) -> dict:
    """For QualityManager (entity_backed:Client). Pass the acting Client.id
    whenever the call is ownership-gated."""
    return build_user_headers(client_id, "QualityManager")
