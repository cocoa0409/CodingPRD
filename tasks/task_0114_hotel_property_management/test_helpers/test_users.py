"""Pre-built role headers for every role in the PRD.

RevenueManager, FrontDeskAgent, and NightAuditor are opaque roles: X-User-ID is an
opaque operator identifier the server never matches to an entity (PRD §2.1), so the
shared constants below are the canonical form for those roles.

Guest is entity_backed: X-User-ID must equal the acting Guest's id (PRD §2.1). Use the
per-instance builder make_guest_headers(guest_id) whenever a call is ownership-gated.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "revenue_manager_headers": build_user_headers("rm-test-1", "RevenueManager"),
    "front_desk_headers": build_user_headers("fda-test-1", "FrontDeskAgent"),
    "night_auditor_headers": build_user_headers("na-test-1", "NightAuditor"),
    # Guest shared constant: a fallback for non-ownership / negative tests only.
    "guest_headers": build_user_headers("guest-test-1", "Guest"),
}


def make_guest_headers(guest_id: str) -> dict:
    """For Guest (entity_backed:Guest). Pass the actual Guest.id as user_id whenever
    the call is ownership-gated (create own reservation, cancel own, read own)."""
    return build_user_headers(guest_id, "Guest")
