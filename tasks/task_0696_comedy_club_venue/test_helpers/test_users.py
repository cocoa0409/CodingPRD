"""Pre-built role headers for every role in the PRD.

Per §2.1: Booker, BoxOffice, FloorManager, and Patron carry an opaque X-User-ID
that the server never compares to an entity id. Performer is entity-backed:
X-User-ID must equal the acting Performer entity's id, and ownership checks on a
LineupSlot compare its performer_id to X-User-ID. The Patron identifier, though
opaque, is recorded in a reservation's patron_id and ownership-checked, so a
builder is provided to mint a Patron whose id matches a target reservation.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles, and for tests that don't exercise
# resource ownership (400/404/role-denial style).
TEST_USERS = {
    "booker_headers": build_user_headers("booker-1", "Booker"),
    "box_office_headers": build_user_headers("box-office-1", "BoxOffice"),
    "floor_manager_headers": build_user_headers("floor-manager-1", "FloorManager"),
    "patron_headers": build_user_headers("patron-1", "Patron"),
    # Opaque fallback Performer constant — used only for non-ownership tests.
    "performer_headers": build_user_headers("performer-1", "Performer"),
}


# Per-instance builders.
def make_booker_headers(user_id: str = "booker-1") -> dict:
    """Booker (opaque identity)."""
    return build_user_headers(user_id, "Booker")


def make_box_office_headers(user_id: str = "box-office-1") -> dict:
    """BoxOffice (opaque identity)."""
    return build_user_headers(user_id, "BoxOffice")


def make_floor_manager_headers(user_id: str = "floor-manager-1") -> dict:
    """FloorManager (opaque identity)."""
    return build_user_headers(user_id, "FloorManager")


def make_patron_headers(patron_id: str) -> dict:
    """Patron acting on their own reservation. Pass the reservation's patron_id
    so ownership checks (patron_id == X-User-ID) pass for owner-gated calls."""
    return build_user_headers(patron_id, "Patron")


def make_performer_headers(performer_id: str) -> dict:
    """Performer (entity_backed:Performer). Pass the actual Performer.id as
    performer_id whenever the call is ownership-gated (counter, own guest list)."""
    return build_user_headers(performer_id, "Performer")
