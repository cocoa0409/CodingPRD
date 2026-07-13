"""Pre-built role headers for every role in the PRD.

Carrier is entity_backed:Carrier — ownership-gated Carrier calls MUST use
make_carrier_headers(carrier_id) with the real Carrier.id. The other four
roles are opaque operator identifiers; their shared constants are canonical.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for Carrier tests that do not
# exercise ownership (e.g. 401/403/404 where no real carrier owns the target).
TEST_USERS = {
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "carrier_headers": build_user_headers("test-carrier-1", "Carrier"),
    # opaque roles: shared constant is the canonical form.
    "permit_officer_headers": build_user_headers("test-permit-officer-1", "PermitOfficer"),
    "bridge_engineer_headers": build_user_headers("test-bridge-engineer-1", "BridgeEngineer"),
    "enforcement_officer_headers": build_user_headers("test-enforcement-1", "EnforcementOfficer"),
    "dot_admin_headers": build_user_headers("test-dot-admin-1", "DOTAdmin"),
}


# Per-instance builder — required for the entity_backed Carrier role.
def make_carrier_headers(user_id: str) -> dict:
    """For Carrier (entity_backed:Carrier). Pass the actual Carrier.id as user_id
    whenever the call is ownership-gated (submit, complete, edit, add segment,
    confirm/cancel escort, accept-conditions, contest)."""
    return build_user_headers(user_id, "Carrier")
