"""Pre-built role headers for every role in the PRD (§2.1).

Pharmacist and PriorAuthCoordinator carry opaque operator identifiers not tied
to any persisted entity, so their shared constants are the canonical form.

Nurse is entity_backed: X-User-ID is the id of the acting Nurse entity. Any
chairside action whose behavior depends on WHICH nurse acted (prepare / verify /
reject / administer / check-in / complete) must carry the real Nurse.id via
make_nurse_headers(nurse_id). The shared constant is a fallback only for tests
that do not exercise nurse identity (e.g. forbidden-role 403, GET reads).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # opaque roles — shared constant is canonical
    "pharmacist_headers": build_user_headers("test-pharmacist-1", "Pharmacist"),
    "prior_auth_coordinator_headers": build_user_headers("test-pa-coordinator-1", "PriorAuthCoordinator"),
    # entity_backed Nurse — shared constant for non-ownership tests only
    "nurse_headers": build_user_headers("test-nurse-1", "Nurse"),
}


def make_pharmacist_headers(user_id: str = "test-pharmacist-1") -> dict:
    """Pharmacist (opaque). user_id is not compared to any entity id."""
    return build_user_headers(user_id, "Pharmacist")


def make_prior_auth_coordinator_headers(user_id: str = "test-pa-coordinator-1") -> dict:
    """PriorAuthCoordinator (opaque). user_id is not compared to any entity id."""
    return build_user_headers(user_id, "PriorAuthCoordinator")


def make_nurse_headers(nurse_id: str) -> dict:
    """Nurse (entity_backed:Nurse). Pass the actual Nurse.id as nurse_id so the
    server records it on the order (prepared_by_nurse_id / verified_by_nurse_id)
    and the segregation-of-duties check sees the correct acting nurse."""
    return build_user_headers(nurse_id, "Nurse")
