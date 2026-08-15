"""Pre-built role headers for every role in the PRD.

Identity semantics (PRD 2.1): only the Researcher role is entity-backed —
its X-User-ID must be the id of the acting Researcher record whenever the
call is ownership-gated. All other roles use opaque operator ids; shared
constants are canonical for them, with per-instance builders provided so
segregation-of-duties and ticket-ownership tests can pin exact user ids.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    "registrar_headers": build_user_headers("registrar-shared-1", "Registrar"),
    "archivist_headers": build_user_headers("archivist-shared-1", "Archivist"),
    "reading_room_staff_headers": build_user_headers("rrs-shared-1", "ReadingRoomStaff"),
    "board_officer_headers": build_user_headers("board-shared-1", "BoardOfficer"),
    "volunteer_coordinator_headers": build_user_headers("coord-shared-1", "VolunteerCoordinator"),
    "volunteer_headers": build_user_headers("vol-shared-1", "Volunteer"),
    # entity_backed:Researcher — fallback for non-ownership calls only.
    "researcher_headers": build_user_headers("researcher-shared-1", "Researcher"),
    "system_admin_headers": build_user_headers("sysadmin-shared-1", "SystemAdmin"),
}


def make_registrar_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Registrar")


def make_archivist_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Archivist")


def make_reading_room_staff_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ReadingRoomStaff")


def make_board_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "BoardOfficer")


def make_volunteer_coordinator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "VolunteerCoordinator")


def make_volunteer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Volunteer")


def make_researcher_headers(user_id: str) -> dict:
    """For Researcher (entity_backed:Researcher). Pass the actual
    Researcher.id as user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Researcher")


def make_system_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SystemAdmin")
