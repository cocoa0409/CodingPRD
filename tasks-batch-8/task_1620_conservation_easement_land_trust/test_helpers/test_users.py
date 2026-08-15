"""Pre-built role headers for every role in the PRD (§2.1).

The Landowner role is entity-backed: its X-User-ID must be the id of the acting
Landowner record, so ownership-gated calls MUST be made with
make_landowner_headers(<landowner id>). The shared "landowner_headers" constant
is a fallback only for tests whose outcome does not depend on landowner identity.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "trust_admin_headers": build_user_headers("admin-1", "TrustAdmin"),
    "coordinator_headers": build_user_headers("coord-1", "StewardshipCoordinator"),
    "field_monitor_headers": build_user_headers("mon-1", "FieldMonitor"),
    "board_reviewer_headers": build_user_headers("board-1", "TrustBoardReviewer"),
    "appraiser_headers": build_user_headers("appr-1", "Appraiser"),
    # Fallback only — never valid for ownership-gated landowner operations.
    "landowner_headers": build_user_headers("landowner-fallback", "Landowner"),
}


def make_trust_admin_headers(user_id: str) -> dict:
    """TrustAdmin is an opaque role; any operator id works."""
    return build_user_headers(user_id, "TrustAdmin")


def make_coordinator_headers(user_id: str) -> dict:
    """StewardshipCoordinator is an opaque role; pick the id to satisfy
    segregation-of-duties pairings (preparer/acceptor, detector/resolver,
    submitter/approver, executor/completer)."""
    return build_user_headers(user_id, "StewardshipCoordinator")


def make_field_monitor_headers(user_id: str) -> dict:
    """FieldMonitor is an opaque role; visit completion requires
    X-User-ID == the visit's monitor_user_id."""
    return build_user_headers(user_id, "FieldMonitor")


def make_board_reviewer_headers(user_id: str) -> dict:
    """TrustBoardReviewer is an opaque role; pick the id to satisfy
    segregation-of-duties pairings."""
    return build_user_headers(user_id, "TrustBoardReviewer")


def make_appraiser_headers(user_id: str) -> dict:
    """Appraiser is an opaque role; delivery requires
    X-User-ID == the appraisal's appraiser_user_id."""
    return build_user_headers(user_id, "Appraiser")


def make_landowner_headers(user_id: str) -> dict:
    """Landowner is entity-backed: pass the actual Landowner.id whenever the
    call is ownership-gated (use-authorization requests, succession notices,
    start-of-cure)."""
    return build_user_headers(user_id, "Landowner")
