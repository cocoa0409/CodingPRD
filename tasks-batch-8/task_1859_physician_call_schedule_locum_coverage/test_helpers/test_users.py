"""Pre-built role headers for every role in the PRD (§2.1).

SchedulerAdmin, ChiefOfStaff and CredentialingOfficer are opaque roles:
X-User-ID is not tied to any persisted entity. The Physician role is
entity-backed: X-User-ID must equal the acting Physician.id whenever the
call is ownership-gated (own unavailability windows, own swap offers and
offerer-cancels, own backup activations). Use make_physician_headers()
with the real physician id for those calls.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for Physician calls whose
# success does NOT depend on owning the subject resource.
TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "SchedulerAdmin"),
    "chief_headers": build_user_headers("test-chief-1", "ChiefOfStaff"),
    "cred_officer_headers": build_user_headers("test-cred-1", "CredentialingOfficer"),
    # Fallback for non-ownership-gated Physician calls only.
    "physician_headers": build_user_headers("test-physician-1", "Physician"),
}


def make_physician_headers(user_id: str) -> dict:
    """For the entity-backed Physician role. Pass the actual Physician.id as
    user_id whenever the call is ownership-gated (window create/cancel, swap
    offer/claim/offerer-cancel, own backup activation)."""
    return build_user_headers(user_id, "Physician")
