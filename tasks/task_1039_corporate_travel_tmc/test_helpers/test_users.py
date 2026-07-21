"""Pre-built role headers for every role in the PRD (§2.1).

Role identities (PRD §2.1):
  - TravelManager, FinanceOfficer, System — opaque operator ids never compared
    to any persisted entity; shared constants are the canonical form.
  - Traveler, Approver — X-User-ID is the acting Traveler's `id`. Ownership and
    segregation-of-duties checks compare it against a resource's traveler_id, so
    per-instance builders MUST be used with the real Traveler.id whenever a call
    is ownership-gated.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — shared constants are canonical.
    "travel_manager_headers": build_user_headers("test-travel-manager-1", "TravelManager"),
    "finance_officer_headers": build_user_headers("test-finance-officer-1", "FinanceOfficer"),
    "system_headers": build_user_headers("test-system-1", "System"),
    # Fallbacks for non-ownership Traveler/Approver tests (e.g. 400/403/404 paths).
    "traveler_headers": build_user_headers("test-traveler-1", "Traveler"),
    "approver_headers": build_user_headers("test-approver-1", "Approver"),
}


def make_traveler_headers(user_id: str) -> dict:
    """For Traveler (entity_backed:Traveler). Pass the real Traveler.id whenever the
    call is ownership-gated (create/submit/book/exchange/cancel on own resources)."""
    return build_user_headers(user_id, "Traveler")


def make_approver_headers(user_id: str) -> dict:
    """For Approver (entity_backed:Traveler). Pass the acting approver Traveler.id;
    segregation of duties compares it against the trip's traveler_id."""
    return build_user_headers(user_id, "Approver")
