"""Operational dashboard aggregation and role-based access denials."""
import pytest
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    TEST_USERS, create_officer_payload,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]
SUPERVISOR = TEST_USERS["supervisor_headers"]


# ==========================================================================
# Corner: calculations
# ==========================================================================
def test_summary_on_empty_db_returns_zeros(api):
    """PRD 3.8: "It reports total_complaints as the count of all complaints
    regardless of status; open_cases as the count of cases whose status is OPEN
    or UNDER_INVESTIGATION; active_quarantine_holds as the count of holds whose
    status is ACTIVE; and total_outstanding_fines as the sum of fine_amount
    across all citations still in ISSUED, rounded half up to two decimal places.
    When nothing matches — including against an empty database — the three counts
    return as the integer 0 and the fines total returns as 0.00."

    Design: Corner/calculations/summary_empty_db_returns_zeros
    """
    data = validate_success(api.get_summary(SUPERVISOR))
    assert data["total_complaints"] == 0
    assert data["open_cases"] == 0
    assert data["active_quarantine_holds"] == 0
    assert data["total_outstanding_fines"] == pytest.approx(0.00, abs=0.001)


# ==========================================================================
# Corner: rbac
# ==========================================================================
def test_dispatcher_cannot_register_officer(api):
    """PRD 2.1: "When the headers are well-formed but the named role is not
    permitted to perform the requested operation, the request is rejected with
    ERR_UNAUTHORIZED." PRD 2.1: "A Supervisor performs administrative and
    override operations: registering officers and kennels ..."

    Design: Corner/rbac/dispatcher_cannot_create_officer
    """
    resp = api.create_officer(create_officer_payload(name="X", badge_number="XB"), DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
