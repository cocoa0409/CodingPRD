"""Pre-built role headers for every role in the PRD (§2.1).

`X-User-ID` is an opaque operator identifier for eight of the nine roles. For
`CertificationBody` it is the `id` of the acting listing body, so ownership-gated
calls MUST use `make_certification_body_headers(listing_body["id"])`.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

# Distinct operator identifiers, so that segregation-of-duties pairs never
# collide by accident.
DESIGN_ENGINEER_USER_ID = "eng-1"
SECOND_DESIGN_ENGINEER_USER_ID = "eng-2"
DESIGN_APPROVER_USER_ID = "appr-1"
SECOND_DESIGN_APPROVER_USER_ID = "appr-2"
TEST_LAB_TECHNICIAN_USER_ID = "lab-1"
PRODUCTION_SUPERVISOR_USER_ID = "prod-1"
COMPLIANCE_OFFICER_USER_ID = "compl-1"
CONSUMER_USER_ID = "cons-1"
SAFETY_DIRECTOR_USER_ID = "safety-1"
SYSTEM_OPERATOR_USER_ID = "sysop-1"

TEST_USERS: Dict[str, Dict[str, str]] = {
    "design_engineer_headers": build_user_headers(
        DESIGN_ENGINEER_USER_ID, "DesignEngineer"
    ),
    "second_design_engineer_headers": build_user_headers(
        SECOND_DESIGN_ENGINEER_USER_ID, "DesignEngineer"
    ),
    "design_approver_headers": build_user_headers(
        DESIGN_APPROVER_USER_ID, "DesignApprover"
    ),
    "second_design_approver_headers": build_user_headers(
        SECOND_DESIGN_APPROVER_USER_ID, "DesignApprover"
    ),
    "test_lab_technician_headers": build_user_headers(
        TEST_LAB_TECHNICIAN_USER_ID, "TestLabTechnician"
    ),
    "production_supervisor_headers": build_user_headers(
        PRODUCTION_SUPERVISOR_USER_ID, "ProductionSupervisor"
    ),
    "compliance_officer_headers": build_user_headers(
        COMPLIANCE_OFFICER_USER_ID, "ComplianceOfficer"
    ),
    "consumer_headers": build_user_headers(CONSUMER_USER_ID, "Consumer"),
    "safety_director_headers": build_user_headers(
        SAFETY_DIRECTOR_USER_ID, "SafetyDirector"
    ),
    "system_operator_headers": build_user_headers(
        SYSTEM_OPERATOR_USER_ID, "SystemOperator"
    ),
    # A CertificationBody header whose X-User-ID matches no persisted listing
    # body. Only for tests that do not exercise the ownership comparison.
    "certification_body_headers": build_user_headers(
        "unowned-body-1", "CertificationBody"
    ),
}


def make_certification_body_headers(listing_body_id: str) -> Dict[str, str]:
    """Headers for the `CertificationBody` role.

    Pass the acting listing body's `id`: the ownership check compares a listing
    record's `listing_body_id` to `X-User-ID`.
    """
    return build_user_headers(listing_body_id, "CertificationBody")


def make_design_engineer_headers(user_id: str) -> Dict[str, str]:
    """Headers for `DesignEngineer` under a caller-chosen operator identifier."""
    return build_user_headers(user_id, "DesignEngineer")


def make_design_approver_headers(user_id: str) -> Dict[str, str]:
    """Headers for `DesignApprover` under a caller-chosen operator identifier."""
    return build_user_headers(user_id, "DesignApprover")


def make_safety_director_headers(user_id: str) -> Dict[str, str]:
    """Headers for `SafetyDirector` under a caller-chosen operator identifier."""
    return build_user_headers(user_id, "SafetyDirector")


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Headers for any role/operator-identifier pair."""
    return build_user_headers(user_id, role)


# A request carrying neither X-User-ID nor X-User-Role.
NO_AUTH_HEADERS: Dict[str, str] = {"Content-Type": "application/json"}

# A request whose X-User-Role is not one of the nine recognized role names.
UNKNOWN_ROLE_HEADERS: Dict[str, str] = build_user_headers(
    "someone-1", "LadderInspector"
)
