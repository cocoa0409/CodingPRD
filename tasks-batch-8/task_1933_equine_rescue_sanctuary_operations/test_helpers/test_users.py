"""Pre-built role headers for every role in the PRD (§2.1).

Entity-backed roles (Veterinarian, Farrier, Adopter, Sponsor, Volunteer) MUST be
built via the per-instance make_*_headers(user_id) builders with the real entity
id whenever the call is ownership- or identity-gated. The shared constants are
safe only for opaque roles or for identity-establishing registration calls.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants for opaque roles (X-User-ID never compared to an entity id).
TEST_USERS = {
    "director_headers": build_user_headers("director-1", "SanctuaryDirector"),
    "intake_headers": build_user_headers("intake-1", "IntakeCoordinator"),
    "officer_1_headers": build_user_headers("officer-1", "AdoptionOfficer"),
    "officer_2_headers": build_user_headers("officer-2", "AdoptionOfficer"),
    "barn_manager_headers": build_user_headers("barn-manager-1", "BarnManager"),
    "vol_coordinator_headers": build_user_headers(
        "vol-coordinator-1", "VolunteerCoordinator"
    ),
    # Registration-call identities (X-User-ID not resolved on these endpoints).
    "adopter_registration_headers": build_user_headers("new-adopter-1", "Adopter"),
    "sponsor_registration_headers": build_user_headers("new-sponsor-1", "Sponsor"),
    "volunteer_registration_headers": build_user_headers("new-volunteer-1", "Volunteer"),
}


# Per-instance builders — required for every entity_backed role.
def make_veterinarian_headers(practitioner_id: str) -> dict:
    """Veterinarian identity must be the id of a Practitioner with specialty VETERINARIAN."""
    return build_user_headers(practitioner_id, "Veterinarian")


def make_farrier_headers(practitioner_id: str) -> dict:
    """Farrier identity must be the id of a Practitioner with specialty FARRIER."""
    return build_user_headers(practitioner_id, "Farrier")


def make_adopter_headers(adopter_id: str) -> dict:
    """Adopter identity must equal the caller's own Adopter id."""
    return build_user_headers(adopter_id, "Adopter")


def make_sponsor_headers(sponsor_id: str) -> dict:
    """Sponsor identity must equal the caller's own Sponsor id."""
    return build_user_headers(sponsor_id, "Sponsor")


def make_volunteer_headers(volunteer_id: str) -> dict:
    """Volunteer identity must equal the caller's own Volunteer id."""
    return build_user_headers(volunteer_id, "Volunteer")
