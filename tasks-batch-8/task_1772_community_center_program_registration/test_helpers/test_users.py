"""Pre-built role headers for every role in PRD §2.1.

HouseholdManager (entity-backed by Household) and Instructor (entity-backed by
Instructor) must be built per-acting-entity with make_household_manager_headers
/ make_instructor_headers whenever the call is ownership-gated (any
HouseholdManager write against its own household's resources; contract
accept/decline and attendance marking for Instructor). The shared constants
for those two roles are fallbacks for negative RBAC probes only.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # opaque roles — canonical shared form (PRD §2.1)
    "program_coordinator_headers": build_user_headers("pc-1", "ProgramCoordinator"),
    "front_desk_headers": build_user_headers("fd-1", "FrontDeskStaff"),
    "finance_officer_headers": build_user_headers("fo-1", "FinanceOfficer"),
    "scholarship_reviewer_headers": build_user_headers("rev-1", "ScholarshipReviewer"),
    # entity_backed:Household — fallback for non-ownership probes only
    "household_manager_headers": build_user_headers("hm-orphan-1", "HouseholdManager"),
    # entity_backed:Instructor — fallback for non-ownership probes only
    "instructor_headers": build_user_headers("ins-orphan-1", "Instructor"),
}


def make_household_manager_headers(household_id: str) -> dict:
    """HouseholdManager is entity-backed by Household: pass the acting
    household's server-minted id whenever the call is ownership-gated."""
    return build_user_headers(household_id, "HouseholdManager")


def make_instructor_headers(instructor_id: str) -> dict:
    """Instructor is entity-backed by Instructor: pass the acting instructor's
    id for contract accept/decline and attendance marking."""
    return build_user_headers(instructor_id, "Instructor")


def make_scholarship_reviewer_headers(user_id: str) -> dict:
    """ScholarshipReviewer identity is opaque but recorded as reviewed_by /
    decided_by; use distinct ids to satisfy segregation of duties (PRD §3.5)."""
    return build_user_headers(user_id, "ScholarshipReviewer")
