"""Pre-built role headers for every role in the PRD.

Customer is entity-backed: its X-User-ID must equal the acting Customer's id for
ownership checks to pass, so ownership-gated calls use make_customer_headers(id).
The other roles (Receiver, Grader, Authenticator, LabAdmin, Anonymous) carry an
opaque id the server never compares to a persisted entity, so shared constants
are the canonical form for them.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # entity_backed:Customer — shared constant is a fallback for non-ownership
    # tests only (e.g. 401/403/404 probes). Ownership-gated calls must instead
    # use make_customer_headers(customer["id"]).
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
    # opaque roles — shared constants are canonical.
    "receiver_headers": build_user_headers("test-receiver-1", "Receiver"),
    "grader_headers": build_user_headers("test-grader-1", "Grader"),
    "authenticator_headers": build_user_headers("test-authenticator-1", "Authenticator"),
    "lab_admin_headers": build_user_headers("test-labadmin-1", "LabAdmin"),
    "anonymous_headers": build_user_headers("test-anon-1", "Anonymous"),
}


def make_customer_headers(user_id: str) -> dict:
    """For Customer (entity_backed:Customer). Pass the actual Customer.id as
    user_id whenever the call is ownership-gated (submit, add/delete item,
    open regrade request)."""
    return build_user_headers(user_id, "Customer")


def make_receiver_headers(user_id: str = "test-receiver-1") -> dict:
    return build_user_headers(user_id, "Receiver")


def make_grader_headers(user_id: str = "test-grader-1") -> dict:
    return build_user_headers(user_id, "Grader")


def make_authenticator_headers(user_id: str = "test-authenticator-1") -> dict:
    return build_user_headers(user_id, "Authenticator")


def make_lab_admin_headers(user_id: str = "test-labadmin-1") -> dict:
    return build_user_headers(user_id, "LabAdmin")
