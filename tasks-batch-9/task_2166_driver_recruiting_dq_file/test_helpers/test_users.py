"""Pre-built role headers for every role in the PRD.

Operator roles carry an opaque ``X-User-ID`` that the server records but never
resolves to a row.  The ``Applicant`` role's ``X-User-ID`` is the driver
applicant record's own ``id``, so ownership-gated calls must use the
per-instance builder below.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "recruiter_headers": build_user_headers("rec-001", "Recruiter"),
    "der_headers": build_user_headers("der-200", "DER"),
    "safety_director_headers": build_user_headers("sd-300", "SafetyDirector"),
    "compliance_auditor_headers": build_user_headers("aud-900", "ComplianceAuditor"),
    "school_coordinator_headers": build_user_headers("sch-100", "SchoolCoordinator"),
    # Applicant identity is entity-backed; this shared constant is only safe for
    # calls that are not ownership-gated (reads, 401/403/404 probes).
    "applicant_headers": build_user_headers("applicant-placeholder", "Applicant"),
}


def make_recruiter_headers(user_id: str) -> dict:
    """Recruiter headers under a specific operator id (recorded as recruiter_user_id)."""
    return build_user_headers(user_id, "Recruiter")


def make_der_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "DER")


def make_safety_director_headers(user_id: str) -> dict:
    """SafetyDirector headers under a specific operator id (e.g. a road-test examiner)."""
    return build_user_headers(user_id, "SafetyDirector")


def make_compliance_auditor_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ComplianceAuditor")


def make_school_coordinator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SchoolCoordinator")


def make_applicant_headers(applicant_id: str) -> dict:
    """Applicant headers. Pass the DriverApplicant's own id — every ownership
    check compares the targeted resource's applicant reference to X-User-ID."""
    return build_user_headers(applicant_id, "Applicant")
