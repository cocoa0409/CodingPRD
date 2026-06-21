"""Pre-built role headers for every role in the PRD.

ProgramAdmin, Clinician, and BillingAgent carry opaque operator identifiers
(no entity backing), so their shared constants are the canonical form. Coach
and Member are entity-backed (their X-User-ID is the id of the acting Coach /
Member entity), so ownership-gated calls must use the per-instance builders
``make_coach_headers(coach_id)`` / ``make_member_headers(member_id)`` with the
real entity id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — opaque roles use these canonically; entity-backed roles
# use them only for tests that do NOT exercise ownership.
TEST_USERS = {
    "program_admin_headers": build_user_headers("admin-1", "ProgramAdmin"),
    "clinician_headers": build_user_headers("clinician-1", "Clinician"),
    "billing_agent_headers": build_user_headers("billing-1", "BillingAgent"),
    "coach_headers": build_user_headers("coach-fallback-1", "Coach"),
    "member_headers": build_user_headers("member-fallback-1", "Member"),
}


def make_program_admin_headers(user_id="admin-1") -> dict:
    return build_user_headers(user_id, "ProgramAdmin")


def make_clinician_headers(user_id="clinician-1") -> dict:
    return build_user_headers(user_id, "Clinician")


def make_billing_agent_headers(user_id="billing-1") -> dict:
    return build_user_headers(user_id, "BillingAgent")


def make_coach_headers(user_id: str) -> dict:
    """For Coach (entity_backed:Coach). Pass the actual Coach.id as user_id
    whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Coach")


def make_member_headers(user_id: str) -> dict:
    """For Member (entity_backed:Member). Pass the actual Member.id as user_id
    whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Member")
