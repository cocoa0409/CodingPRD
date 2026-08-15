"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles (EHSAdmin, CarrierConsultant) and for
# tests that do not exercise ownership (400-on-bad-payload, 404-on-missing-id).
# Entity-backed roles (SafetyManager / Supervisor / Employee / CommitteeChair are
# backed by Employee; ContractorRep is backed by ContractorOrg) MUST use the
# per-instance builders below whenever a call is ownership- or
# segregation-of-duties-gated.
TEST_USERS = {
    "ehs_admin_headers": build_user_headers("test-ehs-admin-1", "EHSAdmin"),
    "safety_manager_headers": build_user_headers("test-safety-manager-1", "SafetyManager"),
    "supervisor_headers": build_user_headers("test-supervisor-1", "Supervisor"),
    "employee_headers": build_user_headers("test-employee-1", "Employee"),
    "committee_chair_headers": build_user_headers("test-committee-chair-1", "CommitteeChair"),
    "contractor_rep_headers": build_user_headers("test-contractor-rep-1", "ContractorRep"),
    "carrier_consultant_headers": build_user_headers("test-carrier-consultant-1", "CarrierConsultant"),
}


def make_ehs_admin_headers(user_id: str = "test-ehs-admin-1") -> dict:
    """EHSAdmin is opaque: the server does not compare X-User-ID to any entity."""
    return build_user_headers(user_id, "EHSAdmin")


def make_safety_manager_headers(employee_id: str) -> dict:
    """SafetyManager is entity-backed by Employee. Pass the acting Employee.id
    whenever segregation-of-duties or record fields are compared to it."""
    return build_user_headers(employee_id, "SafetyManager")


def make_supervisor_headers(employee_id: str) -> dict:
    """Supervisor is entity-backed by Employee. Pass the acting Employee.id
    whenever an ownership check (e.g. action-item completion) applies."""
    return build_user_headers(employee_id, "Supervisor")


def make_employee_headers(employee_id: str) -> dict:
    """Employee is entity-backed by Employee. Pass the acting Employee.id."""
    return build_user_headers(employee_id, "Employee")


def make_committee_chair_headers(employee_id: str) -> dict:
    """CommitteeChair is entity-backed by Employee. Pass the acting Employee.id
    whenever verification segregation-of-duties applies."""
    return build_user_headers(employee_id, "CommitteeChair")


def make_contractor_rep_headers(contractor_org_id: str) -> dict:
    """ContractorRep is entity-backed by ContractorOrg. Pass the actual
    ContractorOrg.id; submitting any other org is an ownership violation."""
    return build_user_headers(contractor_org_id, "ContractorRep")


def make_carrier_consultant_headers(user_id: str = "test-carrier-consultant-1") -> dict:
    """CarrierConsultant is opaque: the server records but never compares it."""
    return build_user_headers(user_id, "CarrierConsultant")
