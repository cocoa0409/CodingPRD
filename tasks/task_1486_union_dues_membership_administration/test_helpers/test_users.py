"""Pre-built role headers for every role in the PRD.

The Member role is identity-bound: X-User-ID must be the id of the Member
record being acted on, so ownership-gated calls MUST use
make_member_headers(member["id"]). The opaque roles (ParentBodyAdmin,
LocalAdmin, SecretaryTreasurer, OfficeClerk) accept any operator id; named
operator ids (clerk_1, st_1, admin_1) exist so segregation-of-duties checks
can compare the same person across two calls.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that never exercise
# Member ownership. The member_headers entry is a fallback ONLY for calls
# where the Member role is denied outright or the target is not owned.
TEST_USERS = {
    "parentbody_admin_headers": build_user_headers("pba_1", "ParentBodyAdmin"),
    "local_admin_headers": build_user_headers("admin_1", "LocalAdmin"),
    "secretary_treasurer_headers": build_user_headers("st_1", "SecretaryTreasurer"),
    "office_clerk_headers": build_user_headers("clerk_1", "OfficeClerk"),
    "member_headers": build_user_headers("member-unowned-1", "Member"),
}

# Named operator identities used when segregation-of-duties bookkeeping must
# record and compare X-User-ID values (received_by / posted_by, created_by /
# approved_by).
OFFICE_CLERK_1_HEADERS = build_user_headers("clerk_1", "OfficeClerk")
SECRETARY_TREASURER_1_HEADERS = build_user_headers("st_1", "SecretaryTreasurer")
LOCAL_ADMIN_1_HEADERS = build_user_headers("admin_1", "LocalAdmin")


def make_parentbody_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ParentBodyAdmin")


def make_local_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "LocalAdmin")


def make_secretary_treasurer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SecretaryTreasurer")


def make_office_clerk_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "OfficeClerk")


def make_member_headers(user_id: str) -> dict:
    """For the Member role (identity-bound to a Member record). Pass the actual
    member id whenever the call is ownership-gated (payments, withdraw,
    objector-case file/appeal, transfer initiate/cancel)."""
    return build_user_headers(user_id, "Member")
