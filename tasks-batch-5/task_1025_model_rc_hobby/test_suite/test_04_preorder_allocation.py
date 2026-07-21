"""Pre-order campaigns: allocation sweep boundary, conserved allocation units,
cross-entity convert gate, the depth-3 campaign-cancel cascade, plus corner
validations (window, pool, OCC, state, listing)."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId,
    create_reservation_payload,
    make_customer, make_product, make_open_campaign, add_reservation,
    allocate_campaign, campaign_version, make_converted_reservation,
    assert_allocation_conserved,
    TEST_USERS,
)

STAFF = TEST_USERS["staff_headers"]
MANAGER = TEST_USERS["manager_headers"]


# ---------------------------------------------------------------------------
# bp_allocation_units_inclusive_boundary
# ---------------------------------------------------------------------------
def test_allocation_inclusive_boundary_allocates_whole_pool_then_waitlists(api):
    """PRD 3.3: "For each reservation in turn, if its `requested_units` is at
    most the remaining pool, the reservation is granted in full — its
    `allocated_units` becomes its `requested_units`, its status moves
    `HELD → ALLOCATED`, and the remaining pool drops by that amount; otherwise
    the reservation is passed over, its `allocated_units` stays 0, and its
    status moves `HELD → WAITLISTED`."

    Design: Difficulty/boundary_precision_check/bp_allocation_units_inclusive_boundary
    """
    cust_a = make_customer(api)
    cust_b = make_customer(api)
    camp, _prod = make_open_campaign(api, total_allocation_units=10,
                                     unit_price_cents=10000, product_stock=50)
    r1 = add_reservation(api, camp["id"], cust_a["id"], 10)
    r2 = add_reservation(api, camp["id"], cust_b["id"], 1)
    allocate_campaign(api, camp["id"])
    r1_after = get_success_data(api.get_reservation(r1["id"], STAFF))
    r2_after = get_success_data(api.get_reservation(r2["id"], STAFF))
    assert r1_after["status"] == "ALLOCATED"
    assert r1_after["allocated_units"] == 10
    assert r2_after["status"] == "WAITLISTED"


def test_allocation_sweep_sets_campaign_allocated_and_remaining(api):
    """PRD 3.3: "After the walk, the campaign's `allocated_units` is
    `total_allocation_units` minus whatever remains in the pool, and
    `remaining_units` is `total_allocation_units` minus `allocated_units`. The
    boundary is inclusive: a reservation whose request exactly equals the
    remaining pool is allocated, not waitlisted."

    Design: Difficulty/boundary_precision_check/bp_allocation_units_inclusive_boundary
    """
    cust_a = make_customer(api)
    cust_b = make_customer(api)
    camp, _prod = make_open_campaign(api, total_allocation_units=10,
                                     unit_price_cents=10000, product_stock=50)
    add_reservation(api, camp["id"], cust_a["id"], 10)
    add_reservation(api, camp["id"], cust_b["id"], 1)
    allocated = allocate_campaign(api, camp["id"])
    assert allocated["allocated_units"] == 10
    assert allocated["remaining_units"] == 0
    assert_allocation_conserved(allocated)


# ---------------------------------------------------------------------------
# ci_allocation_units_conserved_on_release
# ---------------------------------------------------------------------------
def test_cancel_allocated_reservation_releases_units_conserved(api):
    """PRD 3.3: "If the reservation had been `ALLOCATED` or `CONVERTED`, the
    campaign's `allocated_units` is decreased by that reservation's
    `allocated_units`, releasing the units back into the conserved total".

    Design: Difficulty/compensating_invariant/ci_allocation_units_conserved_on_release
    """
    cust_a = make_customer(api)
    cust_b = make_customer(api)
    camp, _prod = make_open_campaign(api, total_allocation_units=10,
                                     unit_price_cents=10000, product_stock=50)
    r1 = add_reservation(api, camp["id"], cust_a["id"], 5)
    add_reservation(api, camp["id"], cust_b["id"], 3)
    allocate_campaign(api, camp["id"])
    validate_success(api.transition_reservation(r1["id"], {"action": "CANCEL"}, STAFF))
    camp_after = get_success_data(api.get_campaign(camp["id"], STAFF))
    assert camp_after["allocated_units"] == 3
    assert camp_after["remaining_units"] == 7
    assert_allocation_conserved(camp_after)


def test_release_does_not_disturb_other_allocated_reservation(api):
    """PRD 3.3: "at all times, after the sweep and after any later release, it
    equals the sum of `allocated_units` over reservations whose status is
    `ALLOCATED` or `CONVERTED`."
    PRD 3.3: "released units are not auto-promoted to any waitlisted
    reservation."

    Design: Difficulty/compensating_invariant/ci_allocation_units_conserved_on_release
    """
    cust_a = make_customer(api)
    cust_b = make_customer(api)
    camp, _prod = make_open_campaign(api, total_allocation_units=10,
                                     unit_price_cents=10000, product_stock=50)
    r1 = add_reservation(api, camp["id"], cust_a["id"], 5)
    r2 = add_reservation(api, camp["id"], cust_b["id"], 3)
    allocate_campaign(api, camp["id"])
    validate_success(api.transition_reservation(r1["id"], {"action": "CANCEL"}, STAFF))
    r2_after = get_success_data(api.get_reservation(r2["id"], STAFF))
    assert r2_after["status"] == "ALLOCATED"
    assert r2_after["allocated_units"] == 3


# ---------------------------------------------------------------------------
# ce_reservation_convert_requires_campaign_allocating (positive path)
# ---------------------------------------------------------------------------
def test_convert_allocated_reservation_moves_to_converted(api):
    """PRD 3.3: "An allocated reservation is turned into a real sale by
    converting it, which requires that the reservation is `ALLOCATED` (otherwise
    `ERR_RESERVATION_NOT_ALLOCATED`), that the campaign is still `ALLOCATING`,
    and that the product has at least `allocated_units` in stock. Conversion
    moves the reservation `ALLOCATED → CONVERTED`".

    Design: Difficulty/cross_entity_state_dependency/ce_reservation_convert_requires_campaign_allocating
    """
    cust = make_customer(api)
    camp, _prod = make_open_campaign(api, total_allocation_units=10,
                                     unit_price_cents=10000, product_stock=50)
    res = add_reservation(api, camp["id"], cust["id"], 3)
    allocate_campaign(api, camp["id"])  # campaign -> ALLOCATING, reservation -> ALLOCATED
    converted = get_success_data(api.transition_reservation(res["id"], {"action": "CONVERT"}, STAFF))
    assert converted["status"] == "CONVERTED"


def test_convert_creates_linked_placed_preorder_order(api):
    """PRD 3.3: "creates an already-`PLACED` order whose `source` is `PRE_ORDER`
    for the reservation's own `customer_id` carrying a single line of the
    campaign's product at the campaign's `unit_price_cents` for the granted
    `allocated_units`, records the new order's id on the reservation's
    `order_id`".

    Design: Difficulty/cross_entity_state_dependency/ce_reservation_convert_requires_campaign_allocating
    """
    ctx = make_converted_reservation(api, requested_units=3,
                                     total_allocation_units=10,
                                     unit_price_cents=10000, product_stock=50)
    res = ctx["reservation"]
    assert res["order_id"] is not None
    order = ctx["order"]
    assert order["status"] == "PLACED"
    assert order["source"] == "PRE_ORDER"
    assert order["customer_id"] == ctx["customer"]["id"]


# ---------------------------------------------------------------------------
# tc_campaign_cancel_depth3_reservation_order_customer
# ---------------------------------------------------------------------------
def test_campaign_cancel_cascades_reservation_and_order_to_cancelled(api):
    """PRD 2.5: "At layer one (L1), each `PreOrderReservation` on the campaign
    that is in `HELD`, `WAITLISTED`, `ALLOCATED`, or `CONVERTED` is moved to
    `CANCELLED`. At layer two (L2), each reservation's own cancellation, if it
    holds an `order_id`, drives that `Order` to `fulfillment_status`
    `CANCELLED`."

    Design: Difficulty/transitive_cascade/tc_campaign_cancel_depth3_reservation_order_customer
    """
    ctx = make_converted_reservation(api, requested_units=5,
                                     total_allocation_units=10,
                                     unit_price_cents=10000, product_stock=100)
    validate_success(api.cancel_campaign(ctx["campaign"]["id"], MANAGER))
    res_after = get_success_data(api.get_reservation(ctx["reservation"]["id"], STAFF))
    order_after = get_success_data(api.get_order(ctx["order"]["id"], STAFF))
    assert res_after["status"] == "CANCELLED"
    assert order_after["fulfillment_status"] == "CANCELLED"


def test_campaign_cancel_restores_stock_and_reverses_points(api):
    """PRD 2.5: "At layer three (L3), each order's own cancellation restores
    product stock and reverses the buyer's provisional loyalty points, exactly
    as described for order cancellation in Section 3.4."

    Design: Difficulty/transitive_cascade/tc_campaign_cancel_depth3_reservation_order_customer
    """
    ctx = make_converted_reservation(api, requested_units=5,
                                     total_allocation_units=10,
                                     unit_price_cents=10000, product_stock=100)
    # After convert: stock reserved (100-5=95) and provisional points credited.
    validate_success(api.cancel_campaign(ctx["campaign"]["id"], MANAGER))
    prod_after = get_success_data(api.get_product(ctx["product"]["id"], STAFF))
    cust_after = get_success_data(api.get_customer(ctx["customer"]["id"], STAFF))
    assert prod_after["stock_on_hand"] == 100, "stock fully restored by L3"
    assert cust_after["loyalty_points_balance"] == 0, "provisional points reversed by L3"


# ---------------------------------------------------------------------------
# cn_campaign_open_from_open_returns_409
# ---------------------------------------------------------------------------
def test_open_already_open_campaign_rejected(api):
    """PRD 3.3: "Opening the campaign advances `DRAFT → OPEN` and is the point
    after which reservations may be created; opening a campaign that is not in
    `DRAFT` is an invalid-state error."

    Design: Corner/state_machines/cn_campaign_open_from_open_returns_409
    """
    camp, _prod = make_open_campaign(api, total_allocation_units=5,
                                     unit_price_cents=10000, product_stock=10)
    resp = api.open_campaign(camp["id"], STAFF)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ---------------------------------------------------------------------------
# cn_campaign_reallocate_returns_already_allocated
# ---------------------------------------------------------------------------
def test_reallocate_already_allocating_campaign_rejected(api):
    """PRD 3.3: "attempting to allocate a campaign that is not `OPEN` —
    including a second attempt on an already-allocating or cancelled campaign —
    is rejected with `ERR_CAMPAIGN_ALREADY_ALLOCATED` (HTTP 409)."

    Design: Corner/state_machines/cn_campaign_reallocate_returns_already_allocated
    """
    camp, _prod = make_open_campaign(api, total_allocation_units=5,
                                     unit_price_cents=10000, product_stock=10)
    allocate_campaign(api, camp["id"])
    resp = api.allocate_campaign(camp["id"], STAFF)
    validate_error(resp, ApiErrorId.ERR_CAMPAIGN_ALREADY_ALLOCATED.value)


# ---------------------------------------------------------------------------
# cn_reservation_window_closed_returns_409
# ---------------------------------------------------------------------------
def test_reservation_before_window_open_rejected(api):
    """PRD 2.8: "Reservations may only be created while the current logical time
    is at or after a campaign's `reservation_open_at` and strictly before its
    `reservation_close_at`; outside that span the reservation is rejected with
    `ERR_WINDOW_CLOSED` (HTTP 409)."

    Design: Corner/validations/cn_reservation_window_closed_returns_409
    """
    cust = make_customer(api)
    # Clock stays at default 2026-07-01; window opens 2026-08-01.
    camp, _prod = make_open_campaign(api, total_allocation_units=5,
                                     unit_price_cents=10000, product_stock=10,
                                     reservation_open_at="2026-08-01T00:00:00Z",
                                     reservation_close_at="2026-12-31T00:00:00Z")
    ver = campaign_version(api, camp["id"])
    resp = api.create_reservation(camp["id"], create_reservation_payload(
        customer_id=cust["id"], requested_units=1, expected_campaign_version=ver), STAFF)
    validate_error(resp, ApiErrorId.ERR_WINDOW_CLOSED.value)


# ---------------------------------------------------------------------------
# cn_reservation_over_pool_returns_allocation_exhausted
# ---------------------------------------------------------------------------
def test_reservation_exceeding_pool_rejected(api):
    """PRD 3.3: "The requested amount must be at least 1 and may not exceed the
    campaign's whole `total_allocation_units` — a single reservation may not ask
    for more than the entire pool — and a request that exceeds the pool is
    rejected with `ERR_ALLOCATION_EXHAUSTED` (HTTP 409)."

    Design: Corner/validations/cn_reservation_over_pool_returns_allocation_exhausted
    """
    cust = make_customer(api)
    camp, _prod = make_open_campaign(api, total_allocation_units=5,
                                     unit_price_cents=10000, product_stock=10)
    ver = campaign_version(api, camp["id"])
    resp = api.create_reservation(camp["id"], create_reservation_payload(
        customer_id=cust["id"], requested_units=999, expected_campaign_version=ver), STAFF)
    validate_error(resp, ApiErrorId.ERR_ALLOCATION_EXHAUSTED.value)


# ---------------------------------------------------------------------------
# cn_occ_stale_campaign_version_returns_412
# ---------------------------------------------------------------------------
def test_reservation_with_stale_campaign_version_rejected(api):
    """PRD 2.4: "If `expected_campaign_version` does not equal the campaign's
    current `version` (for example, because another reservation was created
    after the client last read the campaign, advancing its version), the create
    is rejected with `ERR_STALE_VERSION` (HTTP 412)".

    Design: Corner/cross_cutting_complexity_layers/cn_occ_stale_campaign_version_returns_412
    """
    cust_a = make_customer(api)
    cust_b = make_customer(api)
    camp, _prod = make_open_campaign(api, total_allocation_units=10,
                                     unit_price_cents=10000, product_stock=10)
    stale_version = campaign_version(api, camp["id"])
    # First create succeeds and advances the campaign version.
    validate_success(api.create_reservation(camp["id"], create_reservation_payload(
        customer_id=cust_a["id"], requested_units=1,
        expected_campaign_version=stale_version), STAFF), expected_status=201)
    # Second create reuses the now-stale version.
    resp = api.create_reservation(camp["id"], create_reservation_payload(
        customer_id=cust_b["id"], requested_units=1,
        expected_campaign_version=stale_version), STAFF)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


# ---------------------------------------------------------------------------
# cn_fk_reverse_reservations_by_campaign
# ---------------------------------------------------------------------------
def test_list_reservations_filtered_by_campaign(api):
    """PRD 2.3: "Unless otherwise specified, every list endpoint returns its
    resources sorted by `created_at` in ascending order."
    PRD 2.3: "Each list response reports `limit`, `offset`, `total_count`, and
    `has_more` inside the envelope's `meta` object, where `total_count` is the
    number of matching resources before pagination and `has_more` indicates
    whether further pages remain."

    Design: Corner/endpoints/cn_fk_reverse_reservations_by_campaign
    """
    cust = make_customer(api)
    camp, _prod = make_open_campaign(api, total_allocation_units=5,
                                     unit_price_cents=10000, product_stock=10)
    res = add_reservation(api, camp["id"], cust["id"], 2)
    resp = api.list_reservations(STAFF, params={"campaign_id": camp["id"]})
    data, meta = validate_paginated(resp)
    ids = [r["id"] for r in data]
    assert res["id"] in ids
    assert "total_count" in meta
    assert "has_more" in meta
