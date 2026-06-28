"""Pre-built role headers for every role in the PRD.

Four roles (PracticeAdmin, FrontDesk, PathLab, BillingSpecialist) are opaque operators:
their X-User-ID is never compared to any entity id, so the shared constant is canonical.

The Provider role is entity-backed: X-User-ID must equal the acting Provider entity's id.
Ownership-gated Provider calls MUST use make_provider_headers(provider["id"]).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — canonical for opaque roles; the Provider shared constant is a
# fallback used only for non-ownership tests (e.g. 403/404 checks).
TEST_USERS = {
    "practice_admin_headers": build_user_headers("test-admin-1", "PracticeAdmin"),
    "front_desk_headers": build_user_headers("test-frontdesk-1", "FrontDesk"),
    "provider_headers": build_user_headers("test-provider-1", "Provider"),
    "path_lab_headers": build_user_headers("test-pathlab-1", "PathLab"),
    "billing_specialist_headers": build_user_headers("test-billing-1", "BillingSpecialist"),
}


def make_provider_headers(user_id: str) -> dict:
    """For Provider (entity_backed:Provider). Pass the actual Provider.id as user_id
    whenever the call is ownership-gated (e.g. start/clinical-close an encounter the
    provider owns, act on biopsies under such an encounter, complete a booking)."""
    return build_user_headers(user_id, "Provider")
