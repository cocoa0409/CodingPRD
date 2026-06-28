"""Pre-built role headers for every role in the PRD (§2.1).

All three roles use an opaque X-User-ID that is never compared to any entity id
(PRD §2.1), so shared constants are the canonical form for every role. Tests that
must pin a specific acting identity (ECO authorship / segregation-of-duties checks,
PRD §2.1 and §3.9) build their own headers with build_user_headers(user_id, role).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "process_engineer_headers": build_user_headers("pe-1", "ProcessEngineer"),
    "production_planner_headers": build_user_headers("pp-1", "ProductionPlanner"),
    "quality_engineer_headers": build_user_headers("qe-1", "QualityEngineer"),
}


def make_process_engineer_headers(user_id: str) -> dict:
    """ProcessEngineer headers pinned to a specific X-User-ID (for authorship checks)."""
    return build_user_headers(user_id, "ProcessEngineer")


def make_production_planner_headers(user_id: str) -> dict:
    """ProductionPlanner headers pinned to a specific X-User-ID (for SoD / acting-user checks)."""
    return build_user_headers(user_id, "ProductionPlanner")


def make_quality_engineer_headers(user_id: str) -> dict:
    """QualityEngineer headers pinned to a specific X-User-ID (for approval checks)."""
    return build_user_headers(user_id, "QualityEngineer")
