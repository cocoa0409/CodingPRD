"""Pre-built role headers for every role in the PRD (PRD §2.1).

`Therapist` is the only entity-backed role (PRD §2.1): when `X-User-Role` is
`Therapist`, `X-User-ID` must equal an existing `Therapist.id`. For any
ownership-gated call, callers MUST use `make_therapist_headers(therapist_id)`
with a real Therapist.id — the shared `TEST_USERS["therapist_headers"]`
constant carries a fake user-id string that never equals any real Therapist's
UUID and would therefore be rejected with ERR_FORBIDDEN.

The other four roles (`PlatformAdmin`, `CaseManager`, `BillingClerk`,
`VAReferralCoordinator`) are opaque; the shared constants are the canonical
form for those.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Opaque roles — shared constants are the canonical form.
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "case_manager_headers": build_user_headers("test-case-manager-1", "CaseManager"),
    "billing_clerk_headers": build_user_headers("test-billing-clerk-1", "BillingClerk"),
    "va_coordinator_headers": build_user_headers(
        "test-va-coordinator-1", "VAReferralCoordinator"
    ),
    # Entity-backed role — shared constant is a fallback for non-ownership
    # negative paths (401/403/404 etc.). Real ownership-gated calls must
    # use make_therapist_headers(therapist["id"]).
    "therapist_headers": build_user_headers("test-therapist-1", "Therapist"),
}


def make_therapist_headers(therapist_id: str) -> dict:
    """Headers for the Therapist role bound to a specific Therapist.id (PRD §2.1)."""
    return build_user_headers(therapist_id, "Therapist")


def make_admin_headers(admin_id: str = "test-admin-1") -> dict:
    return build_user_headers(admin_id, "PlatformAdmin")


def make_case_manager_headers(cm_id: str = "test-case-manager-1") -> dict:
    return build_user_headers(cm_id, "CaseManager")


def make_billing_clerk_headers(bc_id: str = "test-billing-clerk-1") -> dict:
    return build_user_headers(bc_id, "BillingClerk")


def make_va_coordinator_headers(va_id: str = "test-va-coordinator-1") -> dict:
    return build_user_headers(va_id, "VAReferralCoordinator")


def make_headers(user_id: str, role: str) -> dict:
    """Generic constructor for parametrized RBAC tests."""
    return build_user_headers(user_id, role)
