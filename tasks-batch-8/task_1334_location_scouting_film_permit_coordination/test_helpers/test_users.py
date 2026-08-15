"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles (LocationManager, FilmOffice), and for
# tests that do not exercise ownership gating.
TEST_USERS = {
    # opaque role: shared constant is the canonical form.
    "location_manager_headers": build_user_headers("test-location-manager-1", "LocationManager"),
    # opaque role: shared constant is the canonical form.
    "film_office_headers": build_user_headers("test-film-office-1", "FilmOffice"),
    # entity_backed role (LocationOwner): fallback for non-ownership tests only.
    "owner_rep_headers": build_user_headers("test-owner-rep-1", "OwnerRep"),
}


# Per-instance builders — required for every entity_backed role.
def make_owner_rep_headers(user_id: str) -> dict:
    """For OwnerRep (entity_backed:LocationOwner). Pass the actual LocationOwner.id
    as user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "OwnerRep")


def make_location_manager_headers(user_id: str) -> dict:
    """For LocationManager (opaque identity — user_id is not entity-compared)."""
    return build_user_headers(user_id, "LocationManager")


def make_film_office_headers(user_id: str) -> dict:
    """For FilmOffice (opaque identity — user_id is not entity-compared)."""
    return build_user_headers(user_id, "FilmOffice")
