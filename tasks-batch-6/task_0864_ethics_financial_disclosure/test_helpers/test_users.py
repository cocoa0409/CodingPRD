"""Pre-built role headers for every role in the PRD.

The `Filer` role is entity-backed: its X-User-ID must equal the acting Filer's id
for ownership-gated calls. Every other role is opaque (its X-User-ID is a free
operator identifier the server records but never compares for ownership).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for Filer tests that do NOT
# exercise ownership (e.g. 401/403/404-on-missing-resource).
TEST_USERS = {
    "registrar_headers": build_user_headers("registrar-1", "Registrar"),
    "ethics_officer_headers": build_user_headers("officer-1", "EthicsOfficer"),
    "investigator_headers": build_user_headers("inv-1", "Investigator"),
    "adjudicator_headers": build_user_headers("adj-1", "Adjudicator"),
    "public_headers": build_user_headers("public-1", "Public"),
    # Filer fallback (non-ownership tests only).
    "filer_headers": build_user_headers("filer-fallback-1", "Filer"),
}


# Per-instance builder — required for the entity_backed Filer role.
def make_filer_headers(filer_id: str) -> dict:
    """Headers for a Filer acting on their own resources. Pass the real Filer.id."""
    return build_user_headers(filer_id, "Filer")


def make_investigator_headers(user_id: str) -> dict:
    """Headers for a specific Investigator operator id (anchors SoD)."""
    return build_user_headers(user_id, "Investigator")


def make_adjudicator_headers(user_id: str) -> dict:
    """Headers for a specific Adjudicator operator id (used to trigger/avoid SoD)."""
    return build_user_headers(user_id, "Adjudicator")
