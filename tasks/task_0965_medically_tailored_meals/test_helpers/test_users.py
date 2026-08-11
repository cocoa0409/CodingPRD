"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise
# ownership. The Member role is entity-backed: the shared constant is only a
# fallback for calls where ownership does not matter.
TEST_USERS = {
    "program_admin_headers": build_user_headers("test-admin-1", "ProgramAdmin"),
    "care_coordinator_headers": build_user_headers("test-coordinator-1", "CareCoordinator"),
    "referring_provider_headers": build_user_headers("test-provider-1", "ReferringProvider"),
    "dietitian_headers": build_user_headers("test-dietitian-1", "Dietitian"),
    "logistics_coordinator_headers": build_user_headers("test-logistics-1", "LogisticsCoordinator"),
    "driver_headers": build_user_headers("test-driver-1", "Driver"),
    "billing_specialist_headers": build_user_headers("bill-1", "BillingSpecialist"),
    "payer_reviewer_headers": build_user_headers("test-payer-1", "PayerReviewer"),
    # entity_backed:Member — fallback only; ownership-gated calls MUST use
    # make_member_headers(member["id"]).
    "member_headers": build_user_headers("test-member-1", "Member"),
}


def make_member_headers(user_id: str) -> dict:
    """For the entity-backed Member role (PRD §2.1): X-User-ID must be the
    acting Member entity's id whenever the call is ownership-gated
    (e.g. confirm-receipt compares X-User-ID to Delivery.member_id)."""
    return build_user_headers(user_id, "Member")


def make_billing_specialist_headers(user_id: str) -> dict:
    """Per-operator headers for BillingSpecialist. Claim submission stamps
    submitted_by_user_id from X-User-ID and segregation of duties bars the
    same operator id from voiding (PRD §3.7), so tests that exercise
    submit/void pairs must pass distinct operator ids."""
    return build_user_headers(user_id, "BillingSpecialist")


def make_operator_headers(user_id: str, role: str) -> dict:
    """Generic per-operator headers for any opaque role."""
    return build_user_headers(user_id, role)
