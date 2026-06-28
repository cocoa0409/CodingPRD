"""Pre-built role headers for every role in the PRD (§2.1).

PracticeAdmin, FrontDesk, and BillingSpecialist carry opaque X-User-IDs the
server never compares to an entity id, so their shared constants are the
canonical form. Consultant and Client are entity_backed: their X-User-ID must
equal the acting Consultant.id / Client.id, so ownership-gated calls MUST use
the per-instance builders below with the real entity id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — opaque roles, plus tests that don't exercise ownership.
TEST_USERS = {
    "practice_admin_headers": build_user_headers("test-admin-1", "PracticeAdmin"),
    "front_desk_headers": build_user_headers("test-frontdesk-1", "FrontDesk"),
    "billing_specialist_headers": build_user_headers("test-billing-1", "BillingSpecialist"),
    # entity_backed fallbacks — used ONLY by non-ownership tests (e.g. 403 RBAC denials).
    "consultant_headers": build_user_headers("test-consultant-1", "Consultant"),
    "client_headers": build_user_headers("test-client-1", "Client"),
}


# ─── Per-instance builders — required for every entity_backed role ───────────

def make_consultant_headers(consultant_id: str) -> dict:
    """For Consultant (entity_backed:Consultant). Pass the real Consultant.id as
    X-User-ID whenever the call is ownership-gated."""
    return build_user_headers(consultant_id, "Consultant")


def make_client_headers(client_id: str) -> dict:
    """For Client (entity_backed:Client). Pass the real Client.id as X-User-ID
    whenever the call is ownership-gated."""
    return build_user_headers(client_id, "Client")
