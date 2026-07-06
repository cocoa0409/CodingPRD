"""Pre-built role headers for every role in the PRD.

Roles (PRD 2.1): Dispatcher, FieldOfficer, Supervisor, HealthDeptLiaison.
Only FieldOfficer is entity-backed (X-User-ID must equal the acting Officer.id
for ownership-gated dispatch/case operations); the other three are opaque.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# officer ownership (e.g. RBAC 403s, 404s, request-integrity 422s).
TEST_USERS = {
    "dispatcher_headers": build_user_headers("test-dispatcher-1", "Dispatcher"),
    "supervisor_headers": build_user_headers("test-supervisor-1", "Supervisor"),
    "health_dept_liaison_headers": build_user_headers("test-liaison-1", "HealthDeptLiaison"),
    # FieldOfficer is entity_backed:Officer — this shared constant is a fallback
    # for non-ownership tests only. Ownership-gated calls MUST use
    # make_field_officer_headers(officer["id"]).
    "field_officer_headers": build_user_headers("test-fieldofficer-1", "FieldOfficer"),
}


def make_field_officer_headers(user_id: str) -> dict:
    """For FieldOfficer (entity_backed:Officer). Pass the actual Officer.id as
    user_id whenever the call is ownership-gated (dispatch accept/clear,
    case investigate/resolve)."""
    return build_user_headers(user_id, "FieldOfficer")
