"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants.
#   SalonManager and FrontDesk carry OPAQUE identities (PRD §2.1): X-User-ID is
#   an operator identifier never compared to any entity id, so the shared
#   constant is the canonical form for these two roles.
#   Technician and Client are ENTITY-BACKED: ownership-gated calls MUST use the
#   per-instance builder with the actual entity id (see make_*_headers below).
TEST_USERS = {
    "salon_manager_headers": build_user_headers("test-manager-1", "SalonManager"),
    "front_desk_headers": build_user_headers("test-frontdesk-1", "FrontDesk"),
    # entity_backed fallbacks — only for non-ownership tests (e.g. 401/404 shapes).
    "technician_headers": build_user_headers("test-technician-1", "Technician"),
    "client_headers": build_user_headers("test-client-1", "Client"),
}


# Per-instance builders — required for the entity_backed roles (PRD §2.1).
def make_technician_headers(user_id: str) -> dict:
    """For Technician (entity_backed:Technician). Pass the actual Technician.id
    as user_id whenever the call is ownership-gated (start-service on own
    appointment, recording sanitation, reading own records)."""
    return build_user_headers(user_id, "Technician")


def make_client_headers(user_id: str) -> dict:
    """For Client (entity_backed:Client). Pass the actual Client.id as user_id
    whenever the call is ownership-gated (cancel own appointment, read own
    records)."""
    return build_user_headers(user_id, "Client")
