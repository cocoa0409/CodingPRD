"""Pre-built role headers for every role in the Research Funding API.

PRD §2.1 explicitly states that for every role, X-User-ID is an opaque operator
identifier and is NOT compared to any persisted entity row's id. Ownership
checks instead compare X-User-ID to a foreign-key field captured earlier on
the resource (e.g., Project.principal_investigator_id).

This means:
  * Every role's identity is opaque — shared TEST_USERS constants are safe for
    most calls.
  * BUT: when an operation is owner-gated (e.g., POST /projects/{id}/submit,
    pi-approve, begin-closing, rework, closing-audit submit/resubmit), the
    acting X-User-ID MUST equal Project.principal_investigator_id. Tests must
    use make_principal_investigator_headers(<the pi_id used at project create>)
    — which is the same id that was passed in the create-project payload.

For convenience, build_user_headers(user_id, role) is the canonical builder.
"""
from prd_bench_local_runner.testing import build_user_headers


# A shared default PI identifier used by fixtures for non-conflict tests.
DEFAULT_PI_ID = "pi-default-001"


# --- Shared constants ---
# Per PRD §2.1, identity is opaque for all roles, so shared constants are safe
# for any operation that does NOT match X-User-ID against a previously-stored
# foreign-key field. For owner-gated operations on a project, callers must use
# make_principal_investigator_headers(<the pi id of the project>).
TEST_USERS = {
    # PI-shared fallback (the same id is used by fixtures' default PI by convention).
    "pi_headers": build_user_headers(DEFAULT_PI_ID, "PrincipalInvestigator"),

    # Other roles are pure opaque — shared constants are canonical.
    "dept_headers": build_user_headers("dept-approver-001", "DepartmentApprover"),
    "dept_headers_alt": build_user_headers("dept-approver-002", "DepartmentApprover"),
    "finance_headers": build_user_headers("finance-officer-001", "FinanceOfficer"),
    "finance_headers_alt": build_user_headers("finance-officer-002", "FinanceOfficer"),
    "research_admin_headers": build_user_headers("research-admin-001", "ResearchAdmin"),
    "audit_officer_headers": build_user_headers("audit-officer-001", "AuditOfficer"),
    "peer_reviewer_headers": build_user_headers("peer-reviewer-001", "PeerReviewer"),
    "peer_reviewer_2_headers": build_user_headers("peer-reviewer-002", "PeerReviewer"),
    "peer_reviewer_3_headers": build_user_headers("peer-reviewer-003", "PeerReviewer"),
    "peer_reviewer_4_headers": build_user_headers("peer-reviewer-004", "PeerReviewer"),
    "test_driver_headers": build_user_headers("test-driver-001", "TestDriver"),
}


# --- Per-instance builders ---
# Even though identity is opaque per PRD §2.1, owner-gated operations compare
# X-User-ID to Project.principal_investigator_id (the value that was passed
# into the create-project payload). The builder below mints a header pair
# whose X-User-ID equals a caller-supplied pi_id — pass the SAME id that was
# used as principal_investigator_id at project creation.

def make_principal_investigator_headers(pi_id: str) -> dict:
    """Build PI headers whose X-User-ID equals the supplied pi_id.

    Pass this the SAME identifier that was used as principal_investigator_id at
    project creation. PRD §2.1: 'Ownership checks ... compare X-User-ID to a
    foreign-key field captured earlier on the resource: the
    principal_investigator_id on a project is the canonical example'.
    """
    return build_user_headers(pi_id, "PrincipalInvestigator")


def make_dept_approver_headers(user_id: str = "dept-approver-001") -> dict:
    return build_user_headers(user_id, "DepartmentApprover")


def make_finance_officer_headers(user_id: str = "finance-officer-001") -> dict:
    return build_user_headers(user_id, "FinanceOfficer")


def make_research_admin_headers(user_id: str = "research-admin-001") -> dict:
    return build_user_headers(user_id, "ResearchAdmin")


def make_audit_officer_headers(user_id: str = "audit-officer-001") -> dict:
    return build_user_headers(user_id, "AuditOfficer")


def make_peer_reviewer_headers(user_id: str) -> dict:
    """Build PeerReviewer headers — PRD §3.1 records X-User-ID as reviewer_id."""
    return build_user_headers(user_id, "PeerReviewer")


def make_test_driver_headers(user_id: str = "test-driver-001") -> dict:
    return build_user_headers(user_id, "TestDriver")
