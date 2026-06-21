"""Pre-built role headers for every role in the PRD (§2.1).

TrustAdmin is opaque (not tied to any persisted entity) — the shared constant is
the canonical form. Grantor / Trustee / Beneficiary are entity-backed: their X-User-ID
is interpreted as the acting entity's id, so ownership-gated calls MUST pass the real
entity id via the per-instance builders below. The shared constants for those roles are
fallbacks for tests that do not exercise ownership.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Opaque role — canonical shared form.
    "trust_admin_headers": build_user_headers("test-admin-1", "TrustAdmin"),
    # Entity-backed roles — shared constants are fallbacks for non-ownership tests only.
    "grantor_headers": build_user_headers("test-grantor-1", "Grantor"),
    "trustee_headers": build_user_headers("test-trustee-1", "Trustee"),
    "beneficiary_headers": build_user_headers("test-beneficiary-1", "Beneficiary"),
}


# ─── Per-instance builders — mandatory for entity-backed roles ────────────

def make_grantor_headers(user_id: str) -> dict:
    """For Grantor (entity_backed:Grantor). Pass the actual Grantor.id as user_id
    whenever the call is ownership-gated (any trust operation scoped to a grantor)."""
    return build_user_headers(user_id, "Grantor")


def make_trustee_headers(user_id: str) -> dict:
    """For Trustee (entity_backed:Trustee). Pass the actual Trustee.id as user_id
    whenever the call is ownership-gated (distribution operations require this trustee
    to hold an ACTIVE appointment over the owning trust)."""
    return build_user_headers(user_id, "Trustee")


def make_beneficiary_headers(user_id: str) -> dict:
    """For Beneficiary (entity_backed:Beneficiary). Pass the actual Beneficiary.id as
    user_id whenever the call is ownership-gated (reading own K-1 / own record)."""
    return build_user_headers(user_id, "Beneficiary")
