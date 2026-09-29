"""Pre-built role headers for every role the program declares."""
from prd_bench_local_runner.testing import build_user_headers

# Opaque operator identities: the server never compares these to a row id, it
# only records them on the audit trail.  Two distinct reviewer/administrator and
# two distinct monitor identities exist so segregation-of-duties chains can be
# driven either legitimately or in violation.
ADMIN_USER_ID = "op-admin-001"
ADMIN_USER_ID_ALT = "op-admin-002"
REVIEWER_USER_ID = "op-reviewer-001"
REVIEWER_USER_ID_ALT = "op-reviewer-002"
DESIGN_BOARD_USER_ID = "op-design-001"
MONITOR_USER_ID = "op-monitor-001"
MONITOR_USER_ID_ALT = "op-monitor-002"

TEST_USERS = {
    "admin_headers": build_user_headers(ADMIN_USER_ID, "ProgramAdministrator"),
    "admin_alt_headers": build_user_headers(ADMIN_USER_ID_ALT, "ProgramAdministrator"),
    "reviewer_headers": build_user_headers(REVIEWER_USER_ID, "SeveranceReviewer"),
    "reviewer_alt_headers": build_user_headers(REVIEWER_USER_ID_ALT, "SeveranceReviewer"),
    "design_board_headers": build_user_headers(DESIGN_BOARD_USER_ID, "DesignReviewBoard"),
    "monitor_headers": build_user_headers(MONITOR_USER_ID, "EasementMonitor"),
    "monitor_alt_headers": build_user_headers(MONITOR_USER_ID_ALT, "EasementMonitor"),
    # Entity-backed roles: these shared constants are safe ONLY for tests that do
    # not exercise an ownership comparison (malformed payloads, unknown ids, or
    # role-permission probes).  Ownership-gated calls MUST use the builders below.
    "landowner_headers": build_user_headers("not-a-real-party-landowner", "Landowner"),
    "developer_headers": build_user_headers("not-a-real-party-developer", "Developer"),
}


def make_admin_headers(user_id: str) -> dict:
    """ProgramAdministrator headers under an explicit operator identity."""
    return build_user_headers(user_id, "ProgramAdministrator")


def make_reviewer_headers(user_id: str) -> dict:
    """SeveranceReviewer headers under an explicit operator identity."""
    return build_user_headers(user_id, "SeveranceReviewer")


def make_design_board_headers(user_id: str) -> dict:
    """DesignReviewBoard headers under an explicit operator identity."""
    return build_user_headers(user_id, "DesignReviewBoard")


def make_monitor_headers(user_id: str) -> dict:
    """EasementMonitor headers under an explicit operator identity."""
    return build_user_headers(user_id, "EasementMonitor")


def make_landowner_headers(party_id: str) -> dict:
    """Landowner headers whose X-User-ID is the acting party's id.

    Required for every ownership-gated landowner call: severance filing,
    resubmission, certificate split and retirement, transaction cancellation.
    """
    return build_user_headers(party_id, "Landowner")


def make_developer_headers(party_id: str) -> dict:
    """Developer headers whose X-User-ID is the acting party's id.

    Required for every ownership-gated developer call: receiving-site filing,
    design resubmission, redemption allocation and release, finalization,
    certificate split and retirement, transaction cancellation.
    """
    return build_user_headers(party_id, "Developer")


ALL_ROLE_NAMES = [
    "ProgramAdministrator",
    "SeveranceReviewer",
    "DesignReviewBoard",
    "EasementMonitor",
    "Landowner",
    "Developer",
]
