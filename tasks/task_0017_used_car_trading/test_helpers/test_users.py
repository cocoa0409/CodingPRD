"""Pre-built role headers for every role in PRD §2.1.

Two forms per role:

- **Shared-constant entries in TEST_USERS** — for tests whose success does NOT
  depend on the caller owning the subject resource (auth-failure tests, plain
  404 probes, RBAC negative tests). Opaque roles (Inspector, PlatformAdmin)
  use the shared constant as their canonical form per PRD §2.1.

- **Per-instance builders make_<role>_headers(user_id)** — REQUIRED for
  every entity-backed role (Seller, Buyer). PRD §2.1: "When X-User-Role is
  Seller, X-User-ID is the id of the acting Seller; ownership checks ...
  compare the resource's foreign-key field to X-User-ID." Fixtures must mint
  X-User-ID equal to the actual entity id whenever the call is ownership-gated;
  otherwise every ownership check rejects every request.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ──────────────────────────────────────────────────────────
# Shared constants — safe for opaque roles, and for tests that don't exercise ownership.
# ──────────────────────────────────────────────────────────

TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque roles — PRD §2.1: "X-User-ID is an opaque operator identifier
    # not tied to any persisted entity".
    "admin_headers": build_user_headers("00000000-0000-4000-8000-00000000ad01", "PlatformAdmin"),
    "inspector_headers": build_user_headers(
        "00000000-0000-4000-8000-0000000a1501", "Inspector"
    ),
    # Entity-backed role fallbacks — only for tests that do NOT exercise ownership.
    "seller_headers": build_user_headers(
        "00000000-0000-4000-8000-00000000fb01", "Seller"
    ),
    "buyer_headers": build_user_headers(
        "00000000-0000-4000-8000-00000000fb02", "Buyer"
    ),
}


# ──────────────────────────────────────────────────────────
# Per-instance builders — REQUIRED for every entity-backed role whenever the
# call is ownership-gated. PRD §2.1: ownership checks compare the resource's
# foreign-key field to X-User-ID.
# ──────────────────────────────────────────────────────────


def make_seller_headers(seller_id: str) -> Dict[str, str]:
    """Build Seller headers where X-User-ID == Seller.id. PRD §2.1: "When
    X-User-Role is Seller, X-User-ID is the id of the acting Seller; ownership
    checks on any resource that references a Seller (notably
    Vehicle.ownership_seller_id, Listing.seller_id, and PurchaseOrder.seller_id)
    compare the resource's foreign-key field to X-User-ID."
    """
    return build_user_headers(seller_id, "Seller")


def make_buyer_headers(buyer_id: str) -> Dict[str, str]:
    """Build Buyer headers where X-User-ID == Buyer.id. PRD §2.1: "When
    X-User-Role is Buyer, X-User-ID is the id of the acting Buyer; ownership
    checks on Bid.buyer_id, Reservation.buyer_id, PurchaseOrder.buyer_id,
    Loan.buyer_id, and any warranty claim, dispute case, or transfer case that
    traces back to one of those rows likewise compare to X-User-ID."
    """
    return build_user_headers(buyer_id, "Buyer")


def make_admin_headers(admin_id: str = "00000000-0000-4000-8000-00000000ad01") -> Dict[str, str]:
    """PlatformAdmin headers. PRD §2.1: X-User-ID is opaque for admins."""
    return build_user_headers(admin_id, "PlatformAdmin")


def make_inspector_headers(
    inspector_id: str = "00000000-0000-4000-8000-0000000a1501",
) -> Dict[str, str]:
    """Inspector headers. PRD §2.1: X-User-ID is opaque for inspectors."""
    return build_user_headers(inspector_id, "Inspector")
