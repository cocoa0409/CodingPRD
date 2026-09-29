"""Pre-built role headers for every role named in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants. Safe for the six opaque-identity roles, whose X-User-ID is
# never resolved to a row. The two entity-backed roles (Supplier, Customer) must
# use the per-instance builders below whenever the call is ownership-gated.
TEST_USERS = {
    "planner_headers": build_user_headers("mp_1", "MillPlanner"),
    "planner_alt_headers": build_user_headers("mp_2", "MillPlanner"),
    "buyer_headers": build_user_headers("fb_1", "FiberBuyer"),
    "lab_headers": build_user_headers("ql_1", "QualityLab"),
    "lab_sampler_headers": build_user_headers("ql_sample", "QualityLab"),
    "lab_dispo_headers": build_user_headers("ql_dispo", "QualityLab"),
    "lab_cert_headers": build_user_headers("ql_cert", "QualityLab"),
    "operator_headers": build_user_headers("mo_1", "MachineOperator"),
    "operator_alt_headers": build_user_headers("mo_2", "MachineOperator"),
    "env_officer_headers": build_user_headers("eo_1", "EnvironmentalOfficer"),
    "env_logger_headers": build_user_headers("eo_log", "EnvironmentalOfficer"),
    "env_preparer_headers": build_user_headers("eo_prep", "EnvironmentalOfficer"),
    "env_signer_headers": build_user_headers("eo_sign", "EnvironmentalOfficer"),
    "energy_headers": build_user_headers("em_1", "EnergyManager"),
    # entity_backed roles: fallback constants for tests that never reach an
    # ownership or identity-resolution check.
    "supplier_headers": build_user_headers("supplier-unresolved", "Supplier"),
    "customer_headers": build_user_headers("customer-unresolved", "Customer"),
}


def make_supplier_headers(supplier_id: str) -> dict:
    """For the Supplier role. Pass the acting Supplier row's id as X-User-ID."""
    return build_user_headers(supplier_id, "Supplier")


def make_customer_headers(customer_id: str) -> dict:
    """For the Customer role. Pass the acting Customer row's id as X-User-ID."""
    return build_user_headers(customer_id, "Customer")


def make_planner_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "MillPlanner")


def make_lab_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "QualityLab")


def make_operator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "MachineOperator")


def make_env_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "EnvironmentalOfficer")


def make_buyer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FiberBuyer")


def make_energy_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "EnergyManager")
