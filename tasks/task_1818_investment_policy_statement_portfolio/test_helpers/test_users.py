"""Pre-built role headers for every role in the PRD (§2.1).

Advisor, ComplianceOfficer, CommitteeMember, CommitteeChair, and PlatformAdmin
are opaque identities: X-User-ID is not tied to any persisted entity, but SoD
rules compare opaque ids (proposer vs voter, recorder vs ratifier), so the
make_* builders accept explicit user ids. Client is entity_backed by Client:
X-User-ID IS the Client.id; ownership-gated calls MUST use
make_client_headers(client["id"]) — never the shared fallback.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership (400-on-bad-payload, 404-on-missing-resource, wrong-role checks).
TEST_USERS = {
    "advisor_headers": build_user_headers("adv-1", "Advisor"),
    "compliance_headers": build_user_headers("co-1", "ComplianceOfficer"),
    "committee_member_headers": build_user_headers("cm-1", "CommitteeMember"),
    "committee_chair_headers": build_user_headers("chair-1", "CommitteeChair"),
    "platform_admin_headers": build_user_headers("admin-1", "PlatformAdmin"),
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "client_headers": build_user_headers("test-client-1", "Client"),
}


def make_advisor_headers(user_id: str = "adv-1") -> dict:
    """Advisor is opaque; pass a distinct id when SoD or audit fields matter."""
    return build_user_headers(user_id, "Advisor")


def make_compliance_headers(user_id: str = "co-1") -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")


def make_committee_member_headers(user_id: str) -> dict:
    """CommitteeMember is opaque; each distinct voter needs a distinct id."""
    return build_user_headers(user_id, "CommitteeMember")


def make_committee_chair_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "CommitteeChair")


def make_platform_admin_headers(user_id: str = "admin-1") -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_client_headers(client_id: str) -> dict:
    """For Client (entity_backed:Client). Pass the actual Client.id as user_id
    whenever the call is ownership-gated."""
    return build_user_headers(client_id, "Client")
