"""Pre-built role headers for every role in PRD §2.1.

All three roles carry an opaque identity model: ``X-User-ID`` is not matched
against any persisted entity row. The per-instance builders exist because
segregation-of-duties checks compare a stored ``X-User-ID`` (for example
``approved_by_director_id``) against the next actor's ``X-User-ID`` — tests
must therefore control the identifier precisely.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles: shared constants are canonical except where a test needs
    # a specific identifier for a segregation-of-duties pairing.
    "compliance_officer_headers": build_user_headers("officer-1", "ComplianceOfficer"),
    "tax_director_headers": build_user_headers("tax-director-1", "TaxDirector"),
    "board_director_headers": build_user_headers("director-1", "BoardDirector"),
}

# Request with no X-User-Role header (PRD §2.1: missing header -> 401).
NO_ROLE_HEADERS = {"X-User-ID": "anon-1", "Content-Type": "application/json"}

# Request with a role outside the declared set (PRD §2.1: unknown role -> 401).
UNKNOWN_ROLE_HEADERS = build_user_headers("anon-2", "Janitor")


def make_compliance_officer_headers(user_id: str) -> dict:
    """ComplianceOfficer is opaque; pass a specific id when a test needs the
    identifier captured (e.g. declared_by_officer_id) to be controlled."""
    return build_user_headers(user_id, "ComplianceOfficer")


def make_tax_director_headers(user_id: str) -> dict:
    """TaxDirector is opaque; the id may be recorded on entities it touches."""
    return build_user_headers(user_id, "TaxDirector")


def make_board_director_headers(user_id: str) -> dict:
    """BoardDirector is opaque; the id is captured into
    approved_by_director_id / decided_by_director_id when the director acts."""
    return build_user_headers(user_id, "BoardDirector")
