"""Pre-built role headers for every role in the PRD (§2.1).

ProgramAdmin and OperationsAgent are opaque identities — the shared constant is
the canonical form. Member is entity_backed:Member, so ownership-gated calls MUST
use make_member_headers(member["id"]); the shared constant is only a fallback for
non-ownership tests (e.g. unauthorized/forbidden checks).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "admin_headers": build_user_headers("admin-1", "ProgramAdmin"),
    "agent_headers": build_user_headers("agent-1", "OperationsAgent"),
    # entity_backed fallback: never use for ownership-gated success paths.
    "member_headers": build_user_headers("member-shared-1", "Member"),
}


def make_member_headers(user_id):
    """Member is entity_backed:Member — pass the actual Member.id as X-User-ID
    whenever the call is ownership-gated (issue/cancel/withdraw/settle/reverse,
    and quoting/gifting as the acting member)."""
    return build_user_headers(user_id, "Member")
