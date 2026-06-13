"""Pre-built role headers for every role in the PRD (§2.1).

BillingClerk, FieldOps, and AssistanceCaseworker are opaque operator identities:
X-User-ID is recorded but never matched against an entity, so a shared constant
is the canonical form. Customer is entity-backed by an Account: ownership checks
compare X-User-ID to the resource's account_id, so Customer headers MUST carry
the actual Account.id via make_customer_headers(account_id).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants.
# - Opaque roles (BillingClerk / FieldOps / AssistanceCaseworker): canonical form.
# - Customer constant: a fallback for tests that do NOT exercise ownership
#   (401/403-by-role/404 paths); ownership-gated calls must use the builder.
TEST_USERS = {
    "billing_clerk_headers": build_user_headers("clerk-1", "BillingClerk"),
    "field_ops_headers": build_user_headers("fieldops-1", "FieldOps"),
    "caseworker_headers": build_user_headers("caseworker-1", "AssistanceCaseworker"),
    "customer_headers": build_user_headers("customer-unowned-1", "Customer"),
}


def make_customer_headers(account_id: str) -> dict:
    """Headers for the Customer role (entity_backed:Account).

    Pass the acting Account.id as user_id so ownership checks (X-User-ID ==
    resource.account_id) pass on customer-scoped reads and writes.
    """
    return build_user_headers(account_id, "Customer")


def make_billing_clerk_headers(user_id: str = "clerk-1") -> dict:
    return build_user_headers(user_id, "BillingClerk")


def make_field_ops_headers(user_id: str = "fieldops-1") -> dict:
    return build_user_headers(user_id, "FieldOps")


def make_caseworker_headers(user_id: str = "caseworker-1") -> dict:
    return build_user_headers(user_id, "AssistanceCaseworker")
