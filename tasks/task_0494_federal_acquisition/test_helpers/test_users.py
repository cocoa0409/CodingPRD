"""Pre-built role headers for every role in the PRD (§2.1).

Three roles: ContractingOfficer (opaque operator id), Vendor (entity-backed:
X-User-ID is the acting VendorRegistration.id), Auditor (opaque, read-only).
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants.
#  - ContractingOfficer / Auditor are opaque: the shared constant is the canonical form.
#  - Vendor is entity-backed: the shared constant is a fallback ONLY for tests that do
#    not exercise vendor ownership (e.g. 400-on-bad-payload, 403/401 auth checks). Any
#    ownership-gated vendor call MUST use make_vendor_headers(vendor["id"]).
TEST_USERS = {
    "co_headers": build_user_headers("co-operator-1", "ContractingOfficer"),
    "auditor_headers": build_user_headers("auditor-1", "Auditor"),
    "vendor_headers": build_user_headers("vendor-fallback-1", "Vendor"),
}


def make_co_headers(user_id: str) -> dict:
    """ContractingOfficer headers for a specific operator id.
    Used where the operator identity matters (evaluation chair vs award maker
    segregation-of-duties, PRD §3.4)."""
    return build_user_headers(user_id, "ContractingOfficer")


def make_vendor_headers(user_id: str) -> dict:
    """Vendor headers (entity-backed:VendorRegistration). Pass the actual
    VendorRegistration.id as user_id whenever the call is ownership-gated
    (creating/scoring/submitting that vendor's proposals, its invoices, its protests)."""
    return build_user_headers(user_id, "Vendor")


def make_auditor_headers(user_id: str) -> dict:
    """Auditor headers (opaque, read-only)."""
    return build_user_headers(user_id, "Auditor")
