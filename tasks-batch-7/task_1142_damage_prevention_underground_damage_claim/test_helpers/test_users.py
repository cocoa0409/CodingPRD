"""Pre-built role headers for every role in the PRD (§2.1).

Opaque roles (IntakeCoordinator, DamageInvestigator, ClaimsAdjuster,
RecoveryManager) use arbitrary operator identifiers; entity-backed roles
(Excavator, Locator) MUST be built per-instance with the entity's id whenever
the call is ownership-gated.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership (bad-payload 400s, 404s, manager-scoped calls).
TEST_USERS = {
    "intake_headers": build_user_headers("intake-1", "IntakeCoordinator"),
    "investigator_headers": build_user_headers("inv-1", "DamageInvestigator"),
    "adjuster_headers": build_user_headers("adj-1", "ClaimsAdjuster"),
    "manager_headers": build_user_headers("mgr-1", "RecoveryManager"),
    # Entity-backed fallbacks — ONLY for non-ownership tests (e.g. plain GETs).
    "excavator_headers": build_user_headers("test-excavator-1", "Excavator"),
    "locator_headers": build_user_headers("test-locator-1", "Locator"),
}


# ---------------------------------------------------------------------------
# Per-instance builders
# ---------------------------------------------------------------------------
def make_excavator_headers(user_id: str) -> dict:
    """Excavator is entity-backed: pass the actual Excavator.id whenever the
    call is ownership-gated (tickets, renew, payments, disputes, contest,
    training complete)."""
    return build_user_headers(user_id, "Excavator")


def make_locator_headers(user_id: str) -> dict:
    """Locator is entity-backed: pass the actual Locator.id whenever the call
    is ownership-gated (responses, payments, disputes, contest)."""
    return build_user_headers(user_id, "Locator")


def make_intake_headers(user_id: str = "intake-1") -> dict:
    return build_user_headers(user_id, "IntakeCoordinator")


def make_investigator_headers(user_id: str = "inv-1") -> dict:
    """DamageInvestigator is opaque, but the id is recorded as the case's
    investigator_user_id at begin-investigation and matters at finalize time
    (segregation of duties) — pick the id deliberately."""
    return build_user_headers(user_id, "DamageInvestigator")


def make_adjuster_headers(user_id: str = "adj-1") -> dict:
    return build_user_headers(user_id, "ClaimsAdjuster")


def make_manager_headers(user_id: str = "mgr-1") -> dict:
    """RecoveryManager is opaque, but the finalize caller's id must differ from
    the case's investigator_user_id (segregation of duties)."""
    return build_user_headers(user_id, "RecoveryManager")
