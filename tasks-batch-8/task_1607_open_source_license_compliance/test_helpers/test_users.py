"""Pre-built role headers for every role in the PRD (§2.1).

All seven roles carry opaque operator identifiers: no role's `X-User-ID` is
ever compared to an entity's `id` for ownership (PRD §2.1). The identifier is
still recorded where a transition writes it — `legal_reviewer_id`,
`engineering_reviewer_id`, `waived_by`, `bypass_approved_by`, and the
originating requester of a license approval request (which the withdrawal
workflow later compares against) — so builders exist to thread a stable id
through those flows.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for any call that does not depend on a previously
# recorded actor id.
TEST_USERS = {
    "analyst_headers": build_user_headers("analyst-1", "ComplianceAnalyst"),
    "legal_headers": build_user_headers("legal-1", "LegalCounsel"),
    "eng_manager_headers": build_user_headers("eng-mgr-1", "EngineeringManager"),
    "security_headers": build_user_headers("sec-1", "SecurityAnalyst"),
    "release_manager_headers": build_user_headers("rel-mgr-1", "ReleaseManager"),
    "ciso_headers": build_user_headers("ciso-1", "CISO"),
    "admin_headers": build_user_headers("admin-1", "PlatformAdmin"),
}


def make_analyst_headers(user_id: str) -> dict:
    """ComplianceAnalyst with a specific operator id. The server records the
    scan-submitting analyst as the originating requester of any spawned
    license approval request, and the withdrawal workflow compares against it
    (PRD §2.1, §3.4) — pass the same id to the withdrawal call."""
    return build_user_headers(user_id, "ComplianceAnalyst")


def make_legal_headers(user_id: str = "legal-1") -> dict:
    return build_user_headers(user_id, "LegalCounsel")


def make_eng_manager_headers(user_id: str = "eng-mgr-1") -> dict:
    return build_user_headers(user_id, "EngineeringManager")


def make_security_headers(user_id: str = "sec-1") -> dict:
    return build_user_headers(user_id, "SecurityAnalyst")


def make_release_manager_headers(user_id: str = "rel-mgr-1") -> dict:
    return build_user_headers(user_id, "ReleaseManager")


def make_ciso_headers(user_id: str = "ciso-1") -> dict:
    return build_user_headers(user_id, "CISO")


def make_admin_headers(user_id: str = "admin-1") -> dict:
    return build_user_headers(user_id, "PlatformAdmin")
