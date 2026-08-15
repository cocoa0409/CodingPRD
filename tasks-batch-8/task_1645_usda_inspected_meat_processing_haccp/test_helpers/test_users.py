"""Pre-built role headers for every role in the PRD.

All six roles are opaque-identity roles: ``X-User-ID`` is an opaque operator
identifier that the server records on touched resources but never compares
to a resource ``id``. Shared constants below are safe for any call; the
``make_*_headers`` builders exist so tests can mint distinct operator
identities of the same role (segregation-of-duties checks, per-inspector
shift windows, check-in identity binding).
"""
from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    INSPECTOR_1,
    LAB_ANALYST_1,
    PLANT_ADMIN_1,
    PROD_MGR_1,
    QA_MANAGER_1,
    QA_TECH_1,
)

TEST_USERS = {
    "plant_admin_headers": build_user_headers(PLANT_ADMIN_1, "PlantAdmin"),
    "qa_manager_headers": build_user_headers(QA_MANAGER_1, "QAManager"),
    "qa_tech_headers": build_user_headers(QA_TECH_1, "QATech"),
    "lab_analyst_headers": build_user_headers(LAB_ANALYST_1, "LabAnalyst"),
    "inspector_headers": build_user_headers(INSPECTOR_1, "Inspector"),
    "production_manager_headers": build_user_headers(PROD_MGR_1, "ProductionManager"),
}


def make_plant_admin_headers(user_id: str) -> dict:
    """Headers for a PlantAdmin operator with the given user id."""
    return build_user_headers(user_id, "PlantAdmin")


def make_qa_manager_headers(user_id: str) -> dict:
    """Headers for a QAManager operator with the given user id."""
    return build_user_headers(user_id, "QAManager")


def make_qa_tech_headers(user_id: str) -> dict:
    """Headers for a QATech operator with the given user id."""
    return build_user_headers(user_id, "QATech")


def make_lab_analyst_headers(user_id: str) -> dict:
    """Headers for a LabAnalyst operator with the given user id."""
    return build_user_headers(user_id, "LabAnalyst")


def make_inspector_headers(user_id: str) -> dict:
    """Headers for an Inspector operator with the given user id.

    For shift check-in/check-out the user id MUST equal the shift's
    recorded inspector_user_id.
    """
    return build_user_headers(user_id, "Inspector")


def make_production_manager_headers(user_id: str) -> dict:
    """Headers for a ProductionManager operator with the given user id."""
    return build_user_headers(user_id, "ProductionManager")
