"""Pre-built role headers for every role in the PRD (§2.1).

Identity binding (PRD §2.1):
  - Member    -> entity_backed: X-User-ID is a Member.id; ownership checks compare
                 a resource's member_id to X-User-ID.
  - Volunteer -> entity_backed: X-User-ID is a Volunteer.id; recorded on a loan's
                 checked_out_by_volunteer_id but not subject to ownership gating.
  - Coordinator -> opaque: X-User-ID is an operator id tied to no entity.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the opaque Coordinator role, and for Member/Volunteer
# tests that do NOT exercise ownership (e.g. 401/403/404 paths). Ownership-gated
# success paths MUST use the per-instance builders below with a real entity id.
TEST_USERS = {
    "coordinator_headers": build_user_headers("coordinator-1", "Coordinator"),
    # entity_backed fallbacks (non-ownership tests only):
    "member_headers": build_user_headers("member-shared", "Member"),
    "volunteer_headers": build_user_headers("volunteer-shared", "Volunteer"),
}


def make_coordinator_headers(user_id: str = "coordinator-1") -> dict:
    """Opaque Coordinator identity (not compared to any entity id)."""
    return build_user_headers(user_id, "Coordinator")


def make_member_headers(member_id: str) -> dict:
    """For the Member role (entity_backed:Member). Pass the actual Member.id so the
    ownership check (resource.member_id == X-User-ID) passes on reservation cancel,
    loan renew, fee pay, and hold operations."""
    return build_user_headers(member_id, "Member")


def make_volunteer_headers(volunteer_id: str) -> dict:
    """For the Volunteer role (entity_backed:Volunteer). Pass the actual Volunteer.id;
    checkout records it as checked_out_by_volunteer_id."""
    return build_user_headers(volunteer_id, "Volunteer")
