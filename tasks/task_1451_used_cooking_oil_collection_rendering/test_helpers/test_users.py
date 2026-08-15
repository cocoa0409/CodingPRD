"""Pre-built role headers for every role in the PRD (§2.1).

Six roles carry opaque X-User-ID identifiers; CustomerContact is
entity-backed by Customer, so ownership-gated calls must be made with
make_customer_contact_headers(<customer.id>).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "system_admin_headers": build_user_headers("test-sysadmin-1", "SystemAdmin"),
    "field_ops_headers": build_user_headers("test-fieldops-1", "FieldOpsManager"),
    "dispatcher_headers": build_user_headers("test-dispatcher-1", "RouteDispatcher"),
    # Opaque driver identifier used as a manifest's driver_ref across fixtures.
    "driver_headers": build_user_headers("drv-1", "Driver"),
    "billing_headers": build_user_headers("test-billing-1", "BillingAnalyst"),
    "plant_headers": build_user_headers("test-plant-1", "PlantOperator"),
    # Fallback only for CustomerContact calls that are NOT ownership-gated.
    "customer_contact_headers": build_user_headers(
        "test-customer-contact-1", "CustomerContact"
    ),
}


def make_driver_headers(driver_ref: str) -> dict:
    """Driver headers whose X-User-ID equals the manifest's driver_ref.

    PRD §2.1: a Driver may start, complete, or fail a pickup visit only when
    the acting X-User-ID equals the owning manifest's driver_ref.
    """
    return build_user_headers(driver_ref, "Driver")


def make_customer_contact_headers(customer_id: str) -> dict:
    """CustomerContact headers whose X-User-ID equals the Customer.id.

    PRD §2.1: a CustomerContact may act only on resources belonging to the
    customer whose id equals the caller's X-User-ID.
    """
    return build_user_headers(customer_id, "CustomerContact")
