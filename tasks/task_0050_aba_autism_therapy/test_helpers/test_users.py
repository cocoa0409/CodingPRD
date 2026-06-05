"""Pre-built role headers for every role in the PRD.

Two opaque roles (IntakeCoordinator, BillingSpecialist) and the read-only
Caregiver use shared constants. The two entity_backed roles (BCBA, RBT) carry
their X-User-ID = the acting Provider's id, so ownership checks resolve; they
get per-instance builders that MUST be called with the real Provider id whenever
the downstream call is ownership-gated.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles and for non-ownership tests.
TEST_USERS = {
    "intake_headers": build_user_headers("intake-op-1", "IntakeCoordinator"),
    "billing_headers": build_user_headers("billing-op-1", "BillingSpecialist"),
    "caregiver_headers": build_user_headers("caregiver-1", "Caregiver"),
    # Fallback BCBA/RBT constants — ONLY for tests that do not exercise ownership.
    "bcba_headers": build_user_headers("bcba-fallback-1", "BCBA"),
    "rbt_headers": build_user_headers("rbt-fallback-1", "RBT"),
}


# Per-instance builders — required for every entity_backed role.
def make_bcba_headers(provider_id: str) -> dict:
    """For BCBA (entity_backed:Provider). Pass the acting Provider.id as user_id
    whenever the call is ownership-gated (evaluation/plan submit) or otherwise
    identity-sensitive."""
    return build_user_headers(provider_id, "BCBA")


def make_rbt_headers(provider_id: str) -> dict:
    """For RBT (entity_backed:Provider). Pass the acting Provider.id as user_id."""
    return build_user_headers(provider_id, "RBT")


def make_intake_headers(user_id: str = "intake-op-1") -> dict:
    return build_user_headers(user_id, "IntakeCoordinator")


def make_billing_headers(user_id: str = "billing-op-1") -> dict:
    return build_user_headers(user_id, "BillingSpecialist")


def make_caregiver_headers(user_id: str = "caregiver-1") -> dict:
    return build_user_headers(user_id, "Caregiver")
