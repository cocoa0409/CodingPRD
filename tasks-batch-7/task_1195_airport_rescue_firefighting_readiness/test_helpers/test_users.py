"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for non-ownership tests.
TEST_USERS = {
    "airport_manager_headers": build_user_headers("user-am-1", "AirportManager"),
    "airport_manager_2_headers": build_user_headers("user-am-9", "AirportManager"),
    "arff_chief_headers": build_user_headers("user-ac-1", "ArffChief"),
    "safety_officer_headers": build_user_headers("user-so-1", "SafetyOfficer"),
    "safety_officer_2_headers": build_user_headers("user-so-2", "SafetyOfficer"),
    "faa_inspector_headers": build_user_headers("user-faa-1", "FaaInspector"),
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "firefighter_headers": build_user_headers("test-firefighter-1", "Firefighter"),
}


# Per-instance builder — required for the entity_backed Firefighter role.
def make_firefighter_headers(firefighter_id: str) -> dict:
    """For Firefighter (entity_backed:Firefighter). Pass the actual
    Firefighter.id as firefighter_id whenever the call is ownership-gated."""
    return build_user_headers(firefighter_id, "Firefighter")


def make_airport_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "AirportManager")


def make_arff_chief_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ArffChief")


def make_safety_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SafetyOfficer")


def make_faa_inspector_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FaaInspector")
