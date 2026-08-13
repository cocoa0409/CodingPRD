"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership (400-on-bad-payload, 404-on-missing-resource, staff-acted calls).
# Segregation-of-duties pairs need distinct X-User-ID values within the same
# role, so "_b" variants are provided for the inspector/operator/officer roles.
TEST_USERS = {
    "admin_headers": build_user_headers("admin-1", "PackinghouseAdmin"),
    "supervisor_headers": build_user_headers("supervisor-1", "FieldSupervisor"),
    "inspector_headers": build_user_headers("inspector-1", "QualityInspector"),
    "inspector_b_headers": build_user_headers("inspector-2", "QualityInspector"),
    "operator_headers": build_user_headers("operator-1", "LineOperator"),
    "operator_b_headers": build_user_headers("operator-2", "LineOperator"),
    "accountant_headers": build_user_headers("accountant-1", "PoolAccountant"),
    "officer_headers": build_user_headers("officer-1", "ComplianceOfficer"),
    "officer_b_headers": build_user_headers("officer-2", "ComplianceOfficer"),
    "officer_c_headers": build_user_headers("officer-3", "ComplianceOfficer"),
    # entity_backed role: shared constant is a fallback for non-ownership
    # tests only (e.g., asserting role-level denial before ownership runs).
    "grower_headers": build_user_headers("grower-placeholder", "Grower"),
}


# Per-instance builders. make_grower_headers is required for the
# entity_backed Grower role: pass the actual Grower.id whenever the call is
# ownership-gated (PRD §2.1 compares X-User-ID against the owning grower id).
def make_grower_headers(grower_id: str) -> dict:
    """For Grower (entity_backed:Grower). Pass the actual Grower.id as
    grower_id whenever the call is ownership-gated."""
    return build_user_headers(grower_id, "Grower")


def make_admin_headers(user_id: str = "admin-1") -> dict:
    return build_user_headers(user_id, "PackinghouseAdmin")


def make_supervisor_headers(user_id: str = "supervisor-1") -> dict:
    return build_user_headers(user_id, "FieldSupervisor")


def make_inspector_headers(user_id: str = "inspector-1") -> dict:
    return build_user_headers(user_id, "QualityInspector")


def make_operator_headers(user_id: str = "operator-1") -> dict:
    return build_user_headers(user_id, "LineOperator")


def make_accountant_headers(user_id: str = "accountant-1") -> dict:
    return build_user_headers(user_id, "PoolAccountant")


def make_officer_headers(user_id: str = "officer-1") -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")
