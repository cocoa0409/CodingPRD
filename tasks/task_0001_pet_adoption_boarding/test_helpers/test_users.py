"""Pre-built role headers from scaffold Table 7 / PRD §2.1."""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "shelter_admin_headers": build_user_headers("user-shelter-admin-1", "ShelterAdmin"),
    "shelter_admin_2_headers": build_user_headers("user-shelter-admin-2", "ShelterAdmin"),
    "veterinarian_headers": build_user_headers("user-veterinarian-1", "Veterinarian"),
    "adoption_reviewer_headers": build_user_headers("user-reviewer-1", "AdoptionReviewer"),
    "adoption_reviewer_2_headers": build_user_headers("user-reviewer-2", "AdoptionReviewer"),
    "adoption_approver_headers": build_user_headers("user-approver-1", "AdoptionApprover"),
    "adoption_approver_2_headers": build_user_headers("user-approver-2", "AdoptionApprover"),
    "home_visit_inspector_headers": build_user_headers("user-inspector-1", "HomeVisitInspector"),
    "home_visit_inspector_2_headers": build_user_headers("user-inspector-2", "HomeVisitInspector"),
    "boarding_coordinator_headers": build_user_headers("user-coordinator-1", "BoardingCoordinator"),
    "finance_officer_headers": build_user_headers("user-finance-1", "FinanceOfficer"),
    "adopter_headers": build_user_headers("user-adopter-1", "Adopter"),
    "adopter_2_headers": build_user_headers("user-adopter-2", "Adopter"),
}


def make_inspector_headers(user_id: str) -> dict:
    """Create a HomeVisitInspector header with a specific user_id (for matching inspector_id)."""
    return build_user_headers(user_id, "HomeVisitInspector")


def make_reviewer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "AdoptionReviewer")


def make_approver_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "AdoptionApprover")


def make_adopter_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Adopter")
