"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Canonical operator ids. Segregation-of-duties checks compare these ids,
# so each controlled role gets a distinct default id (PRD §2.8).
ADMIN_USER = "adm-1"
BU_USER = "bu-1"
MOBILITY_APPROVER_USER = "ma-9"
PAYROLL_USER = "ps-1"
FINANCE_USER = "fc-1"
VENDOR_COORDINATOR_USER = "vc-1"
TAX_VENDOR_USER = "tv-1"

TEST_USERS = {
    # Opaque roles: shared constants are the canonical form.
    "admin_headers": build_user_headers(ADMIN_USER, "MobilityAdmin"),
    "bu_approver_headers": build_user_headers(BU_USER, "BusinessUnitApprover"),
    "mobility_approver_headers": build_user_headers(MOBILITY_APPROVER_USER, "MobilityApprover"),
    "payroll_headers": build_user_headers(PAYROLL_USER, "PayrollSpecialist"),
    "finance_headers": build_user_headers(FINANCE_USER, "FinanceController"),
    "vendor_coordinator_headers": build_user_headers(VENDOR_COORDINATOR_USER, "VendorCoordinator"),
    "tax_vendor_headers": build_user_headers(TAX_VENDOR_USER, "TaxVendor"),
    # entity_backed role: fallback for non-ownership reads only.
    "assignee_headers": build_user_headers("test-assignee-1", "Assignee"),
    "any_headers": build_user_headers("test-any-1", "Any"),
}


def make_admin_headers(user_id: str = ADMIN_USER) -> dict:
    return build_user_headers(user_id, "MobilityAdmin")


def make_bu_approver_headers(user_id: str = BU_USER) -> dict:
    return build_user_headers(user_id, "BusinessUnitApprover")


def make_mobility_approver_headers(user_id: str = MOBILITY_APPROVER_USER) -> dict:
    return build_user_headers(user_id, "MobilityApprover")


def make_payroll_headers(user_id: str = PAYROLL_USER) -> dict:
    return build_user_headers(user_id, "PayrollSpecialist")


def make_finance_headers(user_id: str = FINANCE_USER) -> dict:
    return build_user_headers(user_id, "FinanceController")


def make_vendor_coordinator_headers(user_id: str = VENDOR_COORDINATOR_USER) -> dict:
    return build_user_headers(user_id, "VendorCoordinator")


def make_tax_vendor_headers(user_id: str = TAX_VENDOR_USER) -> dict:
    return build_user_headers(user_id, "TaxVendor")


def make_assignee_headers(user_id: str) -> dict:
    """For Assignee (entity_backed:Employee). Pass the actual Employee.id as
    user_id whenever the call is ownership-gated (settlement dispute, PRD §3.8)."""
    return build_user_headers(user_id, "Assignee")
