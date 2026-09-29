"""Pre-built request headers for every role the PRD recognises.

Two of the seven roles are backed by persisted entities (PRD §2.1): `Athlete`
carries the acting Athlete row's `id` in `X-User-ID`, and `SportOfficial`
carries the acting Personnel row's `id`.  Any ownership-gated call therefore
MUST be made with the per-instance builder below, passing the real row id.

The remaining five roles are opaque operator identifiers that the server never
compares to a row id, so the shared constants are the canonical form for them.
"""
from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ADMIN_USER_ID,
    REGISTRATION_OFFICER_USER_ID,
    MEDICAL_DIRECTOR_USER_ID,
    RECORDS_RATIFIER_USER_ID,
    SPONSOR_LIAISON_USER_ID,
)

TEST_USERS = {
    # Opaque roles — shared constants are the canonical form.
    "games_admin_headers": build_user_headers(ADMIN_USER_ID, "GamesAdmin"),
    "registration_officer_headers": build_user_headers(
        REGISTRATION_OFFICER_USER_ID, "RegistrationOfficer"
    ),
    "medical_director_headers": build_user_headers(
        MEDICAL_DIRECTOR_USER_ID, "MedicalDirector"
    ),
    "records_ratifier_headers": build_user_headers(
        RECORDS_RATIFIER_USER_ID, "RecordsRatifier"
    ),
    "sponsor_liaison_headers": build_user_headers(
        SPONSOR_LIAISON_USER_ID, "SponsorLiaison"
    ),
    # Entity-backed roles — these shared constants are a fallback ONLY for
    # tests that never reach an ownership check (401/403-by-role, 400 on a bad
    # payload, 404 on a missing row).  Ownership-gated calls must use the
    # per-instance builders below.
    "athlete_headers": build_user_headers("test-athlete-not-a-row", "Athlete"),
    "sport_official_headers": build_user_headers("test-official-not-a-row", "SportOfficial"),
}


def make_games_admin_headers(user_id: str) -> dict:
    """GamesAdmin acting under a specific operator identifier."""
    return build_user_headers(user_id, "GamesAdmin")


def make_registration_officer_headers(user_id: str) -> dict:
    """RegistrationOfficer acting under a specific operator identifier.

    Distinct identifiers matter for the segregation-of-duties rule, which
    compares a ratifier against the `verified_by_user_id` a verifier wrote.
    """
    return build_user_headers(user_id, "RegistrationOfficer")


def make_medical_director_headers(user_id: str) -> dict:
    """MedicalDirector acting under a specific operator identifier."""
    return build_user_headers(user_id, "MedicalDirector")


def make_records_ratifier_headers(user_id: str) -> dict:
    """RecordsRatifier acting under a specific operator identifier."""
    return build_user_headers(user_id, "RecordsRatifier")


def make_sponsor_liaison_headers(user_id: str) -> dict:
    """SponsorLiaison acting under a specific operator identifier."""
    return build_user_headers(user_id, "SponsorLiaison")


def make_athlete_headers(athlete_id: str) -> dict:
    """Athlete acting on their own registration: pass the real Athlete row id."""
    return build_user_headers(athlete_id, "Athlete")


def make_sport_official_headers(personnel_id: str) -> dict:
    """SportOfficial acting as themselves: pass the real Personnel row id."""
    return build_user_headers(personnel_id, "SportOfficial")
