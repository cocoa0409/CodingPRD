"""Pre-built role headers for every role in the PRD (Section 2.1).

Roles:
  - Coordinator: opaque operator identity, never tied to a persisted entity and
    never subject to ownership checks -> a shared constant is the canonical form.
  - Couple: X-User-ID is the id of the acting Couple; ownership compares the
    resource's couple_id (via the booking chain) against X-User-ID.
  - Officiant: X-User-ID is the id of the acting Officiant; ownership compares the
    target's officiant_id (or the booking's backup_officiant_id) against X-User-ID.

For ownership-gated calls (confirm, script create/patch/submit, officiant
decision, rehearsal confirm/complete, license file/sign, complete, review submit)
the per-instance builders MUST be called with the real entity id.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for the opaque Coordinator, and for tests that do not
# exercise ownership. The couple/officiant fallbacks below are used only for
# tests where ownership is not the subject under test (e.g. a 403/404 path).
TEST_USERS = {
    "coordinator_headers": build_user_headers("coordinator-1", "Coordinator"),
    "couple_headers": build_user_headers("couple-shared-1", "Couple"),
    "officiant_headers": build_user_headers("officiant-shared-1", "Officiant"),
}


def make_coordinator_headers(user_id: str = "coordinator-1") -> dict:
    """Coordinator is opaque; any operator id works and is never ownership-checked."""
    return build_user_headers(user_id, "Coordinator")


def make_couple_headers(user_id: str) -> dict:
    """For a Couple (entity_backed:Couple). Pass the actual Couple.id as user_id
    whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Couple")


def make_officiant_headers(user_id: str) -> dict:
    """For an Officiant (entity_backed:Officiant). Pass the actual Officiant.id as
    user_id whenever the call is ownership-gated (primary or backup)."""
    return build_user_headers(user_id, "Officiant")


# Headers with no authentication at all — for the ERR_UNAUTHENTICATED path.
NO_AUTH_HEADERS: dict = {}
