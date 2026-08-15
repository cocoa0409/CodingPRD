"""Pre-built role headers for every role in the PRD.

WholesaleBuyer and CrewLead are entity-backed roles: their X-User-ID must be
the id of the acting BuyerAccount / Crew. Fixtures MUST call the per-instance
builders with the real entity id for ownership-gated calls; the shared
constants are only for non-ownership tests (400/404, denials, opaque roles).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles: shared constant is the canonical form.
    "owner_headers": build_user_headers("test-owner-1", "Owner"),
    "farm_manager_headers": build_user_headers("test-fm-1", "FarmManager"),
    # Entity-backed roles: fallback for non-ownership tests only.
    "wholesale_buyer_headers": build_user_headers("test-buyer-1", "WholesaleBuyer"),
    "crew_lead_headers": build_user_headers("test-crew-1", "CrewLead"),
}

# A second Owner identity, used by segregation-of-duties scenarios where the
# deciding Owner must differ from the proposing FarmManager user id.
OWNER_ALT_USER_ID = "owner-sam"


def make_owner_headers(user_id: str = "test-owner-1") -> dict:
    """Owner is an opaque role; any stable user id works."""
    return build_user_headers(user_id, "Owner")


def make_farm_manager_headers(user_id: str) -> dict:
    """FarmManager is an opaque role; the id may be recorded (e.g. as
    proposed_by_user_id on a replant plan) but is never entity-compared."""
    return build_user_headers(user_id, "FarmManager")


def make_buyer_headers(user_id: str) -> dict:
    """WholesaleBuyer is entity-backed: pass the actual BuyerAccount.id as
    user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "WholesaleBuyer")


def make_crew_lead_headers(user_id: str) -> dict:
    """CrewLead is entity-backed: pass the actual Crew.id as user_id whenever
    the call is ownership-gated (ticket posting, ticket lists)."""
    return build_user_headers(user_id, "CrewLead")
