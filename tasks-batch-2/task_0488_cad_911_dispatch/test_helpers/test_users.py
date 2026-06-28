"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles, and for tests that don't exercise
# unit ownership. FieldUnit's shared constant is a fallback for non-ownership
# tests only (e.g. 404/422 paths); ownership-gated field operations MUST use
# make_field_unit_headers(unit_id).
TEST_USERS = {
    "calltaker_headers": build_user_headers("test-calltaker-1", "Calltaker"),
    "dispatcher_headers": build_user_headers("test-dispatcher-1", "Dispatcher"),
    "field_unit_headers": build_user_headers("test-fieldunit-1", "FieldUnit"),
    "supervisor_headers": build_user_headers("test-supervisor-1", "Supervisor"),
    "records_headers": build_user_headers("test-records-1", "Records"),
    "system_clock_headers": build_user_headers("test-clock-1", "SystemClock"),
}


def make_field_unit_headers(unit_id: str) -> dict:
    """For FieldUnit (entity_backed:Unit). Pass the acting Unit.id as X-User-ID
    whenever the field operation advances that unit's own assignment, since
    ownership checks compare the assignment's referenced unit to X-User-ID."""
    return build_user_headers(unit_id, "FieldUnit")
