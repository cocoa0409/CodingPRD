"""Pre-built role headers for every role in the PRD (PRD §2.1).

PRD §2.1: the system recognizes exactly three roles — Owner, WarrantyAdmin,
ClaimsProcessor. When X-User-Role is Owner, X-User-ID is the id of the acting
Owner record and ownership checks compare a resource's owner FK to X-User-ID;
Owner is therefore entity_backed and any ownership-gated call MUST use
`make_owner_headers(owner["id"])`. WarrantyAdmin and ClaimsProcessor X-User-IDs
are opaque operator identifiers not tied to any persisted entity, so their
shared constants are the canonical form.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Owner is entity_backed: this shared constant is a FALLBACK for tests that
    # do NOT exercise ownership (e.g., 401/403/404/400 paths). Ownership-gated
    # calls MUST use make_owner_headers(owner_id) with a real Owner.id.
    "owner_headers": build_user_headers("test-owner-1", "Owner"),
    # WarrantyAdmin / ClaimsProcessor are opaque: shared constants are canonical.
    "warranty_admin_headers": build_user_headers("test-admin-1", "WarrantyAdmin"),
    "claims_processor_headers": build_user_headers("test-cp-1", "ClaimsProcessor"),
}


def make_owner_headers(owner_id: str) -> dict:
    """Headers for an Owner bound to a specific Owner.id (PRD §2.1).

    Any call whose success depends on ownership — filing/withdrawing a claim,
    initiating/accepting/rejecting a transfer, cancelling an extension —
    MUST pass the real Owner.id here so X-User-ID matches the resource's owner
    foreign key.
    """
    return build_user_headers(owner_id, "Owner")


def make_warranty_admin_headers(user_id: str = "test-admin-1") -> dict:
    """Headers for a WarrantyAdmin (PRD §2.1: opaque operator identifier)."""
    return build_user_headers(user_id, "WarrantyAdmin")


def make_claims_processor_headers(user_id: str = "test-cp-1") -> dict:
    """Headers for a ClaimsProcessor (PRD §2.1: opaque operator identifier).

    The id is recorded into Claim.claims_processor_user_id at RMA issuance but
    is never compared to any entity id.
    """
    return build_user_headers(user_id, "ClaimsProcessor")


def make_headers(user_id: str, role: str) -> dict:
    """Generic constructor for parametrized RBAC tests."""
    return build_user_headers(user_id, role)
