"""Pre-built role headers for every role in the PRD.

Only RetailerManager is entity-backed: its X-User-ID must equal the acting
agreement's Store id (PRD section 2.1), so ownership-gated calls MUST build
headers with make_retailer_manager_headers(store["id"]). The other four roles
are opaque operator identifiers; the shared constants are canonical for them,
with builders available when a test must pin a specific identity (e.g.
segregation-of-duties scenarios).
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    "jobber_admin_headers": build_user_headers("admin-1", "JobberAdmin"),
    # Fallback for non-ownership reads only — never use for agreement actions.
    "retailer_manager_headers": build_user_headers(
        "test-retailer-manager-1", "RetailerManager"),
    "route_driver_headers": build_user_headers("drv-1", "RouteDriver"),
    "field_auditor_headers": build_user_headers("aud-1", "FieldAuditor"),
    "jobber_finance_headers": build_user_headers("fin-1", "JobberFinance"),
}


def make_jobber_admin_headers(user_id: str) -> dict:
    """JobberAdmin is opaque; pin an identity for SoD-sensitive flows."""
    return build_user_headers(user_id, "JobberAdmin")


def make_retailer_manager_headers(user_id: str) -> dict:
    """RetailerManager is entity-backed by Store: pass the Store's id as
    user_id for every ownership-gated call (accept/reject/confirm/dispute,
    scan ingest, markdown approve/reject, statement dispute)."""
    return build_user_headers(user_id, "RetailerManager")


def make_route_driver_headers(user_id: str) -> dict:
    """RouteDriver is opaque but visit execution compares X-User-ID to the
    route's assigned_driver_id — pass that string for check-in/submit."""
    return build_user_headers(user_id, "RouteDriver")


def make_field_auditor_headers(user_id: str) -> dict:
    """FieldAuditor is opaque; the id is recorded as counted_by_user_id."""
    return build_user_headers(user_id, "FieldAuditor")


def make_jobber_finance_headers(user_id: str) -> dict:
    """JobberFinance is opaque; the id is recorded as created_by_user_id on
    generated settlement statements (drives the approver SoD check)."""
    return build_user_headers(user_id, "JobberFinance")
