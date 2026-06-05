"""Pre-built role headers for every role in the PRD (PRD §2.1).

PRD §2.1: when X-User-Role is OrderingProvider, Phlebotomist, LabTech, or
LabDirector, X-User-ID is the id of the acting Clinician row. Ownership checks
compare the resource's clinician FK to X-User-ID. The four operator roles are
therefore entity-backed and tests touching ownership-gated calls MUST build the
headers with `make_<role>_headers(clinician["id"])`. The shared `TEST_USERS`
constants are fallbacks for tests that do not exercise ownership (400/404/401
paths) and for the opaque Anonymous role used during bootstrap registration.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Entity-backed roles — shared constants are FALLBACKS for non-ownership tests
    # (e.g., 400-on-bad-payload, 404-on-missing-resource). Ownership-gated calls
    # MUST use the make_<role>_headers builder with the real Clinician.id.
    "ordering_provider_headers": build_user_headers("test-op-1", "OrderingProvider"),
    "phlebotomist_headers": build_user_headers("test-phleb-1", "Phlebotomist"),
    "lab_tech_headers": build_user_headers("test-lt-1", "LabTech"),
    "lab_director_headers": build_user_headers("test-dir-1", "LabDirector"),
    # Anonymous — opaque, used only for bootstrap clinician registration.
    "anonymous_headers": build_user_headers("bootstrap", "Anonymous"),
}


def make_ordering_provider_headers(clinician_id: str) -> dict:
    """Headers for an OrderingProvider bound to a specific Clinician.id.

    PRD §2.1: X-User-ID is the id of the acting Clinician row. Any call whose
    success depends on ownership (e.g., POST /critical-notifications/{id}/
    acknowledgements where X-User-ID must equal recipient_clinician_id) MUST
    pass the real Clinician.id here.
    """
    return build_user_headers(clinician_id, "OrderingProvider")


def make_phlebotomist_headers(clinician_id: str) -> dict:
    """Headers for a Phlebotomist bound to a specific Clinician.id (PRD §2.1, §3.3)."""
    return build_user_headers(clinician_id, "Phlebotomist")


def make_lab_tech_headers(clinician_id: str) -> dict:
    """Headers for a LabTech bound to a specific Clinician.id (PRD §2.1, §3.3, §3.5)."""
    return build_user_headers(clinician_id, "LabTech")


def make_lab_director_headers(clinician_id: str) -> dict:
    """Headers for a LabDirector bound to a specific Clinician.id (PRD §2.1, §3.8)."""
    return build_user_headers(clinician_id, "LabDirector")


def make_anonymous_headers(token: str = "bootstrap") -> dict:
    """Headers for the Anonymous bootstrap role (PRD §2.1, §3.1).

    PRD §2.1: X-User-ID is treated as an opaque pre-authentication token, not
    bound to any persisted entity.
    """
    return build_user_headers(token, "Anonymous")


def make_headers(user_id: str, role: str) -> dict:
    """Generic constructor for parametrized RBAC tests."""
    return build_user_headers(user_id, role)
