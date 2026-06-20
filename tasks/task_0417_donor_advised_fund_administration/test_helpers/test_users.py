"""Pre-built role headers for every role in the PRD.

All five roles are opaque operator roles: X-User-ID is an opaque operator identifier,
not the id of any persisted entity. The DonorAdvisor role is owner-scoped only through a
foreign-key comparison: its X-User-ID must equal the target account's primary_advisor_user_id
for owner-scoped actions. That value is still an opaque string the caller chooses, so a
per-instance builder is provided to thread the correct advisor id into ownership-gated calls.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that do not exercise account ownership.
TEST_USERS = {
    "sponsor_admin_headers": build_user_headers("test-sponsor-admin-1", "SponsorAdmin"),
    "compliance_officer_headers": build_user_headers("test-compliance-1", "ComplianceOfficer"),
    "contribution_admin_headers": build_user_headers("test-contribution-admin-1", "ContributionAdmin"),
    "donor_advisor_headers": build_user_headers("test-donor-advisor-1", "DonorAdvisor"),
    "grant_officer_headers": build_user_headers("test-grant-officer-1", "GrantOfficer"),
}


# Per-instance builders — pass the exact operator id the test/fixture needs.
def make_sponsor_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SponsorAdmin")


def make_compliance_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")


def make_contribution_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ContributionAdmin")


def make_donor_advisor_headers(user_id: str) -> dict:
    """For DonorAdvisor (owner-scoped via primary_advisor_user_id). Pass the account's
    primary_advisor_user_id as user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "DonorAdvisor")


def make_grant_officer_headers(user_id: str) -> dict:
    """For GrantOfficer. Pass the distinct operator id used to satisfy/violate
    segregation of duties relative to the grant's recommended_by_user_id."""
    return build_user_headers(user_id, "GrantOfficer")
