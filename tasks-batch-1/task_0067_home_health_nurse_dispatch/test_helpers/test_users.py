"""Pre-built role headers for the Home Health Nurse Dispatch PRD (§2.1).

Five roles: IntakeCoordinator, Clinician, Scheduler, BillingManager,
ComplianceOfficer. Four of them carry an OPAQUE X-User-ID (never compared to any
entity) so a shared constant is the canonical form. The Clinician role binds
X-User-ID to the acting Clinician.id for ownership checks on visit
confirm/complete (§2.1), so clinician-owned calls MUST use make_clinician_headers
with the real clinician id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "intake_headers": build_user_headers("test-intake-1", "IntakeCoordinator"),
    "scheduler_headers": build_user_headers("test-scheduler-1", "Scheduler"),
    "billing_headers": build_user_headers("test-billing-1", "BillingManager"),
    "compliance_headers": build_user_headers("test-compliance-1", "ComplianceOfficer"),
    # Fallback only for non-ownership tests (e.g. 404/403/role checks). Never use
    # for confirm/complete where ownership is enforced.
    "clinician_headers": build_user_headers("test-clinician-1", "Clinician"),
}


def make_clinician_headers(clinician_id: str) -> dict:
    """For the Clinician role. Pass the real Clinician.id whenever the call is
    ownership-gated (visit confirm / complete / file mileage)."""
    return build_user_headers(clinician_id, "Clinician")
