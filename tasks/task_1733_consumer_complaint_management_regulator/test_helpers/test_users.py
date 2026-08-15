"""Pre-built role headers for every role in the PRD (§2.1).

All seven roles carry opaque identity semantics: `X-User-ID` is an operator
identifier never matched against an entity `id`. Shared constants are the
canonical form; the per-role builders exist for tests that must thread a
specific operator id (e.g. segregation-of-duties comparisons against
`owner_user_id`, `drafted_by_user_id`, or `reviewer_user_id`).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "intake_specialist_headers": build_user_headers("user_intake_default", "IntakeSpecialist"),
    "case_handler_headers": build_user_headers("user_handler_default", "CaseHandler"),
    "qa_reviewer_headers": build_user_headers("user_qa_default", "QAReviewer"),
    "remediation_approver_headers": build_user_headers("user_approver_default", "RemediationApprover"),
    "executive_reviewer_headers": build_user_headers("user_exec_default", "ExecutiveReviewer"),
    "complaint_manager_headers": build_user_headers("user_manager_default", "ComplaintManager"),
    "auditor_headers": build_user_headers("user_auditor_default", "Auditor"),
}


def make_intake_specialist_headers(user_id: str) -> dict:
    """IntakeSpecialist headers with a specific operator id."""
    return build_user_headers(user_id, "IntakeSpecialist")


def make_case_handler_headers(user_id: str) -> dict:
    """CaseHandler headers with a specific operator id."""
    return build_user_headers(user_id, "CaseHandler")


def make_qa_reviewer_headers(user_id: str) -> dict:
    """QAReviewer headers with a specific operator id."""
    return build_user_headers(user_id, "QAReviewer")


def make_remediation_approver_headers(user_id: str) -> dict:
    """RemediationApprover headers with a specific operator id."""
    return build_user_headers(user_id, "RemediationApprover")


def make_executive_reviewer_headers(user_id: str) -> dict:
    """ExecutiveReviewer headers with a specific operator id."""
    return build_user_headers(user_id, "ExecutiveReviewer")


def make_complaint_manager_headers(user_id: str) -> dict:
    """ComplaintManager headers with a specific operator id."""
    return build_user_headers(user_id, "ComplaintManager")


def make_auditor_headers(user_id: str) -> dict:
    """Auditor headers with a specific operator id."""
    return build_user_headers(user_id, "Auditor")


_ROLE_BUILDERS = {
    "IntakeSpecialist": make_intake_specialist_headers,
    "CaseHandler": make_case_handler_headers,
    "QAReviewer": make_qa_reviewer_headers,
    "RemediationApprover": make_remediation_approver_headers,
    "ExecutiveReviewer": make_executive_reviewer_headers,
    "ComplaintManager": make_complaint_manager_headers,
    "Auditor": make_auditor_headers,
}


def headers_for(role: str, user_id: str) -> dict:
    """Build auth headers for any declared role name and operator id."""
    return _ROLE_BUILDERS[role](user_id)


def manager_authority_headers(base_headers: dict) -> dict:
    """Attach the X-Manager-Authority: true header required for over-cap approvals."""
    merged = dict(base_headers)
    merged["X-Manager-Authority"] = "true"
    return merged
