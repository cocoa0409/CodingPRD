"""Pre-built role headers for every role in the PRD (Section 2.1).

Two of the four roles are entity-backed: an Organizer's X-User-ID must equal the
acting Organizer.id, and a Client's X-User-ID must equal the acting Client.id, so
ownership checks pass. Use the per-instance builders below with the real entity id
whenever a call is ownership-gated. The other two roles (OperationsManager,
BillingAdmin) are opaque — a shared constant is the canonical form.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — canonical shared constants.
    "operations_manager_headers": build_user_headers("test-ops-1", "OperationsManager"),
    "billing_admin_headers": build_user_headers("test-billing-1", "BillingAdmin"),
    # Entity-backed roles — shared constant is a fallback for non-ownership tests only.
    "organizer_headers": build_user_headers("test-organizer-1", "Organizer"),
    "client_headers": build_user_headers("test-client-1", "Client"),
}


def make_organizer_headers(user_id: str) -> dict:
    """For the Organizer role (entity-backed). Pass the real Organizer.id whenever
    the call is ownership-gated (session completion, fieldwork)."""
    return build_user_headers(user_id, "Organizer")


def make_client_headers(user_id: str) -> dict:
    """For the Client role (entity-backed). Pass the real Client.id whenever the
    call is ownership-gated (paying/disputing that client's invoices)."""
    return build_user_headers(user_id, "Client")
