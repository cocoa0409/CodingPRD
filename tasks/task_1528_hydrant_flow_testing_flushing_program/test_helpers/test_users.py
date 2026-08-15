"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that don't exercise ownership.
TEST_USERS = {
    "admin_headers": build_user_headers("admin_1", "ProgramAdmin"),
    "operator_headers": build_user_headers("op_1", "FieldOperator"),
    "operator2_headers": build_user_headers("op_2", "FieldOperator"),
    "supervisor_headers": build_user_headers("sup_1", "UtilitySupervisor"),
    "supervisor2_headers": build_user_headers("sup_2", "UtilitySupervisor"),
    "liaison_headers": build_user_headers("fd_1", "FireDeptLiaison"),
    # entity_backed role: fallback only for tests that never hit an ownership-gated path
    "owner_rep_headers": build_user_headers("owner-placeholder", "PrivateOwnerRep"),
}


def make_admin_headers(user_id: str = "admin_1") -> dict:
    return build_user_headers(user_id, "ProgramAdmin")


def make_operator_headers(user_id: str = "op_1") -> dict:
    return build_user_headers(user_id, "FieldOperator")


def make_supervisor_headers(user_id: str = "sup_1") -> dict:
    return build_user_headers(user_id, "UtilitySupervisor")


def make_liaison_headers(user_id: str = "fd_1") -> dict:
    return build_user_headers(user_id, "FireDeptLiaison")


def make_owner_rep_headers(user_id: str) -> dict:
    """For PrivateOwnerRep (entity_backed:PrivateOwner). Pass the actual
    PrivateOwner.id as user_id whenever the call is ownership-gated (PRD §2.1)."""
    return build_user_headers(user_id, "PrivateOwnerRep")
