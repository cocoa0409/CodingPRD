"""Pre-built role headers for every role in the PRD.

All nine roles use opaque operator identities (PRD user/role section): the
X-User-ID is never compared to any resource's id, so the shared constants
below are canonical. The per-instance builders exist for segregation-of-
duties scenarios where a specific user id must appear under a given role
hat (e.g. the approver carrying the submitter's user id).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "quarry_admin_headers": build_user_headers("qa-1", "QuarryAdmin"),
    "site_manager_headers": build_user_headers("sm-1", "SiteManager"),
    "blast_foreman_headers": build_user_headers("bf-1", "BlastForeman"),
    "plant_operator_headers": build_user_headers("po-1", "PlantOperator"),
    "scale_house_operator_headers": build_user_headers("sh-1", "ScaleHouseOperator"),
    "qc_technician_headers": build_user_headers("qc-1", "QCTechnician"),
    "sales_agent_headers": build_user_headers("sa-1", "SalesAgent"),
    "finance_clerk_headers": build_user_headers("fc-1", "FinanceClerk"),
    "safety_officer_headers": build_user_headers("so-1", "SafetyOfficer"),
}


def make_quarry_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "QuarryAdmin")


def make_site_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SiteManager")


def make_blast_foreman_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "BlastForeman")


def make_plant_operator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlantOperator")


def make_scale_house_operator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ScaleHouseOperator")


def make_qc_technician_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "QCTechnician")


def make_sales_agent_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SalesAgent")


def make_finance_clerk_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FinanceClerk")


def make_safety_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SafetyOfficer")
