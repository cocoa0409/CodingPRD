"""Pre-built role headers for every role in the PRD.

BoardAdmin and Auditor carry opaque X-User-IDs (not tied to any entity).
Provider and Licensee are entity_backed: their X-User-ID must equal the acting
entity's id for ownership-gated calls — so use the per-instance builders below.
"""
from prd_bench_local_runner.testing import build_user_headers

from .constants import ADMIN_INITIATOR_ID, AUDITOR_ID

# Shared constants — safe for opaque roles, and for tests that don't exercise ownership.
TEST_USERS = {
    # opaque roles: shared constant is the canonical form.
    "board_admin_headers": build_user_headers("admin-1", "BoardAdmin"),
    "auditor_headers": build_user_headers(AUDITOR_ID, "Auditor"),
    # The dedicated initiating-admin identity (segregation-of-duties scenarios).
    "admin_initiator_headers": build_user_headers(ADMIN_INITIATOR_ID, "BoardAdmin"),
    # entity_backed roles: these are fallbacks for NON-ownership tests only (e.g.
    # 403/404/400 paths). Ownership-gated calls MUST use the builders below.
    "provider_headers": build_user_headers("test-provider-1", "Provider"),
    "licensee_headers": build_user_headers("test-licensee-1", "Licensee"),
}


def make_board_admin_headers(user_id: str = "admin-1") -> dict:
    """BoardAdmin (opaque). The id is recorded but never ownership-compared."""
    return build_user_headers(user_id, "BoardAdmin")


def make_auditor_headers(user_id: str = AUDITOR_ID) -> dict:
    """Auditor (opaque). The id must differ from an audit's initiated_by_user_id."""
    return build_user_headers(user_id, "Auditor")


def make_provider_headers(provider_id: str) -> dict:
    """Provider (entity_backed:Provider). Pass the actual Provider.id as user_id
    whenever the call is ownership-gated (e.g. creating a Course it owns)."""
    return build_user_headers(provider_id, "Provider")


def make_licensee_headers(licensee_id: str) -> dict:
    """Licensee (entity_backed:Licensee). Pass the actual Licensee.id as user_id
    whenever the call is ownership-gated (completions, cycles, reciprocity,
    resubmit, renew, attestations)."""
    return build_user_headers(licensee_id, "Licensee")
