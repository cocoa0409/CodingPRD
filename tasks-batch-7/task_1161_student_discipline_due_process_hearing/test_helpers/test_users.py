"""Pre-built role headers for every role in the PRD (§2.1).

All five roles treat X-User-ID as an opaque operator identifier. Two comparison
duties still apply: a ParentGuardian's X-User-ID must equal the student's
guardian_id on guardian-scoped operations, and a HearingOfficer's X-User-ID must
equal the hearing's hearing_officer_id on rule/convene/decision. Use the
per-instance builders for those calls.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for calls whose success does not depend on the caller
# owning the subject resource (config writes, 400/404 probes, staff reads).
TEST_USERS = {
    "district_admin_headers": build_user_headers("da_1", "DistrictAdmin"),
    # The two canonical school-administrator identities: the referrer of a case
    # must never equal its classifier (segregation of duties, PRD §3.2).
    "school_referrer_headers": build_user_headers("admin_ref_1", "SchoolAdministrator"),
    "school_classifier_headers": build_user_headers("admin_adj_1", "SchoolAdministrator"),
    "hearing_officer_headers": build_user_headers("ho_1", "HearingOfficer"),
    "parent_guardian_headers": build_user_headers("g1", "ParentGuardian"),
    "student_services_headers": build_user_headers("ssd_1", "StudentServicesDirector"),
}


# Per-instance builders — required whenever the call is ownership-gated.

def make_district_admin_headers(user_id: str) -> dict:
    """DistrictAdmin (opaque identity)."""
    return build_user_headers(user_id, "DistrictAdmin")


def make_school_admin_headers(user_id: str) -> dict:
    """SchoolAdministrator (opaque identity; recorded as referrer_id /
    classified_by and compared during segregation-of-duties checks)."""
    return build_user_headers(user_id, "SchoolAdministrator")


def make_hearing_officer_headers(user_id: str) -> dict:
    """HearingOfficer. Pass the hearing's hearing_officer_id as user_id
    whenever calling rule/convene/decision (ownership-gated)."""
    return build_user_headers(user_id, "HearingOfficer")


def make_parent_guardian_headers(user_id: str) -> dict:
    """ParentGuardian. Pass the student's guardian_id as user_id whenever
    filing appeals / expungement requests or reading that student's records."""
    return build_user_headers(user_id, "ParentGuardian")


def make_student_services_headers(user_id: str) -> dict:
    """StudentServicesDirector (opaque identity)."""
    return build_user_headers(user_id, "StudentServicesDirector")
