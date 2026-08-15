"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

from .constants import COORD_1, FIN_1, FOR_1, HEAR_1, INSP_1, INSP_2

# Shared constants — safe for opaque roles, and for entity-backed roles only in
# tests that do not exercise ownership (404/400/role-denial probes).
TEST_USERS = {
    "coordinator_headers": build_user_headers(COORD_1, "ProgramCoordinator"),
    "coordinator2_headers": build_user_headers("coord-2", "ProgramCoordinator"),
    "inspector_headers": build_user_headers(INSP_1, "Inspector"),
    "inspector2_headers": build_user_headers(INSP_2, "Inspector"),
    "forestry_headers": build_user_headers(FOR_1, "ForestryOfficer"),
    "finance_headers": build_user_headers(FIN_1, "FinanceOfficer"),
    "hearing_headers": build_user_headers(HEAR_1, "HearingOfficer"),
    # Entity-backed fallbacks — never valid for ownership-gated calls.
    "owner_headers": build_user_headers("test-owner-1", "PropertyOwner"),
    "contractor_headers": build_user_headers("test-contractor-1", "Contractor"),
}


def make_owner_headers(user_id: str) -> dict:
    """For PropertyOwner (entity_backed:PropertyOwner). Pass the real
    PropertyOwner.id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "PropertyOwner")


def make_contractor_headers(user_id: str) -> dict:
    """For Contractor (entity_backed:Contractor). Pass the real
    Contractor.id whenever the call is ownership-gated (bids, completes)."""
    return build_user_headers(user_id, "Contractor")
