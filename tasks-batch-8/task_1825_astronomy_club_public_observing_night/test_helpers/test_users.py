"""Pre-built role headers for every role in the PRD.

ClubOfficer, EventCoordinator, and EquipmentChair are opaque identities:
X-User-ID is not tied to any persisted entity. Member is entity-backed by
Member (X-User-ID is the acting Member's id); ownership-gated calls MUST use
the per-instance builder with the real entity id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership (400-on-bad-payload, 404-on-missing-resource, wrong-role checks).
TEST_USERS = {
    "club_officer_headers": build_user_headers("test-officer-1", "ClubOfficer"),
    "event_coordinator_headers": build_user_headers("test-coordinator-1",
                                                    "EventCoordinator"),
    "equipment_chair_headers": build_user_headers("test-chair-1",
                                                  "EquipmentChair"),
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "member_headers": build_user_headers("test-member-1", "Member"),
}


def make_club_officer_headers(user_id: str = "test-officer-1") -> dict:
    return build_user_headers(user_id, "ClubOfficer")


def make_event_coordinator_headers(user_id: str = "test-coordinator-1") -> dict:
    return build_user_headers(user_id, "EventCoordinator")


def make_equipment_chair_headers(user_id: str = "test-chair-1") -> dict:
    return build_user_headers(user_id, "EquipmentChair")


def make_member_headers(member_id: str) -> dict:
    """For Member (entity_backed:Member). Pass the acting Member.id whenever
    the call is ownership-gated (loans, bookings, assignments, payments,
    readings, resignation)."""
    return build_user_headers(member_id, "Member")
