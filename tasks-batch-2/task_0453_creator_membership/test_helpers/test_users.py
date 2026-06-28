"""Pre-built role headers for every role in the Creator Membership PRD (§2.1).

The platform recognizes exactly three roles: Creator, Patron, PlatformAdmin.

- Creator is entity-backed: X-User-ID is the id of the acting Creator, and
  ownership checks compare a resource's creator_id to it. Every ownership-gated
  Creator call MUST use make_creator_headers(creator_id) with the real
  Creator.id — the shared constant is a fallback only for tests that do not
  exercise ownership (auth / role-permission rejection paths).

- Patron is entity-backed: X-User-ID is the id of the acting Patron, and
  ownership checks compare a resource's patron_id to it. Every ownership-gated
  Patron call MUST use make_patron_headers(patron_id) with the real Patron.id.

- PlatformAdmin is opaque: X-User-ID is an operator identifier never compared
  to any persisted entity, so the shared constant is the canonical form.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # PlatformAdmin (opaque): shared constant is the canonical form.
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    # Creator (entity_backed): fallback for non-ownership tests only.
    "creator_headers": build_user_headers("test-creator-1", "Creator"),
    # Patron (entity_backed): fallback for non-ownership tests only.
    "patron_headers": build_user_headers("test-patron-1", "Patron"),
}


def make_creator_headers(user_id: str) -> dict:
    """Creator (entity_backed:Creator). Pass the actual Creator.id as user_id
    whenever the call is ownership-gated (tier/post create+publish+retire,
    own-charge refund, creator side of conversations/messages, win-back offers)."""
    return build_user_headers(user_id, "Creator")


def make_patron_headers(user_id: str) -> dict:
    """Patron (entity_backed:Patron). Pass the actual Patron.id as user_id
    whenever the call is ownership-gated (pledge create + lifecycle actions,
    post access, patron side of conversations/messages)."""
    return build_user_headers(user_id, "Patron")


def make_platform_admin_headers(user_id: str = "test-admin-1") -> dict:
    """PlatformAdmin is opaque; user_id is recorded but never matched to an entity."""
    return build_user_headers(user_id, "PlatformAdmin")


# No-auth (anonymous) request carries no headers at all — used to exercise
# ERR_MISSING_AUTH_CONTEXT (PRD §2.1).
NO_AUTH_HEADERS: dict = {}
