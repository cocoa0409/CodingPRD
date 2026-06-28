"""Pre-built role headers for every role in the PRD (§2.1).

Four roles (LightingDesigner, InstallTech, ControlProgrammer, OperationsAdmin)
are opaque operators: their X-User-ID is an opaque handle that is never compared
against any entity id, so the shared constants below are the canonical form.

The Customer role is entity_backed: X-User-ID is the id of the acting Customer
entity, and ownership checks compare a resource's customer reference to it. For
ownership-gated Customer calls, build headers with make_customer_headers(customer_id).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — opaque roles use these directly; the Customer entry is a
# fallback used ONLY by tests whose success does not depend on Customer ownership
# (e.g. a 401/403/404 rejection).
TEST_USERS = {
    "lighting_designer_headers": build_user_headers("op-designer-1", "LightingDesigner"),
    "install_tech_headers": build_user_headers("op-tech-1", "InstallTech"),
    "control_programmer_headers": build_user_headers("op-programmer-1", "ControlProgrammer"),
    "operations_admin_headers": build_user_headers("op-admin-1", "OperationsAdmin"),
    # Fallback for non-ownership Customer tests only.
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}


def make_customer_headers(customer_id: str) -> dict:
    """For the Customer role (entity_backed:Customer). Pass the real Customer.id
    as user_id whenever the call is ownership-gated (quote accept/reject, plan
    activate/cancel, warranty-claim submit, service-visit request)."""
    return build_user_headers(customer_id, "Customer")
