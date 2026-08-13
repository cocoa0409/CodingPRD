"""Pre-built role headers for every role in the PRD (§2.1).

SystemAdmin and ParentGuardian identities are opaque: the server never
compares their X-User-ID to an entity id (for guardians it compares against
the athlete's `guardian_user_id` string), so shared constants are safe for
them — though `make_parent_guardian_headers` is provided for readability at
call sites that exercise guardian ownership.

Staff-backed roles (AthleticTrainer, AthleticDirector, SchoolNurse,
Physician, TeamCoach) compare X-User-ID against Staff ids in ownership and
segregation checks, so any call whose semantics depend on the caller's
identity MUST be built with the per-instance `make_*_headers(staff["id"])`.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque operator identity — never compared to an entity id (PRD §2.1).
    "system_admin_headers": build_user_headers("sysadmin-1", "SystemAdmin"),
    # Fallback constants for staff-backed roles: safe only for calls whose
    # success does not depend on the caller owning the subject resource
    # (bad-payload 400s, 404 probes, reads).
    "athletic_trainer_headers": build_user_headers(
        "trainer-fallback-1", "AthleticTrainer"),
    "athletic_director_headers": build_user_headers(
        "director-fallback-1", "AthleticDirector"),
    "school_nurse_headers": build_user_headers(
        "nurse-fallback-1", "SchoolNurse"),
    "physician_headers": build_user_headers(
        "physician-fallback-1", "Physician"),
    "team_coach_headers": build_user_headers(
        "coach-fallback-1", "TeamCoach"),
    "parent_guardian_headers": build_user_headers(
        "guardian-fallback-1", "ParentGuardian"),
}


def make_system_admin_headers(user_id: str = "sysadmin-1") -> dict:
    """SystemAdmin (opaque identity)."""
    return build_user_headers(user_id, "SystemAdmin")


def make_athletic_trainer_headers(user_id: str) -> dict:
    """AthleticTrainer (backed by a Staff record). Pass the Staff id whenever
    the call is ownership-gated (coverage self-service) or identity-stamped."""
    return build_user_headers(user_id, "AthleticTrainer")


def make_athletic_director_headers(user_id: str) -> dict:
    """AthleticDirector (backed by a Staff record). Pass the Staff id whenever
    segregation-of-duties or identity stamping matters."""
    return build_user_headers(user_id, "AthleticDirector")


def make_school_nurse_headers(user_id: str) -> dict:
    """SchoolNurse (backed by a Staff record). Pass the Staff id whenever
    physical verification segregation matters."""
    return build_user_headers(user_id, "SchoolNurse")


def make_physician_headers(user_id: str) -> dict:
    """Physician (backed by a Staff record). Pass the Staff id whenever the
    call is ownership-gated (referral completion) or authority-gated."""
    return build_user_headers(user_id, "Physician")


def make_team_coach_headers(user_id: str) -> dict:
    """TeamCoach (backed by a Staff record)."""
    return build_user_headers(user_id, "TeamCoach")


def make_parent_guardian_headers(guardian_user_id: str) -> dict:
    """ParentGuardian: X-User-ID is the athlete's guardian_user_id string."""
    return build_user_headers(guardian_user_id, "ParentGuardian")
