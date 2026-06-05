"""Pre-built role headers for every role in the PRD (§2.1).

Six roles exist. Admin and Judge are opaque operator identifiers — their
X-User-ID is never compared to any entity id, so the shared constant is the
canonical form. The other four (IntakeScreener, Investigator, Caseworker,
LicensingWorker) are entity-backed by a Caseworker record: their X-User-ID
must be the id of a real persisted Caseworker for ownership/SoD checks to
pass, so each provides a per-instance builder used by the fixtures.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants.
#  - Admin / Judge: opaque — these are the canonical headers.
#  - The four entity-backed roles: a fallback for tests that do NOT exercise
#    ownership (e.g. 401/403/404/422 paths). Ownership-gated calls MUST use the
#    per-instance builders below threaded with the real Caseworker id.
TEST_USERS = {
    "admin_headers": build_user_headers("admin-operator-1", "Admin"),
    "judge_headers": build_user_headers("judge-officer-1", "Judge"),
    "screener_headers": build_user_headers("test-screener-1", "IntakeScreener"),
    "investigator_headers": build_user_headers("test-investigator-1", "Investigator"),
    "caseworker_headers": build_user_headers("test-caseworker-1", "Caseworker"),
    "licensing_headers": build_user_headers("test-licensing-1", "LicensingWorker"),
}


# Per-instance builders — required for every entity_backed role.
def make_admin_headers(user_id: str = "admin-operator-1") -> dict:
    """Admin is opaque; user_id is an arbitrary operator identifier."""
    return build_user_headers(user_id, "Admin")


def make_judge_headers(user_id: str = "judge-officer-1") -> dict:
    """Judge is opaque; user_id is an arbitrary judicial-officer identifier."""
    return build_user_headers(user_id, "Judge")


def make_screener_headers(user_id: str) -> dict:
    """IntakeScreener (entity_backed:Caseworker). Pass the SCREENER Caseworker.id."""
    return build_user_headers(user_id, "IntakeScreener")


def make_investigator_headers(user_id: str) -> dict:
    """Investigator (entity_backed:Caseworker). Pass the INVESTIGATOR Caseworker.id."""
    return build_user_headers(user_id, "Investigator")


def make_caseworker_headers(user_id: str) -> dict:
    """Caseworker (entity_backed:Caseworker). Pass the CASEWORKER Caseworker.id."""
    return build_user_headers(user_id, "Caseworker")


def make_licensing_headers(user_id: str) -> dict:
    """LicensingWorker (entity_backed:Caseworker). Pass the LICENSING Caseworker.id."""
    return build_user_headers(user_id, "LicensingWorker")
