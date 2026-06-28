"""Pre-built role headers for every role in the PRD.

Only the Podiatrist role is entity-backed (X-User-ID must equal the acting
Provider.id for ownership-gated calls such as complete-exam). The other four
roles carry an opaque operator identifier never compared to any entity id.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles, and for tests that do not exercise
# Provider ownership. For Podiatrist this is a fallback usable only when the call
# is NOT ownership-gated (e.g., create-procedure, create-orthotic-rx, which the
# PRD does not gate on provider identity).
TEST_USERS = {
    "practice_admin_headers": build_user_headers("test-admin-1", "PracticeAdmin"),
    "podiatrist_headers": build_user_headers("test-podiatrist-1", "Podiatrist"),
    "billing_specialist_headers": build_user_headers("test-billing-1", "BillingSpecialist"),
    "front_desk_headers": build_user_headers("test-frontdesk-1", "FrontDesk"),
    "payer_agent_headers": build_user_headers("test-payer-1", "PayerAgent"),
}


# Per-instance builder — REQUIRED for the entity-backed Podiatrist role whenever
# the call is ownership-gated (complete-exam). Pass the rendering Provider.id.
def make_podiatrist_headers(provider_id: str) -> dict:
    """Headers for a Podiatrist whose X-User-ID equals the given Provider.id."""
    return build_user_headers(provider_id, "Podiatrist")
