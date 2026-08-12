"""Pre-built role headers for every role in the PRD (§2.1).

MillManager and Nutritionist are opaque roles: X-User-ID is not tied to any
persisted entity, so shared constants are canonical.

Operator, QualityTech and Customer are entity-backed: X-User-ID must be the id
of the acting Employee / Customer. Use the per-instance builders with the real
entity id whenever the call records or checks that identity.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — shared constants are the canonical form.
    "mill_manager_headers": build_user_headers("test-mill-manager-1", "MillManager"),
    "nutritionist_headers": build_user_headers("test-nutritionist-1", "Nutritionist"),
    # Entity-backed roles — fallback constants ONLY for tests that never touch
    # identity-gated resources (e.g. role-denial probes with placeholder ids).
    "operator_headers": build_user_headers("test-operator-1", "Operator"),
    "quality_tech_headers": build_user_headers("test-quality-tech-1", "QualityTech"),
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}


def make_operator_headers(employee_id: str) -> dict:
    """Operator is entity-backed by Employee: pass the real Employee.id."""
    return build_user_headers(employee_id, "Operator")


def make_quality_tech_headers(employee_id: str) -> dict:
    """QualityTech is entity-backed by Employee: pass the real Employee.id."""
    return build_user_headers(employee_id, "QualityTech")


def make_customer_headers(customer_id: str) -> dict:
    """Customer is entity-backed by Customer: pass the real Customer.id."""
    return build_user_headers(customer_id, "Customer")
