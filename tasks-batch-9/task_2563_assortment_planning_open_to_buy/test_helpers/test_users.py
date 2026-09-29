"""Pre-built role headers.

The four planning roles are opaque operator identifiers; a VendorRep's
X-User-ID is the id of the Vendor row it acts for, so ownership-gated vendor
calls must use make_vendor_rep_headers(vendor["id"]).
"""
from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ADMIN_USER_ID,
    BUYER_USER_ID,
    DIRECTOR_USER_ID,
    PLANNER_USER_ID,
    SECOND_DIRECTOR_USER_ID,
    SECOND_PLANNER_USER_ID,
)

TEST_USERS = {
    "admin_headers": build_user_headers(ADMIN_USER_ID, "MerchOpsAdmin"),
    "planner_headers": build_user_headers(PLANNER_USER_ID, "MerchandisePlanner"),
    "director_headers": build_user_headers(DIRECTOR_USER_ID, "PlanningDirector"),
    "buyer_headers": build_user_headers(BUYER_USER_ID, "CategoryBuyer"),
    "second_planner_headers": build_user_headers(
        SECOND_PLANNER_USER_ID, "MerchandisePlanner"
    ),
    "second_director_headers": build_user_headers(
        SECOND_DIRECTOR_USER_ID, "PlanningDirector"
    ),
    # A VendorRep constant is only safe where ownership is not exercised
    # (401/403/404-shaped tests). Use make_vendor_rep_headers otherwise.
    "vendor_rep_headers": build_user_headers("vendor-rep-unbound", "VendorRep"),
}

ADMIN_HEADERS = TEST_USERS["admin_headers"]
PLANNER_HEADERS = TEST_USERS["planner_headers"]
DIRECTOR_HEADERS = TEST_USERS["director_headers"]
BUYER_HEADERS = TEST_USERS["buyer_headers"]


def make_admin_headers(user_id: str) -> dict:
    """MerchOpsAdmin acting under an explicit operator identifier."""
    return build_user_headers(user_id, "MerchOpsAdmin")


def make_planner_headers(user_id: str) -> dict:
    """MerchandisePlanner acting under an explicit operator identifier."""
    return build_user_headers(user_id, "MerchandisePlanner")


def make_director_headers(user_id: str) -> dict:
    """PlanningDirector acting under an explicit operator identifier."""
    return build_user_headers(user_id, "PlanningDirector")


def make_buyer_headers(user_id: str) -> dict:
    """CategoryBuyer acting under an explicit operator identifier."""
    return build_user_headers(user_id, "CategoryBuyer")


def make_vendor_rep_headers(vendor_id: str) -> dict:
    """VendorRep for the given Vendor row. Pass the vendor's own id, because
    ownership checks compare a commitment's vendor_id to X-User-ID."""
    return build_user_headers(vendor_id, "VendorRep")


ALL_ROLE_NAMES = [
    "MerchOpsAdmin",
    "MerchandisePlanner",
    "PlanningDirector",
    "CategoryBuyer",
    "VendorRep",
]
