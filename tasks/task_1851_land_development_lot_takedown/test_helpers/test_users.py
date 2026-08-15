"""Pre-built role headers for every role in PRD §2.1.

BuilderRep and HOAManager are entity-backed: their X-User-ID must be the acting
Builder / HOAAssociation id whenever the call is ownership-gated (reserve,
closing create/cancel, amend, evaluate-control, complete-transition). Use
make_builder_rep_headers(builder["id"]) / make_hoa_manager_headers(hoa["id"])
for those calls; the shared constants are only safe for negative RBAC probes
and non-ownership tests.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "developer_operator_headers": build_user_headers("dev-user-1", "DeveloperOperator"),
    # entity_backed:Builder — fallback for non-ownership probes only.
    "builder_rep_headers": build_user_headers("builder-orphan-1", "BuilderRep"),
    "lender_officer_headers": build_user_headers("lo-user-1", "LenderOfficer"),
    "municipal_clerk_headers": build_user_headers("clerk-user-1", "MunicipalClerk"),
    # entity_backed:HOAAssociation — fallback for non-ownership probes only.
    "hoa_manager_headers": build_user_headers("hoa-orphan-1", "HOAManager"),
}

# Request carrying neither X-User-Role nor X-User-ID (PRD §2.1).
NO_AUTH_HEADERS = {"Content-Type": "application/json"}


def make_developer_operator_headers(user_id: str) -> dict:
    """DeveloperOperator identity is opaque; the id is recorded on draws as
    requested_by_user_id, which anchors segregation of duties (PRD §3.6)."""
    return build_user_headers(user_id, "DeveloperOperator")


def make_builder_rep_headers(builder_id: str) -> dict:
    """BuilderRep is entity-backed by Builder: pass the acting builder's id
    whenever the call is ownership-gated (PRD §2.1)."""
    return build_user_headers(builder_id, "BuilderRep")


def make_lender_officer_headers(user_id: str) -> dict:
    """LenderOfficer identity is opaque; the id is recorded on draws as
    approved_by_user_id and compared against requested_by_user_id (PRD §3.6)."""
    return build_user_headers(user_id, "LenderOfficer")


def make_municipal_clerk_headers(user_id: str) -> dict:
    """MunicipalClerk identity is opaque (PRD §2.1)."""
    return build_user_headers(user_id, "MunicipalClerk")


def make_hoa_manager_headers(association_id: str) -> dict:
    """HOAManager is entity-backed by HOAAssociation: pass the association's id
    whenever the call is ownership-gated (PRD §2.1)."""
    return build_user_headers(association_id, "HOAManager")
