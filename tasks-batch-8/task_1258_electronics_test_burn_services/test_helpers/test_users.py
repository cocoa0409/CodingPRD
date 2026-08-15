"""Pre-built role headers for every role in the PRD (§2.1).

CustomerRep is entity-backed: its X-User-ID must be the id of the acting
Customer whenever the call is ownership-gated (lot creation, unit
registration on own lots, RMA intake). Use make_customer_rep_headers() with
the real Customer.id in those paths. The shared constant is a fallback only
for tests whose outcome does not depend on the caller owning the resource.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # entity_backed:Customer — fallback for non-ownership tests only.
    "customer_rep_headers": build_user_headers("test-customer-rep-1", "CustomerRep"),
    # opaque roles — shared constants are canonical.
    "test_engineer_headers": build_user_headers("eng-1", "TestEngineer"),
    "test_engineer_2_headers": build_user_headers("eng-2", "TestEngineer"),
    "operations_manager_headers": build_user_headers("ops-1", "OperationsManager"),
    "quality_engineer_headers": build_user_headers("qe-1", "QualityEngineer"),
}


def make_customer_rep_headers(customer_id: str) -> dict:
    """For CustomerRep (entity-backed by Customer). Pass the actual
    Customer.id as customer_id whenever the call is ownership-gated."""
    return build_user_headers(customer_id, "CustomerRep")


def make_test_engineer_headers(user_id: str = "eng-1") -> dict:
    """TestEngineer identity is opaque; distinct ids matter for retest
    segregation of duties (authorizer must differ from recorder)."""
    return build_user_headers(user_id, "TestEngineer")


def make_operations_manager_headers(user_id: str = "ops-1") -> dict:
    return build_user_headers(user_id, "OperationsManager")


def make_quality_engineer_headers(user_id: str = "qe-1") -> dict:
    return build_user_headers(user_id, "QualityEngineer")
