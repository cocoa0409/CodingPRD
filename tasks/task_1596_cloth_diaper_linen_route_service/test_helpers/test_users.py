"""Pre-built role headers for every role named in PRD 2.1.

`Customer` is entity-backed: `X-User-ID` must be the acting Customer row's id,
so any ownership-gated call MUST use make_customer_headers(customer_id).
`PlatformAdmin`, `RouteDriver`, `PlantOperator` and `BillingAdmin` carry opaque
identities, so their shared constants are the canonical form. The plant
operator builder takes a user id because the wash batch records the acting
operator in `wash_started_by` / `validated_by` (PRD 3.5).
"""
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque identities — the shared constant is the canonical form.
    "platform_admin_headers": build_user_headers("admin-1", "PlatformAdmin"),
    "route_driver_headers": build_user_headers("drv-1", "RouteDriver"),
    "plant_operator_headers": build_user_headers("op-1", "PlantOperator"),
    "billing_admin_headers": build_user_headers("bill-1", "BillingAdmin"),
    # Entity-backed identity — fallback for non-ownership tests only.
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}


def make_customer_headers(customer_id: str) -> Dict[str, str]:
    """For Customer (entity-backed). Pass the acting Customer's id whenever the
    call is ownership-gated (own subscription, own pauses, own swaps)."""
    return build_user_headers(customer_id, "Customer")


def make_platform_admin_headers(user_id: str = "admin-1") -> Dict[str, str]:
    return build_user_headers(user_id, "PlatformAdmin")


def make_route_driver_headers(user_id: str = "drv-1") -> Dict[str, str]:
    return build_user_headers(user_id, "RouteDriver")


def make_plant_operator_headers(user_id: str = "op-1") -> Dict[str, str]:
    return build_user_headers(user_id, "PlantOperator")


def make_billing_admin_headers(user_id: str = "bill-1") -> Dict[str, str]:
    return build_user_headers(user_id, "BillingAdmin")


# Headers carrying neither X-User-ID nor X-User-Role — used to exercise the
# authentication stage directly.
NO_AUTH_HEADERS: Dict[str, str] = {"Content-Type": "application/json"}
