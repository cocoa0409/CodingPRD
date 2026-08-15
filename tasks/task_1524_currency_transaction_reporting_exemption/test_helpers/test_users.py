"""Pre-built role headers for every role in the PRD §2.1 role list.

All six roles are `identity: opaque` per the PRD: X-User-ID is an operator
identifier, never tied to a persisted entity id. SoD compares operator ids
against recorded *_by_id fields, so distinct operators need distinct ids.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for every call whose success does not depend on the
# caller's identity matching a recorded operator id on a target resource.
TEST_USERS = {
    "admin_headers": build_user_headers("admin-1", "SystemAdmin"),
    "manager_headers": build_user_headers("manager-1", "BranchManager"),
    "teller_headers": build_user_headers("teller-1", "Teller"),
    "analyst_headers": build_user_headers("analyst-x", "ComplianceAnalyst"),
    "officer_headers": build_user_headers("officer-y", "BSAOfficer"),
    "examiner_headers": build_user_headers("examiner-1", "Examiner"),
}

# Named operators used when SoD or OCC semantics require distinct identities.
OPERATOR_ADMIN = "admin-1"
OPERATOR_MANAGER = "manager-1"
OPERATOR_TELLER = "teller-1"
OPERATOR_ANALYST_X = "analyst-x"
OPERATOR_OFFICER_A = "officer-a"
OPERATOR_OFFICER_B = "officer-b"
OPERATOR_OFFICER_C = "officer-c"
OPERATOR_OFFICER_Y = "officer-y"
OPERATOR_OFFICER_Z = "officer-z"
OPERATOR_EXAMINER = "examiner-1"


def make_admin_headers(user_id: str = OPERATOR_ADMIN) -> dict:
    return build_user_headers(user_id, "SystemAdmin")


def make_manager_headers(user_id: str = OPERATOR_MANAGER) -> dict:
    return build_user_headers(user_id, "BranchManager")


def make_teller_headers(user_id: str = OPERATOR_TELLER) -> dict:
    return build_user_headers(user_id, "Teller")


def make_analyst_headers(user_id: str = OPERATOR_ANALYST_X) -> dict:
    return build_user_headers(user_id, "ComplianceAnalyst")


def make_officer_headers(user_id: str = OPERATOR_OFFICER_Y) -> dict:
    return build_user_headers(user_id, "BSAOfficer")


def make_examiner_headers(user_id: str = OPERATOR_EXAMINER) -> dict:
    return build_user_headers(user_id, "Examiner")
