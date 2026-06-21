"""Pre-built role headers for every role in the Coffee Roaster Wholesale PRD.

RoasterStaff and SalesRep are opaque operator identities — their X-User-ID is not
tied to any persisted entity, so the shared constants below are the canonical form.

WholesaleBuyer is entity-backed: its X-User-ID must be the id of the acting
WholesaleAccount. Tests/fixtures whose success depends on ownership MUST build buyer
headers with make_buyer_headers(account_id), never the shared constant.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque operator roles — shared constants are canonical.
    "roaster_headers": build_user_headers("test-roaster-1", "RoasterStaff"),
    "sales_headers": build_user_headers("test-sales-1", "SalesRep"),
    # entity_backed WholesaleBuyer: shared constant is a fallback only for tests that
    # do NOT exercise ownership (e.g. cross-account 403). Ownership-gated calls must use
    # make_buyer_headers(account_id) instead.
    "buyer_headers": build_user_headers("test-buyer-unowned", "WholesaleBuyer"),
}


def make_roaster_headers(user_id: str = "test-roaster-1") -> dict:
    """Headers for RoasterStaff (opaque). X-User-ID is not entity-checked."""
    return build_user_headers(user_id, "RoasterStaff")


def make_sales_headers(user_id: str = "test-sales-1") -> dict:
    """Headers for SalesRep (opaque). X-User-ID is not entity-checked."""
    return build_user_headers(user_id, "SalesRep")


def make_buyer_headers(account_id: str) -> dict:
    """Headers for WholesaleBuyer (entity_backed:WholesaleAccount).

    Pass the actual WholesaleAccount.id as account_id whenever the call is
    ownership-gated; the server compares X-User-ID to the resource's owning account.
    """
    return build_user_headers(account_id, "WholesaleBuyer")
