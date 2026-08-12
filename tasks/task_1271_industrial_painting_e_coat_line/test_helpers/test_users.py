"""Pre-built role headers for every role in the PRD (§2.1).

All five roles are opaque-identity roles: X-User-ID is an operator identifier,
never compared to any entity's id — except for the segregation-of-duties rule
on lot release (PRD §2.1, §3.6), where the releaser's X-User-ID must differ
from the quality tests' recorded_by_user_id. Tests exercising SoD must pick
distinct operator ids via make_qc_inspector_headers / make_quality_manager_headers.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "PlantAdmin"),
    "scheduler_headers": build_user_headers("test-scheduler-1", "LineScheduler"),
    "chemist_headers": build_user_headers("test-chemist-1", "ProcessChemist"),
    "qc_headers": build_user_headers("test-qc-1", "QcInspector"),
    "qm_headers": build_user_headers("test-qm-1", "QualityManager"),
}


def make_admin_headers(user_id: str) -> dict:
    """PlantAdmin headers with a specific operator id."""
    return build_user_headers(user_id, "PlantAdmin")


def make_scheduler_headers(user_id: str) -> dict:
    """LineScheduler headers with a specific operator id."""
    return build_user_headers(user_id, "LineScheduler")


def make_chemist_headers(user_id: str) -> dict:
    """ProcessChemist headers with a specific operator id (stamped on readings)."""
    return build_user_headers(user_id, "ProcessChemist")


def make_qc_inspector_headers(user_id: str) -> dict:
    """QcInspector headers with a specific operator id (stamped on cycles/tests)."""
    return build_user_headers(user_id, "QcInspector")


def make_quality_manager_headers(user_id: str) -> dict:
    """QualityManager headers with a specific operator id (SoD-checked at release)."""
    return build_user_headers(user_id, "QualityManager")
