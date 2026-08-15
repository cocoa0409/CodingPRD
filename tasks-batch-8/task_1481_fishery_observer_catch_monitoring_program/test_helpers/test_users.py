"""Pre-built role headers for every role in the PRD (§2.1).

Opaque roles (ProgramAdmin, ProgramCoordinator) use shared constants.
Entity-backed roles (Observer, Debriefer, VesselOperator, EMReviewer) MUST be
built per instance with the actual entity id via the make_*_headers builders
whenever the call is ownership-gated; the shared constants are only safe for
non-ownership tests (e.g. malformed-payload 400s or GETs).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — canonical shared form.
    "program_admin_headers": build_user_headers("admin-user-1", "ProgramAdmin"),
    "program_coordinator_headers": build_user_headers("coord-user-1", "ProgramCoordinator"),
    # Entity-backed roles — fallback for non-ownership tests ONLY.
    "observer_headers": build_user_headers("test-observer-1", "Observer"),
    "debriefer_headers": build_user_headers("test-debriefer-1", "Debriefer"),
    "vessel_operator_headers": build_user_headers("test-operator-1", "VesselOperator"),
    "em_reviewer_headers": build_user_headers("test-reviewer-1", "EMReviewer"),
}


def make_program_admin_headers(user_id: str) -> dict:
    """Opaque ProgramAdmin identity (e.g. to pin an issuer id for SoD tests)."""
    return build_user_headers(user_id, "ProgramAdmin")


def make_program_coordinator_headers(user_id: str) -> dict:
    """Opaque ProgramCoordinator identity (e.g. to pin the invoice issuer)."""
    return build_user_headers(user_id, "ProgramCoordinator")


def make_observer_headers(observer_id: str) -> dict:
    """Entity-backed Observer headers; pass the real Observer.id."""
    return build_user_headers(observer_id, "Observer")


def make_debriefer_headers(debriefer_id: str) -> dict:
    """Entity-backed Debriefer headers; pass the real Debriefer.id."""
    return build_user_headers(debriefer_id, "Debriefer")


def make_vessel_operator_headers(operator_id: str) -> dict:
    """Entity-backed VesselOperator headers; pass the real VesselOperator.id."""
    return build_user_headers(operator_id, "VesselOperator")


def make_em_reviewer_headers(reviewer_id: str) -> dict:
    """Entity-backed EMReviewer headers; pass the real EMReviewer.id."""
    return build_user_headers(reviewer_id, "EMReviewer")
