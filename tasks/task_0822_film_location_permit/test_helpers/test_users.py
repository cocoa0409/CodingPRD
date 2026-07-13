"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the opaque coordinator role, and for tests that do not
# exercise resource ownership (e.g. 401/403/404 checks). The entity-backed roles carry
# placeholder ids here; ownership-gated calls MUST use the per-instance builders below.
TEST_USERS = {
    "coordinator_headers": build_user_headers("coordinator-1", "FilmOfficeCoordinator"),
    "production_company_headers": build_user_headers("test-pc-1", "ProductionCompany"),
    "department_reviewer_headers": build_user_headers("test-dept-1", "DepartmentReviewer"),
    "field_officer_headers": build_user_headers("test-officer-1", "FieldOfficer"),
}

# Headers with no authentication material, for ERR_UNAUTHENTICATED tests.
NO_AUTH_HEADERS: dict = {}


def make_coordinator_headers(user_id: str = "coordinator-1") -> dict:
    """FilmOfficeCoordinator identity is opaque; any operator id is accepted."""
    return build_user_headers(user_id, "FilmOfficeCoordinator")


def make_production_company_headers(user_id: str) -> dict:
    """ProductionCompany is entity_backed:ProductionCompany. Pass the ProductionCompany.id
    so ownership checks (resource.production_company_id == X-User-ID) succeed."""
    return build_user_headers(user_id, "ProductionCompany")


def make_department_reviewer_headers(department_id: str) -> dict:
    """DepartmentReviewer is entity_backed:Department. Pass the Department.id so a reviewer
    may decide only its own department's review (review.department_id == X-User-ID)."""
    return build_user_headers(department_id, "DepartmentReviewer")


def make_field_officer_headers(officer_id: str) -> dict:
    """FieldOfficer is entity_backed:Officer. Pass the Officer.id as X-User-ID."""
    return build_user_headers(officer_id, "FieldOfficer")
