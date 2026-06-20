"""Pre-built role headers for every role in the PRD.

Per PRD section 2.1, AgencyAdmin, Scheduler, and BillingClerk are opaque
operator identifiers; their X-User-ID is not compared to any entity. The
Caregiver role is entity-backed: X-User-ID is the id of the acting Caregiver
entity, and ownership checks on caregiver-referencing resources compare the
resource's caregiver foreign key to X-User-ID. Any ownership-gated caregiver
call MUST therefore use make_caregiver_headers(<caregiver_id>).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for caregiver tests that do not
# exercise ownership (e.g. 400-on-bad-payload, 404-on-missing-resource).
TEST_USERS = {
    "agency_admin_headers": build_user_headers("test-admin-1", "AgencyAdmin"),
    "scheduler_headers": build_user_headers("test-scheduler-1", "Scheduler"),
    "billing_clerk_headers": build_user_headers("test-billing-1", "BillingClerk"),
    # Caregiver fallback (entity_backed): only for non-ownership tests.
    "caregiver_headers": build_user_headers("test-caregiver-1", "Caregiver"),
}


def make_agency_admin_headers(user_id: str = "test-admin-1") -> dict:
    return build_user_headers(user_id, "AgencyAdmin")


def make_scheduler_headers(user_id: str = "test-scheduler-1") -> dict:
    return build_user_headers(user_id, "Scheduler")


def make_billing_clerk_headers(user_id: str = "test-billing-1") -> dict:
    return build_user_headers(user_id, "BillingClerk")


def make_caregiver_headers(user_id: str) -> dict:
    """For the Caregiver role (entity_backed:Caregiver). Pass the actual
    Caregiver.id as user_id whenever the call (clock-in/out, depart, mileage)
    is ownership-gated."""
    return build_user_headers(user_id, "Caregiver")
