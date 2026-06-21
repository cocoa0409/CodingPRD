"""Pre-built role headers for every role in the PRD (PRD §2.1).

The PRD identifies `AccountOwner` as the only entity-backed role: when
`X-User-Role` is `AccountOwner`, `X-User-ID` must equal the `AccountOwner.id`
of the calling owner. For any ownership-gated call, callers MUST use
`make_account_owner_headers(owner_id)` with a real `AccountOwner.id` — the
shared `TEST_USERS["account_owner_headers"]` constant carries a placeholder
user-id that will never equal any real owner's UUID and would therefore be
rejected with `ERR_UNAUTHORIZED`.

The other two roles (`PlanAdministrator`, `IRSAuditor`) are opaque per
PRD §2.1; the shared constants are the canonical form.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Opaque roles — shared constants are the canonical form (PRD §2.1).
    "plan_admin_headers": build_user_headers(
        "test-plan-admin-1", "PlanAdministrator"
    ),
    "irs_auditor_headers": build_user_headers("test-irs-auditor-1", "IRSAuditor"),
    # Entity-backed role — shared constant is a fallback for non-ownership
    # negative paths (401/404). Real ownership-gated calls must use
    # make_account_owner_headers(owner["id"]).
    "account_owner_headers": build_user_headers(
        "test-account-owner-1", "AccountOwner"
    ),
}


def make_account_owner_headers(owner_id: str) -> dict:
    """Headers for AccountOwner bound to a specific AccountOwner.id (PRD §2.1)."""
    return build_user_headers(owner_id, "AccountOwner")


def make_plan_admin_headers(admin_id: str = "test-plan-admin-1") -> dict:
    return build_user_headers(admin_id, "PlanAdministrator")


def make_irs_auditor_headers(auditor_id: str = "test-irs-auditor-1") -> dict:
    return build_user_headers(auditor_id, "IRSAuditor")


def make_headers(user_id: str, role: str) -> dict:
    """Generic constructor for parametrized RBAC tests."""
    return build_user_headers(user_id, role)
