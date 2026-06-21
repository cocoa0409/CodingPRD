"""Pre-built role headers for every role in the PRD.

Four roles (FestivalDirector, BoxOffice, VendorManager, GateAttendant) carry an
opaque identity — the X-User-ID is an operator identifier not tied to any entity.
The Vendor role is entity-backed: its X-User-ID must be the acting Vendor entity's
id for ownership-gated transitions (pay-fee, confirm, withdraw), so it gets a
per-instance builder make_vendor_headers(vendor_id).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that do not exercise
# Vendor ownership. The "vendor_headers" entry is a non-ownership fallback only.
TEST_USERS = {
    "director_headers": build_user_headers("test-director-1", "FestivalDirector"),
    "boxoffice_headers": build_user_headers("test-boxoffice-1", "BoxOffice"),
    "vendor_manager_headers": build_user_headers("test-vendor-manager-1", "VendorManager"),
    "gate_attendant_headers": build_user_headers("test-gate-1", "GateAttendant"),
    # Entity-backed role: shared constant is a fallback for non-ownership tests only.
    "vendor_headers": build_user_headers("test-vendor-1", "Vendor"),
}


def make_vendor_headers(vendor_id: str) -> dict:
    """For the Vendor role (entity_backed:Vendor). Pass the actual Vendor.id as
    user_id whenever the call is ownership-gated (pay-fee, confirm, withdraw)."""
    return build_user_headers(vendor_id, "Vendor")
