"""Pre-built role headers for every role in the PRD (§2.1).

Entity-backed roles (AuditManager, FieldAuditor, QualityAssessor) compare
X-User-ID against an Auditor record's id; use the make_*_headers builders
with the actual Auditor.id for any call whose success depends on identity.
Opaque roles may use the shared TEST_USERS constants anywhere.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — canonical form.
    "admin_headers": build_user_headers("admin-1", "AuditAdmin"),
    "cae_headers": build_user_headers("cae-1", "ChiefAuditExecutive"),
    "cae2_headers": build_user_headers("cae-9", "ChiefAuditExecutive"),
    "committee_headers": build_user_headers("ac-1", "AuditCommittee"),
    "committee2_headers": build_user_headers("ac-2", "AuditCommittee"),
    "owner_headers": build_user_headers("mgmt-1", "ManagementOwner"),
    # Entity-backed roles — fallback ONLY for tests that never exercise
    # ownership/grade checks tied to a specific Auditor record.
    "manager_headers": build_user_headers("test-manager-1", "AuditManager"),
    "field_auditor_headers": build_user_headers("test-field-1", "FieldAuditor"),
    "qa_headers": build_user_headers("test-qa-1", "QualityAssessor"),
}


def make_manager_headers(user_id: str) -> dict:
    """AuditManager is entity-backed (Auditor). Pass the actual Auditor.id."""
    return build_user_headers(user_id, "AuditManager")


def make_field_auditor_headers(user_id: str) -> dict:
    """FieldAuditor is entity-backed (Auditor). Pass the actual Auditor.id."""
    return build_user_headers(user_id, "FieldAuditor")


def make_qa_headers(user_id: str) -> dict:
    """QualityAssessor is entity-backed (Auditor). Pass the actual Auditor.id."""
    return build_user_headers(user_id, "QualityAssessor")
