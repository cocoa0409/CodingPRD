"""Pre-built role headers for every role in the PRD (§2.1).

Shared constants are safe only for CashOperationsAdmin (opaque identity) and for
tests whose outcome does not depend on the caller owning the subject resource.

Every entity-backed role (VaultCustodian, FedCoordinator, AtmAnalyst,
ComplianceOfficer backed by StaffMember; CarrierDispatcher backed by Carrier)
MUST use the per-instance builder with the real entity id whenever the call is
site-scoped or ownership-gated.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and non-ownership tests only.
TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "CashOperationsAdmin"),
    # Fallbacks for non-ownership contexts only (e.g., permission checks where
    # authentication must fail, or reads that are not site-scoped assertions).
    "custodian_headers": build_user_headers("test-custodian-1", "VaultCustodian"),
    "fed_coordinator_headers": build_user_headers("test-coordinator-1", "FedCoordinator"),
    "atm_analyst_headers": build_user_headers("test-analyst-1", "AtmAnalyst"),
    "compliance_officer_headers": build_user_headers("test-compliance-1", "ComplianceOfficer"),
    "carrier_dispatcher_headers": build_user_headers("test-carrier-1", "CarrierDispatcher"),
}


def make_custodian_headers(user_id: str) -> dict:
    """For VaultCustodian (entity-backed by StaffMember). Pass the acting staff id."""
    return build_user_headers(user_id, "VaultCustodian")


def make_fed_coordinator_headers(user_id: str) -> dict:
    """For FedCoordinator (entity-backed by StaffMember). Pass the acting staff id."""
    return build_user_headers(user_id, "FedCoordinator")


def make_atm_analyst_headers(user_id: str) -> dict:
    """For AtmAnalyst (entity-backed by StaffMember). Pass the acting staff id."""
    return build_user_headers(user_id, "AtmAnalyst")


def make_compliance_officer_headers(user_id: str) -> dict:
    """For ComplianceOfficer (entity-backed by StaffMember). Pass the acting staff id."""
    return build_user_headers(user_id, "ComplianceOfficer")


def make_carrier_dispatcher_headers(carrier_id: str) -> dict:
    """For CarrierDispatcher (entity-backed by Carrier). Pass the acting carrier id."""
    return build_user_headers(carrier_id, "CarrierDispatcher")
