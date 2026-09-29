"""Pre-built role headers for every role in the PRD (§2.1).

Six roles exist and these exact spellings are the only accepted values:
PerformanceDirector, Coach, MedicalProvider, FrontDesk, Athlete, Guardian.

`Coach` is backed by a `StaffMember` row (its `X-User-ID` must equal a real
`StaffMember.id`), while `Athlete` and `Guardian` are backed by an `Athlete` row
(a Guardian's `X-User-ID` is the minor athlete's own id).  Every ownership-gated
call for those roles MUST use the per-instance builders below, never the shared
constants.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the roles whose identity is opaque, and for tests
# that do not exercise ownership (missing-resource, bad-payload, listing).
TEST_USERS = {
    "performance_director_headers": build_user_headers("pd-1", "PerformanceDirector"),
    "medical_provider_headers": build_user_headers("mp-1", "MedicalProvider"),
    "front_desk_headers": build_user_headers("fd-1", "FrontDesk"),
    # Fallbacks for entity-backed roles: only for non-ownership assertions.
    "coach_headers": build_user_headers("coach-unresolvable-1", "Coach"),
    "athlete_headers": build_user_headers("athlete-unresolvable-1", "Athlete"),
    "guardian_headers": build_user_headers("guardian-unresolvable-1", "Guardian"),
}

# A second medical-provider identity, for the segregation-of-duties rules of §2.11
# where the acting principal must differ from an earlier one.
SECOND_MEDICAL_PROVIDER_ID = "mp-2"


def make_coach_headers(staff_member_id: str) -> dict:
    """Headers for a `Coach`.  Pass the real `StaffMember.id`: the server copies
    this `X-User-ID` into `administered_by_staff_id` and resolves it against the
    staff roster."""
    return build_user_headers(staff_member_id, "Coach")


def make_athlete_headers(athlete_id: str) -> dict:
    """Headers for an `Athlete`.  Pass the real `Athlete.id` — ownership scoping
    compares this `X-User-ID` against the addressed athlete."""
    return build_user_headers(athlete_id, "Athlete")


def make_guardian_headers(athlete_id: str) -> dict:
    """Headers for a `Guardian`.  Pass the minor athlete's own `id`."""
    return build_user_headers(athlete_id, "Guardian")


def make_medical_provider_headers(user_id: str) -> dict:
    """Headers for a `MedicalProvider` with an explicit acting identity."""
    return build_user_headers(user_id, "MedicalProvider")


def make_performance_director_headers(user_id: str) -> dict:
    """Headers for a `PerformanceDirector` with an explicit acting identity."""
    return build_user_headers(user_id, "PerformanceDirector")


def make_front_desk_headers(user_id: str) -> dict:
    """Headers for a `FrontDesk` operator with an explicit acting identity."""
    return build_user_headers(user_id, "FrontDesk")
