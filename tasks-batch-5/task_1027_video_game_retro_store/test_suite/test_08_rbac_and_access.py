"""RBAC denials, ownership checks, invalid-state on release, and pagination bounds.

Corner: rbac, state_machines, validations.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, TEST_USERS,
    create_member, create_member_payload, grade_payload,
    setup_embargoed_pool, setup_submitted_tradein, setup_waitlisted_preorder,
    release_stock, make_member_headers, no_role_headers,
)

CLERK = TEST_USERS["clerk_headers"]
MANAGER = TEST_USERS["manager_headers"]


# ─── Corner: rbac / Member cannot grade a trade-in ────────────────────────
def test_member_cannot_grade_tradein(api):
    """PRD §2.1: "If the header is valid but the role is not permitted to perform the
    requested operation, the request is rejected with ERR_FORBIDDEN (HTTP 403)."
    PRD §2.1: "A Clerk is a front-of-house operator who is a superset of Member business
    operations and additionally grades trade-ins."

    Design: Corner/rbac/member_cannot_grade_tradein_returns_forbidden
    """
    member, product, trade_in = setup_submitted_tradein(
        base_trade_value_cents=3000, stated_grade="A", payout_method="CASH")
    res = api.grade_trade_in(trade_in["id"], grade_payload("A"), make_member_headers(member["id"]))
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)


# ─── Corner: rbac / Clerk cannot release an embargo ───────────────────────
def test_clerk_cannot_release_stock(api):
    """PRD §2.1: "A Manager is a full operator who can do everything a Clerk can, plus
    release allocation pools from embargo."
    PRD §3.2: "Only a manager can lift the embargo, transitioning the pool
    EMBARGOED → RELEASED."

    Design: Corner/rbac/clerk_cannot_release_stock_returns_forbidden
    """
    product, stock = setup_embargoed_pool(unit_price_cents=3000, deposit_cents=500, total_count=2)
    res = api.release_product_stock(stock["id"], CLERK)
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)


# ─── Corner: rbac / Member cannot cancel another member's pre-order ───────
def test_member_cannot_cancel_other_members_preorder(api):
    """PRD §2.1: "a Member may only act on a PreOrder, TradeIn, or Rental whose member_id
    equals their own X-User-ID; an attempt to act on another member's resource is rejected
    with ERR_NOT_RESOURCE_OWNER (HTTP 403)."

    Design: Corner/rbac/member_cannot_cancel_other_members_preorder_returns_forbidden
    """
    member_a, product, stock, po_a = setup_waitlisted_preorder(
        unit_price_cents=6000, deposit_cents=1000, total_count=2)
    member_b = create_member(full_name="OwnB")
    res = api.cancel_pre_order(po_a["id"], make_member_headers(member_b["id"]))
    validate_error(res, "ERR_NOT_RESOURCE_OWNER", expected_status=403)


# ─── Corner: rbac / missing role header ───────────────────────────────────
def test_missing_role_header_unauthenticated(api):
    """PRD §2.1: "If X-User-Role is missing or is any value other than these three, the
    request is rejected with ERR_UNAUTHENTICATED (HTTP 401)."

    Design: Corner/rbac/missing_role_header_returns_unauthenticated
    """
    res = api.create_member(create_member_payload(full_name="NoRole"), no_role_headers())
    validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)


# ─── Corner: state_machines / release an already-released pool ────────────
def test_release_already_released_stock_rejected(api):
    """PRD §3.2: "Once RELEASED, the pool is terminal in this dimension and cannot return
    to embargo."
    PRD §2.11: "then the target resource being in a legal state for the requested
    transition (ERR_INVALID_STATE, 409)."

    Design: Corner/state_machines/release_already_released_stock_rejected
    """
    product, stock = setup_embargoed_pool(unit_price_cents=3000, deposit_cents=500, total_count=2)
    release_stock(stock["id"])
    res = api.release_product_stock(stock["id"], MANAGER)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


# ─── Corner: validations / pagination limit below minimum ─────────────────
def test_pagination_limit_zero_rejected(api):
    """PRD §2.3: "The limit parameter caps the number of items returned; it defaults to
    10, with a minimum of 1 and a maximum of 100. ... A limit outside 1 through 100, or a
    negative offset, is rejected with ERR_PAGINATION_INVALID (HTTP 400)."

    Design: Corner/validations/pagination_limit_zero_returns_400
    """
    res = api.list_pre_orders(CLERK, params={"limit": 0})
    validate_error(res, "ERR_PAGINATION_INVALID", expected_status=400)
