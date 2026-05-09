"""Pre-built role headers for every role in the PRD.

PRD §2.1 distinguishes roles by identity binding:

- PlatformAdmin: opaque — X-User-ID is not compared to any entity row.
- RegulatoryGateway: opaque — X-User-ID is not compared to any entity row.
- VendorAdmin: entity-backed on Vendor — ownership-gated calls (most
  importantly resubmit-qualification) compare X-User-ID to vendor.id.
- PrescriptionReviewer / PharmacistReReviewer / Pharmacist: entity-backed on
  Pharmacist — X-User-ID is the acting Pharmacist.id. The segregation-of-duties
  rule (PRD §3.6) compares X-User-ID byte-equal to prescription.reviewer_pharmacist_id.
- Customer: entity-backed on Customer — placing/paying/cancelling an order
  requires X-User-ID == order.customer_id.

For every entity-backed role, ownership-gated calls MUST use the per-instance
builder make_<role>_headers(actual_entity_id). The shared TEST_USERS constants
exist only as a fallback for tests whose success does NOT depend on owning a
specific resource (e.g., 400 on bad payload, 404 on missing path,
ERR_INSUFFICIENT_PERMISSIONS where the role is rejected before identity check).
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles; for entity-backed roles, use
# only when the test does not exercise an ownership comparison.
TEST_USERS = {
    # Opaque roles — shared constants are canonical (PRD §2.1).
    "admin_headers": build_user_headers("admin-001", "PlatformAdmin"),
    "regulatory_headers": build_user_headers("reg-001", "RegulatoryGateway"),

    # Entity-backed roles — shared constants are FALLBACK for non-ownership tests.
    "vendor_admin_headers": build_user_headers("test-vendor-admin-001", "VendorAdmin"),
    "prescription_reviewer_headers": build_user_headers("test-pr-001", "PrescriptionReviewer"),
    "pharmacist_re_reviewer_headers": build_user_headers("test-rr-001", "PharmacistReReviewer"),
    "pharmacist_headers": build_user_headers("test-ph-001", "Pharmacist"),
    "customer_headers": build_user_headers("test-customer-001", "Customer"),
}


# --- Per-instance builders for entity-backed roles ---
# Each builder threads the actual entity id through X-User-ID so that
# ownership checks (PRD §2.1, §3.1, §3.5, §3.6) succeed for real-world flows.

def make_admin_headers(admin_id: str = "admin-001") -> dict:
    """PlatformAdmin headers; identity is opaque per PRD §2.1.

    Optional admin_id allows tests that need to distinguish two admin
    operators in audit log assertions. The server does not compare
    X-User-ID to any entity id for this role.
    """
    return build_user_headers(admin_id, "PlatformAdmin")


def make_regulatory_headers(operator_id: str = "reg-001") -> dict:
    """RegulatoryGateway headers; identity is opaque per PRD §2.1."""
    return build_user_headers(operator_id, "RegulatoryGateway")


def make_vendor_admin_headers(vendor_id: str) -> dict:
    """VendorAdmin headers. PRD §2.1: 'When X-User-Role is VendorAdmin,
    X-User-ID is the id of the acting Vendor; ownership checks on any
    resource that references a Vendor (most importantly,
    resubmit-qualification on a vendor) compare the resource's vendor
    foreign key to X-User-ID.'

    Pass the actual Vendor.id whenever the request is ownership-gated.
    """
    return build_user_headers(vendor_id, "VendorAdmin")


def make_prescription_reviewer_headers(pharmacist_id: str) -> dict:
    """PrescriptionReviewer headers. PRD §2.1: X-User-ID is the id of the
    acting Pharmacist. PRD §3.4: approval sets reviewer_pharmacist_id =
    X-User-ID; the segregation-of-duties rule later compares this id
    byte-equal to the second-line pharmacist's X-User-ID.
    """
    return build_user_headers(pharmacist_id, "PrescriptionReviewer")


def make_pharmacist_re_reviewer_headers(pharmacist_id: str) -> dict:
    """PharmacistReReviewer headers. PRD §3.6: X-User-ID must NOT equal
    prescription.reviewer_pharmacist_id (segregation of duties), and on
    review action endpoints X-User-ID must equal review.assigned_pharmacist_id.
    """
    return build_user_headers(pharmacist_id, "PharmacistReReviewer")


def make_pharmacist_headers(pharmacist_id: str) -> dict:
    """Generic Pharmacist headers (cold-chain readings + dispense).
    PRD §2.1: X-User-ID is the id of the acting Pharmacist.
    """
    return build_user_headers(pharmacist_id, "Pharmacist")


def make_customer_headers(customer_id: str) -> dict:
    """Customer headers. PRD §2.1: 'placing, paying for, or cancelling an
    order requires X-User-ID to equal the customer_id on the order.'

    Pass the actual Customer.id whenever the request is ownership-gated.
    """
    return build_user_headers(customer_id, "Customer")
