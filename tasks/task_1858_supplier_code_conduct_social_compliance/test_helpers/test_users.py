"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# entity-backed ownership (bad-payload 400s, missing-resource 404s, role
# permission 403s).
TEST_USERS = {
    # Opaque roles: shared constant is the canonical form.
    "program_admin_headers": build_user_headers(
        "test-program-admin-1", "SourcingProgramAdmin"
    ),
    "audit_coordinator_headers": build_user_headers(
        "test-audit-coordinator-1", "AuditCoordinator"
    ),
    "compliance_officer_headers": build_user_headers(
        "test-compliance-officer-1", "ComplianceOfficer"
    ),
    "worker_hotline_headers": build_user_headers(
        "test-worker-hotline-1", "WorkerHotline"
    ),
    # Entity-backed roles: fallback for non-ownership tests only.
    "auditor_headers": build_user_headers("test-auditor-1", "Auditor"),
    "supplier_contact_headers": build_user_headers(
        "test-supplier-contact-1", "SupplierContact"
    ),
}


def make_auditor_headers(auditor_id: str) -> dict:
    """For Auditor (entity-backed by Auditor). Pass the actual Auditor.id
    whenever the call is ownership-gated (start, findings, interviews, fee
    review, submit-report, void, verify)."""
    return build_user_headers(auditor_id, "Auditor")


def make_supplier_contact_headers(supplier_id: str) -> dict:
    """For SupplierContact (entity-backed by Supplier). Pass the actual
    Supplier.id whenever the call is ownership-gated (acknowledgments, CAP
    create/resubmit/request-verification, mutual-recognition claims)."""
    return build_user_headers(supplier_id, "SupplierContact")
