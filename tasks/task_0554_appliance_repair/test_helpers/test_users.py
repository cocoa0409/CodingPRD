"""Pre-built role headers for the four recognized roles (PRD §2.1).

Dispatcher and ServiceAdmin authenticate with opaque operator ids that the server
never compares to any entity id, so their shared constants are the canonical form.

Customer and Technician are entity-backed: their X-User-ID must equal the acting
Customer.id / Technician.id for ownership-gated calls. Both therefore expose a
per-instance builder that ownership-gated fixtures MUST call with the real entity id.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Opaque roles — shared constant is canonical.
    "dispatcher_headers": build_user_headers("dispatcher-1", "Dispatcher"),
    "service_admin_headers": build_user_headers("admin-1", "ServiceAdmin"),
    # Entity-backed roles — these placeholders are a fallback for tests that do NOT
    # exercise ownership. Ownership-gated calls MUST use the make_* builders below.
    "customer_headers": build_user_headers("customer-placeholder", "Customer"),
    "technician_headers": build_user_headers("technician-placeholder", "Technician"),
}


def make_customer_headers(customer_id: str) -> dict:
    """Headers for a Customer. Pass the real Customer.id whenever the call is
    ownership-gated (deciding an estimate on / paying for that customer's request)."""
    return build_user_headers(customer_id, "Customer")


def make_technician_headers(technician_id: str) -> dict:
    """Headers for a Technician. Pass the real Technician.id whenever the call is
    ownership-gated (diagnose / revise / complete / second-trip / truck-stock / duty status)."""
    return build_user_headers(technician_id, "Technician")
