"""Pre-built role headers for every role in the PRD (§2.1).

VendorUser is entity-backed: its X-User-ID MUST equal the acting Vendor.id on
any ownership-gated call. Use make_vendor_user_headers(vendor_id) for those;
the shared constant is only safe for non-ownership contexts (e.g. role-denial
checks where the specific vendor identity is irrelevant).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "manager_headers": build_user_headers("test-manager-1", "SustainabilityManager"),
    "vendor_user_headers": build_user_headers("test-vendor-1", "VendorUser"),
    "steward_headers": build_user_headers("test-steward-1", "DataSteward"),
    "auditor_headers": build_user_headers("test-auditor-1", "WasteAuditor"),
    "officer_headers": build_user_headers("test-officer-1", "CertificationOfficer"),
}


def make_manager_headers(user_id: str = "test-manager-1") -> dict:
    return build_user_headers(user_id, "SustainabilityManager")


def make_vendor_user_headers(user_id: str) -> dict:
    """For VendorUser (entity_backed: Vendor). Pass the actual Vendor.id as
    user_id whenever the call is ownership-gated (ticket create / resubmit)."""
    return build_user_headers(user_id, "VendorUser")


def make_steward_headers(user_id: str = "test-steward-1") -> dict:
    return build_user_headers(user_id, "DataSteward")


def make_auditor_headers(user_id: str = "test-auditor-1") -> dict:
    return build_user_headers(user_id, "WasteAuditor")


def make_officer_headers(user_id: str = "test-officer-1") -> dict:
    return build_user_headers(user_id, "CertificationOfficer")
