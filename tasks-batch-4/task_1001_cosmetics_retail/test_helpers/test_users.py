"""Pre-built role headers for every role in the PRD (§2.1)."""

from prd_bench_local_runner.testing import build_user_headers

# Shared constants.
#
# StoreAssociate and MerchandisingAdmin have opaque identities: X-User-ID is an
# operator identifier never compared to any entity id, so the shared constant is
# the canonical form for those roles.
#
# Customer and BeautyArtist are entity-backed: X-User-ID must be the acting
# Customer.id / Artist.id. The shared constants below are only safe for tests
# that never reach an ownership comparison (e.g. missing-resource 404s). Every
# ownership-gated call MUST use make_customer_headers() / make_artist_headers().
TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "MerchandisingAdmin"),
    "associate_headers": build_user_headers("test-associate-1", "StoreAssociate"),
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
    "artist_headers": build_user_headers("test-artist-1", "BeautyArtist"),
}

# Headers carrying no identity at all — used to prove the authentication gate.
NO_AUTH_HEADERS = {"Content-Type": "application/json"}


def make_customer_headers(customer_id: str) -> dict:
    """Headers for a Customer. Pass the acting Customer's own id — ownership
    checks compare the resource's customer_id against X-User-ID (PRD §2.1)."""
    return build_user_headers(customer_id, "Customer")


def make_artist_headers(artist_id: str) -> dict:
    """Headers for a BeautyArtist. Pass the acting Artist's own id — X-User-ID is
    the id of the acting Artist entity (PRD §2.1)."""
    return build_user_headers(artist_id, "BeautyArtist")


def make_associate_headers(operator_id: str = "test-associate-1") -> dict:
    """Headers for a StoreAssociate (opaque identity, PRD §2.1)."""
    return build_user_headers(operator_id, "StoreAssociate")


def make_admin_headers(operator_id: str = "test-admin-1") -> dict:
    """Headers for a MerchandisingAdmin (opaque identity, PRD §2.1)."""
    return build_user_headers(operator_id, "MerchandisingAdmin")
