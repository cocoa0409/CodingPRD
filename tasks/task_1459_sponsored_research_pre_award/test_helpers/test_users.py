"""Pre-built role headers for every role in the PRD (§2.1).

Two forms per role:
- a shared constant in TEST_USERS (safe for opaque roles, and for PI calls
  whose success does NOT depend on owning the subject resource);
- a per-instance builder make_<role>_headers(user_id) — mandatory for the
  entity-backed PI role whenever the call is ownership-gated: pass the actual
  PrincipalInvestigator.id so X-User-ID equals the resource's pi_id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # entity_backed:PrincipalInvestigator — fallback for non-ownership calls only.
    "pi_headers": build_user_headers("test-pi-1", "PI"),
    # opaque roles — canonical form.
    "analyst_headers": build_user_headers("analyst-1", "PreAwardAnalyst"),
    "chair_headers": build_user_headers("chair-1", "DepartmentChair"),
    "compliance_headers": build_user_headers("compliance-1", "ComplianceOfficer"),
    "sub_manager_headers": build_user_headers("submgr-1", "SubrecipientManager"),
    "director_headers": build_user_headers("director-1", "OSPDirector"),
    "admin_headers": build_user_headers("admin-1", "OSPSystemAdmin"),
}


def make_pi_headers(user_id: str) -> dict:
    """For the PI role (entity_backed:PrincipalInvestigator). Pass the actual
    PrincipalInvestigator.id as user_id whenever the call is ownership-gated
    (proposal create, PATCH, respond, withdraw)."""
    return build_user_headers(user_id, "PI")


def make_analyst_headers(user_id: str) -> dict:
    """PreAwardAnalyst is opaque, but routing records routed_by_user_id from
    X-User-ID and pledges record committed_by_user_id; pick the id explicitly
    when a segregation-of-duties check follows."""
    return build_user_headers(user_id, "PreAwardAnalyst")


def make_chair_headers(user_id: str) -> dict:
    """DepartmentChair is opaque; pick the id explicitly so it differs from a
    pledge's committed_by_user_id when approving cost share."""
    return build_user_headers(user_id, "DepartmentChair")


def make_director_headers(user_id: str) -> dict:
    """OSPDirector is opaque; pick the id explicitly so it differs from
    routed_by_user_id when approving institutionally."""
    return build_user_headers(user_id, "OSPDirector")


def make_compliance_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")


def make_sub_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SubrecipientManager")


def make_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "OSPSystemAdmin")
