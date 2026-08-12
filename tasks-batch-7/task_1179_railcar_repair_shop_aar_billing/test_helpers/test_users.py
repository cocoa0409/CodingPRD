"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that never exercise
# entity-backed ownership (party-gated) checks.
TEST_USERS = {
    "shop_admin": build_user_headers("admin-1", "ShopAdmin"),
    "yard_clerk": build_user_headers("yard-1", "YardClerk"),
    "car_inspector": build_user_headers("inspector-1", "CarInspector"),
    "repair_foreman": build_user_headers("foreman-1", "RepairForeman"),
    "quality_inspector": build_user_headers("qi-1", "QualityInspector"),
    "parts_clerk": build_user_headers("parts-1", "PartsClerk"),
    "billing_clerk": build_user_headers("billing-1", "BillingClerk"),
    # Entity-backed roles: shared constants are a fallback for non-ownership
    # tests only; ownership-gated calls MUST use the builders below.
    "car_owner_rep": build_user_headers("owner-rep-1", "CarOwnerRep"),
    "handling_line_rep": build_user_headers("line-rep-1", "HandlingLineRep"),
}


def make_shop_admin_headers(user_id: str = "admin-1") -> dict:
    return build_user_headers(user_id, "ShopAdmin")


def make_yard_clerk_headers(user_id: str = "yard-1") -> dict:
    return build_user_headers(user_id, "YardClerk")


def make_car_inspector_headers(user_id: str = "inspector-1") -> dict:
    return build_user_headers(user_id, "CarInspector")


def make_repair_foreman_headers(user_id: str = "foreman-1") -> dict:
    return build_user_headers(user_id, "RepairForeman")


def make_quality_inspector_headers(user_id: str = "qi-1") -> dict:
    return build_user_headers(user_id, "QualityInspector")


def make_parts_clerk_headers(user_id: str = "parts-1") -> dict:
    return build_user_headers(user_id, "PartsClerk")


def make_billing_clerk_headers(user_id: str = "billing-1") -> dict:
    return build_user_headers(user_id, "BillingClerk")


def make_car_owner_rep_headers(user_id: str) -> dict:
    """CarOwnerRep is entity-backed: pass the acting CarOwner's id so
    party-gated operations match the railcar's owner_id (PRD §2.1)."""
    return build_user_headers(user_id, "CarOwnerRep")


def make_handling_line_rep_headers(user_id: str) -> dict:
    """HandlingLineRep is entity-backed: pass the acting HandlingLine's id so
    party-gated operations match the railcar's handling_line_id (PRD §2.1)."""
    return build_user_headers(user_id, "HandlingLineRep")
