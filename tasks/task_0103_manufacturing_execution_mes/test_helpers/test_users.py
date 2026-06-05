"""Pre-built role headers for every role in the MES PRD §2.1.

All five roles use an OPAQUE X-User-ID that is never matched against any entity id
(PRD §2.1: "There are no entity-backed roles in this system; authorization is
determined solely by X-User-Role against the operation"). Shared constants are
therefore the canonical form for every role; no per-instance builders are needed.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "manufacturing_engineer_headers": build_user_headers("test-eng-1", "ManufacturingEngineer"),
    "production_planner_headers": build_user_headers("test-planner-1", "ProductionPlanner"),
    "machine_operator_headers": build_user_headers("test-operator-1", "MachineOperator"),
    "quality_inspector_headers": build_user_headers("test-inspector-1", "QualityInspector"),
    "plant_admin_headers": build_user_headers("test-admin-1", "PlantAdmin"),
}
