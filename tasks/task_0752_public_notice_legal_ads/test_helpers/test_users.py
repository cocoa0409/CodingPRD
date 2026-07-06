"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles (ComplianceOfficer, PlatformAdmin) and for
# tests that do not exercise entity-backed ownership (e.g. 400/404/401/403-role checks).
TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "compliance_officer_headers": build_user_headers("test-compliance-1", "ComplianceOfficer"),
    # entity_backed roles: shared constant is a fallback for non-ownership tests only.
    "advertiser_headers": build_user_headers("test-advertiser-1", "Advertiser"),
    "publisher_headers": build_user_headers("test-publisher-1", "Publisher"),
}


# Per-instance builders — REQUIRED for every entity_backed role. Ownership-gated calls
# MUST pass the actual entity id as user_id.

def make_advertiser_headers(account_id: str) -> dict:
    """For Advertiser (entity_backed:Account). Pass the acting Account.id as user_id
    whenever the call is ownership-gated (PRD §2.1)."""
    return build_user_headers(account_id, "Advertiser")


def make_publisher_headers(newspaper_id: str) -> dict:
    """For Publisher (entity_backed:Newspaper). Pass the acting Newspaper.id as user_id
    whenever the call is ownership-gated (PRD §2.1)."""
    return build_user_headers(newspaper_id, "Publisher")


def platform_admin_headers() -> dict:
    return TEST_USERS["platform_admin_headers"]


def compliance_officer_headers() -> dict:
    return TEST_USERS["compliance_officer_headers"]
