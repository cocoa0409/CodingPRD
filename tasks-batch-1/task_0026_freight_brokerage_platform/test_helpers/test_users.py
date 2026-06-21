"""Pre-built role headers for every role in the PRD (PRD §2.1).

Two of the three roles are entity-backed (Shipper, Carrier). For those, tests
that depend on ownership MUST use the per-instance builders
`make_shipper_headers(shipper_id)` / `make_carrier_headers(carrier_id)` — the
shared `TEST_USERS` constants carry placeholder user-id strings that never
equal any real entity's UUID, so falling back to them for ownership-gated
calls reproduces the canonical bug of "every ownership check rejects every
request, Setup failed cascades into every test".

The BrokerOps role is opaque (PRD §2.1) — its `X-User-ID` is a free-form
operator handle, so the shared constant works everywhere it is allowed.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Opaque role — shared constant is the canonical form.
    "broker_ops_headers": build_user_headers("test-broker-ops-1", "BrokerOps"),
    # Entity-backed roles — shared constants are a fallback ONLY for
    # non-ownership tests (401/403/404 paths, malformed payloads, etc.).
    "shipper_headers": build_user_headers("test-shipper-1", "Shipper"),
    "carrier_headers": build_user_headers("test-carrier-1", "Carrier"),
    # Anonymous — request without auth headers.
    "anonymous_headers": {},
}


def make_shipper_headers(shipper_id: str) -> dict:
    """Headers for the Shipper role bound to a specific Shipper.id."""
    return build_user_headers(shipper_id, "Shipper")


def make_carrier_headers(carrier_id: str) -> dict:
    """Headers for the Carrier role bound to a specific Carrier.id."""
    return build_user_headers(carrier_id, "Carrier")


def make_broker_ops_headers(user_id: str = "test-broker-ops-1") -> dict:
    """Headers for the BrokerOps role (PRD §2.1: opaque user-id)."""
    return build_user_headers(user_id, "BrokerOps")


def make_headers(user_id: str, role: str) -> dict:
    """Generic constructor for parametrized RBAC tests."""
    return build_user_headers(user_id, role)
