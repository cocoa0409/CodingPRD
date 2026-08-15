"""Pre-built role headers for every role in the PRD (§2.1).

Opaque roles (URNurse, PayerReviewer, CaseManager, AppealsCoordinator,
URDirector): the server does not compare X-User-ID to any entity id, so the
shared constants are canonical.

Entity-backed roles (AttendingPhysician, PhysicianAdvisor): X-User-ID is the
id of the acting Physician (PRD §2.1). Any ownership-gated call (peer-to-peer
schedule/reschedule/cancel, CC44 concurrence) or segregation-of-duties-gated
call (advisor review, CC44 committee review) MUST build headers with the
actual Physician.id via make_attending_headers / make_advisor_headers. The
shared constants for those two roles are fallbacks for non-ownership tests
only (e.g., RBAC denial checks).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — canonical shared form.
    "ur_nurse_headers": build_user_headers("test-ur-nurse-1", "URNurse"),
    "payer_reviewer_headers": build_user_headers("test-payer-reviewer-1", "PayerReviewer"),
    "case_manager_headers": build_user_headers("test-case-manager-1", "CaseManager"),
    "appeals_coordinator_headers": build_user_headers("test-appeals-coord-1", "AppealsCoordinator"),
    "ur_director_headers": build_user_headers("test-ur-director-1", "URDirector"),
    # Entity-backed roles — fallback for non-ownership tests only.
    "attending_headers": build_user_headers("test-attending-1", "AttendingPhysician"),
    "advisor_headers": build_user_headers("test-advisor-1", "PhysicianAdvisor"),
}


def make_ur_nurse_headers(user_id: str = "test-ur-nurse-1") -> dict:
    """URNurse is opaque; any identifier works."""
    return build_user_headers(user_id, "URNurse")


def make_payer_reviewer_headers(user_id: str = "test-payer-reviewer-1") -> dict:
    """PayerReviewer is opaque; any identifier works."""
    return build_user_headers(user_id, "PayerReviewer")


def make_case_manager_headers(user_id: str = "test-case-manager-1") -> dict:
    """CaseManager is opaque; any identifier works."""
    return build_user_headers(user_id, "CaseManager")


def make_appeals_coordinator_headers(user_id: str = "test-appeals-coord-1") -> dict:
    """AppealsCoordinator is opaque; any identifier works."""
    return build_user_headers(user_id, "AppealsCoordinator")


def make_ur_director_headers(user_id: str = "test-ur-director-1") -> dict:
    """URDirector is opaque; any identifier works."""
    return build_user_headers(user_id, "URDirector")


def make_attending_headers(user_id: str) -> dict:
    """AttendingPhysician is entity-backed (PRD §2.1): pass the actual
    Physician.id of the case's attending whenever the call is
    ownership-gated (peer-to-peer schedule/reschedule/cancel, CC44
    concurrence)."""
    return build_user_headers(user_id, "AttendingPhysician")


def make_advisor_headers(user_id: str) -> dict:
    """PhysicianAdvisor is entity-backed (PRD §2.1): pass the actual
    Physician.id of the acting advisor whenever the call is
    segregation-of-duties-gated (advisor review, CC44 committee review,
    peer-to-peer completion)."""
    return build_user_headers(user_id, "PhysicianAdvisor")
