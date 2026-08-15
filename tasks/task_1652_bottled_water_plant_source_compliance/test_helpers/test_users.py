"""Pre-built role headers for every role in the PRD (§2.1).

Every role in this API is `opaque`: X-User-ID is an operator identifier never
compared against any entity id (§2.1). Shared constants are therefore the
canonical form; per-instance builders exist only so tests can thread distinct
operator ids through segregation-of-duties scenarios (§2.10).
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — one per role. Suitable for every call in this API because
# no ownership check compares X-User-ID to an entity id.
TEST_USERS = {
    "plant_admin_headers": build_user_headers("pa-1", "PlantAdmin"),
    "source_monitor_headers": build_user_headers("sm-1", "SourceMonitor"),
    "qa_officer_headers": build_user_headers("qa-1", "QAOfficer"),
    "production_lead_headers": build_user_headers("pl-1", "ProductionLead"),
    "sanitation_lead_headers": build_user_headers("sl-1", "SanitationLead"),
    "compliance_officer_headers": build_user_headers("co-1", "ComplianceOfficer"),
}


# Per-instance builders — for segregation-of-duties scenarios where the same
# role must appear under distinct operator ids (§2.10).
def make_plant_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlantAdmin")


def make_source_monitor_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SourceMonitor")


def make_qa_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "QAOfficer")


def make_production_lead_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ProductionLead")


def make_sanitation_lead_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SanitationLead")


def make_compliance_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")
