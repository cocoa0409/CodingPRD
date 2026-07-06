"""Pre-built role headers for every role in the MSP Managed IT PRD (§2.1).

Three roles are opaque operator identities (ServiceManager, Dispatcher,
AccountManager). Two roles are entity_backed:
  - Technician  — X-User-ID is a Technician.id
  - ClientContact — X-User-ID is a Client.id

For any ownership-gated call by an entity_backed role, mint per-instance headers
by passing the actual entity's id to the corresponding make_* function.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — opaque roles, or entity_backed calls that don't exercise
# ownership (e.g. GET /assets/{missing} → 404).
TEST_USERS = {
    "service_manager_headers": build_user_headers("test-service-manager-1", "ServiceManager"),
    "dispatcher_headers":      build_user_headers("test-dispatcher-1", "Dispatcher"),
    "account_manager_headers": build_user_headers("test-account-manager-1", "AccountManager"),
    # Fallbacks — the make_* builders below are the correct choice when the
    # entity_backed role must own the resource under test.
    "technician_headers":      build_user_headers("test-technician-fallback", "Technician"),
    "client_contact_headers":  build_user_headers("test-client-fallback", "ClientContact"),
}


def make_service_manager_headers(user_id: str = "test-service-manager-1") -> dict:
    return build_user_headers(user_id, "ServiceManager")


def make_dispatcher_headers(user_id: str = "test-dispatcher-1") -> dict:
    return build_user_headers(user_id, "Dispatcher")


def make_account_manager_headers(user_id: str = "test-account-manager-1") -> dict:
    return build_user_headers(user_id, "AccountManager")


def make_technician_headers(user_id: str) -> dict:
    """For Technician (entity_backed:Technician). Pass the actual Technician.id
    as user_id whenever the call is ownership-gated (dispatch/patch execution)."""
    return build_user_headers(user_id, "Technician")


def make_client_contact_headers(user_id: str) -> dict:
    """For ClientContact (entity_backed:Client). Pass the actual Client.id as
    user_id whenever the call is ownership-gated (quote accept/revise, ticket
    open/reopen)."""
    return build_user_headers(user_id, "ClientContact")
