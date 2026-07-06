"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles (RegulatorAuditor, PublicViewer) whose
# X-User-ID is never compared to any entity id, and for Treasurer/LobbyRegistrant only
# in tests that do NOT exercise ownership (e.g. 401/404/pre-creation register calls).
TEST_USERS = {
    "regulator_headers": build_user_headers("agency-op-1", "RegulatorAuditor"),
    "public_headers": build_user_headers("public-1", "PublicViewer"),
    # entity_backed fallbacks — for register calls (no owner check) or non-ownership tests.
    "treasurer_headers": build_user_headers("treasurer-1", "Treasurer"),
    "registrant_headers": build_user_headers("registrant-1", "LobbyRegistrant"),
}

# Request with no authentication headers at all (for ERR_UNAUTHENTICATED tests).
NO_AUTH_HEADERS: dict = {}


# Per-instance builders — required for every entity_backed role.
def make_treasurer_headers(committee_id: str) -> dict:
    """For Treasurer (entity_backed:Committee). Pass the owning Committee.id as X-User-ID
    whenever the call is ownership-gated (contribution/expenditure/report writes, terminate)."""
    return build_user_headers(committee_id, "Treasurer")


def make_registrant_headers(registrant_id: str) -> dict:
    """For LobbyRegistrant (entity_backed:LobbyingRegistrant). Pass the owning
    LobbyingRegistrant.id as X-User-ID whenever the call is ownership-gated
    (client/activity writes, terminate)."""
    return build_user_headers(registrant_id, "LobbyRegistrant")
