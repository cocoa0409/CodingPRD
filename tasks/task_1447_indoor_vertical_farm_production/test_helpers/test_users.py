"""Pre-built role headers for every role in the PRD (§2.1).

Worker is entity-backed: for ownership-gated calls (assignment confirm) the
X-User-ID must equal the Worker record's id — use make_worker_headers(worker_id).
The other six roles carry an opaque X-User-ID; the make_* builders exist for
segregation-of-duties scenarios that must control the exact operator id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and non-ownership-gated calls.
TEST_USERS = {
    "farm_manager_headers": build_user_headers("fm-1", "FarmManager"),
    "grower_headers": build_user_headers("grower-1", "Grower"),
    "sanitation_lead_headers": build_user_headers("san-1", "SanitationLead"),
    "quality_assurance_headers": build_user_headers("qa-1", "QualityAssurance"),
    "contracts_manager_headers": build_user_headers("cm-1", "ContractsManager"),
    "labor_planner_headers": build_user_headers("lp-1", "LaborPlanner"),
    # Worker is entity_backed:Worker — this shared constant is a fallback for
    # non-ownership reads only; confirm calls MUST use make_worker_headers.
    "worker_headers": build_user_headers("test-worker-1", "Worker"),
}


def make_farm_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FarmManager")


def make_grower_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Grower")


def make_sanitation_lead_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SanitationLead")


def make_quality_assurance_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "QualityAssurance")


def make_contracts_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ContractsManager")


def make_labor_planner_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "LaborPlanner")


def make_worker_headers(user_id: str) -> dict:
    """For Worker (entity_backed:Worker). Pass the actual Worker.id as user_id
    whenever the call is ownership-gated (assignment confirm)."""
    return build_user_headers(user_id, "Worker")
