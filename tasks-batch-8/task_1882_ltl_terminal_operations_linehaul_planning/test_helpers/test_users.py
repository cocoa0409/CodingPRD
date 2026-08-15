"""Pre-built role headers for every role in the PRD (§2.1).

All five roles hold an opaque identity: the server never compares X-User-ID to a
resource's id, so shared constants are the canonical form for every role. The
fixed ids in TEST_USER_IDS matter only where the PRD requires provenance — the
RatingClerk's X-User-ID is persisted as scanned_by on a dimensioner scan (§3.4).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USER_IDS = {
    "TerminalAdmin": "test-terminal-admin-1",
    "Dispatcher": "test-dispatcher-1",
    "DockSupervisor": "test-dock-supervisor-1",
    "RatingClerk": "test-rating-clerk-1",
    "OsdClerk": "test-osd-clerk-1",
}

TEST_USERS = {
    "terminal_admin_headers": build_user_headers(
        TEST_USER_IDS["TerminalAdmin"], "TerminalAdmin"
    ),
    "dispatcher_headers": build_user_headers(TEST_USER_IDS["Dispatcher"], "Dispatcher"),
    "dock_supervisor_headers": build_user_headers(
        TEST_USER_IDS["DockSupervisor"], "DockSupervisor"
    ),
    "rating_clerk_headers": build_user_headers(
        TEST_USER_IDS["RatingClerk"], "RatingClerk"
    ),
    "osd_clerk_headers": build_user_headers(TEST_USER_IDS["OsdClerk"], "OsdClerk"),
}


def make_headers_for_role(role: str, user_id: str = None) -> dict:
    """Build headers for any of the five PRD roles (all opaque identity)."""
    return build_user_headers(user_id or TEST_USER_IDS[role], role)
