"""Pre-built role headers for every role in the PRD.

All six roles are opaque identities: X-User-ID is not tied to any persisted
entity, but segregation-of-duties compares the recorded identifier fields
(created_by_user_id / recorded_by_user_id vs. the caller's X-User-ID).
The shared constants therefore use stable, distinct user ids per function so
that default fixture flows never trip SoD: creators are pm-1 / proc-1,
recorders are tech-1, and approver/verifier/acceptor is qa-mgr-1.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "plant_manager_headers": build_user_headers("pm-1", "PlantManager"),
    "procurement_manager_headers": build_user_headers("proc-1", "ProcurementManager"),
    "qa_technician_headers": build_user_headers("tech-1", "QATechnician"),
    "qa_manager_headers": build_user_headers("qa-mgr-1", "QAManager"),
    "production_operator_headers": build_user_headers("op-1", "ProductionOperator"),
    "warehouse_clerk_headers": build_user_headers("clerk-1", "WarehouseClerk"),
}


def make_plant_manager_headers(user_id: str = "pm-1") -> dict:
    return build_user_headers(user_id, "PlantManager")


def make_procurement_manager_headers(user_id: str = "proc-1") -> dict:
    return build_user_headers(user_id, "ProcurementManager")


def make_qa_technician_headers(user_id: str = "tech-1") -> dict:
    return build_user_headers(user_id, "QATechnician")


def make_qa_manager_headers(user_id: str = "qa-mgr-1") -> dict:
    return build_user_headers(user_id, "QAManager")


def make_production_operator_headers(user_id: str = "op-1") -> dict:
    return build_user_headers(user_id, "ProductionOperator")


def make_warehouse_clerk_headers(user_id: str = "clerk-1") -> dict:
    return build_user_headers(user_id, "WarehouseClerk")
