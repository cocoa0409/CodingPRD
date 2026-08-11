"""Pre-built role headers for the five roles in PRD 2.1.

PRD 2.1: "When `X-User-Role` is `Instructor`, `X-User-ID` is the `id` of the
acting `Instructor` row" - so every ownership-gated Instructor call MUST use
`make_instructor_headers(instructor["id"])`. The four other roles carry an
opaque operator identifier that is never compared to any entity's `id`, so the
shared constants below are the canonical form for them.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque roles - the shared constant is the canonical form.
    "program_admin_headers": build_user_headers("ops-admin-1", "ProgramAdmin"),
    "volunteer_coordinator_headers": build_user_headers(
        "ops-vol-coord-1", "VolunteerCoordinator"
    ),
    "intake_coordinator_headers": build_user_headers(
        "ops-intake-1", "IntakeCoordinator"
    ),
    "billing_clerk_headers": build_user_headers("ops-billing-1", "BillingClerk"),
    # Instructor identity is entity-backed; this fallback is only safe for calls
    # that never compare X-User-ID to an instructor foreign key.
    "instructor_headers": build_user_headers("ops-instructor-1", "Instructor"),
}


def make_instructor_headers(instructor_id: str) -> Dict[str, str]:
    """Headers for the Instructor role, carrying a real Instructor row's id."""
    return build_user_headers(instructor_id, "Instructor")


def make_program_admin_headers(user_id: str = "ops-admin-1") -> Dict[str, str]:
    return build_user_headers(user_id, "ProgramAdmin")


def make_volunteer_coordinator_headers(
    user_id: str = "ops-vol-coord-1",
) -> Dict[str, str]:
    return build_user_headers(user_id, "VolunteerCoordinator")


def make_intake_coordinator_headers(user_id: str = "ops-intake-1") -> Dict[str, str]:
    return build_user_headers(user_id, "IntakeCoordinator")


def make_billing_clerk_headers(user_id: str = "ops-billing-1") -> Dict[str, str]:
    return build_user_headers(user_id, "BillingClerk")


def headers_without_role(user_id: str = "ops-intake-1") -> Dict[str, str]:
    """Headers carrying X-User-ID but no X-User-Role at all (PRD 2.7 rung 1)."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_with_unknown_role(
    user_id: str = "ops-intake-1", role: str = "BarnManager"
) -> Dict[str, str]:
    """Headers naming a role outside the five in PRD 2.1 (PRD 2.7 rung 2)."""
    return build_user_headers(user_id, role)
