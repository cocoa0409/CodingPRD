"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise ownership.
TEST_USERS = {
    "plan_admin_headers": build_user_headers("test-admin-1", "PlanAdmin"),
    "contract_manager_headers": build_user_headers("test-cm-1", "ContractManager"),
    "contract_legal_headers": build_user_headers("test-cl-1", "ContractLegal"),
    "configuration_analyst_headers": build_user_headers("test-ca-1", "ConfigurationAnalyst"),
    "payment_integrity_headers": build_user_headers("test-pi-1", "PaymentIntegrityAnalyst"),
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "provider_rep_headers": build_user_headers("test-rep-1", "ProviderRep"),
}


def make_plan_admin_headers(user_id: str = "test-admin-1") -> dict:
    return build_user_headers(user_id, "PlanAdmin")


def make_contract_manager_headers(user_id: str) -> dict:
    """For ContractManager (opaque). Use a distinct user_id when the flow records
    the caller (e.g. submit-for-signature with 'cm-1')."""
    return build_user_headers(user_id, "ContractManager")


def make_contract_legal_headers(user_id: str) -> dict:
    """For ContractLegal (opaque). Use a distinct user_id for sign (e.g. 'cl-1')."""
    return build_user_headers(user_id, "ContractLegal")


def make_configuration_analyst_headers(user_id: str = "test-ca-1") -> dict:
    return build_user_headers(user_id, "ConfigurationAnalyst")


def make_payment_integrity_headers(user_id: str = "test-pi-1") -> dict:
    return build_user_headers(user_id, "PaymentIntegrityAnalyst")


def make_provider_rep_headers(user_id: str) -> dict:
    """For ProviderRep (entity_backed:Provider). Pass the actual Provider.id as
    user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "ProviderRep")
