"""Pre-built role headers for every role in the PRD (§2.1).

Identity binding (PRD §2.1): for Member, DutyOfficer, Instructor and TowPilot
the X-User-ID is the id of the acting Member entity, so ownership-gated calls
MUST use the per-instance builders below with the real Member.id. ClubAdmin's
X-User-ID is an opaque operator identifier never compared to any entity id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for ClubAdmin (opaque identity) and for tests whose
# outcome does not depend on the caller owning the subject resource.
TEST_USERS = {
    "club_admin_headers": build_user_headers("test-club-admin-1", "ClubAdmin"),
    "member_headers": build_user_headers("test-member-1", "Member"),
    "duty_officer_headers": build_user_headers("test-duty-officer-1", "DutyOfficer"),
    "instructor_headers": build_user_headers("test-instructor-1", "Instructor"),
    "tow_pilot_headers": build_user_headers("test-tow-pilot-1", "TowPilot"),
}


def make_member_headers(user_id: str) -> dict:
    """Member is entity-backed: pass the actual Member.id as user_id whenever
    the call is ownership-gated (own reservations, own duty slots, own
    payments, own resignation)."""
    return build_user_headers(user_id, "Member")


def make_duty_officer_headers(user_id: str) -> dict:
    """DutyOfficer is entity-backed: pass a real Member.id as user_id."""
    return build_user_headers(user_id, "DutyOfficer")


def make_instructor_headers(user_id: str) -> dict:
    """Instructor is entity-backed: pass the instructor Member.id as user_id
    for availability and signoff ownership checks."""
    return build_user_headers(user_id, "Instructor")


def make_tow_pilot_headers(user_id: str) -> dict:
    """TowPilot is entity-backed: pass the tow-pilot Member.id as user_id."""
    return build_user_headers(user_id, "TowPilot")
