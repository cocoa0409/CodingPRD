"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants.
#   IntakeCoordinator / CaseManager / ProgramAdmin are opaque: the server never
#   compares X-User-ID to any persisted record, so a fixed identifier is safe.
#   Inspector / Contractor are entity_backed: the shared constant is a fallback
#   ONLY for tests whose success does not depend on ownership (e.g. 401/403/404).
TEST_USERS = {
    "intake_headers": build_user_headers("ic-1", "IntakeCoordinator"),
    "case_manager_headers": build_user_headers("cm-1", "CaseManager"),
    "program_admin_headers": build_user_headers("pa-1", "ProgramAdmin"),
    # entity_backed fallbacks (non-ownership tests only)
    "inspector_headers": build_user_headers("insp-x", "Inspector"),
    "contractor_headers": build_user_headers("con-x", "Contractor"),
}


# Per-instance builders — mandatory for entity_backed roles when the call is
# ownership-gated (findings/complete require X-User-ID == investigation.inspector_id;
# start/complete/request-clearance require X-User-ID == project.contractor_id).
def make_inspector_headers(inspector_id: str) -> dict:
    """For Inspector (entity_backed:Inspector). Pass the Inspector.id as X-User-ID."""
    return build_user_headers(inspector_id, "Inspector")


def make_contractor_headers(contractor_id: str) -> dict:
    """For Contractor (entity_backed:Contractor). Pass the Contractor.id as X-User-ID."""
    return build_user_headers(contractor_id, "Contractor")
