"""Canonical actors and their auth headers.

All seven roles carry opaque identity: the API never compares X-User-ID to an
entity's own id, so a single stable user id per role is enough. Segregation of
duties is the one place where the concrete id matters, so a few extra ids of the
same role are provided for author-versus-decider pairings.
"""

from prd_bench_local_runner.testing import build_user_headers

ROLE_PROGRAM_ADMIN = "ProgramAdmin"
ROLE_COMPLIANCE_ANALYST = "ComplianceAnalyst"
ROLE_CLASSIFICATION_REVIEWER = "ClassificationReviewer"
ROLE_COMPENSATION_MANAGER = "CompensationManager"
ROLE_EMPLOYEE_RELATIONS_LEAD = "EmployeeRelationsLead"
ROLE_LEGAL_COUNSEL = "LegalCounsel"
ROLE_AUDITOR = "Auditor"

PROGRAM_ADMIN_ID = "pa-1"
COMPLIANCE_ANALYST_ID = "ca-1"
CLASSIFICATION_REVIEWER_ID = "cr-1"
COMPENSATION_MANAGER_ID = "cm-1"
EMPLOYEE_RELATIONS_LEAD_ID = "er-1"
LEGAL_COUNSEL_ID = "lc-1"
LEGAL_COUNSEL_SECOND_ID = "lc-7"
AUDITOR_ID = "aud-1"

# One human who holds two hats: used to construct self-review situations.
DUAL_HAT_ID = "dual-1"

TEST_USERS = {
    "program_admin": {"id": PROGRAM_ADMIN_ID, "role": ROLE_PROGRAM_ADMIN},
    "compliance_analyst": {"id": COMPLIANCE_ANALYST_ID, "role": ROLE_COMPLIANCE_ANALYST},
    "classification_reviewer": {
        "id": CLASSIFICATION_REVIEWER_ID,
        "role": ROLE_CLASSIFICATION_REVIEWER,
    },
    "compensation_manager": {
        "id": COMPENSATION_MANAGER_ID,
        "role": ROLE_COMPENSATION_MANAGER,
    },
    "employee_relations_lead": {
        "id": EMPLOYEE_RELATIONS_LEAD_ID,
        "role": ROLE_EMPLOYEE_RELATIONS_LEAD,
    },
    "legal_counsel": {"id": LEGAL_COUNSEL_ID, "role": ROLE_LEGAL_COUNSEL},
    "auditor": {"id": AUDITOR_ID, "role": ROLE_AUDITOR},
}

PROGRAM_ADMIN_HEADERS = build_user_headers(PROGRAM_ADMIN_ID, ROLE_PROGRAM_ADMIN)
COMPLIANCE_ANALYST_HEADERS = build_user_headers(
    COMPLIANCE_ANALYST_ID, ROLE_COMPLIANCE_ANALYST
)
CLASSIFICATION_REVIEWER_HEADERS = build_user_headers(
    CLASSIFICATION_REVIEWER_ID, ROLE_CLASSIFICATION_REVIEWER
)
COMPENSATION_MANAGER_HEADERS = build_user_headers(
    COMPENSATION_MANAGER_ID, ROLE_COMPENSATION_MANAGER
)
EMPLOYEE_RELATIONS_LEAD_HEADERS = build_user_headers(
    EMPLOYEE_RELATIONS_LEAD_ID, ROLE_EMPLOYEE_RELATIONS_LEAD
)
LEGAL_COUNSEL_HEADERS = build_user_headers(LEGAL_COUNSEL_ID, ROLE_LEGAL_COUNSEL)
LEGAL_COUNSEL_SECOND_HEADERS = build_user_headers(
    LEGAL_COUNSEL_SECOND_ID, ROLE_LEGAL_COUNSEL
)
AUDITOR_HEADERS = build_user_headers(AUDITOR_ID, ROLE_AUDITOR)

# The same person acting under each of the two hats they hold.
DUAL_HAT_ANALYST_HEADERS = build_user_headers(DUAL_HAT_ID, ROLE_COMPLIANCE_ANALYST)
DUAL_HAT_REVIEWER_HEADERS = build_user_headers(
    DUAL_HAT_ID, ROLE_CLASSIFICATION_REVIEWER
)

# Header dicts that deliberately omit or blank the user context.
NO_USER_ID_HEADERS = {
    "X-User-Role": ROLE_PROGRAM_ADMIN,
    "Content-Type": "application/json",
}
EMPTY_USER_ID_HEADERS = {
    "X-User-ID": "",
    "X-User-Role": ROLE_PROGRAM_ADMIN,
    "Content-Type": "application/json",
}
NO_ROLE_HEADERS = {
    "X-User-ID": PROGRAM_ADMIN_ID,
    "Content-Type": "application/json",
}


def headers_for(user_id: str, role: str) -> dict:
    """Build auth headers for an arbitrary user id / role pairing."""
    return build_user_headers(user_id, role)
