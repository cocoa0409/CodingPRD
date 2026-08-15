"""Pre-built role headers for every role in the PRD.

Five roles are opaque (X-User-ID not tied to any entity). VendorPortal is
entity-backed: its X-User-ID must equal the path vendor's id, so tests that
exercise portal calls MUST build headers with make_vendor_portal_headers
(vendor["id"]) — never the shared placeholder constant.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "ap_clerk_headers": build_user_headers("test-ap-clerk-1", "APClerk"),
    "tax_specialist_headers": build_user_headers("test-tax-specialist-1", "TaxSpecialist"),
    "tax_transmitter_headers": build_user_headers("test-tax-transmitter-1", "TaxTransmitter"),
    "tax_admin_headers": build_user_headers("test-tax-admin-1", "TaxAdmin"),
    "irs_system_headers": build_user_headers("test-irs-system-1", "IRSSystem"),
    # Placeholder only: real portal calls must use make_vendor_portal_headers(vendor_id).
    "vendor_portal_headers": build_user_headers("test-vendor-portal-placeholder", "VendorPortal"),
}


def make_ap_clerk_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "APClerk")


def make_tax_specialist_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "TaxSpecialist")


def make_tax_transmitter_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "TaxTransmitter")


def make_tax_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "TaxAdmin")


def make_irs_system_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "IRSSystem")


def make_vendor_portal_headers(user_id: str) -> dict:
    """VendorPortal is entity-backed: pass the acting Vendor.id as user_id so
    the ownership check (X-User-ID == path vendor id) can succeed."""
    return build_user_headers(user_id, "VendorPortal")
