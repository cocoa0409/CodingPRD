"""Pre-built role headers for every role in the PRD.

PlanAdmin, ClinicStaff, and BillingAdmin are opaque operator identities — their
X-User-ID is not tied to any persisted entity, so a shared constant is the
canonical form. Member is entity-backed: X-User-ID must equal the acting
MemberAccount's id for ownership-gated calls, so a per-instance builder is
required (use make_member_headers(account_id)).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for Member tests that do NOT
# exercise per-owner ownership (e.g., 401/403/422/404 negative checks).
TEST_USERS = {
    "plan_admin_headers": build_user_headers("test-plan-admin-1", "PlanAdmin"),
    "clinic_staff_headers": build_user_headers("test-clinic-staff-1", "ClinicStaff"),
    "billing_admin_headers": build_user_headers("test-billing-admin-1", "BillingAdmin"),
    # Fallback for non-ownership Member tests only.
    "member_headers": build_user_headers("test-member-1", "Member"),
}


def make_member_headers(account_id: str) -> dict:
    """For Member (entity_backed:MemberAccount). Pass the actual MemberAccount.id
    as user_id whenever the call is ownership-gated (create membership, add pet,
    activate, suspend, resume, plan-change, cancel, remove pet, owner reads)."""
    return build_user_headers(account_id, "Member")
