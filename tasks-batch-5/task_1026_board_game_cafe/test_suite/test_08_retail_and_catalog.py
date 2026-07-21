"""Retail order totals, membership uniqueness / not-found / pagination, and F&B
void idempotency."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, NON_EXISTENT_UUID, TEST_USERS,
    create_membership, create_table, create_seated_reservation, add_fnb,
)

MGR = TEST_USERS["manager_headers"]
STAFF = TEST_USERS["staff_headers"]


# ─── Corner/entities/retail_order_total_is_quantity_times_unit_price ───────
def test_retail_order_total_is_quantity_times_unit_price(api):
    """PRD §3.8: "The `total_cents` is computed at create as the `quantity` multiplied by
    the `unit_price_cents`. An `IN_STOCK` order is immediately `READY`; a `PREORDER` order
    starts `AWAITING_STOCK`."

    Design: Corner/entities/retail_order_total_is_quantity_times_unit_price
    """
    data = validate_success(api.create_retail_order(
        {"product_title": "Gloomhaven", "fulfillment_type": "IN_STOCK",
         "quantity": 3, "unit_price_cents": 1500}, STAFF), expected_status=201)
    assert data["total_cents"] == 4500, "3 * 1500"
    assert data["status"] == "READY", "IN_STOCK starts READY"


# ─── Corner/entities/create_membership_duplicate_email_returns_validation ──
def test_duplicate_membership_email_returns_validation(api):
    """PRD §3.1: "A `Membership` is created from an `email` and a `full_name`; the email
    must be unique across all memberships, and a duplicate is a malformed request."

    Design: Corner/entities/create_membership_duplicate_email_returns_validation
    """
    create_membership(api, email="dup@x.com", full_name="First")
    res = api.create_membership({"email": "dup@x.com", "full_name": "Second"}, STAFF)
    validate_error(res, "ERR_VALIDATION")


# ─── Corner/entities/get_membership_nonexistent_returns_not_found ──────────
def test_get_nonexistent_membership_returns_not_found(api):
    """PRD §2.8: "resource existence is checked: every id in the path and then every
    foreign-key id in the body must resolve, validated left-to-right along the path first
    and then the body, failing with `ERR_NOT_FOUND`."

    Design: Corner/entities/get_membership_nonexistent_returns_not_found
    """
    res = api.get_membership(NON_EXISTENT_UUID, STAFF)
    validate_error(res, "ERR_NOT_FOUND")


# ─── Corner/entities/list_memberships_is_paginated ─────────────────────────
def test_list_memberships_pagination_metadata(api):
    """PRD §2.3: "The `meta` block of a list response carries `limit`, `offset`,
    `total_count` (the number of records matching the query before pagination) and
    `has_more` (true when records remain beyond the current page)."

    Design: Corner/entities/list_memberships_is_paginated
    """
    create_membership(api, email="p1@x.com", full_name="P1")
    create_membership(api, email="p2@x.com", full_name="P2")
    data, meta = validate_paginated(api.list_memberships(STAFF, params={"limit": 1, "offset": 0}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1


# ─── Corner/state_machines/void_already_void_order_returns_invalid_state ───
def test_void_already_void_order_returns_invalid_state(api):
    """PRD §3.3: "An order may be voided, moving it from `OPEN` to `VOID`; a `VOID` order is
    excluded from both the bill and the food-and-beverage minimum."
    PRD §2.8: "Only then are state-machine legality (`ERR_INVALID_STATE`) and the
    domain-specific business constraints (capacity, suspension, availability, time
    conflicts, points sufficiency, and the like) evaluated."

    Design: Corner/state_machines/void_already_void_order_returns_invalid_state
    """
    table = create_table(api, label="C5", seats=4, half_hour_rate_cents=0, day_pass_cents=0,
                         cover_fee_cents=0, min_spend_cents=0)
    resv = create_seated_reservation(
        api, table_id=table["id"], party_size=2,
        start_at="2026-07-05T12:00:00Z", end_at="2026-07-05T14:00:00Z",
        seated_at="2026-07-05T12:00:00Z", booking_clock="2026-07-05T12:00:00Z",
    )
    order = add_fnb(api, resv["id"], 700, "Fries")
    validate_success(api.void_fnb_order(order["id"], STAFF))
    res = api.void_fnb_order(order["id"], STAFF)
    validate_error(res, "ERR_INVALID_STATE")
