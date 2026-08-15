"""Pre-built role headers for every role in the PRD (§2.1).

Grower is entity-backed: X-User-ID must equal the acting Customer's `id`
whenever the call is ownership-gated. Use make_grower_headers(customer_id)
for those calls; the shared constant is only safe for tests that do not
exercise ownership (e.g. role-authorization failures).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants for the opaque operator roles (X-User-ID never compared to
# an entity id) and a fallback Grower identity for non-ownership tests.
TEST_USERS = {
    "manager_headers": build_user_headers("mgr-1", "ElevatorManager"),
    "manager2_headers": build_user_headers("mgr-2", "ElevatorManager"),
    "technician_headers": build_user_headers("tech-1", "IntakeTechnician"),
    "technician2_headers": build_user_headers("tech-2", "IntakeTechnician"),
    "operator_headers": build_user_headers("op-1", "DryerOperator"),
    "adjuster_headers": build_user_headers("adj-1", "ClaimsAdjuster"),
    "adjuster2_headers": build_user_headers("adj-2", "ClaimsAdjuster"),
    "grower_headers": build_user_headers("test-grower-1", "Grower"),
}


def make_grower_headers(user_id: str) -> dict:
    """Grower headers whose X-User-ID IS a Customer id (entity-backed role).

    Mandatory for every ownership-gated call: ticket create/cancel/requeue,
    moisture-test dispute, claim file/appeal/withdraw, grower reads, grower
    payments.
    """
    return build_user_headers(user_id, "Grower")


def make_manager_headers(user_id: str) -> dict:
    """ElevatorManager headers with a specific operator id (blend SoD)."""
    return build_user_headers(user_id, "ElevatorManager")


def make_technician_headers(user_id: str) -> dict:
    """IntakeTechnician headers with a specific operator id (retest SoD)."""
    return build_user_headers(user_id, "IntakeTechnician")


def make_operator_headers(user_id: str) -> dict:
    """DryerOperator headers with a specific operator id (claim SoD)."""
    return build_user_headers(user_id, "DryerOperator")


def make_adjuster_headers(user_id: str) -> dict:
    """ClaimsAdjuster headers with a specific operator id (claim SoD)."""
    return build_user_headers(user_id, "ClaimsAdjuster")
