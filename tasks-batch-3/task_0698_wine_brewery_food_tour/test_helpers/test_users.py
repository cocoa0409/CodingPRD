"""Pre-built role headers for every role in the PRD (§2.1).

Operator, Guide, Anonymous are opaque identities (X-User-ID not tied to any
entity). PartnerVenue and Guest are entity_backed: when a call is ownership- or
identity-gated, the header's X-User-ID MUST be the actual PartnerVenue.id /
Guest.id — use the make_* builders below.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests whose success does NOT
# depend on the caller owning the subject resource (e.g. 400/404/403-role checks).
TEST_USERS = {
    "operator_headers": build_user_headers("operator-1", "Operator"),
    "guide_headers": build_user_headers("guide-1", "Guide"),
    # entity_backed fallbacks — only for non-ownership tests:
    "partner_venue_headers": build_user_headers("partner-venue-1", "PartnerVenue"),
    "guest_headers": build_user_headers("guest-1", "Guest"),
}

# Anonymous: no auth headers at all (PRD §2.1 — a mutating call with no headers
# fails ERR_UNAUTHENTICATED; public GETs may omit headers).
ANONYMOUS_HEADERS: dict = {}


# Per-instance builders — required for every entity_backed role.
def make_operator_headers(user_id: str = "operator-1") -> dict:
    """Operator is opaque; user_id is recorded but not compared to any entity."""
    return build_user_headers(user_id, "Operator")


def make_guide_headers(user_id: str = "guide-1") -> dict:
    """Guide is opaque; user_id is recorded but not compared to any entity."""
    return build_user_headers(user_id, "Guide")


def make_partner_venue_headers(venue_id: str) -> dict:
    """For PartnerVenue (entity_backed:PartnerVenue). Pass the actual
    PartnerVenue.id as user_id whenever the call is ownership-gated
    (confirm / request-changes / decline on its own venue confirmation)."""
    return build_user_headers(venue_id, "PartnerVenue")


def make_guest_headers(guest_id: str) -> dict:
    """For Guest (entity_backed:Guest). Pass the actual Guest.id as user_id
    on guest-driven booking/waiver calls so X-User-ID is a real entity id."""
    return build_user_headers(guest_id, "Guest")
