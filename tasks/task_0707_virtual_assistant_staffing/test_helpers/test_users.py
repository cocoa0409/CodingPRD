"""Pre-built role headers for every role in the PRD.

Two roles are entity-backed (PRD §2.1): Client (X-User-ID is the acting
Client.id) and VA (X-User-ID is the acting VirtualAssistant.id). For
ownership-gated calls these MUST be built per-instance with the real entity id
via make_client_headers(client_id) / make_va_headers(va_id). StaffingManager is
opaque (its X-User-ID is not tied to any persisted entity), so its shared
constant is the canonical form.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the opaque StaffingManager role, and for tests
# that do not exercise Client/VA ownership (e.g. 401/404/422-on-bad-payload).
TEST_USERS = {
    "staffing_manager_headers": build_user_headers("test-staffing-manager-1", "StaffingManager"),
    # Client/VA shared constants are fallbacks for non-ownership tests only.
    "client_headers": build_user_headers("test-client-1", "Client"),
    "va_headers": build_user_headers("test-va-1", "VA"),
}


def make_staffing_manager_headers(user_id: str = "test-staffing-manager-1") -> dict:
    """StaffingManager is opaque; its id is not compared to any entity."""
    return build_user_headers(user_id, "StaffingManager")


def make_client_headers(client_id: str) -> dict:
    """For the Client role (entity_backed:Client). Pass the actual Client.id as
    user_id whenever the call is ownership-gated (scope, accept/reject, approve,
    addon request, own-tree reads)."""
    return build_user_headers(client_id, "Client")


def make_va_headers(va_id: str) -> dict:
    """For the VA role (entity_backed:VirtualAssistant). Pass the actual
    VirtualAssistant.id as user_id whenever the call is ownership-gated (start,
    block, unblock, complete, log time)."""
    return build_user_headers(va_id, "VA")
