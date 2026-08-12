"""Pre-built role headers for every role in the PRD.

Eight roles are opaque operator identities; the Distributor role is backed by a
persisted Distributor record, so any ownership-gated Distributor call MUST be
built with make_distributor_headers(<distributor id>).
"""
from prd_bench_local_runner.testing import build_user_headers

from .constants import QA_MANAGER_USER_ID, QA_TECH_USER_ID

TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "plant_manager_headers": build_user_headers("test-pm-1", "PlantManager"),
    "batch_operator_headers": build_user_headers("test-bo-1", "BatchOperator"),
    "qa_technician_headers": build_user_headers(QA_TECH_USER_ID, "QATechnician"),
    "qa_manager_headers": build_user_headers(QA_MANAGER_USER_ID, "QAManager"),
    "tech_service_headers": build_user_headers("test-tse-1", "TechServiceEngineer"),
    "commercial_manager_headers": build_user_headers("test-cm-1", "CommercialManager"),
    "logistics_headers": build_user_headers("test-lc-1", "LogisticsCoordinator"),
    # Fallback for Distributor calls that are NOT ownership-gated (none of the
    # consignment/request writes are — always prefer make_distributor_headers).
    "distributor_headers": build_user_headers("test-dist-1", "Distributor"),
}


def make_distributor_headers(distributor_id: str) -> dict:
    """Distributor is entity-backed: X-User-ID must be the Distributor record's
    id for ownership-gated calls (requests, reports, respond, revise)."""
    return build_user_headers(distributor_id, "Distributor")


def make_qa_manager_headers(user_id: str) -> dict:
    """QAManager headers bound to a specific user id (segregation-of-duties
    scenarios need a releaser distinct from the recording technician)."""
    return build_user_headers(user_id, "QAManager")


def make_qa_technician_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "QATechnician")
