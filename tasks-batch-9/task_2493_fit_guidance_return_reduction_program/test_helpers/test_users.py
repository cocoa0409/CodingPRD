"""Pre-built operator headers for the five roles the PRD recognizes.

Two roles are backed by persisted entities: `VendorUser` carries the acting
`Vendor.id` in `X-User-ID`, and `Customer` carries the acting
`CustomerProfile.id`.  For those two roles the shared constants below are only
safe on requests whose outcome does not depend on ownership; anything
ownership-gated must use the per-instance builders.

The remaining three roles carry an opaque operator identifier that the server
may record but never compares to an entity id.
"""

from prd_bench_local_runner.testing import build_user_headers

# Opaque operator identifiers used consistently across the suite.  The two
# auditor identities matter because closing a case must be done by an operator
# other than the one who coded it.
ANALYST_USER_ID = "analyst-7"
CLASSIFY_AUDITOR_USER_ID = "auditor-1"
RESOLVE_AUDITOR_USER_ID = "auditor-2"
VOID_AUDITOR_USER_ID = "auditor-3"
ADMIN_USER_ID = "merch-ops-1"


TEST_USERS = {
    # Opaque roles — the shared constant is the canonical form.
    "merch_ops_admin_headers": build_user_headers(ADMIN_USER_ID, "MerchOpsAdmin"),
    "fit_analyst_headers": build_user_headers(ANALYST_USER_ID, "FitAnalyst"),
    "returns_auditor_headers": build_user_headers(
        CLASSIFY_AUDITOR_USER_ID, "ReturnsAuditor"
    ),
    "returns_auditor_2_headers": build_user_headers(
        RESOLVE_AUDITOR_USER_ID, "ReturnsAuditor"
    ),
    "returns_auditor_3_headers": build_user_headers(
        VOID_AUDITOR_USER_ID, "ReturnsAuditor"
    ),
    # Entity-backed roles — fallback for non-ownership tests only.
    "vendor_user_headers": build_user_headers("test-vendor-1", "VendorUser"),
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}


def make_merch_ops_admin_headers(user_id: str = ADMIN_USER_ID) -> dict:
    """For `MerchOpsAdmin`; the identifier is opaque and never matched to a row."""
    return build_user_headers(user_id, "MerchOpsAdmin")


def make_fit_analyst_headers(user_id: str = ANALYST_USER_ID) -> dict:
    """For `FitAnalyst`.  The identifier is recorded as `verified_by_user_id`
    when a verification is decided."""
    return build_user_headers(user_id, "FitAnalyst")


def make_returns_auditor_headers(user_id: str = CLASSIFY_AUDITOR_USER_ID) -> dict:
    """For `ReturnsAuditor`.  The identifier is recorded as
    `classified_by_user_id` on coding and `resolved_by_user_id` on closing, and
    the two must differ."""
    return build_user_headers(user_id, "ReturnsAuditor")


def make_vendor_user_headers(vendor_id: str) -> dict:
    """For `VendorUser`.  Pass the acting `Vendor.id`: a specification write is
    permitted only when it equals the `vendor_id` of the item described."""
    return build_user_headers(vendor_id, "VendorUser")


def make_customer_headers(customer_profile_id: str) -> dict:
    """For `Customer`.  Pass the acting `CustomerProfile.id`: return-case,
    fit-feedback and recommendation calls compare it to the resource's customer
    foreign key."""
    return build_user_headers(customer_profile_id, "Customer")


def make_headers(user_id: str, role: str) -> dict:
    """Escape hatch for tests that need an arbitrary role string, including role
    names the API does not recognize."""
    return build_user_headers(user_id, role)
