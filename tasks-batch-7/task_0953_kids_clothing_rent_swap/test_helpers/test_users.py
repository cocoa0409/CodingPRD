"""Pre-built role headers for every role in the PRD.

PRD 2.1 binds identity in exactly one of two ways.  When `X-User-Role` is
`Member`, `X-User-ID` is the `id` of the acting `Member` row, so every
member-scoped call MUST use `make_member_headers(member["id"])`.  For the seven
operator roles `X-User-ID` is an opaque operator identifier that is never
compared to any entity's `id`, so a shared constant is correct for those.

Grade confirmation is the one place where two *operator* identifiers must
differ (PRD 2.1 segregation of duties), so distinct builder functions are
provided for the grading technician and the merchandise planner.
"""

from prd_bench_local_runner.testing import build_user_headers

# Shared constants.  Safe for every opaque operator role, and for Member-role
# calls that do not depend on owning the addressed resource (401/403/404 probes).
TEST_USERS = {
    "admin_headers": build_user_headers("op-admin-1", "PlatformAdmin"),
    "member_headers": build_user_headers("test-member-unowned", "Member"),
    "warehouse_headers": build_user_headers("op-warehouse-1", "WarehouseOperator"),
    "grader_headers": build_user_headers("op-grader-1", "GradingTechnician"),
    "vendor_headers": build_user_headers("op-vendor-1", "CleaningVendor"),
    "logistics_headers": build_user_headers("op-logistics-1", "LogisticsCoordinator"),
    "billing_headers": build_user_headers("op-billing-1", "BillingAgent"),
    "planner_headers": build_user_headers("op-planner-1", "MerchandisePlanner"),
}

ADMIN = TEST_USERS["admin_headers"]
WAREHOUSE = TEST_USERS["warehouse_headers"]
GRADER = TEST_USERS["grader_headers"]
VENDOR = TEST_USERS["vendor_headers"]
LOGISTICS = TEST_USERS["logistics_headers"]
BILLING = TEST_USERS["billing_headers"]
PLANNER = TEST_USERS["planner_headers"]


def make_member_headers(member_id: str) -> dict:
    """Headers for the Member role.  `X-User-ID` MUST be the acting member's own
    `id` whenever the call is ownership-gated (PRD 2.1)."""
    return build_user_headers(member_id, "Member")


def make_admin_headers(user_id: str = "op-admin-1") -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_warehouse_headers(user_id: str = "op-warehouse-1") -> dict:
    return build_user_headers(user_id, "WarehouseOperator")


def make_grader_headers(user_id: str = "op-grader-1") -> dict:
    """Grading technician.  The identifier lands in `graded_by_user_id`."""
    return build_user_headers(user_id, "GradingTechnician")


def make_vendor_headers(user_id: str = "op-vendor-1") -> dict:
    return build_user_headers(user_id, "CleaningVendor")


def make_logistics_headers(user_id: str = "op-logistics-1") -> dict:
    return build_user_headers(user_id, "LogisticsCoordinator")


def make_billing_headers(user_id: str = "op-billing-1") -> dict:
    return build_user_headers(user_id, "BillingAgent")


def make_planner_headers(user_id: str = "op-planner-1") -> dict:
    """Merchandise planner.  The identifier lands in `confirmed_by_user_id` and
    must differ from the assessment's `graded_by_user_id`."""
    return build_user_headers(user_id, "MerchandisePlanner")


def make_role_headers(role: str, user_id: str) -> dict:
    """Arbitrary role/identifier pair — used by the header-validation probes."""
    return build_user_headers(user_id, role)
