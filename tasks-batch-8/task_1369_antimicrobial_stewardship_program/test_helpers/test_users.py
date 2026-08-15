"""Pre-built role headers for every role in the PRD RBAC model.

Per PRD Section 2.1: StewardshipAdmin carries an opaque X-User-ID; the other
five roles are entity-backed — X-User-ID must be the acting Practitioner's id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque StewardshipAdmin and for tests whose
# outcome does not depend on the caller's X-User-ID matching a Practitioner.id
# (e.g. 400-on-bad-payload, 404-on-missing-resource, RBAC denial by role).
TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "StewardshipAdmin"),
    # Entity-backed role fallbacks — use ONLY for non-ownership-gated calls.
    "director_headers": build_user_headers("test-director-1", "StewardshipDirector"),
    "pharmacist_headers": build_user_headers("test-pharmacist-1", "IDPharmacist"),
    "physician_headers": build_user_headers("test-physician-1", "AttendingPhysician"),
    "microbiologist_headers": build_user_headers("test-microbiologist-1", "Microbiologist"),
    "preventionist_headers": build_user_headers("test-preventionist-1", "InfectionPreventionist"),
}


# Per-instance builders — mandatory for entity_backed roles whenever the call
# is ownership-gated (prescriber/requester/auditor/decider checks compare the
# resource field against X-User-ID per PRD Section 2.1).
def make_admin_headers(user_id: str = "test-admin-1") -> dict:
    """StewardshipAdmin is opaque; any stable id works."""
    return build_user_headers(user_id, "StewardshipAdmin")


def make_director_headers(user_id: str) -> dict:
    """StewardshipDirector (entity_backed: Practitioner)."""
    return build_user_headers(user_id, "StewardshipDirector")


def make_pharmacist_headers(user_id: str) -> dict:
    """IDPharmacist (entity_backed: Practitioner)."""
    return build_user_headers(user_id, "IDPharmacist")


def make_physician_headers(user_id: str) -> dict:
    """AttendingPhysician (entity_backed: Practitioner)."""
    return build_user_headers(user_id, "AttendingPhysician")


def make_microbiologist_headers(user_id: str) -> dict:
    """Microbiologist (entity_backed: Practitioner)."""
    return build_user_headers(user_id, "Microbiologist")


def make_preventionist_headers(user_id: str) -> dict:
    """InfectionPreventionist (entity_backed: Practitioner)."""
    return build_user_headers(user_id, "InfectionPreventionist")
