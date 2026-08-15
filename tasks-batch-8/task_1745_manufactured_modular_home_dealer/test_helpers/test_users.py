"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that do not exercise
# ownership. For Customer calls that are ownership-gated (warranty create /
# resubmit, trade-in decide) use make_customer_headers(customer["id"]).
TEST_USERS = {
    "admin_headers": build_user_headers("admin-1", "DealershipAdmin"),
    "consultant_headers": build_user_headers("consultant-1", "SalesConsultant"),
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
    "evaluator_headers": build_user_headers("eval-1", "SiteEvaluator"),
    "installer_headers": build_user_headers("install-1", "InstallationManager"),
    "coordinator_headers": build_user_headers("coord-1", "TransportCoordinator"),
    "lender_headers": build_user_headers("lender-1", "LenderAgent"),
    "service_headers": build_user_headers("svc-1", "ServiceManager"),
    "appraiser_headers": build_user_headers("appraiser-1", "Appraiser"),
}


def make_headers(user_id: str, role: str) -> dict:
    return build_user_headers(user_id, role)


def make_customer_headers(user_id: str) -> dict:
    """Customer is entity-backed: X-User-ID must equal the Customer.id whenever
    the call is ownership-gated (warranty create/resubmit, trade-in decide)."""
    return build_user_headers(user_id, "Customer")


def make_site_evaluator_headers(user_id: str) -> dict:
    """record-findings requires X-User-ID == the evaluation's evaluator_id."""
    return build_user_headers(user_id, "SiteEvaluator")


def make_service_manager_headers(user_id: str) -> dict:
    """Distinct ServiceManager users are needed for review vs resolve (SoD)."""
    return build_user_headers(user_id, "ServiceManager")
