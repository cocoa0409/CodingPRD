"""Pre-built role headers for every role in the PRD (§2.1).

All roles use opaque X-User-ID values per PRD §2.1; for PanelManager the id is
also the value recorded as panel_manager_id on owned panels, so ownership-gated
flows should use make_panel_manager_headers() with the owning manager id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "admin_headers": build_user_headers("admin_1", "ProgramAdministrator"),
    "panel_manager_headers": build_user_headers("pm_1", "PanelManager"),
    "quality_reviewer_headers": build_user_headers("qr_1", "QualityReviewer"),
    "transport_coordinator_headers": build_user_headers("tc_1", "TransportationCoordinator"),
    "reconciliation_bot_headers": build_user_headers("bot_1", "DataReconciliationBot"),
}


def make_admin_headers(user_id: str = "admin_1") -> dict:
    """ProgramAdministrator headers (opaque identity)."""
    return build_user_headers(user_id, "ProgramAdministrator")


def make_panel_manager_headers(user_id: str) -> dict:
    """PanelManager headers. Pass the owning panel_manager_id (e.g. the value
    used as panel_manager_id when creating the panel) for ownership-gated flows."""
    return build_user_headers(user_id, "PanelManager")


def make_quality_reviewer_headers(user_id: str) -> dict:
    """QualityReviewer headers. For segregation-of-duties, approver user_id must
    differ from the submitter's X-User-ID (PRD §3.6/§3.7)."""
    return build_user_headers(user_id, "QualityReviewer")


def make_transport_coordinator_headers(user_id: str = "tc_1") -> dict:
    """TransportationCoordinator headers (opaque identity)."""
    return build_user_headers(user_id, "TransportationCoordinator")


def make_reconciliation_bot_headers(user_id: str = "bot_1") -> dict:
    """DataReconciliationBot headers (opaque identity)."""
    return build_user_headers(user_id, "DataReconciliationBot")
