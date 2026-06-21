"""Pre-built role headers for every role in the PRD.

Two roles are entity_backed (Consumer, Furnisher) — ownership-gated calls MUST
use the per-instance builders with the real entity id. CreditBureau and Regulator
are opaque operator identities; their shared constants are the canonical form.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise ownership.
TEST_USERS = {
    # entity_backed: shared constant is a fallback for non-ownership tests only.
    "consumer_headers": build_user_headers("test-consumer-1", "Consumer"),
    "furnisher_headers": build_user_headers("test-furnisher-1", "Furnisher"),
    # opaque: shared constant is the canonical form.
    "bureau_headers": build_user_headers("test-bureau-1", "CreditBureau"),
    "regulator_headers": build_user_headers("test-regulator-1", "Regulator"),
}


# Per-instance builders — required for every entity_backed role.
def make_consumer_headers(user_id: str) -> dict:
    """For Consumer (entity_backed:Consumer). Pass the actual Consumer.id whenever
    the call is ownership-gated (file/dispute/freeze/complaint)."""
    return build_user_headers(user_id, "Consumer")


def make_furnisher_headers(user_id: str) -> dict:
    """For Furnisher (entity_backed:Furnisher). Pass the actual Furnisher.id whenever
    the call is ownership-gated (reverification response / direct re-age)."""
    return build_user_headers(user_id, "Furnisher")


def make_bureau_headers(user_id: str = "test-bureau-1") -> dict:
    """For CreditBureau (opaque)."""
    return build_user_headers(user_id, "CreditBureau")


def make_regulator_headers(user_id: str = "test-regulator-1") -> dict:
    """For Regulator (opaque)."""
    return build_user_headers(user_id, "Regulator")
