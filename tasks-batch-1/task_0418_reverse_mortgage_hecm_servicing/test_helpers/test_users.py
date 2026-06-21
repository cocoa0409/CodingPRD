"""Pre-built role headers for every role in the PRD.

The PRD recognizes exactly five roles: ServicerOps, ComplianceOfficer,
Borrower, HudAuditor, System. Only Borrower is entity-backed: when the role is
Borrower, X-User-ID is the id of the acting Borrower and ownership checks compare
the resource's borrower foreign key to X-User-ID. All other roles are opaque
operator identifiers not tied to any persisted entity.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — opaque roles use these directly; the Borrower shared
# constant is a fallback only for tests that do NOT exercise ownership.
TEST_USERS = {
    "servicer_ops_headers": build_user_headers("test-servicer-ops-1", "ServicerOps"),
    "compliance_officer_headers": build_user_headers("test-compliance-1", "ComplianceOfficer"),
    "hud_auditor_headers": build_user_headers("test-hud-auditor-1", "HudAuditor"),
    "system_headers": build_user_headers("test-system-1", "System"),
    # Fallback only — never use for ownership-gated Borrower calls.
    "borrower_headers": build_user_headers("test-borrower-1", "Borrower"),
}


def make_servicer_ops_headers(user_id: str = "test-servicer-ops-1") -> dict:
    return build_user_headers(user_id, "ServicerOps")


def make_compliance_officer_headers(user_id: str = "test-compliance-1") -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")


def make_hud_auditor_headers(user_id: str = "test-hud-auditor-1") -> dict:
    return build_user_headers(user_id, "HudAuditor")


def make_system_headers(user_id: str = "test-system-1") -> dict:
    return build_user_headers(user_id, "System")


def make_borrower_headers(user_id: str) -> dict:
    """For the Borrower role (entity_backed:Borrower). Pass the actual
    Borrower.id as user_id whenever the call is ownership-gated (requesting a
    draw on the borrower's loan, self-certifying occupancy)."""
    return build_user_headers(user_id, "Borrower")
