"""Pre-built role headers for every role in the PRD (§2.1).

CenterAdmin and SchedulingClerk are opaque operator identities: their
X-User-ID is not compared to any persisted entity, so a shared constant is the
canonical form (PRD §2.1).

Nurse, Technologist, and Radiologist are entity-backed by a Staff record: when
acting under those roles, X-User-ID is the id of the acting Staff member, and
ownership checks (e.g. exam.technologist_id, exam.radiologist_id,
report.radiologist_id) compare the stored FK to X-User-ID (PRD §2.1). For any
ownership-gated call, pass the actual Staff id via the make_*_headers builders;
the shared constants are safe ONLY for tests that do not exercise ownership
(e.g. 403 RBAC checks, 401 missing-header checks).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — shared constant is canonical.
    "center_admin_headers": build_user_headers("test-center-admin-1", "CenterAdmin"),
    "scheduling_clerk_headers": build_user_headers("test-scheduling-clerk-1", "SchedulingClerk"),
    # Entity-backed roles — shared constant is a fallback for non-ownership tests only.
    "nurse_headers": build_user_headers("test-nurse-1", "Nurse"),
    "technologist_headers": build_user_headers("test-technologist-1", "Technologist"),
    "radiologist_headers": build_user_headers("test-radiologist-1", "Radiologist"),
}


# ─── Per-instance builders — required for entity_backed:Staff roles ───

def make_nurse_headers(staff_id: str) -> dict:
    """For Nurse (entity_backed:Staff). Pass the acting nurse Staff.id."""
    return build_user_headers(staff_id, "Nurse")


def make_technologist_headers(staff_id: str) -> dict:
    """For Technologist (entity_backed:Staff). Pass the acting technologist
    Staff.id whenever the call is ownership-gated (check-in, acquisition,
    series capture/finalize must come from exam.technologist_id)."""
    return build_user_headers(staff_id, "Technologist")


def make_radiologist_headers(staff_id: str) -> dict:
    """For Radiologist (entity_backed:Staff). Pass the acting radiologist
    Staff.id whenever the call is ownership-gated (claim-read, sign-off,
    finalize, addendum, critical-result acknowledge)."""
    return build_user_headers(staff_id, "Radiologist")
