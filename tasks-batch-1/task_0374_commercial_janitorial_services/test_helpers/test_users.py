"""Pre-built role headers for every role in the PRD.

All four roles use an opaque identity model: X-User-ID is an opaque operator
identifier not compared to any persisted entity's id. For ClientContact, the
opaque X-User-ID carries an ownership meaning — it is matched against a site's
contact_user_id. Fixtures create sites whose contact_user_id equals the
canonical ClientContact id below, so the shared ClientContact constant owns its
own sites.
"""
from prd_bench_local_runner.testing import build_user_headers
from .constants import DEFAULT_CONTACT_USER_ID

TEST_USERS = {
    "account_manager_headers": build_user_headers("am-1", "AccountManager"),
    "field_supervisor_headers": build_user_headers("fs-1", "FieldSupervisor"),
    # ClientContact whose opaque id is the canonical site contact_user_id.
    "client_contact_headers": build_user_headers(DEFAULT_CONTACT_USER_ID, "ClientContact"),
    "platform_admin_headers": build_user_headers("pa-1", "PlatformAdmin"),
}


def make_client_contact_headers(contact_user_id: str) -> dict:
    """ClientContact headers whose X-User-ID equals a given site's contact_user_id.

    Use when a test needs a ClientContact bound to a specific site's
    contact_user_id (the ownership value matched in §2.1)."""
    return build_user_headers(contact_user_id, "ClientContact")
