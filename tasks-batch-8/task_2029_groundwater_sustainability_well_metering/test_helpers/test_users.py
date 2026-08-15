"""Pre-built role headers for every role in the PRD (§2.1).

WellOwner is entity-backed: X-User-ID must equal the owning WaterUserAccount.id,
so ownership-gated calls MUST use make_well_owner_headers(account_id) — never the
shared fallback constant. The four agency roles are opaque: their X-User-ID is a
plain operator identifier, and shared constants are safe for them except where a
test needs to control the exact identifier (segregation-of-duties checks), in
which case the per-role builders below take an explicit user_id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that don't exercise ownership.
TEST_USERS = {
    # entity_backed role: fallback for non-ownership tests only (e.g. 404s).
    "well_owner_headers": build_user_headers("test-well-owner-1", "WellOwner"),
    "water_master_headers": build_user_headers("wm-1", "WaterMaster"),
    "enforcement_officer_headers": build_user_headers("eo-1", "EnforcementOfficer"),
    "appeals_officer_headers": build_user_headers("ao-1", "AppealsOfficer"),
    "state_regulator_headers": build_user_headers("sr-1", "StateRegulator"),
}


# Per-instance builders.
def make_well_owner_headers(account_id: str) -> dict:
    """WellOwner is entity-backed: pass the owning WaterUserAccount.id whenever the
    call is ownership-gated (well writes, report submit/resubmit, transfer
    propose/accept/cancel, assessment pay/appeal)."""
    return build_user_headers(account_id, "WellOwner")


def make_water_master_headers(user_id: str = "wm-1") -> dict:
    return build_user_headers(user_id, "WaterMaster")


def make_enforcement_officer_headers(user_id: str = "eo-1") -> dict:
    return build_user_headers(user_id, "EnforcementOfficer")


def make_appeals_officer_headers(user_id: str = "ao-1") -> dict:
    return build_user_headers(user_id, "AppealsOfficer")


def make_state_regulator_headers(user_id: str = "sr-1") -> dict:
    return build_user_headers(user_id, "StateRegulator")
