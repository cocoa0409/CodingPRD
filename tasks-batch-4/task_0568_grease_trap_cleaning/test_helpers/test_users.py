"""Pre-built role headers for every role in the PRD (§2.1).

Four of the five roles (Admin, Dispatcher, ComplianceOfficer, BillingClerk) are opaque:
their X-User-ID is an operator identifier never compared to any entity id, so the shared
constants below are the canonical form. Technician is entity_backed — ownership checks
compare a work order's technician_id to X-User-ID — so tests that exercise ownership MUST
build Technician headers with the actual Technician.id via make_technician_headers().
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — canonical for the four opaque roles; a Technician fallback usable
# only by tests that do not exercise work-order ownership.
TEST_USERS = {
    "admin_headers": build_user_headers("admin-1", "Admin"),
    "dispatcher_headers": build_user_headers("dispatcher-1", "Dispatcher"),
    "compliance_officer_headers": build_user_headers("compliance-1", "ComplianceOfficer"),
    "billing_clerk_headers": build_user_headers("billing-1", "BillingClerk"),
    "technician_headers": build_user_headers("technician-fallback-1", "Technician"),
}


def make_technician_headers(user_id: str) -> dict:
    """For the entity_backed Technician role. Pass the actual Technician.id as user_id
    whenever the call is ownership-gated (start / complete / file manifest / void / certify)."""
    return build_user_headers(user_id, "Technician")


def make_headers(user_id: str, role: str) -> dict:
    """Build headers for an arbitrary (user_id, role) pair."""
    return build_user_headers(user_id, role)
