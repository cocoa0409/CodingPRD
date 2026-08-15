"""Pre-built role headers for every role in the PRD (§2.1).

The Organizer role is entity-backed: X-User-ID must equal the Organizer record's
id for ownership-gated calls, so fixtures MUST thread the real organizer id via
make_organizer_headers(). All other roles are opaque operator identifiers.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — shared constants are the canonical form.
    "anonymous_headers": build_user_headers("anon-1", "Anonymous"),
    "neighbor_headers": build_user_headers("neighbor-1", "Neighbor"),
    "traffic_reviewer_headers": build_user_headers("tr-1", "TrafficReviewer"),
    "safety_reviewer_headers": build_user_headers("sr-1", "SafetyReviewer"),
    "permit_officer_headers": build_user_headers("po-1", "PermitOfficer"),
    "city_admin_headers": build_user_headers("admin-1", "CityAdmin"),
    # Depot officers: two distinct opaque ids for segregation-of-duties flows.
    "depot_officer_1_headers": build_user_headers("depot-1", "DepotOfficer"),
    "depot_officer_2_headers": build_user_headers("depot-2", "DepotOfficer"),
    # Fallback only — never use for ownership-gated Organizer calls.
    "organizer_headers": build_user_headers("test-organizer-1", "Organizer"),
}


def make_organizer_headers(user_id: str) -> dict:
    """Organizer is entity-backed: pass the actual Organizer.id as user_id
    whenever the call is ownership-gated (petition/application/children)."""
    return build_user_headers(user_id, "Organizer")


def make_neighbor_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Neighbor")


def make_depot_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "DepotOfficer")
