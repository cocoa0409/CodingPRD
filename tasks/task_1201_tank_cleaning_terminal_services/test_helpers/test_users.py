"""Pre-built role headers for every role in the PRD (§2.1).

Entity-backed roles (ContractorSupervisor -> Contractor.id,
API653Inspector -> Inspector.id) MUST be built per-instance via the make_*
builders with the real entity id; the shared constants for those roles are
fallbacks for non-ownership-gated calls only.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and non-ownership tests.
TEST_USERS = {
    "admin_headers": build_user_headers("admin-1", "TerminalAdmin"),
    "operator_headers": build_user_headers("op-1", "TerminalOperator"),
    "operator2_headers": build_user_headers("op-2", "TerminalOperator"),
    "chemist_headers": build_user_headers("chemist-1", "MarineChemist"),
    "chemist2_headers": build_user_headers("chemist-2", "MarineChemist"),
    "ehs_headers": build_user_headers("ehs-1", "EHSOfficer"),
    "ehs2_headers": build_user_headers("ehs-2", "EHSOfficer"),
    "lab_headers": build_user_headers("lab-1", "LabTechnician"),
    "lab2_headers": build_user_headers("lab-2", "LabTechnician"),
    # entity_backed fallbacks — never equal a real entity id; ownership-gated
    # calls must use the make_* builders below instead.
    "contractor_headers": build_user_headers("no-such-contractor", "ContractorSupervisor"),
    "inspector_headers": build_user_headers("no-such-inspector", "API653Inspector"),
}


def make_contractor_supervisor_headers(user_id: str) -> dict:
    """ContractorSupervisor is entity-backed: pass the acting Contractor.id
    whenever the call is ownership-gated (job/waste/permit/repair actions)."""
    return build_user_headers(user_id, "ContractorSupervisor")


def make_inspector_headers(user_id: str) -> dict:
    """API653Inspector is entity-backed: pass the acting Inspector.id
    whenever the call is ownership-gated (inspection start/report/amend,
    findings, repair verify/reject)."""
    return build_user_headers(user_id, "API653Inspector")
