"""Pre-built role headers for every role in the PRD (§2.1).

GalleryAdmin, Registrar, and SalesAssociate carry opaque X-User-IDs the server
never compares to any entity id, so their shared constants are the canonical
form. Artist is entity_backed: when X-User-Role is Artist, X-User-ID is the id
of the acting Artist record, and ownership checks compare a resource's artist
foreign key to X-User-ID. Ownership-gated Artist calls MUST therefore use the
per-instance builder below with the real Artist.id; the shared constant is only
for tests that don't exercise ownership (e.g. a 403 RBAC denial).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — opaque roles, plus tests that don't exercise ownership.
TEST_USERS = {
    "gallery_admin_headers": build_user_headers("test-admin-1", "GalleryAdmin"),
    "registrar_headers": build_user_headers("test-registrar-1", "Registrar"),
    "sales_associate_headers": build_user_headers("test-sales-1", "SalesAssociate"),
    # entity_backed fallback — used ONLY by non-ownership tests (e.g. 403 RBAC denials).
    "artist_headers": build_user_headers("test-artist-1", "Artist"),
}


# ─── Per-instance builders — required for every entity_backed role ───────────
def make_artist_headers(artist_id: str) -> dict:
    """For Artist (entity_backed:Artist). Pass the real Artist.id as X-User-ID
    whenever the call is ownership-gated."""
    return build_user_headers(artist_id, "Artist")


def make_unknown_role_headers(user_id: str = "ghost-1", role: str = "Ghost") -> dict:
    """Headers carrying an unrecognized X-User-Role, used to exercise the
    ERR_UNAUTHENTICATED path (PRD §2.1: an X-User-Role that is not one of the
    recognized roles is rejected with ERR_UNAUTHENTICATED)."""
    return build_user_headers(user_id, role)
