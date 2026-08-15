"""Pre-built role headers for every role in the PRD (§2.1).

Two roles are entity-backed: Driver binds X-User-ID to a Driver entity id,
StoreReceiver binds X-User-ID to a Store entity id. For those, fixtures that
exercise ownership or segregation MUST call make_driver_headers(driver.id) /
make_store_receiver_headers(store.id) — never the shared constants, which
carry non-entity ids and would fail every ownership check.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles (PlantAdmin, Planner, LineOperator,
# QALead, ThriftClerk, PricingAnalyst) and for the Any pseudo-role on reads.
# The driver/store_receiver entries below are fallbacks for non-ownership
# probes only (e.g. 404-before-ownership is never legitimate; ownership is
# checked at priority 2, so these constants must not be used for real flows).
TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "PlantAdmin"),
    "planner_headers": build_user_headers("test-planner-1", "Planner"),
    "operator_headers": build_user_headers("op-1", "LineOperator"),
    "operator2_headers": build_user_headers("op-2", "LineOperator"),
    "qa_headers": build_user_headers("qa-1", "QALead"),
    "qa2_headers": build_user_headers("qa-2", "QALead"),
    "thrift_headers": build_user_headers("test-thrift-1", "ThriftClerk"),
    "pricing_headers": build_user_headers("test-pricing-1", "PricingAnalyst"),
    # Fallback constants for entity-backed roles — only for non-ownership tests.
    "driver_headers": build_user_headers("test-driver-1", "Driver"),
    "store_receiver_headers": build_user_headers("test-store-1", "StoreReceiver"),
}


# Per-instance builders — required for entity-backed roles on ownership- or
# segregation-gated calls (PRD §2.1).

def make_driver_headers(driver_id: str) -> dict:
    """Driver (entity_backed:Driver). Pass the actual Driver.id whenever the
    call is ownership-gated (route loading/dispatch/complete, stop deliver/skip,
    stale return create) or attribution-gated (recorded_by_driver_id)."""
    return build_user_headers(driver_id, "Driver")


def make_store_receiver_headers(store_id: str) -> dict:
    """StoreReceiver (entity_backed:Store). Pass the actual Store.id whenever
    the call is ownership-gated (request-amendment, dispute)."""
    return build_user_headers(store_id, "StoreReceiver")


def make_operator_headers(user_id: str) -> dict:
    """LineOperator identity is opaque; the server only compares recorded
    X-User-ID strings against each other for segregation of duties (PRD §2.10).
    Use a distinct user_id from the QA verifier on shared flows."""
    return build_user_headers(user_id, "LineOperator")


def make_qa_headers(user_id: str) -> dict:
    """QALead identity is opaque; the server only compares recorded X-User-ID
    strings for segregation of duties (PRD §2.10). Use a distinct user_id from
    the operator/driver on shared flows."""
    return build_user_headers(user_id, "QALead")


def make_planner_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Planner")


def make_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlantAdmin")
