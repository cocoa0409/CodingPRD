"""Pre-built role headers for every role in the PRD (§2.1).

Three roles (FarmManager, Agronomist, SalesAgent) are opaque: X-User-ID is an
operator identifier not tied to any entity, so the shared constant is canonical.

Applicator is entity-backed: on a restricted-use confirm the acting applicator's
id (X-User-ID) must equal the application's applicator_user_id, else the confirm
is rejected (PRD §2.1, §3.4). Tests that confirm a restricted application MUST
build Applicator headers from the real Applicator.id via make_applicator_headers().
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles, and for tests that do not exercise
# applicator ownership (e.g. confirming a NON-restricted application, where any
# applicator id is accepted; or pure 401/403/404 probes).
TEST_USERS = {
    "farm_manager_headers": build_user_headers("test-farm-manager-1", "FarmManager"),
    "agronomist_headers": build_user_headers("test-agronomist-1", "Agronomist"),
    "applicator_headers": build_user_headers("test-applicator-1", "Applicator"),
    "sales_agent_headers": build_user_headers("test-sales-agent-1", "SalesAgent"),
}


def make_farm_manager_headers(user_id="test-farm-manager-1") -> dict:
    """FarmManager is opaque; user_id is not compared to any entity."""
    return build_user_headers(user_id, "FarmManager")


def make_agronomist_headers(user_id="test-agronomist-1") -> dict:
    """Agronomist is opaque; user_id is not compared to any entity."""
    return build_user_headers(user_id, "Agronomist")


def make_sales_agent_headers(user_id="test-sales-agent-1") -> dict:
    """SalesAgent is opaque; user_id is not compared to any entity."""
    return build_user_headers(user_id, "SalesAgent")


def make_applicator_headers(user_id: str) -> dict:
    """For the Applicator role (entity_backed:Applicator). Pass the actual
    Applicator.id as user_id whenever confirming a restricted application, so the
    identity check (acting id == application.applicator_user_id) passes."""
    return build_user_headers(user_id, "Applicator")
