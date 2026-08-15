"""Pre-built role headers for every role in the PRD.

PlatformAdmin, TrustAgent, AppealsOfficer, and Sponsor are opaque identities:
X-User-ID is not tied to any persisted entity (Sponsor calls additionally carry
the business identity rule X-User-ID == deal.sponsor_ref, so use
make_sponsor_headers with the deal's sponsor_ref for sponsor-privileged calls).

Creator is entity-backed by Channel and Moderator is entity-backed by
Moderator: X-User-ID must equal the acting entity's id. Ownership-gated calls
MUST use the per-instance builders with the real entity id.
"""
from prd_bench_local_runner.testing import build_user_headers

from .constants import APPEALS_OFFICER_ID, SPONSOR_ACME_ID, TRUST_AGENT_ISSUER_ID

# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership (400-on-bad-payload, 404-on-missing-resource, wrong-role checks).
TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "trust_agent_headers": build_user_headers(TRUST_AGENT_ISSUER_ID, "TrustAgent"),
    "appeals_officer_headers": build_user_headers(APPEALS_OFFICER_ID, "AppealsOfficer"),
    "sponsor_headers": build_user_headers(SPONSOR_ACME_ID, "Sponsor"),
    # entity_backed roles: shared constants are fallbacks for non-ownership tests only.
    "creator_headers": build_user_headers("test-creator-1", "Creator"),
    "moderator_headers": build_user_headers("test-moderator-1", "Moderator"),
}


def make_platform_admin_headers(user_id: str = "test-platform-admin-1") -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_trust_agent_headers(user_id: str = TRUST_AGENT_ISSUER_ID) -> dict:
    return build_user_headers(user_id, "TrustAgent")


def make_appeals_officer_headers(user_id: str = APPEALS_OFFICER_ID) -> dict:
    return build_user_headers(user_id, "AppealsOfficer")


def make_sponsor_headers(sponsor_ref: str = SPONSOR_ACME_ID) -> dict:
    """For Sponsor-privileged actions, X-User-ID must equal deal.sponsor_ref."""
    return build_user_headers(sponsor_ref, "Sponsor")


def make_creator_headers(channel_id: str) -> dict:
    """For Creator (entity_backed:Channel). Pass the owning Channel.id whenever
    the call is ownership-gated."""
    return build_user_headers(channel_id, "Creator")


def make_moderator_headers(moderator_id: str) -> dict:
    """For Moderator (entity_backed:Moderator). Pass the acting Moderator.id
    whenever the call is ownership-gated (e.g. invite ACCEPT)."""
    return build_user_headers(moderator_id, "Moderator")
