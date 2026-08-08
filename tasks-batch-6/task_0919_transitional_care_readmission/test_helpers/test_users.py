"""Pre-built role headers for every programme actor named in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants. Safe for the four roles whose X-User-ID is an opaque
# operator identifier, and for CareNavigator calls that never touch an
# ownership check (for example a 404 on an unknown resource).
TEST_USERS = {
    "program_admin_headers": build_user_headers("admin-1", "ProgramAdmin"),
    "intake_coordinator_headers": build_user_headers("intake-1", "IntakeCoordinator"),
    "clinician_headers": build_user_headers("clin-1", "Clinician"),
    "billing_specialist_headers": build_user_headers("bill-prep-1", "BillingSpecialist"),
    # CareNavigator is backed by a Navigator row; this constant never equals a
    # real navigator id, so ownership-gated calls must use the builder below.
    "care_navigator_headers": build_user_headers("nav-unowned", "CareNavigator"),
}


def make_program_admin_headers(user_id: str = "admin-1") -> dict:
    """ProgramAdmin acts under an opaque operator identifier."""
    return build_user_headers(user_id, "ProgramAdmin")


def make_intake_coordinator_headers(user_id: str = "intake-1") -> dict:
    """IntakeCoordinator acts under an opaque operator identifier."""
    return build_user_headers(user_id, "IntakeCoordinator")


def make_care_navigator_headers(navigator_id: str) -> dict:
    """For CareNavigator calls. Pass the real Navigator id: ownership checks on
    anything hanging off a care episode compare that episode's navigator_id to
    X-User-ID, and a handoff response compares it to to_navigator_id."""
    return build_user_headers(navigator_id, "CareNavigator")


def make_clinician_headers(user_id: str = "clin-1") -> dict:
    """Clinician acts under an opaque operator identifier recorded on the row."""
    return build_user_headers(user_id, "Clinician")


def make_billing_specialist_headers(user_id: str = "bill-prep-1") -> dict:
    """BillingSpecialist acts under an opaque operator identifier; the preparer
    and the submitter of a claim must be two different values."""
    return build_user_headers(user_id, "BillingSpecialist")


def make_headers(role: str, user_id: str) -> dict:
    """Generic builder used by role-matrix tests."""
    return build_user_headers(user_id, role)
