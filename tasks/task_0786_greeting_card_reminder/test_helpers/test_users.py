"""Pre-built role headers for every role in the PRD.

Roles (PRD §2.1):
  - AccountHolder — entity_backed by Account; X-User-ID is the acting Account.id
    and ownership checks compare a resource's account_id to X-User-ID.
  - StudioOperator — opaque identity (operator id not tied to any entity).
  - PlatformAdmin — opaque identity.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the two opaque roles, and for AccountHolder tests
# that do NOT exercise ownership (e.g. 401/403/404 negative cases).
TEST_USERS = {
    "account_holder_headers": build_user_headers("test-account-holder-1", "AccountHolder"),
    "studio_operator_headers": build_user_headers("test-studio-operator-1", "StudioOperator"),
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
}


def make_account_holder_headers(user_id: str) -> dict:
    """For AccountHolder (entity_backed:Account). Pass the real Account.id as
    user_id whenever the call is ownership-gated (create/act on that account's
    contacts, important dates, orders, proofs, subscription)."""
    return build_user_headers(user_id, "AccountHolder")


def make_studio_operator_headers(user_id: str = "test-studio-operator-1") -> dict:
    return build_user_headers(user_id, "StudioOperator")


def make_platform_admin_headers(user_id: str = "test-platform-admin-1") -> dict:
    return build_user_headers(user_id, "PlatformAdmin")
