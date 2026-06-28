"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants.
#  - StudioAdmin and FrontDesk are opaque operator identities (PRD 2.1): the
#    server never compares X-User-ID to any entity id, so a shared constant is
#    the canonical form for them.
#  - The Technician / Member shared constants are fallbacks for tests that do NOT
#    exercise ownership (e.g. 401/403 denial probes). Ownership-gated calls MUST
#    use the per-instance builders below threaded with the real entity id.
TEST_USERS = {
    "studio_admin_headers": build_user_headers("op-admin-1", "StudioAdmin"),
    "front_desk_headers": build_user_headers("op-frontdesk-1", "FrontDesk"),
    "technician_headers": build_user_headers("test-technician-1", "Technician"),
    "member_headers": build_user_headers("test-member-1", "Member"),
}


def make_studio_admin_headers(user_id: str = "op-admin-1") -> dict:
    """StudioAdmin is opaque; user_id is not compared to any entity id."""
    return build_user_headers(user_id, "StudioAdmin")


def make_front_desk_headers(user_id: str = "op-frontdesk-1") -> dict:
    """FrontDesk is opaque; user_id is not compared to any entity id."""
    return build_user_headers(user_id, "FrontDesk")


def make_member_headers(user_id: str) -> dict:
    """For Member (entity_backed:Member). Pass the actual Member.id as user_id
    whenever the call is ownership-gated (book/cancel/freeze/unfreeze/retail/own-reads)."""
    return build_user_headers(user_id, "Member")


def make_technician_headers(user_id: str) -> dict:
    """For Technician (entity_backed:Technician). Pass the actual Technician.id as
    user_id whenever the call is ownership-gated (complete own reservation)."""
    return build_user_headers(user_id, "Technician")
