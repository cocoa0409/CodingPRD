"""Pre-built role headers for every role in the PRD.

PRD 2.1 binds identity in exactly one of two ways.  When `X-User-Role` is
`Member`, `X-User-ID` is the `id` of the acting Member record, so every
member-scoped call MUST use `make_member_headers(member["id"])`.  For
`Anonymous`, `OperationsManager`, `CustomerService` and `PlatformAdmin` the
`X-User-ID` is an opaque operator identifier never compared to any entity's
`id`, so shared constants are correct for those roles.
"""

from prd_bench_local_runner.testing import build_user_headers

# Shared constants.  Safe for the opaque roles, and for Member-role calls whose
# success does not depend on owning the addressed resource (401/403/404 probes).
TEST_USERS = {
    "anonymous_headers": build_user_headers("anon-visitor-1", "Anonymous"),
    "member_headers": build_user_headers("test-member-unowned", "Member"),
    "ops_headers": build_user_headers("op-warehouse-1", "OperationsManager"),
    "support_headers": build_user_headers("op-support-1", "CustomerService"),
    "admin_headers": build_user_headers("op-admin-1", "PlatformAdmin"),
}

ANONYMOUS = TEST_USERS["anonymous_headers"]
MEMBER_UNOWNED = TEST_USERS["member_headers"]
OPS = TEST_USERS["ops_headers"]
SUPPORT = TEST_USERS["support_headers"]
ADMIN = TEST_USERS["admin_headers"]


def make_member_headers(member_id: str) -> dict:
    """Headers for the Member role.  `X-User-ID` MUST be the acting member's own
    `id` whenever the call is ownership-gated (PRD 2.1)."""
    return build_user_headers(member_id, "Member")


def make_anonymous_headers(user_id: str = "anon-visitor-1") -> dict:
    return build_user_headers(user_id, "Anonymous")


def make_ops_headers(user_id: str = "op-warehouse-1") -> dict:
    return build_user_headers(user_id, "OperationsManager")


def make_support_headers(user_id: str = "op-support-1") -> dict:
    return build_user_headers(user_id, "CustomerService")


def make_admin_headers(user_id: str = "op-admin-1") -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_role_headers(role: str, user_id: str = "op-x-1") -> dict:
    """Arbitrary role/identifier pair — used by the header-validation probes."""
    return build_user_headers(user_id, role)
