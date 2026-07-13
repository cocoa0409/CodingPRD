"""Pre-built role headers for every role in the PRD (§2.1).

`CampaignAuthor` and `ComplianceApprover` are entity-backed: their X-User-ID must
be the id of an existing AccountUser whose user_role permits the claimed header.
The shared constants below are therefore ONLY safe for tests that never reach the
identity check (for example a missing-header probe). Every real call must use
make_campaign_author_headers(user["id"]) / make_compliance_approver_headers(user["id"])
with the id returned by POST /accounts/{id}/users.

`PlatformAdmin` is opaque — the server never resolves its id to an entity — so its
shared constant is the canonical form. `Anonymous` carries no X-User-ID at all.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "platform_admin_headers": build_user_headers("platform-admin-1", "PlatformAdmin"),
    # Entity-backed fallbacks — non-identity tests only.
    "campaign_author_headers": build_user_headers("test-author-1", "CampaignAuthor"),
    "compliance_approver_headers": build_user_headers("test-approver-1", "ComplianceApprover"),
}


def make_platform_admin_headers(user_id: str = "platform-admin-1") -> dict:
    """PlatformAdmin identity is opaque and not tied to any persisted entity."""
    return build_user_headers(user_id, "PlatformAdmin")


def make_campaign_author_headers(account_user_id: str) -> dict:
    """CampaignAuthor headers. Pass the AccountUser.id of a CAMPAIGN_AUTHOR or DUAL operator."""
    return build_user_headers(account_user_id, "CampaignAuthor")


def make_compliance_approver_headers(account_user_id: str) -> dict:
    """ComplianceApprover headers. Pass the AccountUser.id of a COMPLIANCE_APPROVER or DUAL operator."""
    return build_user_headers(account_user_id, "ComplianceApprover")


def anonymous_headers() -> dict:
    """Anonymous sends X-User-Role and no X-User-ID at all (PRD §2.1)."""
    return {"X-User-Role": "Anonymous", "Content-Type": "application/json"}


def no_auth_headers() -> dict:
    """No X-User-Role header at all — must draw ERR_UNAUTHENTICATED (PRD §2.1)."""
    return {"Content-Type": "application/json"}


PLATFORM = TEST_USERS["platform_admin_headers"]
ANONYMOUS = anonymous_headers()
NO_AUTH = no_auth_headers()
