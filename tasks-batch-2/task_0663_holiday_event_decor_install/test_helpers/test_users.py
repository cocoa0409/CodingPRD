"""Pre-built role headers for every role in the PRD.

Three of the four roles (AccountManager, FieldSupervisor, PlatformAdmin) are opaque
operator identities whose X-User-ID is never compared to any entity (PRD §2.1) — the
shared constants below are the canonical form for them. The fourth role, ClientContact,
is entity-backed:Client; its ownership-gated calls (sign / accept / reject / decline) must
use make_client_contact_headers(client_id) with the owning Client's id (PRD §2.1).
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Opaque operator roles — shared constants are canonical.
    "account_manager_headers": build_user_headers("test-account-manager-1", "AccountManager"),
    "field_supervisor_headers": build_user_headers("test-field-supervisor-1", "FieldSupervisor"),
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    # entity_backed:Client — shared constant is a fallback for non-ownership reads only.
    "client_contact_headers": build_user_headers("test-client-contact-1", "ClientContact"),
}


def make_client_contact_headers(client_id: str) -> dict:
    """For ClientContact (entity_backed:Client). Pass the owning Client.id as the user id
    whenever the call is ownership-gated (sign / accept / reject / decline)."""
    return build_user_headers(client_id, "ClientContact")
