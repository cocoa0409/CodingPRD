"""Pre-built role headers for every role in the PRD.

PlatformAdmin is an opaque identity: X-User-ID is not tied to any persisted
entity. AssetManager, Broker, and LandlordCounsel are entity-backed by
Contact (X-User-ID is the acting Contact's id); ownership-gated calls MUST
use the per-instance builders with the real Contact id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the opaque role and for tests that do not
# exercise ownership (400-on-bad-payload, 404-on-missing-resource, wrong-role).
TEST_USERS = {
    "admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    # entity_backed roles: shared constants are fallbacks for non-ownership tests only.
    "am_headers": build_user_headers("test-am-1", "AssetManager"),
    "bk_headers": build_user_headers("test-bk-1", "Broker"),
    "lc_headers": build_user_headers("test-lc-1", "LandlordCounsel"),
}


def make_admin_headers(user_id: str = "test-platform-admin-1") -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_am_headers(contact_id: str) -> dict:
    """For AssetManager (entity_backed:Contact). Pass the acting Contact.id
    whenever the call is ownership-gated."""
    return build_user_headers(contact_id, "AssetManager")


def make_bk_headers(contact_id: str) -> dict:
    """For Broker (entity_backed:Contact). Pass the acting Contact.id
    whenever the call is ownership-gated."""
    return build_user_headers(contact_id, "Broker")


def make_lc_headers(contact_id: str) -> dict:
    """For LandlordCounsel (entity_backed:Contact). Pass the acting Contact.id
    whenever the call is ownership-gated."""
    return build_user_headers(contact_id, "LandlordCounsel")
