"""Pre-built role headers for every role in the PRD.

PRD §2.1: SalonManager and FrontDeskAgent are opaque operator identities whose
X-User-ID is not compared to any entity id. Technician and Member are
entity-backed: X-User-ID must equal the acting Technician.id / Member.id, and
ownership checks compare resource foreign keys to it.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise ownership.
TEST_USERS = {
    # Opaque roles: the shared constant is the canonical form.
    "manager_headers": build_user_headers("test-manager-1", "SalonManager"),
    "front_desk_headers": build_user_headers("test-frontdesk-1", "FrontDeskAgent"),
    # Entity-backed roles: shared constant is a fallback for non-ownership tests only
    # (e.g. 401/403/404 checks that never reach an ownership comparison).
    "technician_headers": build_user_headers("test-technician-1", "Technician"),
    "member_headers": build_user_headers("test-member-1", "Member"),
}


# Per-instance builders — required for every entity-backed role.
def make_manager_headers(user_id: str = "test-manager-1") -> dict:
    """SalonManager is opaque; user_id is accepted but never compared to an entity id."""
    return build_user_headers(user_id, "SalonManager")


def make_front_desk_headers(user_id: str = "test-frontdesk-1") -> dict:
    """FrontDeskAgent is opaque; user_id is accepted but never compared to an entity id."""
    return build_user_headers(user_id, "FrontDeskAgent")


def make_technician_headers(user_id: str) -> dict:
    """For Technician (entity_backed:Technician). Pass the actual Technician.id as
    user_id whenever the call is ownership-gated (e.g. complete/line-item by the tech)."""
    return build_user_headers(user_id, "Technician")


def make_member_headers(user_id: str) -> dict:
    """For Member (entity_backed:Member). Pass the actual Member.id as user_id
    whenever the call is ownership-gated (e.g. activate/cancel own package, own reads)."""
    return build_user_headers(user_id, "Member")
