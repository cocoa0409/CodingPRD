"""Pre-built role headers for every role in the PRD (Section 2.1).

Coder and Auditor are entity-backed roles: their X-User-ID must be the id of a
persisted Coder for any ownership-gated call. Use make_coder_headers /
make_auditor_headers with the real Coder.id in that case. The shared constants
for those two roles exist only for calls where no ownership check applies.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — canonical for the opaque roles (CodingManager,
# BillingClerk, ComplianceOfficer); fallback-only for the entity-backed roles.
TEST_USERS = {
    "manager_headers": build_user_headers("test-manager-1", "CodingManager"),
    "coder_headers": build_user_headers("test-coder-1", "Coder"),
    "auditor_headers": build_user_headers("test-auditor-1", "Auditor"),
    "clerk_headers": build_user_headers("test-clerk-1", "BillingClerk"),
    "officer_headers": build_user_headers("test-officer-1", "ComplianceOfficer"),
}


def make_coder_headers(user_id: str) -> dict:
    """Coder is entity-backed: X-User-ID must be the acting Coder's id."""
    return build_user_headers(user_id, "Coder")


def make_auditor_headers(user_id: str) -> dict:
    """Auditor is entity-backed: X-User-ID must be the auditor Coder's id."""
    return build_user_headers(user_id, "Auditor")


def make_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "CodingManager")


def make_clerk_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "BillingClerk")


def make_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")
