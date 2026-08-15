"""Pre-built role headers for every role in the PRD (§2.1).

Opaque roles (all except Customer) use fixed operator ids. Customer is
entity-backed: X-User-ID must be the acting Customer record's id, so tests
must build headers with make_customer_headers(customer["id"]).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque operator roles — shared constants are canonical.
    "foundry_admin_headers": build_user_headers("admin_1", "FoundryAdmin"),
    "pattern_maker_headers": build_user_headers("pm_1", "PatternMaker"),
    "melt_supervisor_headers": build_user_headers("melt_1", "MeltSupervisor"),
    "line_operator_headers": build_user_headers("line_1", "LineOperator"),
    # Segregation-of-duties probes need stable, distinct operator ids.
    "spectro_1_headers": build_user_headers("spectro_1", "Spectrographer"),
    "spectro_2_headers": build_user_headers("spectro_2", "Spectrographer"),
    "qi_1_headers": build_user_headers("qi_1", "QualityInspector"),
    "wm_1_headers": build_user_headers("wm_1", "WarrantyManager"),
    "wm_2_headers": build_user_headers("wm_2", "WarrantyManager"),
    # A QualityInspector badge carried by the heat certifier's user id (SoD probe).
    "qi_as_spectro_1_headers": build_user_headers("spectro_1", "QualityInspector"),
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}


def make_customer_headers(user_id: str) -> dict:
    """For Customer (entity_backed:Customer). Pass the actual Customer.id as
    user_id whenever the call is ownership-gated (orders, claims, appeals)."""
    return build_user_headers(user_id, "Customer")
