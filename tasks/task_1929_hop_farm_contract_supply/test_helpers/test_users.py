"""Pre-built role headers for every role in the PRD (§2.1).

All four roles are opaque: the server never compares X-User-ID to an entity id.
The single place an operator identifier is persisted and later compared is an
insurance claim's filed_by_user_id, checked by the segregation-of-duties rule
(§3.8) — so tests control the user id explicitly via the per-role builders.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "farm_manager_headers": build_user_headers("test-farm-manager-1", "FarmManager"),
    "lab_technician_headers": build_user_headers("test-lab-tech-1", "LabTechnician"),
    "contract_manager_headers": build_user_headers("test-contract-manager-1", "ContractManager"),
    "insurance_adjuster_headers": build_user_headers("test-insurance-adjuster-1", "InsuranceAdjuster"),
}


def make_farm_manager_headers(user_id: str) -> dict:
    """FarmManager headers with a specific X-User-ID (e.g. the claim filer)."""
    return build_user_headers(user_id, "FarmManager")


def make_lab_technician_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "LabTechnician")


def make_contract_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ContractManager")


def make_insurance_adjuster_headers(user_id: str) -> dict:
    """InsuranceAdjuster headers with a specific X-User-ID (segregation of
    duties tests pick an id equal to or different from filed_by_user_id)."""
    return build_user_headers(user_id, "InsuranceAdjuster")
