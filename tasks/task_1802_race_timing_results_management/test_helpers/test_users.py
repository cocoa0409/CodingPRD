"""Pre-built role headers for every role in the PRD.

All six roles are opaque identities (PRD §2.1): X-User-ID is never compared
against any entity's id. It IS compared against recorded operator ids for the
segregation-of-duties rules (PRD §2.9), so the per-instance builders exist to
thread specific user ids (e.g. the director who locked timing vs. the officer
who certifies).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — canonical caller for each role when the specific user id
# does not matter (no SoD comparison involved).
TEST_USERS = {
    "race_director_headers": build_user_headers("director-1", "RaceDirector"),
    "timing_operator_headers": build_user_headers("operator-1", "TimingOperator"),
    "registration_clerk_headers": build_user_headers("clerk-1", "RegistrationClerk"),
    "race_official_headers": build_user_headers("official-1", "RaceOfficial"),
    "certification_officer_headers": build_user_headers("cert-1", "CertificationOfficer"),
    "spectator_headers": build_user_headers("spectator-1", "Spectator"),
}


def make_race_director_headers(user_id: str = "director-1") -> dict:
    """RaceDirector headers; pass a specific user_id when lock-timing's
    locked_by_user_id matters to a later segregation-of-duties check."""
    return build_user_headers(user_id, "RaceDirector")


def make_timing_operator_headers(user_id: str = "operator-1") -> dict:
    return build_user_headers(user_id, "TimingOperator")


def make_registration_clerk_headers(user_id: str = "clerk-1") -> dict:
    """RegistrationClerk headers; the protest filer's id is recorded as
    filed_by_user_id and constrains who may resolve the protest (PRD §2.9)."""
    return build_user_headers(user_id, "RegistrationClerk")


def make_race_official_headers(user_id: str = "official-1") -> dict:
    """RaceOfficial headers; protest resolution requires this id to differ
    from the protest's filed_by_user_id (PRD §2.9)."""
    return build_user_headers(user_id, "RaceOfficial")


def make_certification_officer_headers(user_id: str = "cert-1") -> dict:
    """CertificationOfficer headers; certification requires this id to differ
    from the race's locked_by_user_id (PRD §2.9)."""
    return build_user_headers(user_id, "CertificationOfficer")


def make_spectator_headers(user_id: str = "spectator-1") -> dict:
    return build_user_headers(user_id, "Spectator")
