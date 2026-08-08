"""Pre-built role headers for every role in the PRD.

Opaque roles (PlatformAdmin, ComplianceOfficer, BillingAgent) carry an operator
identifier that is never compared to any entity id, so a shared constant is the
canonical form. The facility roles (FacilityScheduler, FacilityVerifier) are
entity_backed:Facility and the Clinician role is entity_backed:Clinician — for
ownership-gated calls their X-User-ID MUST be the real entity id, so use the
per-instance builders below.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — shared constants are the canonical form.
    "platform_admin_headers": build_user_headers("platform-admin-1", "PlatformAdmin"),
    "compliance_officer_headers": build_user_headers("compliance-officer-1", "ComplianceOfficer"),
    "billing_agent_headers": build_user_headers("biller-alpha", "BillingAgent"),
    "billing_agent_beta_headers": build_user_headers("biller-beta", "BillingAgent"),
    # entity_backed roles — shared constants are ONLY safe for non-ownership tests
    # (e.g. 400/404 checks). Ownership-gated calls must use the builders below.
    "facility_scheduler_headers": build_user_headers("facility-scheduler-1", "FacilityScheduler"),
    "facility_verifier_headers": build_user_headers("facility-verifier-1", "FacilityVerifier"),
    "clinician_headers": build_user_headers("clinician-1", "Clinician"),
}


# --------------------------------------------------------------------------- #
# Per-instance builders — mandatory for the entity_backed roles.
# --------------------------------------------------------------------------- #
def make_platform_admin_headers(user_id: str = "platform-admin-1") -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_compliance_officer_headers(user_id: str = "compliance-officer-1") -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")


def make_billing_agent_headers(user_id: str = "biller-alpha") -> dict:
    return build_user_headers(user_id, "BillingAgent")


def make_scheduler_headers(facility_id: str) -> dict:
    """For FacilityScheduler (entity_backed:Facility). Pass the Facility.id whenever
    the call is scoped to that facility."""
    return build_user_headers(facility_id, "FacilityScheduler")


def make_verifier_headers(facility_id: str) -> dict:
    """For FacilityVerifier (entity_backed:Facility). Pass the Facility.id whenever
    the call is scoped to that facility."""
    return build_user_headers(facility_id, "FacilityVerifier")


def make_clinician_headers(clinician_id: str) -> dict:
    """For Clinician (entity_backed:Clinician). Pass the Clinician.id whenever the
    call is ownership-gated."""
    return build_user_headers(clinician_id, "Clinician")
