"""Pre-built role headers for every role in the PRD §2.1.

All roles are opaque: X-User-ID is never compared to a resource id, only to
other actors' ids (the segregation-of-duties check of PRD §3.7). The shared
constants are the canonical form; the per-instance builders exist so a test
can pin a specific X-User-ID (e.g. making the submitting Promoter and the
verifying SettlementAccountant share one X-User-ID).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "tour_manager_headers": build_user_headers("test-tour-manager-1", "TourManager"),
    "promoter_headers": build_user_headers("test-promoter-1", "Promoter"),
    "venue_rep_headers": build_user_headers("test-venue-rep-1", "VenueRep"),
    "settlement_accountant_headers": build_user_headers("test-accountant-1",
                                                        "SettlementAccountant"),
    "any_headers": build_user_headers("test-any-1", "Any"),
}


def make_tour_manager_headers(user_id: str) -> dict:
    """TourManager headers with a specific X-User-ID (opaque role, PRD §2.1)."""
    return build_user_headers(user_id, "TourManager")


def make_promoter_headers(user_id: str) -> dict:
    """Promoter headers with a specific X-User-ID (opaque role, PRD §2.1)."""
    return build_user_headers(user_id, "Promoter")


def make_venue_rep_headers(user_id: str) -> dict:
    """VenueRep headers with a specific X-User-ID (opaque role, PRD §2.1)."""
    return build_user_headers(user_id, "VenueRep")


def make_settlement_accountant_headers(user_id: str) -> dict:
    """SettlementAccountant headers with a specific X-User-ID (opaque role, PRD §2.1)."""
    return build_user_headers(user_id, "SettlementAccountant")
