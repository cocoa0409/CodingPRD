"""Pre-built role headers for every role in PRD §2.1.

All four roles carry an opaque identity: X-User-ID is an operator identifier
that the server compares against recorded attributes (client_ref on an order,
abstracter_ref on an assignment, reviewer_examiner_ref on a report). Fixtures
MUST build headers whose X-User-ID matches the ref they booked on the resource
— use the make_*_headers builders with the same ref string used at creation.
"""
from prd_bench_local_runner.testing import build_user_headers

# Canonical ref strings used by the fixtures below. A fixture that books a
# resource under one of these refs can safely use the matching shared header.
DEFAULT_CLIENT_REF = "client_t1"
DEFAULT_ABSTRACTER_REF = "abs_t1"
DEFAULT_EXAMINER_REF = "ex_t1"
DEFAULT_OPS_REF = "ops_t1"

TEST_USERS = {
    # Safe for calls that are not ownership-gated against a specific resource.
    "client_headers": build_user_headers(DEFAULT_CLIENT_REF, "Client"),
    "abstracter_headers": build_user_headers(DEFAULT_ABSTRACTER_REF, "Abstracter"),
    "examiner_headers": build_user_headers(DEFAULT_EXAMINER_REF, "Examiner"),
    "ops_manager_headers": build_user_headers(DEFAULT_OPS_REF, "OperationsManager"),
}

# Header sets for negative authentication probes (PRD §2.1).
NO_AUTH_HEADERS = {"Content-Type": "application/json"}
UNKNOWN_ROLE_HEADERS = {
    "X-User-ID": "mystery_user",
    "X-User-Role": "Notary",
    "Content-Type": "application/json",
}


def make_client_headers(user_id: str) -> dict:
    """Client ownership: X-User-ID must equal the order's client_ref."""
    return build_user_headers(user_id, "Client")


def make_abstracter_headers(user_id: str) -> dict:
    """Abstracter ownership: X-User-ID must equal the assignment's abstracter_ref."""
    return build_user_headers(user_id, "Abstracter")


def make_examiner_headers(user_id: str) -> dict:
    """Examiner ownership: X-User-ID must equal the report's reviewer_examiner_ref
    for approve / require-revision, and must differ from a requirement's raiser
    on waive."""
    return build_user_headers(user_id, "Examiner")


def make_ops_headers(user_id: str = DEFAULT_OPS_REF) -> dict:
    """OperationsManager is never attribute-gated; any well-formed id works."""
    return build_user_headers(user_id, "OperationsManager")
