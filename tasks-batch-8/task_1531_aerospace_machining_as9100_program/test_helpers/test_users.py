"""Pre-built role headers for every role in the PRD (§2.1).

All eight roles use an opaque identity model: `X-User-ID` is never compared
against any entity's `id`, so shared constants are canonical. Distinct named
users exist because segregation-of-duties and delegation rules compare
`X-User-ID` values recorded on resources (PRD §2.9, §3.8).
"""
from prd_bench_local_runner.testing import build_user_headers

# Named user ids referenced by the segregation-of-duties and delegation rules.
USER_CONTRACTS_MANAGER = "cm-1"
USER_SUPPLY_CHAIN_MANAGER = "scm-1"
USER_MANUFACTURING_PLANNER = "mp-1"
USER_QUALITY_INSPECTOR = "insp-1"
USER_QUALITY_INSPECTOR_2 = "insp-2"
USER_QUALITY_INSPECTOR_3 = "insp-3"
USER_QUALITY_INSPECTOR_9 = "insp-9"
USER_MRB_MEMBER = "mrb-1"
USER_QUALITY_MANAGER = "qm-1"
USER_CUSTOMER_QUALITY_REP = "cqr-1"
USER_SYSTEM_ADMIN = "admin-1"

TEST_USERS = {
    "contracts_manager": build_user_headers(
        USER_CONTRACTS_MANAGER, "ContractsManager"
    ),
    "supply_chain_manager": build_user_headers(
        USER_SUPPLY_CHAIN_MANAGER, "SupplyChainManager"
    ),
    "manufacturing_planner": build_user_headers(
        USER_MANUFACTURING_PLANNER, "ManufacturingPlanner"
    ),
    "quality_inspector": build_user_headers(
        USER_QUALITY_INSPECTOR, "QualityInspector"
    ),
    "quality_inspector_2": build_user_headers(
        USER_QUALITY_INSPECTOR_2, "QualityInspector"
    ),
    "quality_inspector_3": build_user_headers(
        USER_QUALITY_INSPECTOR_3, "QualityInspector"
    ),
    "quality_inspector_9": build_user_headers(
        USER_QUALITY_INSPECTOR_9, "QualityInspector"
    ),
    "mrb_member": build_user_headers(USER_MRB_MEMBER, "MRBMember"),
    "quality_manager": build_user_headers(USER_QUALITY_MANAGER, "QualityManager"),
    "customer_quality_rep": build_user_headers(
        USER_CUSTOMER_QUALITY_REP, "CustomerQualityRep"
    ),
    "system_admin": build_user_headers(USER_SYSTEM_ADMIN, "SystemAdmin"),
}


def make_headers(user_id: str, role: str) -> dict:
    """Build headers for an ad-hoc user id under a named role.

    Useful when a test needs a fresh identity (e.g. a disposition attempted
    by the same user id that discovered the report, under the MRBMember role).
    """
    return build_user_headers(user_id, role)
