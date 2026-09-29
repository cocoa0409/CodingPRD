"""Pre-built role headers for every role in the PRD (§2.1).

`ClubAdmin` is the club office: its `X-User-ID` is an opaque operator identifier
not tied to any persisted entity, so the shared constant is the canonical form.
The other six roles are entity-backed — `X-User-ID` is the `id` of the acting
`Member` record — so ownership-gated calls MUST use the per-instance builders.
"""

from prd_bench_local_runner.testing import build_user_headers

# Shared constants. Safe for the opaque ClubAdmin role, and for calls that never
# compare X-User-ID against a stored member reference (for example header-absence
# and role-authorisation checks).
TEST_USERS = {
    "club_admin_headers": build_user_headers("ops-club-admin-1", "ClubAdmin"),
    "member_headers": build_user_headers("test-member-1", "Member"),
    "coach_headers": build_user_headers("test-coach-1", "Coach"),
    "safety_officer_headers": build_user_headers("test-safety-officer-1", "SafetyOfficer"),
    "equipment_manager_headers": build_user_headers("test-equipment-manager-1", "EquipmentManager"),
    "race_official_headers": build_user_headers("test-race-official-1", "RaceOfficial"),
    "jury_chair_headers": build_user_headers("test-jury-chair-1", "JuryChair"),
}

CLUB_ADMIN_HEADERS = TEST_USERS["club_admin_headers"]


def make_club_admin_headers(user_id: str = "ops-club-admin-1") -> dict:
    """ClubAdmin acts under an opaque operator identifier."""
    return build_user_headers(user_id, "ClubAdmin")


def make_member_headers(member_id: str) -> dict:
    """For Member. Pass the acting Member's id."""
    return build_user_headers(member_id, "Member")


def make_coach_headers(member_id: str) -> dict:
    """For Coach. Pass the acting Member's id."""
    return build_user_headers(member_id, "Coach")


def make_safety_officer_headers(member_id: str) -> dict:
    """For SafetyOfficer. Pass the acting Member's id."""
    return build_user_headers(member_id, "SafetyOfficer")


def make_equipment_manager_headers(member_id: str) -> dict:
    """For EquipmentManager. Pass the acting Member's id."""
    return build_user_headers(member_id, "EquipmentManager")


def make_race_official_headers(member_id: str) -> dict:
    """For RaceOfficial. Pass the acting Member's id."""
    return build_user_headers(member_id, "RaceOfficial")


def make_jury_chair_headers(member_id: str) -> dict:
    """For JuryChair. Pass the acting Member's id."""
    return build_user_headers(member_id, "JuryChair")
