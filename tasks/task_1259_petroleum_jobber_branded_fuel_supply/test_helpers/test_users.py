"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# DealerOperator ownership.
TEST_USERS = {
    "admin_headers": build_user_headers("ops-admin-1", "JobberAdmin"),
    "pricing_headers": build_user_headers("desk-pricing-1", "PricingDesk"),
    "dispatcher_headers": build_user_headers("dispatch-1", "Dispatcher"),
    "credit_headers": build_user_headers("credit-1", "CreditManager"),
    "tax_headers": build_user_headers("tax-1", "TaxAccountant"),
    "inspector_headers": build_user_headers("brand-1", "BrandInspector"),
    # Fallback for non-ownership contexts only; use make_dealer_operator_headers
    # for any ownership-gated call.
    "dealer_headers": build_user_headers("test-dealer-1", "DealerOperator"),
}


def make_dealer_operator_headers(station_id: str) -> dict:
    """For DealerOperator (entity_backed:DealerStation). Pass the actual
    DealerStation.id whenever the call is ownership-gated (tank gauge, meter
    readings, loss events)."""
    return build_user_headers(station_id, "DealerOperator")


def make_admin_headers(user_id: str) -> dict:
    """JobberAdmin with a specific opaque user id (used for SoD tests where the
    opener and resolver must differ)."""
    return build_user_headers(user_id, "JobberAdmin")
