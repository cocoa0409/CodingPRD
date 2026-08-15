"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that do not exercise
# ownership. Entity-backed roles (CarrierRep, EscortOperator) MUST use the
# per-instance builders below whenever the call is ownership-gated.
TEST_USERS = {
    "dispatcher_headers": build_user_headers("disp-1", "Dispatcher"),
    "route_surveyor_headers": build_user_headers("rs-1", "RouteSurveyor"),
    "safety_manager_headers": build_user_headers("sm-1", "SafetyManager"),
    "billing_clerk_headers": build_user_headers("bc-1", "BillingClerk"),
    "billing_clerk_checker_headers": build_user_headers("bc-2", "BillingClerk"),
    "finance_manager_headers": build_user_headers("fm-1", "FinanceManager"),
    # Fallback only for non-ownership contexts (e.g. forbidden-role probes).
    "carrier_rep_headers": build_user_headers("test-carrier-1", "CarrierRep"),
    "escort_operator_headers": build_user_headers("test-escort-1", "EscortOperator"),
}


def make_carrier_rep_headers(carrier_id: str) -> dict:
    """For CarrierRep (entity-backed by Carrier). Pass the actual Carrier.id
    whenever the call is ownership-gated (book/accept/cancel/dispute)."""
    return build_user_headers(carrier_id, "CarrierRep")


def make_escort_operator_headers(escort_id: str) -> dict:
    """For EscortOperator (entity-backed by Escort). Pass the actual Escort.id
    whenever the call is ownership-gated (accept/decline/check-in)."""
    return build_user_headers(escort_id, "EscortOperator")


def make_dispatcher_headers(user_id: str) -> dict:
    """Dispatcher is opaque; user_id is recorded but never ownership-compared."""
    return build_user_headers(user_id, "Dispatcher")


def make_safety_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SafetyManager")


def make_billing_clerk_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "BillingClerk")


def make_finance_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FinanceManager")
