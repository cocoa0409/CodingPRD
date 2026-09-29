"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants.  Safe for the three opaque operator roles, and for tests
# that never exercise an ownership or identity-resolution check.
TEST_USERS = {
    "admin_headers": build_user_headers("op-admin-1", "HRComplianceAdmin"),
    "author_headers": build_user_headers("op-author-1", "PolicyAuthor"),
    "localizer_headers": build_user_headers("op-localizer-1", "LocalizationSpecialist"),
    # Entity-backed roles: these shared constants resolve to no persisted row,
    # so they are only appropriate where ERR_ACTOR_IDENTITY_UNKNOWN is expected
    # or where the endpoint is reached before identity resolution.
    "counsel_headers": build_user_headers("unknown-counsel-1", "LegalCounsel"),
    "employee_headers": build_user_headers("unknown-employee-1", "Employee"),
    "manager_headers": build_user_headers("unknown-manager-1", "PeopleManager"),
}


def make_admin_headers(user_id: str = "op-admin-1") -> dict:
    """HRComplianceAdmin — opaque operator identifier, never resolved."""
    return build_user_headers(user_id, "HRComplianceAdmin")


def make_author_headers(user_id: str = "op-author-1") -> dict:
    """PolicyAuthor — opaque operator identifier, recorded as owner_user_id."""
    return build_user_headers(user_id, "PolicyAuthor")


def make_localizer_headers(user_id: str = "op-localizer-1") -> dict:
    """LocalizationSpecialist — opaque operator identifier, never resolved."""
    return build_user_headers(user_id, "LocalizationSpecialist")


def make_counsel_headers(legal_reviewer_id: str) -> dict:
    """LegalCounsel: X-User-ID is the id of the acting LegalReviewer."""
    return build_user_headers(legal_reviewer_id, "LegalCounsel")


def make_employee_headers(employee_id: str) -> dict:
    """Employee: X-User-ID is the id of the acting Employee."""
    return build_user_headers(employee_id, "Employee")


def make_manager_headers(employee_id: str) -> dict:
    """PeopleManager: X-User-ID is the id of the acting (manager) Employee."""
    return build_user_headers(employee_id, "PeopleManager")


ALL_ROLES = [
    "HRComplianceAdmin",
    "PolicyAuthor",
    "LegalCounsel",
    "LocalizationSpecialist",
    "Employee",
    "PeopleManager",
]
