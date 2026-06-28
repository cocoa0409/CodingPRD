"""Pre-built role headers for every role in the PRD (§2.1).

Three roles are opaque operator identities (Underwriter, ClaimsAdjuster, Appraiser):
their X-User-ID is not matched against any persisted entity, so a shared constant is
the canonical form. Two roles are entity-backed (Policyholder, RepairShop): ownership
checks compare X-User-ID to the owning entity's id, so for ownership-gated calls the
per-instance builder must be used with the real entity id.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Opaque operator roles — shared constant is canonical.
    "underwriter_headers": build_user_headers("test-underwriter-1", "Underwriter"),
    "claims_adjuster_headers": build_user_headers("test-adjuster-1", "ClaimsAdjuster"),
    "appraiser_headers": build_user_headers("test-appraiser-1", "Appraiser"),
    # Entity-backed roles — shared constant is a fallback for NON-ownership tests only
    # (e.g. 404/422/403-wrong-owner scenarios). Ownership-gated calls must use the
    # per-instance builders below with the real entity id.
    "policyholder_headers": build_user_headers("test-policyholder-1", "Policyholder"),
    "repair_shop_headers": build_user_headers("test-repairshop-1", "RepairShop"),
}


def make_underwriter_headers(user_id: str = "test-underwriter-1") -> dict:
    return build_user_headers(user_id, "Underwriter")


def make_claims_adjuster_headers(user_id: str = "test-adjuster-1") -> dict:
    return build_user_headers(user_id, "ClaimsAdjuster")


def make_appraiser_headers(user_id: str = "test-appraiser-1") -> dict:
    return build_user_headers(user_id, "Appraiser")


def make_policyholder_headers(user_id: str) -> dict:
    """For Policyholder (entity_backed:Policyholder). Pass the actual Policyholder.id
    as user_id whenever the call is ownership-gated (payments, claims, provide_info,
    cancel-own-policy, reads of own resources)."""
    return build_user_headers(user_id, "Policyholder")


def make_repair_shop_headers(user_id: str) -> dict:
    """For RepairShop (entity_backed:RepairShop). Pass the actual RepairShop.id as
    user_id whenever the call is ownership-gated (accept/complete the order assigned
    to that shop)."""
    return build_user_headers(user_id, "RepairShop")
