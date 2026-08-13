"""Pre-built role headers for every role in the PRD (§2.1).

Retailer is entity-backed: when a call is ownership-gated, its X-User-ID must be
the acting Retailer entity's id — use make_retailer_headers(retailer["id"]).
The shared constant below is only for tests that do not exercise ownership.
"""
from prd_bench_local_runner.testing import build_user_headers

# Two ComplianceOfficer identities: approvals must come from a different
# X-User-ID than the creator (PRD §2.9 segregation of duties).
TEST_USERS = {
    "plant_manager_headers": build_user_headers("pm-1", "PlantManager"),
    "compliance_creator_headers": build_user_headers("co-1", "ComplianceOfficer"),
    "compliance_approver_headers": build_user_headers("co-2", "ComplianceOfficer"),
    "line_supervisor_headers": build_user_headers("ls-1", "LineSupervisor"),
    "qc_inspector_headers": build_user_headers("qc-1", "QcInspector"),
    "logistics_headers": build_user_headers("log-1", "LogisticsCoordinator"),
    # Fallback only for non-ownership tests (e.g. RBAC denial on a foreign write).
    "retailer_headers": build_user_headers("test-retailer-1", "Retailer"),
}


def make_retailer_headers(retailer_id: str) -> dict:
    """Retailer is entity-backed: pass the actual Retailer.id as X-User-ID."""
    return build_user_headers(retailer_id, "Retailer")


def make_plant_manager_headers(user_id: str = "pm-1") -> dict:
    return build_user_headers(user_id, "PlantManager")


def make_compliance_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")


def make_line_supervisor_headers(user_id: str = "ls-1") -> dict:
    return build_user_headers(user_id, "LineSupervisor")


def make_qc_inspector_headers(user_id: str = "qc-1") -> dict:
    return build_user_headers(user_id, "QcInspector")


def make_logistics_headers(user_id: str = "log-1") -> dict:
    return build_user_headers(user_id, "LogisticsCoordinator")
