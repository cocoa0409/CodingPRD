"""Pre-built role headers for every role in the Boat Club PRD.

- ``ClubAdmin`` and ``DockStaff`` are opaque operator identities (PRD §2.1): their
  ``X-User-ID`` is never compared to any persisted entity, so a shared constant is
  the canonical form.
- ``Member`` is entity-backed: ownership checks compare a resource's member foreign
  key to ``X-User-ID``. Ownership-gated Member calls MUST use ``make_member_headers``
  with the actual Member.id; the shared constant is a fallback only for tests whose
  success does not depend on owning the subject resource.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "club_admin_headers": build_user_headers("test-club-admin-1", "ClubAdmin"),
    "dock_staff_headers": build_user_headers("test-dock-staff-1", "DockStaff"),
    # Fallback Member constant — non-ownership tests only.
    "member_headers": build_user_headers("test-member-1", "Member"),
}


def make_member_headers(user_id: str) -> dict:
    """For the Member role (entity_backed:Member). Pass the actual Member.id as
    user_id whenever the call is ownership-gated (request/confirm/checkout/return/
    cancel a reservation, create an enrollment, pay a dues invoice)."""
    return build_user_headers(user_id, "Member")
