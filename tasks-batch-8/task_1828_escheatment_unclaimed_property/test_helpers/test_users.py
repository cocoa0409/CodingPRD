"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants for the opaque roles — X-User-ID is never compared to an
# entity id for these roles (PRD §2.1), so a fixed test id is safe.
TEST_USERS = {
    "holder_admin_headers": build_user_headers("ha-1", "HolderAdmin"),
    "compliance_officer_headers": build_user_headers("co-1", "ComplianceOfficer"),
    "state_auditor_headers": build_user_headers("sa-1", "StateAuditor"),
    "treasury_ops_headers": build_user_headers("to-1", "TreasuryOps"),
    "claims_examiner_headers": build_user_headers("ce-1", "ClaimsExaminer"),
    "claims_approver_headers": build_user_headers("ap-1", "ClaimsApprover"),
    # Fallback for Claimant only where ownership is NOT exercised
    # (e.g., a 404 read against a nonexistent id). Ownership-gated calls
    # MUST use make_claimant_headers(owner_id) instead.
    "claimant_headers": build_user_headers("test-claimant-1", "Claimant"),
    # Read endpoints accept any declared role (pseudo-role Any, PRD §2.1);
    # use a declared role value for them.
    "reader_headers": build_user_headers("reader-1", "ComplianceOfficer"),
}


def make_claimant_headers(owner_id: str) -> dict:
    """For Claimant (entity_backed: Owner): X-User-ID must equal the Owner id
    whenever the call is ownership-gated (PRD §2.1, §3.1, §3.7)."""
    return build_user_headers(owner_id, "Claimant")
