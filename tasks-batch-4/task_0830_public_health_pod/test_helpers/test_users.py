"""Pre-built role headers for every role in the PRD (§2.1 RBAC)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the four opaque roles, and for Volunteer tests that
# don't exercise ownership. For Volunteer calls gated by resource ownership, use
# make_volunteer_headers(staff_member_id) instead (see below).
TEST_USERS = {
    "public_health_admin_headers": build_user_headers("test-admin-1", "PublicHealthAdmin"),
    "logistics_coordinator_headers": build_user_headers("test-logistics-1", "LogisticsCoordinator"),
    "mutual_aid_partner_headers": build_user_headers("test-partner-1", "MutualAidPartner"),
    "clinical_lead_headers": build_user_headers("test-clinical-1", "ClinicalLead"),
    "volunteer_headers": build_user_headers("test-volunteer-1", "Volunteer"),
}


def make_volunteer_headers(staff_member_id: str) -> dict:
    """For Volunteer (identity: entity_backed:StaffMember). Pass the actual
    StaffMember.id as staff_member_id whenever the call is ownership-gated
    (PRD §2.1: X-User-ID must equal the resource's staff_member_id)."""
    return build_user_headers(staff_member_id, "Volunteer")
