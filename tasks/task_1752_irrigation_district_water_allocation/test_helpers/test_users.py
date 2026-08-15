"""Pre-built role headers for every role in the PRD (§2.1).

DistrictAdmin and DitchRider identities are opaque operator ids; WaterUser is
entity-backed: its X-User-ID must equal the acting WaterAccount id, so any
ownership-gated call MUST be made with make_water_user_headers(account["id"]).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles: shared constants are the canonical form.
    "district_admin_headers": build_user_headers("district-admin-1", "DistrictAdmin"),
    "ditch_rider_headers": build_user_headers("rider-1", "DitchRider"),
    # Entity-backed role: fallback for non-ownership tests only (e.g., a
    # WaterUser attempting an admin endpoint). Ownership-gated calls must use
    # make_water_user_headers with the real WaterAccount id.
    "water_user_headers": build_user_headers("test-water-user-1", "WaterUser"),
}


def make_water_user_headers(account_id: str) -> dict:
    """WaterUser headers whose X-User-ID is the acting WaterAccount id (PRD §2.1)."""
    return build_user_headers(account_id, "WaterUser")


def make_ditch_rider_headers(rider_user_id: str) -> dict:
    """DitchRider headers for the operator id stored as rider_user_id (PRD §2.1)."""
    return build_user_headers(rider_user_id, "DitchRider")


def make_district_admin_headers(operator_id: str = "district-admin-1") -> dict:
    return build_user_headers(operator_id, "DistrictAdmin")
