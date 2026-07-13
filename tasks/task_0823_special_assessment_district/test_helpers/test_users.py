"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — DistrictAdministrator, CountyTreasurer, and Auditor all have an
# `opaque` identity: X-User-ID is a free operator identifier never compared to any entity.
# ParcelOwner is entity_backed:Parcel — the shared constant here is a fallback used ONLY
# for non-ownership tests (e.g. 403-on-wrong-role); ownership-gated calls must instead use
# make_parcel_owner_headers(parcel_id).
TEST_USERS = {
    "admin_headers": build_user_headers("admin-1", "DistrictAdministrator"),
    "treasurer_headers": build_user_headers("treasurer-1", "CountyTreasurer"),
    "auditor_headers": build_user_headers("auditor-1", "Auditor"),
    "parcel_owner_headers": build_user_headers("owner-fallback", "ParcelOwner"),
}


def make_parcel_owner_headers(user_id: str) -> dict:
    """For ParcelOwner (identity entity_backed:Parcel). Pass the owned Parcel.id as
    user_id whenever the call is ownership-gated (protests, own payments, own payoff quotes)."""
    return build_user_headers(user_id, "ParcelOwner")
