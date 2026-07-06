"""Pre-built role headers for every role in the PRD (PRD §2.1).

Excavator, FacilityOwner, and LocateTech are entity-backed: X-User-ID must resolve to an
existing Excavator / MemberUtility / LocateTech record for any ownership-gated call. Use the
per-instance builders with a real entity id in those cases. The shared TEST_USERS constants are
safe only for opaque roles (CallCenter, Admin) or for tests that do not exercise ownership.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — shared constants are the canonical form.
    "call_center_headers": build_user_headers("test-callcenter-1", "CallCenter"),
    "admin_headers": build_user_headers("test-admin-1", "Admin"),
    # Entity-backed roles — shared constants are a fallback for non-ownership tests only.
    "excavator_headers": build_user_headers("test-excavator-1", "Excavator"),
    "facility_owner_headers": build_user_headers("test-facilityowner-1", "FacilityOwner"),
    "locate_tech_headers": build_user_headers("test-locatetech-1", "LocateTech"),
}


def make_excavator_headers(user_id: str) -> dict:
    """For Excavator (entity_backed:Excavator). Pass the actual Excavator.id whenever the call
    is ownership-gated (create/submit/cancel/close a ticket, dispute a damage report)."""
    return build_user_headers(user_id, "Excavator")


def make_facility_owner_headers(user_id: str) -> dict:
    """For FacilityOwner (entity_backed:MemberUtility). Pass the actual MemberUtility.id whenever
    the call is ownership-gated (positive responses, meet schedule/complete/decline, damage
    review/settle, assignment dispatch/cancel by owner)."""
    return build_user_headers(user_id, "FacilityOwner")


def make_locate_tech_headers(user_id: str) -> dict:
    """For LocateTech (entity_backed:LocateTech). Pass the actual LocateTech.id whenever the call
    is ownership-gated (assignment en-route/complete, mark-out create/complete)."""
    return build_user_headers(user_id, "LocateTech")


def call_center_headers() -> dict:
    return TEST_USERS["call_center_headers"]


def admin_headers() -> dict:
    return TEST_USERS["admin_headers"]
