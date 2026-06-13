"""Pre-built role headers for every role in the PRD (§2.1).

Three roles carry an opaque identity (ConcessionsManager, StockRunner,
StandOperator): X-User-ID is an opaque operator id never compared to any
entity. The Patron role is entity-backed: X-User-ID must be the acting
Patron entity's id, and order ownership compares the order's patron_id to it.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the three opaque roles, and for Patron tests that
# do NOT exercise order ownership (e.g. forbidden-role, register-patron, reads).
TEST_USERS = {
    "manager_headers": build_user_headers("test-manager-1", "ConcessionsManager"),
    "runner_headers": build_user_headers("test-runner-1", "StockRunner"),
    "operator_headers": build_user_headers("test-operator-1", "StandOperator"),
    # Patron entity_backed: this shared constant is a fallback for non-ownership tests only.
    "patron_headers": build_user_headers("test-patron-1", "Patron"),
}


# Per-instance builder — required for the entity_backed Patron role.
def make_patron_headers(patron_id: str) -> dict:
    """For the Patron role (entity_backed:Patron). Pass the actual Patron.id as
    user_id whenever the call is order-ownership-gated."""
    return build_user_headers(patron_id, "Patron")


# Opaque-role builders (identity not compared to any entity; provided for symmetry).
def make_manager_headers(user_id: str = "test-manager-1") -> dict:
    return build_user_headers(user_id, "ConcessionsManager")


def make_runner_headers(user_id: str = "test-runner-1") -> dict:
    return build_user_headers(user_id, "StockRunner")


def make_operator_headers(user_id: str = "test-operator-1") -> dict:
    return build_user_headers(user_id, "StandOperator")
