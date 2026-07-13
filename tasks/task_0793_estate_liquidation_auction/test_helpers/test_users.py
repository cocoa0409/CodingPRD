"""Pre-built role headers for every role in the PRD.

Operator and Anonymous are opaque roles (X-User-ID not tied to any entity),
so their shared constants are the canonical form. Buyer is entity_backed:
its X-User-ID must equal the acting Buyer.id, so ownership-gated calls MUST
use make_buyer_headers(buyer["id"]).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — shared constant is canonical.
    "operator_headers": build_user_headers("test-operator-1", "Operator"),
    "anonymous_headers": build_user_headers("anon", "Anonymous"),
    # Entity_backed Buyer — shared constant is a fallback for NON-ownership
    # tests only (e.g. 403-unauthorized-role checks). Ownership-gated calls
    # must use make_buyer_headers(buyer_id).
    "buyer_headers": build_user_headers("test-buyer-1", "Buyer"),
}


def make_buyer_headers(user_id: str) -> dict:
    """For the Buyer role (entity_backed:Buyer). Pass the actual Buyer.id as
    user_id whenever the call is ownership-gated (bids, pay, schedule/cancel
    pickup, disputes)."""
    return build_user_headers(user_id, "Buyer")


def operator_headers() -> dict:
    return TEST_USERS["operator_headers"]


def anonymous_headers() -> dict:
    return TEST_USERS["anonymous_headers"]
