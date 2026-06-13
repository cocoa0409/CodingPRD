"""Pre-built role headers for every role in the PRD (§2.1).

- `Customer` is the only entity_backed role: X-User-ID must equal the acting
  Customer.id. For any ownership-gated trade-in action (quote / ship-kit /
  accept-requote / decline-requote / cancel, and trade-in creation) tests MUST
  call `make_customer_headers(customer_id)` with the actual Customer.id captured
  at fixture time; otherwise PRD §2.1's ownership comparison fails with
  ERR_NOT_OWNER. The shared `customer_headers` fallback is only safe for
  negative tests that do NOT exercise ownership (e.g. a missing-resource 404).
- `CatalogAdmin`, `GradingAgent`, and `FinanceOperator` are opaque operator
  identities (X-User-ID recorded but never compared to any entity id); their
  shared constants are canonical.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS: dict = {
    # opaque operator identities — shared constants are canonical.
    "catalog_admin_headers": build_user_headers("test-catalog-admin", "CatalogAdmin"),
    "grading_agent_headers": build_user_headers("test-grading-agent", "GradingAgent"),
    "finance_operator_headers": build_user_headers("test-finance-operator", "FinanceOperator"),
    # entity_backed Customer — fallback for non-ownership tests only.
    "customer_headers": build_user_headers("test-customer-fallback", "Customer"),
}


def make_customer_headers(customer_id: str) -> dict:
    """Per PRD §2.1, X-User-ID for a Customer MUST equal the acting Customer.id.
    Pass the Customer.id captured at registration time for every ownership-gated
    Customer call."""
    return build_user_headers(customer_id, "Customer")


def make_catalog_admin_headers(user_id: str = "test-catalog-admin") -> dict:
    return build_user_headers(user_id, "CatalogAdmin")


def make_grading_agent_headers(user_id: str = "test-grading-agent") -> dict:
    return build_user_headers(user_id, "GradingAgent")


def make_finance_operator_headers(user_id: str = "test-finance-operator") -> dict:
    return build_user_headers(user_id, "FinanceOperator")


def make_unauthenticated_headers() -> dict:
    """Headers that omit X-User-Role and X-User-ID to trigger ERR_UNAUTHENTICATED (PRD §2.1)."""
    return {"Content-Type": "application/json"}
