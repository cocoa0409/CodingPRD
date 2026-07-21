"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants.
# - ClaimsManager / FinanceOfficer / SiuInvestigator are opaque operator identifiers
#   (their X-User-ID is not compared to any entity id) — the shared constant is canonical.
# - Adjuster / Vendor are entity-backed; the shared constant is a fallback used only for
#   tests that do NOT exercise ownership (e.g. an unauthorized-role probe). Ownership-gated
#   calls MUST use make_adjuster_headers(...) / make_vendor_headers(...) with a real id.
TEST_USERS = {
    "claims_manager_headers": build_user_headers("test-cm-1", "ClaimsManager"),
    "finance_officer_headers": build_user_headers("test-fo-1", "FinanceOfficer"),
    "siu_investigator_headers": build_user_headers("test-siu-1", "SiuInvestigator"),
    "adjuster_headers": build_user_headers("test-adj-1", "Adjuster"),
    "vendor_headers": build_user_headers("test-ven-1", "Vendor"),
}


def make_adjuster_headers(user_id: str) -> dict:
    """For Adjuster (entity_backed:Adjuster). Pass the actual Adjuster.id as user_id."""
    return build_user_headers(user_id, "Adjuster")


def make_vendor_headers(user_id: str) -> dict:
    """For Vendor (entity_backed:Vendor). Pass the actual Vendor.id as user_id
    whenever the call is ownership-gated (vendor invoice submission)."""
    return build_user_headers(user_id, "Vendor")
