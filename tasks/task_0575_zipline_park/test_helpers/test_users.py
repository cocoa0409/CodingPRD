"""Pre-built role headers for every role in the PRD (§2.1).

Operator is opaque: X-User-ID is not tied to any entity, so a shared constant
is canonical. Customer (entity_backed:Participant) and Guide (entity_backed:Guide)
must present X-User-ID equal to the acting entity's id whenever a call is
ownership-gated, so those calls MUST use the per-instance builders below.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Opaque operator role — shared constant is canonical.
    "operator_headers": build_user_headers("test-operator-1", "Operator"),
    # entity_backed roles: these shared constants are fallbacks for non-ownership
    # tests only (e.g. 401/403 role-denial checks). Ownership-gated calls use the
    # builders below threaded with the real entity id.
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
    "guide_headers": build_user_headers("test-guide-1", "Guide"),
}


def make_customer_headers(user_id: str) -> dict:
    """For the Customer role (entity_backed:Participant). Pass the acting
    Participant.id as user_id whenever the call is ownership-gated (own waiver /
    own booking cancel / own rain-check redeem)."""
    return build_user_headers(user_id, "Customer")


def make_guide_headers(user_id: str) -> dict:
    """For the Guide role (entity_backed:Guide). Pass the acting Guide.id as
    user_id."""
    return build_user_headers(user_id, "Guide")
