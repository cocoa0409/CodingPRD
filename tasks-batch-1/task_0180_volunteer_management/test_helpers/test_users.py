"""Pre-built role headers for every role in the PRD.

PRD §2.1: X-User-Role is one of Volunteer, ShiftCoordinator, ComplianceOfficer,
CorporateSponsor.

A Volunteer is entity-backed: X-User-ID must equal the acting Volunteer.id, and
ownership checks on a signup compare the signup's volunteer_id to X-User-ID.
Therefore ownership-gated volunteer actions (sign up, confirm, cancel, log-hours)
MUST use make_volunteer_headers(volunteer_id) with the real Volunteer.id.

The other three roles are opaque operator identities not tied to any persisted
entity; their shared-constant headers are the canonical form.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for Volunteer tests that do NOT
# exercise ownership (e.g. header/RBAC/404 checks before ownership comparison).
TEST_USERS = {
    "shift_coordinator_headers": build_user_headers("coordinator-operator-1", "ShiftCoordinator"),
    "compliance_officer_headers": build_user_headers("compliance-operator-1", "ComplianceOfficer"),
    "corporate_sponsor_headers": build_user_headers("sponsor-operator-1", "CorporateSponsor"),
    # Fallback only — never use for an ownership-gated call against a real volunteer.
    "volunteer_headers": build_user_headers("volunteer-fallback-1", "Volunteer"),
}


def make_volunteer_headers(volunteer_id: str) -> dict:
    """For Volunteer (entity_backed:Volunteer). Pass the real Volunteer.id as
    user_id whenever the call is ownership-gated (signup/confirm/cancel/log-hours)."""
    return build_user_headers(volunteer_id, "Volunteer")
