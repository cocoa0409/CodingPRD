"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles (Coordinator, Anonymous) and for
# tests that do not exercise entity ownership.
TEST_USERS = {
    "coordinator_headers": build_user_headers("test-coordinator-1", "Coordinator"),
    "anonymous_headers": build_user_headers("test-anon-1", "Anonymous"),
    # Entity-backed roles: shared constants are a fallback for non-ownership tests only.
    "surgeon_headers": build_user_headers("test-surgeon-1", "Surgeon"),
    "optometrist_headers": build_user_headers("test-optometrist-1", "Optometrist"),
    "patient_headers": build_user_headers("test-patient-1", "Patient"),
}


# Per-instance builders — required for every entity_backed role. Pass the actual
# entity id whenever the downstream call is ownership-gated.
def make_surgeon_headers(user_id: str) -> dict:
    """For Surgeon (entity_backed:Surgeon). Pass the acting Surgeon.id."""
    return build_user_headers(user_id, "Surgeon")


def make_optometrist_headers(user_id: str) -> dict:
    """For Optometrist (entity_backed:Optometrist). Pass the acting Optometrist.id."""
    return build_user_headers(user_id, "Optometrist")


def make_patient_headers(user_id: str) -> dict:
    """For Patient (entity_backed:Patient). Pass the acting Patient.id."""
    return build_user_headers(user_id, "Patient")


def coordinator_headers() -> dict:
    return TEST_USERS["coordinator_headers"]


def anonymous_headers() -> dict:
    return TEST_USERS["anonymous_headers"]
