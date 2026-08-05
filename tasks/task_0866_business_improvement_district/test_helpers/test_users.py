"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles (DistrictAdministrator, BoardMember,
# TaxCollector) and for tests that do NOT exercise ownership. The two entity-backed
# roles (PropertyOwner, Ambassador) also appear here as a fallback for non-ownership
# tests only; ownership-gated calls MUST use the per-instance builders below.
TEST_USERS = {
    "district_administrator_headers": build_user_headers("admin-1", "DistrictAdministrator"),
    "board_member_headers": build_user_headers("board-1", "BoardMember"),
    "tax_collector_headers": build_user_headers("collector-1", "TaxCollector"),
    "property_owner_headers": build_user_headers("owner-1", "PropertyOwner"),
    "ambassador_headers": build_user_headers("ambassador-1", "Ambassador"),
}


def make_property_owner_headers(parcel_id: str) -> dict:
    """For PropertyOwner (entity_backed:Parcel). Pass the acting Parcel.id as X-User-ID
    whenever the call is ownership-gated (payments, dispute RESPOND/WITHDRAW, signatures,
    own service requests)."""
    return build_user_headers(parcel_id, "PropertyOwner")


def make_ambassador_headers(ambassador_id: str) -> dict:
    """For Ambassador (entity_backed:Ambassador). Pass the acting Ambassador.id as
    X-User-ID whenever the call is ownership-gated (service-request START/RESOLVE)."""
    return build_user_headers(ambassador_id, "Ambassador")


def make_board_member_headers(user_id: str) -> dict:
    """BoardMember with an explicit X-User-ID. BoardMember is opaque, but the four-eyes
    control compares the vote's X-User-ID against the verifier's recorded id, so verify
    and vote must be driven by distinct ids."""
    return build_user_headers(user_id, "BoardMember")


def make_district_administrator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "DistrictAdministrator")


def make_tax_collector_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "TaxCollector")
