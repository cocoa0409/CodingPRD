"""Pre-built role headers for every role in the PRD (Section 2.1).

Treasurer, Cashier, CollectionsOfficer, and ReliefOfficer carry OPAQUE
identities: X-User-ID is not tied to any persisted entity, so the shared
constants are the canonical form. Where a four-eyes segregation-of-duties
equality is under test (PRD 2.9), a distinct X-User-ID is supplied via the
make_* builders (e.g. make_treasurer_headers("tr-2")).

Taxpayer is entity_backed:Parcel: X-User-ID must equal the acting Parcel.id.
Ownership-gated Taxpayer calls MUST use make_taxpayer_headers(parcel_id).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "treasurer_headers": build_user_headers("treasurer-1", "Treasurer"),
    "cashier_headers": build_user_headers("cashier-1", "Cashier"),
    "collections_headers": build_user_headers("collections-1", "CollectionsOfficer"),
    "relief_headers": build_user_headers("relief-1", "ReliefOfficer"),
    # Taxpayer fallback — only valid where Parcel ownership is not enforced.
    "taxpayer_headers": build_user_headers("taxpayer-unowned", "Taxpayer"),
}


def make_treasurer_headers(user_id: str = "treasurer-1") -> dict:
    return build_user_headers(user_id, "Treasurer")


def make_cashier_headers(user_id: str = "cashier-1") -> dict:
    return build_user_headers(user_id, "Cashier")


def make_collections_headers(user_id: str = "collections-1") -> dict:
    return build_user_headers(user_id, "CollectionsOfficer")


def make_relief_headers(user_id: str = "relief-1") -> dict:
    return build_user_headers(user_id, "ReliefOfficer")


def make_taxpayer_headers(parcel_id: str) -> dict:
    """Taxpayer headers whose X-User-ID equals the owned Parcel.id (PRD 2.1)."""
    return build_user_headers(parcel_id, "Taxpayer")


def anonymous_headers() -> dict:
    """Headers with NO X-User-Role, for unauthenticated-request tests."""
    return {"X-User-ID": "anon", "Content-Type": "application/json"}
