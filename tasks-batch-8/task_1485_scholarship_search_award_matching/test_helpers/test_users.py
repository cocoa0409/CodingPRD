"""Pre-built role headers for every role in the PRD (§2.1).

Student and Donor are entity-backed roles: their X-User-ID must be the id of
the acting Student / Donor record. Fixtures MUST call the per-instance
builders with the real entity id for ownership-gated calls; the shared
constants are only for non-ownership tests (400/404 probes, denials).
ScholarshipCoordinator, CommitteeReviewer, FinancialAidOfficer and
PlatformAdmin are opaque roles: any stable user id works, but money-moving
scenarios rely on distinct ids (see the canonical ids in constants.py).
"""
from prd_bench_local_runner.testing import build_user_headers

from .constants import ADMIN_USER_ID

TEST_USERS = {
    # Opaque roles: shared constant is the canonical form.
    "coordinator_headers": build_user_headers("test-coord-1", "ScholarshipCoordinator"),
    "reviewer_headers": build_user_headers("test-rev-1", "CommitteeReviewer"),
    "fao_headers": build_user_headers("test-fao-1", "FinancialAidOfficer"),
    "admin_headers": build_user_headers(ADMIN_USER_ID, "PlatformAdmin"),
    # Entity-backed roles: fallback for non-ownership tests only.
    "student_headers": build_user_headers("test-student-1", "Student"),
    "donor_headers": build_user_headers("test-donor-1", "Donor"),
}


def make_student_headers(user_id: str) -> dict:
    """Student is entity-backed: pass the actual Student.id as user_id
    whenever the call is ownership-gated (submit, accept, letter submit...)."""
    return build_user_headers(user_id, "Student")


def make_donor_headers(user_id: str) -> dict:
    """Donor is entity-backed: pass the actual Donor.id as user_id whenever
    the call is ownership-gated (report acknowledge)."""
    return build_user_headers(user_id, "Donor")


def make_coordinator_headers(user_id: str = "coord_1") -> dict:
    """ScholarshipCoordinator is opaque; the id may be recorded (e.g. as
    sent_by_user_id or created_by_user_id) but is never entity-compared."""
    return build_user_headers(user_id, "ScholarshipCoordinator")


def make_reviewer_headers(user_id: str) -> dict:
    """CommitteeReviewer is opaque; the id is recorded as reviewer_user_id
    and compared on score submit/recall ownership checks."""
    return build_user_headers(user_id, "CommitteeReviewer")


def make_fao_headers(user_id: str) -> dict:
    """FinancialAidOfficer is opaque; the id may be recorded (e.g. as
    approved_by_user_id) but is never entity-compared."""
    return build_user_headers(user_id, "FinancialAidOfficer")


def make_admin_headers(user_id: str = ADMIN_USER_ID) -> dict:
    """PlatformAdmin is opaque; it authenticates the logical-clock and
    daily-operations-run capabilities only."""
    return build_user_headers(user_id, "PlatformAdmin")
