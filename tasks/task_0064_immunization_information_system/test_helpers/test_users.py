"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants.
# ImmunizationRegistrar and RecordsClerk identify by an OPAQUE operator id that
# is never compared to any entity id (PRD §2.1), so the shared constant is the
# canonical form for them. Provider's X-User-ID must equal the acting Provider
# entity's id for ownership-gated calls, so its shared constant is a fallback
# usable only for non-ownership tests (e.g. 401/403/404 negatives).
TEST_USERS = {
    "registrar_headers": build_user_headers("op-registrar-1", "ImmunizationRegistrar"),
    "clerk_headers": build_user_headers("op-clerk-1", "RecordsClerk"),
    "provider_headers": build_user_headers("test-provider-1", "Provider"),
}


def make_registrar_headers(user_id: str = "op-registrar-1") -> dict:
    """ImmunizationRegistrar (opaque identity); user_id is recorded but never
    compared to an entity id."""
    return build_user_headers(user_id, "ImmunizationRegistrar")


def make_clerk_headers(user_id: str = "op-clerk-1") -> dict:
    """RecordsClerk (opaque identity); user_id is recorded but never compared
    to an entity id."""
    return build_user_headers(user_id, "RecordsClerk")


def make_provider_headers(provider_id: str) -> dict:
    """Provider (entity_backed:Provider). Pass the actual Provider.id as user_id
    whenever the call is ownership-gated (submit/report ops) — per PRD §2.1 a
    Provider may act only on a ProviderReport whose provider_id equals its own
    X-User-ID."""
    return build_user_headers(provider_id, "Provider")
