"""Pre-built role headers for every role in the Salon Spa Booking PRD.

Two of the four roles are opaque operator identities (SalonOwner, FrontDesk):
their X-User-ID is not compared to any entity. The other two (Stylist, Client)
are entity-backed: their X-User-ID must equal the acting entity's id whenever
the call is ownership-gated (PRD §2.1). For those, use the per-instance builders.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants.
# - SalonOwner / FrontDesk: opaque — the shared constant is the canonical form.
# - Stylist / Client: entity_backed — the shared constant is a fallback usable
#   ONLY for non-ownership tests (e.g. a 403 that fires before any ownership
#   check, or a read where ownership is not exercised). Ownership-gated calls
#   MUST use make_stylist_headers / make_client_headers with the real entity id.
TEST_USERS = {
    "salon_owner_headers": build_user_headers("owner-1", "SalonOwner"),
    "front_desk_headers": build_user_headers("frontdesk-1", "FrontDesk"),
    "stylist_headers": build_user_headers("stylist-fallback-1", "Stylist"),
    "client_headers": build_user_headers("client-fallback-1", "Client"),
    # An unknown role for the ERR_UNAUTHENTICATED path.
    "nobody_headers": {"X-User-ID": "nobody-1", "X-User-Role": "Nobody",
                       "Content-Type": "application/json"},
}


def make_salon_owner_headers(user_id: str = "owner-1") -> dict:
    """SalonOwner is opaque; user_id is recorded but never compared."""
    return build_user_headers(user_id, "SalonOwner")


def make_front_desk_headers(user_id: str = "frontdesk-1") -> dict:
    """FrontDesk is opaque; user_id is recorded but never compared."""
    return build_user_headers(user_id, "FrontDesk")


def make_stylist_headers(user_id: str) -> dict:
    """For the Stylist role (entity_backed:Stylist). Pass the acting Stylist.id
    so ownership checks comparing a resource's stylist FK to X-User-ID resolve."""
    return build_user_headers(user_id, "Stylist")


def make_client_headers(user_id: str) -> dict:
    """For the Client role (entity_backed:Client). Pass the acting Client.id so
    ownership checks comparing a resource's client FK to X-User-ID resolve."""
    return build_user_headers(user_id, "Client")
