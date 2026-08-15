"""Pre-built role headers for every role in the PRD.

The Customer role is entity-backed: X-User-ID must equal the acting Customer's
id for ownership-gated calls. Use make_customer_headers(customer_id) for those;
the shared TEST_USERS["customer_headers"] entry is a fallback only for tests
that do not exercise ownership (e.g., RBAC denials against missing resources).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "estimator_headers": build_user_headers("test-estimator-1", "Estimator"),
    # Fallback ONLY for Customer calls whose success does not depend on owning
    # the target resource (e.g., 403/404 paths).
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
    "prepress_headers": build_user_headers("test-prepress-1", "PrepressOperator"),
    "scheduler_headers": build_user_headers("test-scheduler-1", "PressScheduler"),
    "purchasing_headers": build_user_headers("test-purchasing-1", "PurchasingManager"),
    "mail_headers": build_user_headers("test-mail-1", "MailSpecialist"),
    "plant_manager_headers": build_user_headers("test-plant-manager-1", "PlantManager"),
}


def make_customer_headers(customer_id: str) -> dict:
    """Customer is entity-backed: pass the actual Customer.id for
    ownership-gated calls (accept, decline, proof approve/changes, dispute,
    claim filing, own-resource reads)."""
    return build_user_headers(customer_id, "Customer")


def make_plant_manager_headers(user_id: str) -> dict:
    """PlantManager is opaque, but claim segregation-of-duties compares
    X-User-ID values, so distinct operator ids are needed for review vs
    approve/deny. Use make_plant_manager_headers('pm-1') etc."""
    return build_user_headers(user_id, "PlantManager")
