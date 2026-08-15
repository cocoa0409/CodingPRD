"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants for the nine opaque roles — safe for any call.
TEST_USERS = {
    "platform_admin": build_user_headers("admin-1", "PlatformAdmin"),
    "rep": build_user_headers("rep-1", "MemberServicesRep"),
    "rep2": build_user_headers("rep-2", "MemberServicesRep"),
    "board_director": build_user_headers("director-1", "BoardDirector"),
    "board_director2": build_user_headers("director-2", "BoardDirector"),
    "board_secretary": build_user_headers("secretary-1", "BoardSecretary"),
    "rate_analyst": build_user_headers("analyst-1", "RateAnalyst"),
    "billing_clerk": build_user_headers("clerk-1", "BillingClerk"),
    "field_ops": build_user_headers("field-1", "FieldOpsCoordinator"),
    "dispatcher": build_user_headers("disp-1", "Dispatcher"),
    "legal_counsel": build_user_headers("legal-1", "LegalCounsel"),
    # Member is entity_backed: shared constant only for non-ownership assertions
    # (e.g. RBAC denial on a non-member endpoint). For ownership-gated calls,
    # use make_member_headers(member["id"]).
    "member": build_user_headers("test-member-1", "Member"),
}


def make_member_headers(user_id: str) -> dict:
    """For Member (entity_backed:Member). Pass the actual Member.id as user_id
    whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Member")


def make_rep_headers(user_id: str) -> dict:
    """MemberServicesRep with a specific opaque id (needed for SoD scenarios)."""
    return build_user_headers(user_id, "MemberServicesRep")


def make_director_headers(user_id: str) -> dict:
    """BoardDirector with a specific opaque id (needed for SoD scenarios)."""
    return build_user_headers(user_id, "BoardDirector")
