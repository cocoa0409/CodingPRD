"""Pre-built role headers for every role in the PRD (section 2.1).

PlatformAdmin, BoardOfficer, BoardMember, and ManagingAgent are opaque
identities: X-User-ID is not tied to any persisted entity, so the shared
constants are canonical. Shareholder is entity-backed (X-User-ID is the acting
Shareholder's id); ownership-gated calls MUST use make_shareholder_headers()
with the real Shareholder.id — never the shared fallback constant.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the opaque roles, and for tests that do not
# exercise ownership (400-on-bad-payload, 404-on-missing-resource, wrong-role).
TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "board_officer_headers": build_user_headers("test-board-officer-1", "BoardOfficer"),
    "board_member_headers": build_user_headers("test-board-member-1", "BoardMember"),
    "managing_agent_headers": build_user_headers("test-managing-agent-1", "ManagingAgent"),
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "shareholder_headers": build_user_headers("test-shareholder-1", "Shareholder"),
}


def make_platform_admin_headers(user_id: str = "test-platform-admin-1") -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_board_officer_headers(user_id: str = "test-board-officer-1") -> dict:
    return build_user_headers(user_id, "BoardOfficer")


def make_board_member_headers(user_id: str) -> dict:
    """BoardMember is opaque; pass the member's operator id (recorded as
    voter_user_id on votes and as panel entries on interviews)."""
    return build_user_headers(user_id, "BoardMember")


def make_managing_agent_headers(user_id: str = "test-managing-agent-1") -> dict:
    return build_user_headers(user_id, "ManagingAgent")


def make_shareholder_headers(shareholder_id: str) -> dict:
    """For Shareholder (entity_backed:Shareholder). Pass the acting
    Shareholder.id whenever the call is ownership-gated (submit/withdraw
    purchase application, submit-info, sublet create/submit, alteration
    lifecycle, ballot casting)."""
    return build_user_headers(shareholder_id, "Shareholder")
