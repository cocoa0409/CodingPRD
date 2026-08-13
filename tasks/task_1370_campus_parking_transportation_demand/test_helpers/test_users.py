"""Pre-built role headers for every role in the PRD (PRD §2.1).

Commuter is entity-backed: its X-User-ID must be the id of the acting Patron
whenever the call is ownership-gated, so use make_commuter_headers(patron_id)
for those calls. The shared "commuter_headers" constant is only a fallback for
tests that never exercise ownership.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # entity_backed:Patron — fallback for non-ownership tests only
    "commuter_headers": build_user_headers("test-commuter-1", "Commuter"),
    # opaque operator identities
    "admin_headers": build_user_headers("test-admin-1", "ParkingAdmin"),
    "officer_headers": build_user_headers("off-1", "EnforcementOfficer"),
    "appeals_headers": build_user_headers("off-9", "AppealsOfficer"),
}


def make_commuter_headers(user_id: str) -> dict:
    """For Commuter (entity_backed: Patron). Pass the actual Patron.id as
    user_id whenever the call is ownership-gated (purchase/cancel, waitlist
    join/claim/withdraw, citation pay/appeal, incentive enroll/redeem)."""
    return build_user_headers(user_id, "Commuter")


def make_admin_headers(user_id: str = "test-admin-1") -> dict:
    """ParkingAdmin is opaque — any operator identifier works."""
    return build_user_headers(user_id, "ParkingAdmin")


def make_officer_headers(user_id: str) -> dict:
    """EnforcementOfficer is opaque; the id is recorded as issued_by_officer_id."""
    return build_user_headers(user_id, "EnforcementOfficer")


def make_appeals_headers(user_id: str) -> dict:
    """AppealsOfficer is opaque; the id is recorded as appeal_decided_by and
    must differ from the citation's issued_by_officer_id."""
    return build_user_headers(user_id, "AppealsOfficer")
