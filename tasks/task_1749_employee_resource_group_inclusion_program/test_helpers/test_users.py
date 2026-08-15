"""Pre-built role headers for every role in the PRD.

Identity model (PRD section 2.1):
- DeiAdmin, GroupLeader, Employee carry an opaque X-User-ID never compared to
  an entity id; the shared constants are safe for calls whose success does not
  depend on the caller owning a resource.
- ExecutiveSponsor is entity-backed: X-User-ID must be the id of the acting
  ExecutiveSponsor entity. Always use make_sponsor_headers(sponsor["id"]) for
  sponsor-decision calls; the shared "sponsor_headers" entry is a fallback for
  role-denial tests only.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles: shared constants are canonical for non-ownership calls.
    "dei_admin_headers": build_user_headers("test-dei-admin-1", "DeiAdmin"),
    "group_leader_headers": build_user_headers("test-group-leader-1", "GroupLeader"),
    "employee_headers": build_user_headers("test-employee-1", "Employee"),
    # Entity-backed role: fallback for calls that only exercise the role check
    # (e.g. a sponsor attempting a DeiAdmin-exclusive operation).
    "sponsor_headers": build_user_headers("test-sponsor-1", "ExecutiveSponsor"),
}

# Header set with no auth context at all (authentication-gate tests).
NO_AUTH_HEADERS = {"Content-Type": "application/json"}


def make_dei_admin_headers(user_id: str = "test-dei-admin-1") -> dict:
    """DeiAdmin is opaque; any stable operator id works."""
    return build_user_headers(user_id, "DeiAdmin")


def make_group_leader_headers(user_id: str) -> dict:
    """GroupLeader is opaque: pass the employee id the PRD compares against
    (charter owner / ACTIVE-term leader / request submitter)."""
    return build_user_headers(user_id, "GroupLeader")


def make_employee_headers(user_id: str) -> dict:
    """Employee is opaque: pass the employee id recorded on the resource."""
    return build_user_headers(user_id, "Employee")


def make_sponsor_headers(sponsor_entity_id: str) -> dict:
    """ExecutiveSponsor is entity-backed: X-User-ID must equal the persisted
    ExecutiveSponsor entity's id for sponsor-matching checks to pass."""
    return build_user_headers(sponsor_entity_id, "ExecutiveSponsor")
