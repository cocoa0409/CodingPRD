"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise
# ownership. For entity-backed roles (Landlord, Applicant), prefer the
# per-instance builders below whenever the call is ownership-gated.
TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "ComplianceAdmin"),
    "screener_headers": build_user_headers("test-screener-1", "Screener"),
    # Named screeners used by segregation-of-duties scenarios.
    "screener_1_headers": build_user_headers("scr-1", "Screener"),
    "screener_2_headers": build_user_headers("scr-2", "Screener"),
    "screener_3_headers": build_user_headers("scr-3", "Screener"),
    # Fallbacks for non-ownership calls only (see make_*_headers below).
    "landlord_headers": build_user_headers("test-landlord-1", "Landlord"),
    "applicant_headers": build_user_headers("test-applicant-1", "Applicant"),
}


def make_landlord_headers(user_id: str) -> dict:
    """Landlord is entity_backed: pass the actual Landlord.id as user_id
    whenever the call is ownership-gated (criteria, applications, notices)."""
    return build_user_headers(user_id, "Landlord")


def make_applicant_headers(user_id: str) -> dict:
    """Applicant is entity_backed: pass the actual Applicant.id as user_id
    whenever the call is ownership-gated (consent, withdraw, disputes)."""
    return build_user_headers(user_id, "Applicant")


def make_screener_headers(user_id: str) -> dict:
    """Screener is opaque; user_id is an operator identifier. Used when a
    scenario needs a specific screener identity (segregation of duties)."""
    return build_user_headers(user_id, "Screener")
