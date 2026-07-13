"""Pre-built role headers for every role in the PRD (§2.1).

`Customer` is the only entity-backed role: its `X-User-ID` IS the id of a real
`Customer` record, and every ownership check compares a resource's `customer_id`
to it. Any ownership-gated call MUST therefore use `make_customer_headers(id)`
with the real customer id — never the shared constant below.

The other five roles have opaque identity: `X-User-ID` is an operator string the
server never compares against an entity id, so the shared constants are canonical.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

TEST_USERS: Dict[str, Dict[str, str]] = {
    # Entity-backed role — this shared constant is only safe for calls that do
    # NOT depend on the caller owning the subject resource (400-on-bad-payload,
    # 404-on-missing-resource, 403-on-wrong-role).
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
    # Opaque operator roles — the shared constants are the canonical form.
    "optician_headers": build_user_headers("test-optician-1", "OpticianVerifier"),
    "store_associate_headers": build_user_headers("test-store-1", "StoreAssociate"),
    "lab_tech_headers": build_user_headers("test-lab-1", "LabTechnician"),
    "benefits_admin_headers": build_user_headers("test-benefits-1", "BenefitsAdmin"),
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
}


def make_customer_headers(customer_id: str) -> Dict[str, str]:
    """Headers for the Customer role. `customer_id` MUST be a real Customer.id —
    PRD §2.1 makes X-User-ID the acting customer's id for every ownership check."""
    return build_user_headers(customer_id, "Customer")


def make_optician_headers(user_id: str = "test-optician-1") -> Dict[str, str]:
    return build_user_headers(user_id, "OpticianVerifier")


def make_store_associate_headers(user_id: str = "test-store-1") -> Dict[str, str]:
    return build_user_headers(user_id, "StoreAssociate")


def make_lab_tech_headers(user_id: str = "test-lab-1") -> Dict[str, str]:
    return build_user_headers(user_id, "LabTechnician")


def make_benefits_admin_headers(user_id: str = "test-benefits-1") -> Dict[str, str]:
    return build_user_headers(user_id, "BenefitsAdmin")


def make_platform_admin_headers(user_id: str = "test-admin-1") -> Dict[str, str]:
    return build_user_headers(user_id, "PlatformAdmin")


# PRD §2.1: a request that omits X-User-ID / X-User-Role is ERR_UNAUTHENTICATED.
NO_AUTH_HEADERS: Dict[str, str] = {"Content-Type": "application/json"}
