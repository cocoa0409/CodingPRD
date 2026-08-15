"""Pre-built role headers for every role in the PRD.

PlatformAdmin, RecordsManager, LegalCounsel and Auditor are opaque identities:
X-User-ID is not tied to any persisted entity. Custodian is entity-backed by
the Custodian entity (X-User-ID is the acting custodian's id); ownership-gated
calls (acknowledgment) MUST use make_custodian_headers with the real id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership (400-on-bad-payload, 404-on-missing-resource, wrong-role checks).
TEST_USERS = {
    "platform_admin_headers": build_user_headers("admin-1", "PlatformAdmin"),
    "records_manager_headers": build_user_headers("rm-1", "RecordsManager"),
    "legal_counsel_headers": build_user_headers("lc-1", "LegalCounsel"),
    "auditor_headers": build_user_headers("aud-1", "Auditor"),
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "custodian_headers": build_user_headers("test-custodian-1", "Custodian"),
}


def make_platform_admin_headers(user_id: str = "admin-1") -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_records_manager_headers(user_id: str) -> dict:
    """RecordsManager is opaque; pass a distinct user id when requester
    identity matters (disposition-request ownership, segregation of duties)."""
    return build_user_headers(user_id, "RecordsManager")


def make_legal_counsel_headers(user_id: str) -> dict:
    """LegalCounsel is opaque; pass a distinct user id when the approver /
    resolver identity matters (segregation of duties, decided_by fields)."""
    return build_user_headers(user_id, "LegalCounsel")


def make_auditor_headers(user_id: str = "aud-1") -> dict:
    return build_user_headers(user_id, "Auditor")


def make_custodian_headers(custodian_id: str) -> dict:
    """For Custodian (entity_backed:Custodian). Pass the actual Custodian.id
    whenever the call is ownership-gated (acknowledgment)."""
    return build_user_headers(custodian_id, "Custodian")
