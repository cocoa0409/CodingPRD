"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles (Anonymous / Registrar / Admin carry no
# ownership meaning, PRD §2.1), and for tests that don't exercise ownership.
TEST_USERS = {
    # opaque role: shared constant is the canonical form.
    "anonymous_headers": build_user_headers("anon-1", "Anonymous"),
    "registrar_headers": build_user_headers("registrar-1", "Registrar"),
    "admin_headers": build_user_headers("admin-1", "Admin"),
    # entity_backed roles: shared constants are fallbacks for non-ownership tests only.
    "owner_headers": build_user_headers("owner-1", "Owner"),
    "partner_headers": build_user_headers("partner-1", "Partner"),
}


# Per-instance builders — required for entity_backed roles (PRD §2.1):
# Owner: X-User-ID is the acting Owner's id; Partner: X-User-ID is the PartnerOrg id.
def make_owner_headers(user_id: str) -> dict:
    """For Owner (entity_backed:Owner). Pass the actual Owner.id as user_id
    whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Owner")


def make_partner_headers(org_id: str) -> dict:
    """For Partner (entity_backed:PartnerOrg). Pass the actual PartnerOrg.id as
    org_id whenever the call is org-scoped."""
    return build_user_headers(org_id, "Partner")
