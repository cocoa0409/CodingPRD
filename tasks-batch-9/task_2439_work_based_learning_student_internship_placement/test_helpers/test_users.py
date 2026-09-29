"""Pre-built role headers for every role the PRD defines.

`WblCoordinator`, `SafetyReviewer` and `ComplianceOfficer` are opaque operator
identities, so a shared constant is the canonical form for them. Several rules
compare one operator's `X-User-ID` against another's, so distinct coordinator
identities are provided for drafting, executing, approving and awarding.

`EmployerSupervisor` and `Student` are backed by real rows — the supervisor's
`id` and the student's `id` respectively — so any ownership-gated call MUST use
the per-instance builders below with the actual entity id.
"""

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# Distinct coordinator operators. Several transitions require the acting
# operator to differ from an operator recorded earlier on the record.
COORDINATOR_DRAFTER = "coord-drafter-1"
COORDINATOR_SIGNER = "coord-signer-2"
COORDINATOR_APPROVER = "coord-approver-3"
COORDINATOR_AWARDER = "coord-awarder-4"
SAFETY_REVIEWER_USER = "safety-reviewer-1"
COMPLIANCE_OFFICER_USER = "compliance-officer-1"


TEST_USERS = {
    # Opaque operator identities — the shared constant is the canonical form.
    "coordinator_headers": build_user_headers(
        COORDINATOR_DRAFTER, UserRole.WBL_COORDINATOR.value
    ),
    "coordinator_drafter_headers": build_user_headers(
        COORDINATOR_DRAFTER, UserRole.WBL_COORDINATOR.value
    ),
    "coordinator_signer_headers": build_user_headers(
        COORDINATOR_SIGNER, UserRole.WBL_COORDINATOR.value
    ),
    "coordinator_approver_headers": build_user_headers(
        COORDINATOR_APPROVER, UserRole.WBL_COORDINATOR.value
    ),
    "coordinator_awarder_headers": build_user_headers(
        COORDINATOR_AWARDER, UserRole.WBL_COORDINATOR.value
    ),
    "safety_reviewer_headers": build_user_headers(
        SAFETY_REVIEWER_USER, UserRole.SAFETY_REVIEWER.value
    ),
    "compliance_officer_headers": build_user_headers(
        COMPLIANCE_OFFICER_USER, UserRole.COMPLIANCE_OFFICER.value
    ),
    # Entity-backed roles: these shared constants are only safe for tests that
    # do not exercise ownership (role-rejection probes, 404 probes, 400 probes).
    "employer_supervisor_headers": build_user_headers(
        "unbound-supervisor-1", UserRole.EMPLOYER_SUPERVISOR.value
    ),
    "student_headers": build_user_headers("unbound-student-1", UserRole.STUDENT.value),
}


def make_coordinator_headers(user_id: str) -> dict:
    """For WblCoordinator (an opaque operator identity)."""
    return build_user_headers(user_id, UserRole.WBL_COORDINATOR.value)


def make_safety_reviewer_headers(user_id: str) -> dict:
    """For SafetyReviewer (an opaque operator identity)."""
    return build_user_headers(user_id, UserRole.SAFETY_REVIEWER.value)


def make_compliance_officer_headers(user_id: str) -> dict:
    """For ComplianceOfficer (an opaque operator identity)."""
    return build_user_headers(user_id, UserRole.COMPLIANCE_OFFICER.value)


def make_employer_supervisor_headers(supervisor_id: str) -> dict:
    """For EmployerSupervisor. Pass the supervisor row's `id` — the PRD makes
    that id the role's `X-User-ID`, and ownership checks compare against it."""
    return build_user_headers(supervisor_id, UserRole.EMPLOYER_SUPERVISOR.value)


def make_student_headers(student_id: str) -> dict:
    """For Student. Pass the student row's `id` whenever the call is
    ownership-gated (reflection submission, own-record reads)."""
    return build_user_headers(student_id, UserRole.STUDENT.value)
