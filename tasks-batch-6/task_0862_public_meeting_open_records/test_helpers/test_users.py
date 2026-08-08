"""Pre-built role headers for every role in the PRD (§2.1).

Two roles are entity-backed (Requester, BodyMember): their X-User-ID must be the
id of the persisted record for ownership / presiding checks — use the
make_*_headers(user_id) builders. The other roles are opaque operator ids.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that do NOT exercise
# ownership / presiding gating.
TEST_USERS = {
    "clerk_headers": build_user_headers("clerk-1", "Clerk"),
    "records_officer_headers": build_user_headers("officer-1", "RecordsOfficer"),
    "appeals_officer_headers": build_user_headers("appeals-1", "AppealsOfficer"),
    # entity-backed fallbacks (non-ownership tests only)
    "requester_headers": build_user_headers("test-requester-1", "Requester"),
    "body_member_headers": build_user_headers("test-member-1", "BodyMember"),
}

# Unauthenticated caller: no valid header pair (PRD §2.1 -> ERR_UNAUTHENTICATED).
ANON_HEADERS: dict = {}


# ---- opaque-role builders (let a test pin a specific operator id, e.g. SoD) --
def make_clerk_headers(user_id="clerk-1") -> dict:
    return build_user_headers(user_id, "Clerk")


def make_records_officer_headers(user_id="officer-1") -> dict:
    """RecordsOfficer id is recorded as determined_by_user_id (basis for SoD)."""
    return build_user_headers(user_id, "RecordsOfficer")


def make_appeals_officer_headers(user_id="appeals-1") -> dict:
    """AppealsOfficer id is compared against determined_by_user_id (SoD)."""
    return build_user_headers(user_id, "AppealsOfficer")


# ---- entity-backed builders (MUST pass the real entity id when gated) --------
def make_requester_headers(user_id: str) -> dict:
    """For Requester (entity_backed:Requester). Pass the actual Requester.id."""
    return build_user_headers(user_id, "Requester")


def make_body_member_headers(user_id: str) -> dict:
    """For BodyMember (entity_backed:BodyMember). Pass the actual BodyMember.id
    for presiding / mover / voter checks."""
    return build_user_headers(user_id, "BodyMember")
