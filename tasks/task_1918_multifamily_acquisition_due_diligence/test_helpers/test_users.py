"""Pre-built role headers for every role in the PRD (§2.1).

All seven roles are opaque operator identities: the `X-User-ID` header is
never compared to any entity `id`. Segregation-of-duties checks compare the
caller header against stored `*_by_user_id` attribution fields, so tests that
exercise SoD pick distinct operator ids per workflow seat (e.g. um-1/um-2/um-3
for statement creator/reviewer/approver).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — the canonical form for every role in this domain; SoD
# tests build per-seat headers through the make_* builders below.
TEST_USERS = {
    "platform_admin_headers": build_user_headers("pa-1", "PlatformAdmin"),
    "analyst_headers": build_user_headers("aa-1", "AcquisitionsAnalyst"),
    "underwriting_manager_headers": build_user_headers("um-1", "UnderwritingManager"),
    "property_ops_headers": build_user_headers("pol-1", "PropertyOperationsLead"),
    "hr_partner_headers": build_user_headers("hr-1", "HRPartner"),
    "vendor_manager_headers": build_user_headers("vm-1", "VendorManager"),
    "escrow_officer_headers": build_user_headers("eo-1", "EscrowOfficer"),
}


def make_platform_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_analyst_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "AcquisitionsAnalyst")


def make_underwriting_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "UnderwritingManager")


def make_property_ops_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PropertyOperationsLead")


def make_hr_partner_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "HRPartner")


def make_vendor_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "VendorManager")


def make_escrow_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "EscrowOfficer")
