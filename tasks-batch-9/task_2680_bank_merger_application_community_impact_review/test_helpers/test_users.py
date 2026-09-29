"""Pre-built role headers for every role in the PRD.

Every request must carry X-User-ID and X-User-Role. For a Filer, X-User-ID is the
id of the acting Institution, so ownership-gated calls must use the per-instance
builder make_filer_headers(institution_id). The other four roles carry opaque
identifiers that are never compared to any entity's id.
"""
from prd_bench_local_runner.testing import build_user_headers

ANALYST_USER_ID = "analyst-1"
OFFICIAL_USER_ID = "official-1"
SECOND_OFFICIAL_USER_ID = "official-2"
MONITOR_USER_ID = "monitor-1"
COMMENTER_USER_ID = "commenter-1"
SECOND_COMMENTER_USER_ID = "commenter-2"

TEST_USERS = {
    # Filer is entity_backed:Institution — this shared constant is a fallback for
    # tests that never exercise ownership (401/400/404 paths and role-rejection).
    "filer_headers": build_user_headers("filer-unowned-1", "Filer"),
    "commenter_headers": build_user_headers(COMMENTER_USER_ID, "PublicCommenter"),
    "second_commenter_headers": build_user_headers(SECOND_COMMENTER_USER_ID, "PublicCommenter"),
    "analyst_headers": build_user_headers(ANALYST_USER_ID, "CaseAnalyst"),
    "official_headers": build_user_headers(OFFICIAL_USER_ID, "ApprovingOfficial"),
    "second_official_headers": build_user_headers(SECOND_OFFICIAL_USER_ID, "ApprovingOfficial"),
    "monitor_headers": build_user_headers(MONITOR_USER_ID, "ComplianceMonitor"),
}


def make_filer_headers(institution_id: str) -> dict:
    """For Filer, whose X-User-ID is the id of the acting Institution. Pass the
    acquirer's id whenever the call is ownership-gated against acquirer_id."""
    return build_user_headers(institution_id, "Filer")


def make_commenter_headers(user_id: str) -> dict:
    """For PublicCommenter, whose X-User-ID is an opaque commenter identifier."""
    return build_user_headers(user_id, "PublicCommenter")


def make_analyst_headers(user_id: str) -> dict:
    """For CaseAnalyst, whose X-User-ID is an opaque regulator-staff identifier."""
    return build_user_headers(user_id, "CaseAnalyst")


def make_official_headers(user_id: str) -> dict:
    """For ApprovingOfficial, whose X-User-ID is an opaque operator identifier."""
    return build_user_headers(user_id, "ApprovingOfficial")


def make_monitor_headers(user_id: str) -> dict:
    """For ComplianceMonitor, whose X-User-ID is an opaque operator identifier."""
    return build_user_headers(user_id, "ComplianceMonitor")


ALL_ROLE_NAMES = ["Filer", "PublicCommenter", "CaseAnalyst", "ApprovingOfficial", "ComplianceMonitor"]
