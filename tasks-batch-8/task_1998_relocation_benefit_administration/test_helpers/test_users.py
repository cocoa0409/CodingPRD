"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership. For Employee/Vendor-role calls that ARE ownership-gated, use
# make_employee_headers(<employee_id>) / make_vendor_headers(<vendor_id>).
TEST_USERS = {
    # entity_backed roles: fallback only for non-ownership tests.
    "employee_headers": build_user_headers("test-employee-1", "Employee"),
    "vendor_headers": build_user_headers("test-vendor-1", "Vendor"),
    # opaque roles: shared constants are canonical.
    "coordinator_headers": build_user_headers("test-coordinator-1", "MobilityCoordinator"),
    "finance_headers": build_user_headers("test-finance-1", "FinanceSpecialist"),
    "program_manager_headers": build_user_headers("test-pm-1", "ProgramManager"),
}


def make_employee_headers(user_id: str) -> dict:
    """For Employee (entity_backed:Employee). Pass the actual Employee.id as
    user_id whenever the call is ownership-gated (claims, bookings, rating,
    signing, employee-filed exceptions/appeals)."""
    return build_user_headers(user_id, "Employee")


def make_vendor_headers(user_id: str) -> dict:
    """For Vendor (entity_backed:Vendor). Pass the actual Vendor.id as user_id
    whenever the call is ownership-gated (submit-estimate, mark-delivered,
    submit-invoice)."""
    return build_user_headers(user_id, "Vendor")


def make_coordinator_headers(user_id: str) -> dict:
    """Opaque MobilityCoordinator identity with a caller-chosen id."""
    return build_user_headers(user_id, "MobilityCoordinator")


def make_finance_headers(user_id: str) -> dict:
    """Opaque FinanceSpecialist identity with a caller-chosen id."""
    return build_user_headers(user_id, "FinanceSpecialist")


def make_program_manager_headers(user_id: str) -> dict:
    """Opaque ProgramManager identity with a caller-chosen id."""
    return build_user_headers(user_id, "ProgramManager")
