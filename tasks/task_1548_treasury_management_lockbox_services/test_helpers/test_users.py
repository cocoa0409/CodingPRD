"""Pre-built role headers for every role in the PRD (§2.1).

CustomerOperator is entity-backed by Customer: X-User-ID must be the acting
Customer's id, and ownership-gated calls MUST use make_customer_operator_headers
with the real customer id. Every other role is an opaque operator identifier.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that do not exercise
# ownership (400-on-bad-payload, 404-on-missing-resource, wrong-role checks).
TEST_USERS = {
    "bank_admin_headers": build_user_headers("bank-admin-1", "BankOperationsAdmin"),
    "implementer_headers": build_user_headers("impl-user-1", "TreasuryImplementer"),
    "activator_headers": build_user_headers("act-user-1", "TreasuryActivator"),
    "lockbox_op_headers": build_user_headers("lock-op-1", "LockboxOperator"),
    "lockbox_op2_headers": build_user_headers("lock-op-2", "LockboxOperator"),
    "billing_specialist_headers": build_user_headers("billing-spec-1", "BillingSpecialist"),
    "billing_approver_headers": build_user_headers("billing-appr-1", "BillingApprover"),
    "auditor_headers": build_user_headers("auditor-1", "Auditor"),
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "customer_operator_headers": build_user_headers("test-customer-1", "CustomerOperator"),
}


def make_bank_admin_headers(user_id: str = "bank-admin-1") -> dict:
    return build_user_headers(user_id, "BankOperationsAdmin")


def make_implementer_headers(user_id: str = "impl-user-1") -> dict:
    return build_user_headers(user_id, "TreasuryImplementer")


def make_activator_headers(user_id: str = "act-user-1") -> dict:
    return build_user_headers(user_id, "TreasuryActivator")


def make_lockbox_operator_headers(user_id: str = "lock-op-1") -> dict:
    return build_user_headers(user_id, "LockboxOperator")


def make_billing_specialist_headers(user_id: str = "billing-spec-1") -> dict:
    return build_user_headers(user_id, "BillingSpecialist")


def make_billing_approver_headers(user_id: str = "billing-appr-1") -> dict:
    return build_user_headers(user_id, "BillingApprover")


def make_auditor_headers(user_id: str = "auditor-1") -> dict:
    return build_user_headers(user_id, "Auditor")


def make_customer_operator_headers(customer_id: str) -> dict:
    """For CustomerOperator (entity_backed:Customer). Pass the acting
    Customer.id whenever the call is ownership-gated."""
    return build_user_headers(customer_id, "CustomerOperator")
