"""Pre-built role headers for every role in PRD §2.1.

Rep and PrincipalOps are entity-backed: their X-User-ID must resolve to an
existing Rep / Principal record on every call (pipeline check 1), and
ownership-gated calls compare it to the resource's rep_id / principal_id.
Always use make_rep_headers(rep["id"]) / make_principal_ops_headers(principal["id"])
with a freshly created entity. The shared constants for those two roles are
fallbacks for negative probes only.

AgencyAdmin and Auditor are opaque: the shared constants are canonical.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # opaque roles — canonical form.
    "agency_admin_headers": build_user_headers("admin-1", "AgencyAdmin"),
    "auditor_headers": build_user_headers("auditor-1", "Auditor"),
    # entity_backed roles — fallback constants for negative probes only.
    "rep_headers": build_user_headers("rep-orphan-1", "Rep"),
    "principal_ops_headers": build_user_headers("principal-orphan-1", "PrincipalOps"),
}

# Header sets for the pipeline check-1 probes (PRD §2.1).
ANONYMOUS_HEADERS = {"X-User-ID": "anon-1", "Content-Type": "application/json"}
NO_AUTH_HEADERS = {"Content-Type": "application/json"}


def make_rep_headers(rep_id: str) -> dict:
    """Rep is entity-backed by Rep: pass the acting rep's id on every call."""
    return build_user_headers(rep_id, "Rep")


def make_principal_ops_headers(principal_id: str) -> dict:
    """PrincipalOps is entity-backed by Principal: pass the principal's id."""
    return build_user_headers(principal_id, "PrincipalOps")
