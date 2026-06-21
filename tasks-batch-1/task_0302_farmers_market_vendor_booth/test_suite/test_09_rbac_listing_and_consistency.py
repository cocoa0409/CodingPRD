"""Role-based access control, ownership isolation, and immediate ledger
consistency.

Covers the corner `rbac` and `consistency_model` instances.

Note: the corner `endpoints/list_assignments_filtered_by_booth` instance is NOT
translated here. The booth_id list-filter behaviour is stated only in the §4
routing-table parenthetical ("filterable by ... booth_id ..."), which §4 itself
declares "a routing summary only" and defers query parameters to §3; §3 carries
no rule-bearing prose describing the filter, so the instance fails the PRD
coverage condition and is left as a documented gap.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    make_vendor_headers, build_user_headers, TEST_USERS,
    create_market, create_booth, create_vendor, create_active_vendor,
    create_rejected_application, reserve_season_assignment,
    create_under_review_application, create_booth_payload,
)

ADMIN = TEST_USERS["admin_headers"]
MANAGER = TEST_USERS["manager_headers"]


# ---------------------------------------------------------------------------
# Corner: rbac section
# ---------------------------------------------------------------------------
def test_vendor_cannot_create_booth(api):
    """PRD 2.1: "A request whose role is valid but is not permitted to perform the
    requested operation ... is rejected with ERR_FORBIDDEN_ROLE." PRD 4 lists POST
    /booths as MarketAdmin-only.

    Design: Corner/rbac/vendor_cannot_create_booth
    """
    market = create_market()
    vendor = create_vendor(market["id"], legal_name="V1", contact_email="v1@x.com")
    vh = make_vendor_headers(vendor["id"])
    res = api.create_booth(
        create_booth_payload(market["id"], label="X-1", grid_row=0, grid_col=1,
                            size_class="SINGLE", allowed_categories=[]), vh)
    validate_error(res, "ERR_FORBIDDEN_ROLE")


def test_market_manager_cannot_approve_application(api):
    """PRD 2.1: MarketManager "issues voucher batches, reconciles redemptions, and
    disputes or reconciles sales reports and the commission they carry, but it
    cannot configure the map or review applications." A request "whose role is
    valid but is not permitted to perform the requested operation ... is rejected
    with ERR_FORBIDDEN_ROLE."

    Design: Corner/rbac/market_manager_cannot_approve_application
    """
    market = create_market()
    vendor, app = create_under_review_application(market["id"], "CRAFTS", "V1", "v1@x.com")
    res = api.approve_application(app["id"], {"review_note": "x"}, MANAGER)
    validate_error(res, "ERR_FORBIDDEN_ROLE")


def test_vendor_cannot_resubmit_other_vendors_application(api):
    """PRD 2.1: "a Vendor attempting to act on a resource it does not own — is
    rejected with ERR_FORBIDDEN_ROLE." PRD 3.2: only "the vendor that owns it,
    verified by matching the application's vendor_id against X-User-ID" may resubmit.

    Design: Corner/rbac/vendor_cannot_resubmit_other_vendors_application
    """
    market = create_market()
    vendor_a, app = create_rejected_application(market["id"], "CRAFTS", "A", "a@x.com")
    vendor_b = create_vendor(market["id"], legal_name="B", contact_email="b@x.com")
    vh_b = make_vendor_headers(vendor_b["id"])

    res = api.resubmit_application(app["id"], vh_b)
    validate_error(res, "ERR_FORBIDDEN_ROLE")


def test_unknown_role_returns_unauthenticated(api):
    """PRD 2.1: "a request ... that carries an X-User-Role value that is not one of
    these three known roles, is rejected with ERR_UNAUTHENTICATED."

    Design: Corner/rbac/missing_headers_returns_unauthenticated
    """
    market = create_market()
    ghost_headers = build_user_headers("ghost-1", "Ghost")
    res = api.get_market(market["id"], ghost_headers)
    validate_error(res, "ERR_UNAUTHENTICATED")


# ---------------------------------------------------------------------------
# Corner: consistency_model section
# ---------------------------------------------------------------------------
def test_ledger_reflected_immediately_after_reserve(api):
    """PRD 2.9: "All four computed fields are recomputed atomically inside the
    request that triggers the change." PRD 3.3: a season reservation recomputes
    "the market's total_fees_collected_cents" — so a subsequent GET reflects the
    SEASON CORNER fee 75000 with no lag.

    Design: Corner/consistency_model/ledger_visible_in_same_request_response
    """
    market = create_market()
    booth = create_booth(market["id"], label="C-1", grid_row=0, grid_col=1, size_class="CORNER")
    vendor = create_active_vendor(market["id"], product_category="CRAFTS")
    reserve_season_assignment(market["id"], booth["id"], vendor["id"])

    got = validate_success(api.get_market(market["id"], ADMIN), 200)
    assert got["total_fees_collected_cents"] == 75000
