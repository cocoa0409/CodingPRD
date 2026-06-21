"""Pre-built role headers for every role in the PRD (§2.1).

Three roles are opaque operator identities the server never reconciles against a
stored entity: ClaimsAdmin, RatingSpecialist, SchoolCertifyingOfficial. For these,
the shared TEST_USERS constant is the canonical form (X-User-ID is an opaque
operator id).

The fourth role, Veteran, is entity_backed: X-User-ID MUST equal the acting
Veteran.id, and a veteran may act only on resources whose veteran_id equals
X-User-ID (PRD §2.1). Ownership-gated Veteran calls MUST use
make_veteran_headers(veteran_id) with the real Veteran.id — the shared constant
is a fallback for non-ownership scenarios (e.g., the cross-ownership FORBIDDEN test).
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS: dict = {
    # Opaque roles — shared constant is canonical (PRD §2.1).
    "claims_admin_headers": build_user_headers("admin-001", "ClaimsAdmin"),
    "rating_specialist_headers": build_user_headers("rater-001", "RatingSpecialist"),
    "school_official_headers": build_user_headers("sco-001", "SchoolCertifyingOfficial"),
    # Entity-backed Veteran — fallback only; ownership-gated calls MUST use
    # make_veteran_headers(veteran_id).
    "veteran_headers": build_user_headers("veteran-fallback", "Veteran"),
}


def make_veteran_headers(veteran_id: str) -> dict:
    """Veteran headers where X-User-ID equals the acting Veteran.id (PRD §2.1).

    Required for every ownership-gated Veteran call — submitting / cancelling own
    enrollments, filing own claims, managing own dependents, proposing own voc-rehab
    plans. Falling back to the shared constant would mismatch every ownership check.
    """
    return build_user_headers(veteran_id, "Veteran")


def make_unauthenticated_headers() -> dict:
    """Headers carrying an undeclared role, used to trigger ERR_UNAUTHENTICATED
    (PRD §2.1 — X-User-Role not one of the four declared names)."""
    return build_user_headers("anon-001", "Anonymous")
