"""Pre-built role headers for every role in the Car Shipping PRD.

Two roles are entity-backed (PRD §2.1): `Shipper` (X-User-ID is the Shipper.id)
and `Carrier` (X-User-ID is the Carrier.id). For ownership-gated calls, fixtures
MUST build headers with the real entity id via make_shipper_headers(id) /
make_carrier_headers(id) — never the shared constant, whose static id equals no
real entity and would fail every ownership check.

`Broker` and `Admin` are opaque: X-User-ID is an operator identifier that is
never compared to an entity id, so the shared constants are canonical for them.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — canonical for opaque roles; fallback only for
# non-ownership-gated tests (e.g. 404 / 401 / role-denial probes).
TEST_USERS = {
    # entity_backed roles: shared constant is a fallback for non-ownership tests only.
    "shipper_headers": build_user_headers("test-shipper-1", "Shipper"),
    "carrier_headers": build_user_headers("test-carrier-1", "Carrier"),
    # opaque roles: shared constants are canonical.
    "broker_headers": build_user_headers("test-broker-1", "Broker"),
    "admin_headers": build_user_headers("test-admin-1", "Admin"),
    # Anonymous — no auth headers (for explicit ERR_MISSING_AUTH probes).
    "anonymous_headers": {},
}


def make_shipper_headers(user_id: str) -> dict:
    """For the Shipper role (entity_backed:Shipper). Pass the real Shipper.id as
    user_id whenever the call is ownership-gated (order/vehicle/claim actions)."""
    return build_user_headers(user_id, "Shipper")


def make_carrier_headers(user_id: str) -> dict:
    """For the Carrier role (entity_backed:Carrier). Pass the real Carrier.id as
    user_id whenever the call is ownership-gated (offer/inspection actions)."""
    return build_user_headers(user_id, "Carrier")


def make_broker_headers(opaque_id: str = "test-broker-1") -> dict:
    """For the Broker role (identity: opaque)."""
    return build_user_headers(opaque_id, "Broker")


def make_admin_headers(opaque_id: str = "test-admin-1") -> dict:
    """For the Admin role (identity: opaque)."""
    return build_user_headers(opaque_id, "Admin")
