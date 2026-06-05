"""Pre-built role headers for every role in the PRD.

Fan is the only entity_backed role: its X-User-ID must equal the acting Fan.id
whenever a call is ownership-gated. Use make_fan_headers(fan_id) in those cases.
Anonymous, PromoterAdmin, and GateScanner are opaque — a shared constant is correct.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Opaque roles — shared constants are the canonical form.
    "anonymous_headers": build_user_headers("anon-1", "Anonymous"),
    "promoter_headers": build_user_headers("promoter-1", "PromoterAdmin"),
    "scanner_headers": build_user_headers("scanner-1", "GateScanner"),
    # entity_backed Fan: shared constant is a fallback for non-ownership tests only.
    "fan_headers": build_user_headers("fan-shared-1", "Fan"),
}


def make_fan_headers(fan_id: str) -> dict:
    """For the entity_backed Fan role. Pass the actual Fan.id as user_id
    whenever the call is ownership-gated (queue join, order, pay, refund,
    transfer party, resale seller/buyer)."""
    return build_user_headers(fan_id, "Fan")
