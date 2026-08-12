"""Pre-built role headers for every role in the PRD (§2.1).

Coordinator, IntakeVolunteer and SafetyOfficer are opaque roles: X-User-ID is an
operator identifier not tied to any persisted entity, so shared constants are
canonical. Fixer is entity-backed: X-User-ID IS a FixerProfile id, so any
ownership-gated call MUST use make_fixer_headers(fixer["id"]) with the real id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — shared constants are the canonical form.
    "coordinator_headers": build_user_headers("coordinator-1", "Coordinator"),
    "intake_volunteer_headers": build_user_headers("intake-volunteer-1", "IntakeVolunteer"),
    "safety_officer_headers": build_user_headers("safety-officer-1", "SafetyOfficer"),
    # Entity-backed role fallback: ONLY for calls whose outcome cannot depend on
    # the caller owning the resource (e.g. not-found / role-gated checks).
    "fixer_headers": build_user_headers("fixer-unbound", "Fixer"),
}


def make_fixer_headers(user_id: str) -> dict:
    """For the entity-backed Fixer role. Pass the actual FixerProfile.id as
    user_id whenever the call is ownership-gated (own shifts, assigned items)."""
    return build_user_headers(user_id, "Fixer")


def make_safety_officer_headers(user_id: str) -> dict:
    """SafetyOfficer with a specific opaque id (needed for segregation-of-duties
    scenarios where resolver and reporter must differ)."""
    return build_user_headers(user_id, "SafetyOfficer")


def make_coordinator_headers(user_id: str) -> dict:
    """Coordinator with a specific opaque id."""
    return build_user_headers(user_id, "Coordinator")


def make_intake_volunteer_headers(user_id: str) -> dict:
    """IntakeVolunteer with a specific opaque id."""
    return build_user_headers(user_id, "IntakeVolunteer")
