"""Pre-built role headers for every role in the PRD (§2.1).

Regulator and LEPCCoordinator are opaque roles: X-User-ID is not tied to any
entity, so a shared constant is the canonical form. FacilityOperator is
entity_backed:Facility — its X-User-ID must equal the acting facility's id for
ownership checks, so ownership-gated calls MUST use make_facility_operator_headers(facility_id).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "regulator_headers": build_user_headers("test-regulator-1", "Regulator"),
    "lepc_coordinator_headers": build_user_headers("test-lepc-1", "LEPCCoordinator"),
    # Fallback for FacilityOperator tests that do NOT exercise ownership
    # (e.g. role-denied on a Regulator-exclusive endpoint).
    "facility_operator_headers": build_user_headers(
        "00000000-0000-4000-8000-000000000099", "FacilityOperator"
    ),
}


def make_regulator_headers(user_id: str = "test-regulator-1") -> dict:
    """Regulator is opaque; user_id is not compared to any entity id."""
    return build_user_headers(user_id, "Regulator")


def make_lepc_coordinator_headers(user_id: str = "test-lepc-1") -> dict:
    """LEPCCoordinator is opaque; user_id is not compared to any entity id."""
    return build_user_headers(user_id, "LEPCCoordinator")


def make_facility_operator_headers(user_id: str) -> dict:
    """For FacilityOperator (entity_backed:Facility). Pass the acting Facility.id
    as user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "FacilityOperator")
