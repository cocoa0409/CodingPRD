"""Pre-built operator headers for every role the PRD recognises."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants. Safe for the four administrative roles whose X-User-ID is an
# opaque operator identifier, and for tests on the three staff-backed roles that
# do not exercise an ownership or segregation check.
TEST_USERS = {
    "practice_admin_headers": build_user_headers("op-admin-1", "PracticeAdministrator"),
    "scheduling_coordinator_headers": build_user_headers(
        "op-scheduler-1", "SchedulingCoordinator"
    ),
    "benefits_specialist_headers": build_user_headers(
        "op-benefits-1", "BenefitsSpecialist"
    ),
    "inventory_manager_headers": build_user_headers("op-inventory-1", "InventoryManager"),
    # Staff-backed roles: these fallbacks never equal a real StaffMember id, so
    # they are only valid where no ownership comparison is performed.
    "surgeon_headers": build_user_headers("op-surgeon-1", "Surgeon"),
    "anesthesia_coordinator_headers": build_user_headers(
        "op-anesthesia-1", "AnesthesiaCoordinator"
    ),
    "quality_reviewer_headers": build_user_headers("op-quality-1", "QualityReviewer"),
}


def make_surgeon_headers(staff_id: str) -> dict:
    """Headers for a Surgeon. Pass the acting StaffMember's id: a surgeon may only
    move a case into recovery or complete it when X-User-ID equals that case's
    primary_surgeon_id."""
    return build_user_headers(staff_id, "Surgeon")


def make_anesthesia_coordinator_headers(staff_id: str) -> dict:
    """Headers for an AnesthesiaCoordinator. Pass the acting StaffMember's id:
    signing an evaluation requires X-User-ID to equal evaluator_staff_id."""
    return build_user_headers(staff_id, "AnesthesiaCoordinator")


def make_quality_reviewer_headers(staff_id: str) -> dict:
    """Headers for a QualityReviewer. Pass the acting StaffMember's id: signing off
    a morbidity review requires X-User-ID to equal the event's reviewer_staff_id."""
    return build_user_headers(staff_id, "QualityReviewer")


def make_practice_admin_headers(user_id: str = "op-admin-1") -> dict:
    return build_user_headers(user_id, "PracticeAdministrator")


def make_scheduling_coordinator_headers(user_id: str = "op-scheduler-1") -> dict:
    return build_user_headers(user_id, "SchedulingCoordinator")


def make_benefits_specialist_headers(user_id: str = "op-benefits-1") -> dict:
    return build_user_headers(user_id, "BenefitsSpecialist")


def make_inventory_manager_headers(user_id: str = "op-inventory-1") -> dict:
    return build_user_headers(user_id, "InventoryManager")


def headers_for_role(role: str, user_id: str = "op-generic-1") -> dict:
    """Headers for an arbitrary role spelling — used by role-matrix tests."""
    return build_user_headers(user_id, role)


ADMIN = TEST_USERS["practice_admin_headers"]
SCHEDULER = TEST_USERS["scheduling_coordinator_headers"]
BENEFITS = TEST_USERS["benefits_specialist_headers"]
INVENTORY = TEST_USERS["inventory_manager_headers"]
