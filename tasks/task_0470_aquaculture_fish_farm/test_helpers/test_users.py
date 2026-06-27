"""Pre-built role headers for every role in the PRD.

Every role here is an opaque operator category, not an entity-backed identity:
per the PRD, X-User-ID is an opaque operator identifier the server records for
audit but never compares to any entity's id, and authorization is decided
purely by role. Shared constants are therefore the canonical form for all roles
and there are no per-instance ownership builders.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "farm_manager_headers": build_user_headers("op-farm-manager-1", "FarmManager"),
    "farm_technician_headers": build_user_headers("op-farm-tech-1", "FarmTechnician"),
    "veterinarian_headers": build_user_headers("op-vet-1", "Veterinarian"),
    "harvest_operator_headers": build_user_headers("op-harvest-1", "HarvestOperator"),
    "sales_agent_headers": build_user_headers("op-sales-1", "SalesAgent"),
}
