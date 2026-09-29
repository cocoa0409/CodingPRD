"""Pre-built role headers for every role in the PRD (§2.1).

Five roles are operator desks whose `X-User-ID` is an opaque operator identifier
never compared to any entity id — the shared constants below are the canonical
form for them. Two roles are entity-backed: `CustomerRep` acts as a `Customer`
and `BargeMaster` acts as a `DeliveryAsset`, so ownership-gated calls must use
the per-instance builders with the real entity id.
"""

from prd_bench_local_runner.testing import build_user_headers

# Opaque operator identifiers used across the suite.
OPS_USER_ID = "ops-001"
COMPLIANCE_USER_ID = "co-001"
COMPLIANCE_USER_ID_ALT = "co-002"
SURVEYOR_USER_ID = "sv-001"
CREDIT_USER_ID = "cc-001"
LAB_USER_ID = "lt-001"


TEST_USERS = {
    # Opaque roles — the shared constant is the canonical form.
    "ops_coordinator_headers": build_user_headers(OPS_USER_ID, "OpsCoordinator"),
    "compliance_officer_headers": build_user_headers(COMPLIANCE_USER_ID, "ComplianceOfficer"),
    "surveyor_headers": build_user_headers(SURVEYOR_USER_ID, "Surveyor"),
    "credit_controller_headers": build_user_headers(CREDIT_USER_ID, "CreditController"),
    "lab_technician_headers": build_user_headers(LAB_USER_ID, "LabTechnician"),
    # Entity-backed roles — fallbacks for tests that never exercise ownership
    # (for example a 401/404 probe). Ownership-gated calls MUST use the builders.
    "customer_rep_headers": build_user_headers("test-customer-rep-1", "CustomerRep"),
    "barge_master_headers": build_user_headers("test-barge-master-1", "BargeMaster"),
}


def make_ops_coordinator_headers(user_id: str) -> dict:
    """For OpsCoordinator, whose X-User-ID is an opaque operator identifier.
    Use a distinct id when segregation of duties is under test."""
    return build_user_headers(user_id, "OpsCoordinator")


def make_compliance_officer_headers(user_id: str) -> dict:
    """For ComplianceOfficer, whose X-User-ID is recorded as
    compliance_reviewer_user_id on the nomination it reviews."""
    return build_user_headers(user_id, "ComplianceOfficer")


def make_surveyor_headers(user_id: str) -> dict:
    """For Surveyor, whose X-User-ID is recorded as proposed_by_user_id on a
    remediation proposal."""
    return build_user_headers(user_id, "Surveyor")


def make_credit_controller_headers(user_id: str) -> dict:
    """For CreditController, whose X-User-ID is recorded as
    accepted_by_user_id when a remediation credit is booked."""
    return build_user_headers(user_id, "CreditController")


def make_lab_technician_headers(user_id: str) -> dict:
    """For LabTechnician, whose X-User-ID is recorded as analyzed_by_user_id."""
    return build_user_headers(user_id, "LabTechnician")


def make_customer_rep_headers(user_id: str) -> dict:
    """For CustomerRep: X-User-ID is the id of the acting Customer. Pass the
    real Customer id whenever the call is scope-gated."""
    return build_user_headers(user_id, "CustomerRep")


def make_barge_master_headers(user_id: str) -> dict:
    """For BargeMaster: X-User-ID is the id of the acting DeliveryAsset. Pass
    the real DeliveryAsset id whenever the call is assignment-gated."""
    return build_user_headers(user_id, "BargeMaster")


def make_headers(user_id: str, role: str) -> dict:
    """Generic escape hatch for parametrized role tests."""
    return build_user_headers(user_id, role)


__all__ = [
    "TEST_USERS",
    "OPS_USER_ID",
    "COMPLIANCE_USER_ID",
    "COMPLIANCE_USER_ID_ALT",
    "SURVEYOR_USER_ID",
    "CREDIT_USER_ID",
    "LAB_USER_ID",
    "make_ops_coordinator_headers",
    "make_compliance_officer_headers",
    "make_surveyor_headers",
    "make_credit_controller_headers",
    "make_lab_technician_headers",
    "make_customer_rep_headers",
    "make_barge_master_headers",
    "make_headers",
]
