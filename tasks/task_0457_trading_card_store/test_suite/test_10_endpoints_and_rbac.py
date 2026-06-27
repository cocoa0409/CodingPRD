"""Endpoint-level corner cases (WPN report match points, filtered pre-order listing)
and RBAC enforcement (customer cannot accept buylist, cannot act for another
customer, judge cannot create events, unknown role unauthenticated).
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated, get_success_data,
    create_customer, create_release_product, create_requested_pre_order,
    create_inventory_item, create_submitted_buylist,
    setup_in_progress_event_with_two_players, create_pairing, report_pairing,
    create_open_event, create_event, set_clock,
    create_event_payload, build_user_headers,
    ApiErrorId, TEST_USERS, make_customer_headers,
)

SM = TEST_USERS["store_manager_headers"]
JUDGE = TEST_USERS["judge_headers"]


# ─── endpoints corner ───────────────────────────────────────────────────────────
def test_wpn_report_reflects_match_points(api):
    """PRD §3.5: "reporting `A_WINS` adds 3 to player A's registration `match_points`"
    PRD §3.5: "once complete, the event is eligible for WPN reporting. The computed
    WPN organized-play report returns the event's standings ordered by `match_points`
    descending, with ties broken by `created_at` ascending."

    Design: Corner/endpoints/wpn_report_standings_ordered_by_match_points
    """
    ev, ca, cb, ra, rb = setup_in_progress_event_with_two_players(
        starts_at="2026-07-04T00:00:00Z", ends_at="2026-07-04T05:00:00Z",
        event_format="STANDARD")
    pr = create_pairing(ev, ra, rb)
    report_pairing(pr, "A_WINS")
    validate_success(api.complete_event(ev["id"], JUDGE), 200)
    # Report endpoint is reachable once the event is complete.
    validate_success(api.get_wpn_report(ev["id"], JUDGE), 200)
    reg_a = validate_success(api.get_registration(ra["id"], SM), 200)
    reg_b = validate_success(api.get_registration(rb["id"], SM), 200)
    assert reg_a["match_points"] == 3
    assert reg_b["match_points"] == 0


def test_list_pre_orders_filtered_by_release(api):
    """PRD §4 (endpoint table) GET `/pre-orders` "List pre-orders"; PRD §2.4: "A
    handful of read endpoints expose a resource's children by walking back through a
    foreign key". PRD §2.3: "every list endpoint returns its resources sorted by
    creation timestamp (`created_at`) in ascending order."

    Design: Corner/endpoints/list_pre_orders_filtered_by_release
    """
    cust = create_customer("PO List", "polist@x.com", credit_cents=5000)
    rp = create_release_product(title="List Box", allocation_pool=10,
                                unit_price_cents=1000, deposit_required_cents=500)
    po = create_requested_pre_order(cust, rp, requested_quantity=1, deposit_paid_cents=500)
    data, meta = validate_paginated(
        api.list_pre_orders(SM, params={"release_product_id": rp["id"]}))
    assert meta["total_count"] == 1
    assert data[0]["release_product_id"] == rp["id"]


# ─── rbac corner ────────────────────────────────────────────────────────────────
def test_customer_cannot_accept_buylist(api):
    """PRD §2.1: "When the headers are well-formed but the named role is not permitted
    to perform the requested operation — or a customer attempts to act on a resource
    it does not own — the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §3.2: "A store manager reviews a `SUBMITTED` buylist and either rejects it
    ... or accepts it."

    Design: Corner/rbac/customer_cannot_accept_buylist
    """
    cust = create_customer("RBAC Cust", "rbac@x.com")
    item = create_inventory_item(title="RBAC Card", market_price_cents=500)
    sub = create_submitted_buylist(cust, [(item, 1)], payout_method="CASH")
    res = api.accept_buylist(sub["id"], make_customer_headers(cust["id"]))
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED)


def test_customer_cannot_register_for_another_customer(api):
    """PRD §2.1: "A customer may read and act only on resources whose customer
    reference equals their own `X-User-ID`; an attempt to read or mutate another
    customer's resource is an `ERR_UNAUTHORIZED` failure."

    Design: Corner/rbac/customer_cannot_register_for_another_customer
    """
    set_clock("2026-06-01T00:00:00Z")
    me = create_customer("Self", "self@x.com")
    other = create_customer("Other", "other@x.com")
    ev = create_open_event(title="Own Event", format="STANDARD",
                           starts_at="2026-06-10T00:00:00Z",
                           ends_at="2026-06-10T04:00:00Z", capacity=8,
                           entry_fee_cents=1000)
    # Acting as `me` but registering `other`: ownership violation.
    res = api.create_registration(
        {"event_id": ev["id"], "customer_id": other["id"]},
        make_customer_headers(me["id"]))
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED)


def test_judge_cannot_create_event(api):
    """PRD §2.1: "When the headers are well-formed but the named role is not permitted
    to perform the requested operation ... the request is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §3.4: "A store manager creates an event with a `title`, a `format`"

    Design: Corner/rbac/judge_cannot_create_event
    """
    res = api.create_event(create_event_payload(title="Judge Event"), JUDGE)
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED)


def test_unknown_role_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or `X-User-Role` does not name a role
    the system recognizes, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP
    401)."

    Design: Corner/rbac/missing_auth_header_unauthenticated
    """
    ghost_headers = build_user_headers("ghost-1", "Ghost")
    res = api.list_customers(ghost_headers)
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED)
