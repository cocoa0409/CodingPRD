"""Pre-built role headers for every role in the PRD.

Four roles are opaque operator identities (PlatformAdmin, Recruiter,
CredentialingSpecialist, PayrollAdmin): their X-User-ID is a free operator
string. Two roles are entity-backed (Clinician -> Clinician.id,
FacilityManager -> Facility.id): ownership-gated calls MUST use the per-instance
builder with the real entity id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — opaque roles use these directly; entity-backed roles only
# use theirs for tests that do NOT exercise ownership.
TEST_USERS = {
    "platform_admin_headers": build_user_headers("platform-admin-1", "PlatformAdmin"),
    "recruiter_headers": build_user_headers("recruiter-1", "Recruiter"),
    "credentialing_specialist_headers": build_user_headers("cs-1", "CredentialingSpecialist"),
    "credentialing_specialist_2_headers": build_user_headers("cs-2", "CredentialingSpecialist"),
    "payroll_admin_headers": build_user_headers("pa-1", "PayrollAdmin"),
    "payroll_admin_2_headers": build_user_headers("pa-2", "PayrollAdmin"),
    "payroll_admin_3_headers": build_user_headers("pa-3", "PayrollAdmin"),
    # entity-backed roles: shared fallback for non-ownership tests only.
    "clinician_headers": build_user_headers("clinician-generic-1", "Clinician"),
    "facility_manager_headers": build_user_headers("facility-generic-1", "FacilityManager"),
}


def make_platform_admin_headers(user_id="platform-admin-1"):
    return build_user_headers(user_id, "PlatformAdmin")


def make_recruiter_headers(user_id="recruiter-1"):
    return build_user_headers(user_id, "Recruiter")


def make_credentialing_specialist_headers(user_id="cs-1"):
    return build_user_headers(user_id, "CredentialingSpecialist")


def make_payroll_admin_headers(user_id="pa-1"):
    return build_user_headers(user_id, "PayrollAdmin")


def make_clinician_headers(user_id):
    """For role Clinician (entity_backed:Clinician). Pass the acting Clinician.id
    as user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Clinician")


def make_facility_manager_headers(user_id):
    """For role FacilityManager (entity_backed:Facility). Pass the acting
    Facility.id as user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "FacilityManager")


def raw_headers(user_id=None, role=None):
    """Build a header dict with optionally missing auth headers, for
    authentication tests. Content-Type is always present."""
    h = {"Content-Type": "application/json"}
    if user_id is not None:
        h["X-User-ID"] = user_id
    if role is not None:
        h["X-User-Role"] = role
    return h
