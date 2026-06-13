"""Pre-built role headers for every role in the PRD (§2.1).

CarrierAdmin, Underwriter, ClaimsAdjuster, System and Any are opaque operator
identities — their X-User-ID is not compared to any persisted entity, so a shared
constant is the canonical form.

Traveler is entity-backed: ownership checks compare X-User-ID against a policy's
owner_traveler_id (or the owning traveler of a claim's policy). For any
ownership-gated call, use make_traveler_headers(traveler_id) with the real
Traveler.id — never the shared TEST_USERS constant.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Opaque operator roles — shared constants are canonical.
    "carrier_admin_headers": build_user_headers("test-carrier-admin-1", "CarrierAdmin"),
    "underwriter_headers": build_user_headers("test-underwriter-1", "Underwriter"),
    "claims_adjuster_headers": build_user_headers("test-claims-adjuster-1", "ClaimsAdjuster"),
    # Entity-backed Traveler — shared constant is a fallback for non-ownership tests
    # (e.g. 401/403/404 on resources the traveler does not own). Ownership-gated
    # calls MUST use make_traveler_headers(traveler_id).
    "traveler_headers": build_user_headers("test-traveler-1", "Traveler"),
}


def make_traveler_headers(traveler_id: str) -> dict:
    """For the Traveler role (entity_backed:Traveler). Pass the actual Traveler.id
    as user_id whenever the call is ownership-gated (own policy / own claim)."""
    return build_user_headers(traveler_id, "Traveler")


def make_carrier_admin_headers(user_id: str = "test-carrier-admin-1") -> dict:
    return build_user_headers(user_id, "CarrierAdmin")


def make_underwriter_headers(user_id: str = "test-underwriter-1") -> dict:
    return build_user_headers(user_id, "Underwriter")


def make_claims_adjuster_headers(user_id: str = "test-claims-adjuster-1") -> dict:
    return build_user_headers(user_id, "ClaimsAdjuster")
