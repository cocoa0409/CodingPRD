"""Pre-built role headers for every role in the Loyalty Rewards API.

- ProgramAdmin and Anonymous identities are opaque; the shared constants are the
  canonical forms for them.
- Member and PartnerOperator are entity_backed: their X-User-ID is the id of the
  acting Member / PartnerAccount entity. For ownership-gated calls, build headers
  with the actual entity id via make_member_headers(id) / make_partner_operator_headers(id).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque operator identity — never compared to any entity id.
    "program_admin_headers": build_user_headers("test-admin-1", "ProgramAdmin"),
    # entity_backed fallbacks — safe only for non-ownership negative-path tests.
    "member_headers": build_user_headers("test-member-1", "Member"),
    "partner_operator_headers": build_user_headers("test-partner-op-1", "PartnerOperator"),
}


def make_program_admin_headers(user_id: str = "test-admin-1") -> dict:
    """Opaque ProgramAdmin headers."""
    return build_user_headers(user_id, "ProgramAdmin")


def make_member_headers(user_id: str) -> dict:
    """For Member (entity_backed:Member). Pass the actual Member.id as user_id
    whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Member")


def make_partner_operator_headers(user_id: str) -> dict:
    """For PartnerOperator (entity_backed:PartnerAccount). Pass the actual
    PartnerAccount.id as user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "PartnerOperator")


def anonymous_headers() -> dict:
    """Unauthenticated caller: no auth headers at all (negative auth tests)."""
    return {"Content-Type": "application/json"}
