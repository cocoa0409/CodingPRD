"""Pre-built role headers for every role in the PRD (§2.1).

Shared constants are safe for opaque roles and for calls whose success does
not depend on the caller owning the subject resource. For CustomerRep — whose
X-User-ID is the id of the acting Customer — ownership-gated calls MUST use
make_customer_rep_headers(<customer id>).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "terminal_manager_headers": build_user_headers("tm-1", "TerminalManager"),
    "terminal_operator_headers": build_user_headers("to-1", "TerminalOperator"),
    "scheduler_headers": build_user_headers("sched-1", "Scheduler"),
    "gauger_headers": build_user_headers("gauger-1", "Gauger"),
    "quality_inspector_headers": build_user_headers("qi-1", "QualityInspector"),
    "billing_clerk_headers": build_user_headers("bc-1", "BillingClerk"),
    # CustomerRep is entity-backed: shared constant only for non-ownership probes.
    "customer_rep_headers": build_user_headers("rep-unknown", "CustomerRep"),
}


def make_customer_rep_headers(customer_id: str) -> dict:
    """CustomerRep is entity-backed: pass the actual Customer.id whenever the
    call is ownership-gated (lease create, amendment propose, custody dispute)."""
    return build_user_headers(customer_id, "CustomerRep")


def make_manager_headers(user_id: str) -> dict:
    """TerminalManager with a specific operator id (segregation-of-duties probes)."""
    return build_user_headers(user_id, "TerminalManager")


def make_gauger_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Gauger")


def make_inspector_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "QualityInspector")
