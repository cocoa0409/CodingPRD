"""Pre-built role headers for every role in the PRD."""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

# Shared constants. Safe for the four opaque roles, and for tests whose success
# does not depend on the caller owning the subject resource.
TEST_USERS: Dict[str, Dict[str, str]] = {
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "vendor_ops_analyst_headers": build_user_headers("test-ops-1", "VendorOpsAnalyst"),
    "merchandise_manager_headers": build_user_headers("test-mm-1", "MerchandiseManager"),
    "care_agent_headers": build_user_headers("test-care-1", "CareAgent"),
    # VendorUser identity is backed by a Vendor row: this shared constant only
    # serves tests that never reach a vendor-owned resource.
    "vendor_user_headers": build_user_headers("test-vendor-1", "VendorUser"),
}


def make_platform_admin_headers(user_id: str) -> Dict[str, str]:
    """PlatformAdmin headers under a caller-chosen operator id."""
    return build_user_headers(user_id, "PlatformAdmin")


def make_vendor_ops_analyst_headers(user_id: str) -> Dict[str, str]:
    """VendorOpsAnalyst headers under a caller-chosen operator id.

    Onboarding splits duties by operator id, so recording and evaluating an
    integration test, and certifying a vendor, each need a distinct id.
    """
    return build_user_headers(user_id, "VendorOpsAnalyst")


def make_merchandise_manager_headers(user_id: str) -> Dict[str, str]:
    """MerchandiseManager headers under a caller-chosen operator id.

    Activation must be performed by an id other than the certifier's.
    """
    return build_user_headers(user_id, "MerchandiseManager")


def make_care_agent_headers(user_id: str) -> Dict[str, str]:
    """CareAgent headers under a caller-chosen operator id."""
    return build_user_headers(user_id, "CareAgent")


def make_vendor_user_headers(vendor_id: str) -> Dict[str, str]:
    """For VendorUser, whose identity is the acting Vendor row.

    Pass the real Vendor.id: every vendor-owned resource the call reaches is
    checked against it.
    """
    return build_user_headers(vendor_id, "VendorUser")


# Distinct operator ids for the segregation-of-duties split.
OPS_RECORDER_ID = "ops-recorder-1"
OPS_EVALUATOR_ID = "ops-evaluator-1"
OPS_CERTIFIER_ID = "ops-cert-1"
MM_ACTIVATOR_ID = "mm-activator-1"
