"""Order confirmation: strict confirm cutoff, per-zone half-open truck
capacity, freshness-aware batch allocation, validation precedence at confirm,
and immediate response consistency (PRD §2.2, §2.9, §3.5)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    accept_quote,
    assert_instant_equals,
    assert_money_eq,
    create_batch,
    complete_batch,
    create_config,
    create_customer,
    create_field,
    create_quote,
    create_variety,
    factories,
    get_success_data,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId

FARM = TEST_USERS["farm_manager_headers"]
SALES = TEST_USERS["sales_rep_headers"]
HARVEST = TEST_USERS["harvest_supervisor_headers"]
FLEET = TEST_USERS["fleet_manager_headers"]

WIN_0803 = "2026-08-03T08:00:00Z"


def _two_orders_two_batches(api):
    """Two PLACED orders (10 PREMIUM pallets each, zone split 0/10/0) created
    at 2026-08-01T09:00 for delivery 2026-08-03 -> cutoff 2026-08-02T14:00;
    one READY field carrying two 10-pallet PREMIUM batches."""
    create_config(api)
    v = create_variety(api)
    f = create_field(api, v["id"])
    b1 = create_batch(api, f["id"], pallet_count=10)
    b2 = create_batch(api, f["id"], pallet_count=10)
    c1 = create_customer(api)
    c2 = create_customer(api, full_name="Bo Lin", email="bo@example.com",
                         phone="555-0102", freight_zone=2, address="4 Pine Ave")
    set_clock(api, "2026-08-01T09:00:00Z")
    q1 = create_quote(api, c1["id"],
                      [factories.quote_line(v["id"], "PREMIUM", 10)], 0, 10, 0)
    o1 = accept_quote(api, q1["id"])
    q2 = create_quote(api, c2["id"],
                      [factories.quote_line(v["id"], "PREMIUM", 10)], 0, 10, 0)
    o2 = accept_quote(api, q2["id"])
    return {"v": v, "f": f, "b1": b1, "b2": b2, "c1": c1, "c2": c2,
            "q1": q1, "q2": q2, "o1": o1, "o2": o2}


# ---------------------------------------------------------------------------
# Difficulty: boundary_precision_check / confirm_cutoff_exactly_at_deadline
# ---------------------------------------------------------------------------

def test_confirm_one_second_before_cutoff_succeeds(api):
    """PRD §3.5: "For a future-day order, the cutoff falls on the day before `delivery_date` at `future_day_cutoff_hour` (14:00 by default). Confirmation is permitted only strictly before the cutoff; an attempt at exactly the cutoff instant fails with `ERR_CUTOFF_PASSED`."

    Design: Difficulty/boundary_precision_check/confirm_cutoff_exactly_at_deadline
    """
    s = _two_orders_two_batches(api)
    set_clock(api, "2026-08-02T13:59:59Z")
    o1 = confirm_and_validate(api, s["o1"]["id"])
    assert o1["status"] == "CONFIRMED", "one second before the cutoff is allowed"


def test_confirm_exactly_at_cutoff_fails(api):
    """PRD §3.5: "For a future-day order, the cutoff falls on the day before `delivery_date` at `future_day_cutoff_hour` (14:00 by default). Confirmation is permitted only strictly before the cutoff; an attempt at exactly the cutoff instant fails with `ERR_CUTOFF_PASSED`."

    Design: Difficulty/boundary_precision_check/confirm_cutoff_exactly_at_deadline
    """
    s = _two_orders_two_batches(api)
    set_clock(api, "2026-08-02T14:00:00Z")  # exactly the cutoff second
    resp = api.confirm_order(s["o2"]["id"],
                             factories.confirm_order_payload(), SALES)
    validate_error(resp, ApiErrorId.ERR_CUTOFF_PASSED, 409)
    o2 = get_success_data(api.get_order(s["o2"]["id"], SALES))
    assert o2["status"] == "PLACED", "rejected confirm leaves the order PLACED"


def confirm_and_validate(api, order_id, window_start=WIN_0803):
    return validate_success(
        api.confirm_order(
            order_id, factories.confirm_order_payload(
                delivery_window_start=window_start
            ), SALES
        ), 200
    )


# ---------------------------------------------------------------------------
# Difficulty: boundary_precision_check / zone_truck_capacity_exactly_at_limit
# reached via POST /truck-blocks: the 4th overlapping consumer succeeds, the
# 5th fails, an adjacent window and another zone succeed.
# ---------------------------------------------------------------------------

def _four_zone1_blocks(api):
    create_config(api)
    for i in range(1, 5):
        get_success_data(api.create_truck_block(
            factories.create_truck_block_payload(reason=f"b{i}"), FLEET
        ))


def test_zone_capacity_four_blocks_allowed_fifth_rejected(api):
    """PRD §3.5: "When the existing consumer count already equals `zone_truck_capacity` (four by default), the request is rejected with `ERR_CAPACITY_EXCEEDED` — four overlapping consumers may hold capacity at once, and the one that would become the fifth fails."
    PRD §3.5: "A `FleetManager` draws on the same pool by registering a `TruckBlock` with a `freight_zone` of 1, 2, or 3, an hour-aligned `window_start`, a `window_end` strictly later than the start (otherwise `ERR_INVALID_REQUEST`), and an optional `reason` that defaults to an empty string; a block that would push the zone past capacity meets the same `ERR_CAPACITY_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/zone_truck_capacity_exactly_at_limit
    """
    _four_zone1_blocks(api)
    resp = api.create_truck_block(
        factories.create_truck_block_payload(reason="b5"), FLEET
    )
    validate_error(resp, ApiErrorId.ERR_CAPACITY_EXCEEDED, 409)


def test_zone_capacity_adjacent_window_and_other_zone_allowed(api):
    """PRD §3.5: "Delivery windows are treated as half-open intervals — a window includes its start instant and excludes its end instant, so two windows that merely touch at a boundary do not overlap."
    PRD §3.5: "The consumers of a zone for a requested window are the orders in `CONFIRMED` or `OUT_FOR_DELIVERY` whose `capacity_zone` matches and whose booked windows overlap it, plus the `TruckBlock` records in that zone whose windows overlap it."

    Design: Difficulty/boundary_precision_check/zone_truck_capacity_exactly_at_limit
    """
    _four_zone1_blocks(api)
    # [10:00,12:00) touches [08:00,10:00) at the boundary -> not an overlap.
    adjacent = validate_success(api.create_truck_block(
        factories.create_truck_block_payload(
            window_start="2026-08-04T10:00:00Z",
            window_end="2026-08-04T12:00:00Z",
            reason="b6-adjacent",
        ), FLEET
    ), 201)
    assert adjacent["freight_zone"] == 1
    # Capacity is per zone: zone 2 is empty for the same window.
    other_zone = validate_success(api.create_truck_block(
        factories.create_truck_block_payload(freight_zone=2, reason="b7-other-zone"),
        FLEET,
    ), 201)
    assert other_zone["freight_zone"] == 2


# ---------------------------------------------------------------------------
# Difficulty: resource_temporal_overlap / zone_fleet_half_open_aggregate_overlap
# ---------------------------------------------------------------------------

def test_partial_overlap_counts_against_zone_capacity(api):
    """PRD §3.5: "Delivery windows are treated as half-open intervals — a window includes its start instant and excludes its end instant, so two windows that merely touch at a boundary do not overlap. The consumers of a zone for a requested window are the orders in `CONFIRMED` or `OUT_FOR_DELIVERY` whose `capacity_zone` matches and whose booked windows overlap it, plus the `TruckBlock` records in that zone whose windows overlap it."

    Design: Difficulty/resource_temporal_overlap/zone_fleet_half_open_aggregate_overlap
    """
    _four_zone1_blocks(api)
    # [09:00,11:00) overlaps the four [08:00,10:00) blocks -> 5th consumer.
    resp = api.create_truck_block(
        factories.create_truck_block_payload(
            window_start="2026-08-04T09:00:00Z",
            window_end="2026-08-04T11:00:00Z",
            reason="partial-overlap",
        ),
        FLEET,
    )
    validate_error(resp, ApiErrorId.ERR_CAPACITY_EXCEEDED, 409)


def test_exact_adjacency_is_not_an_overlap(api):
    """PRD §3.5: "Delivery windows are treated as half-open intervals — a window includes its start instant and excludes its end instant, so two windows that merely touch at a boundary do not overlap."

    Design: Difficulty/resource_temporal_overlap/zone_fleet_half_open_aggregate_overlap
    """
    _four_zone1_blocks(api)
    block = validate_success(api.create_truck_block(
        factories.create_truck_block_payload(
            window_start="2026-08-04T10:00:00Z",
            window_end="2026-08-04T12:00:00Z",
            reason="adjacent",
        ),
        FLEET,
    ), 201)
    assert block["window_start"].startswith("2026-08-04T10:00")


# ---------------------------------------------------------------------------
# Difficulty: priority_pair_validation_conflict / confirm_state_vs_temporal_conflict
# CANCELLED order whose cutoff has also passed: the state-category guard
# (tier 6) surfaces before temporal rules (tier 9).
# ---------------------------------------------------------------------------

def _cancelled_order(api):
    create_config(api)
    v = create_variety(api)
    c = create_customer(api)
    set_clock(api, "2026-08-01T09:00:00Z")
    q = create_quote(api, c["id"],
                     [factories.quote_line(v["id"], "PREMIUM", 10)], 0, 10, 0)
    o = accept_quote(api, q["id"])
    get_success_data(api.cancel_order(o["id"], SALES))
    return o


def test_confirm_cancelled_order_past_cutoff_reports_terminal(api):
    """PRD §2.9: "The server evaluates twelve tiers in the following sequence and surfaces the first failure:" with "6. **Terminal guard** — the target entity is not in a terminal state for this action; otherwise `ERR_ALREADY_TERMINAL`." evaluated before "9. **Temporal rules** — delivery date not in the past, quote not expired, confirm before the cutoff, harvest times inside the daylight window, claim inside its thirty-day window; the corresponding error among `ERR_DELIVERY_DATE_TOO_SOON`, `ERR_QUOTE_EXPIRED`, `ERR_CUTOFF_PASSED`, `ERR_HARVEST_WINDOW`, and `ERR_CLAIM_WINDOW_EXPIRED`."
    PRD §2.9: "The ordering is observable."

    Design: Difficulty/priority_pair_validation_conflict/confirm_state_vs_temporal_conflict
    """
    o = _cancelled_order(api)
    # Cutoff for delivery 2026-08-03 is 2026-08-02T14:00; move past it.
    set_clock(api, "2026-08-02T15:00:00Z")
    resp = api.confirm_order(o["id"], factories.confirm_order_payload(), SALES)
    validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL, 409)


def test_confirm_cancelled_order_before_cutoff_still_terminal(api):
    """PRD §2.9: "6. **Terminal guard** — the target entity is not in a terminal state for this action; otherwise `ERR_ALREADY_TERMINAL`."
    PRD §3.6: "A `SalesRep` may cancel an order in `PLACED`, `CONFIRMED`, or `OUT_FOR_DELIVERY` provided nothing has been paid — a `total_paid` above zero rejects the cancel with `ERR_INVALID_STATE`, since paid orders require a credit workflow that is out of scope."

    Design: Difficulty/priority_pair_validation_conflict/confirm_state_vs_temporal_conflict
    """
    o = _cancelled_order(api)
    # Still before the cutoff: only the terminal guard can fire.
    resp = api.confirm_order(o["id"], factories.confirm_order_payload(), SALES)
    validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL, 409)


# ---------------------------------------------------------------------------
# Difficulty: priority_pair_validation_conflict / confirm_temporal_vs_capacity_conflict
# PLACED order past its cutoff AND facing a full zone: temporal (tier 9)
# surfaces before fiscal capacity (tier 12).
# ---------------------------------------------------------------------------

def _placed_order_behind_full_zone(api):
    create_config(api)
    v = create_variety(api)
    c = create_customer(api, full_name="Bo Lin", email="bo@example.com",
                        phone="555-0102", freight_zone=1, address="4 Pine Ave")
    for i in range(1, 5):
        get_success_data(api.create_truck_block(
            factories.create_truck_block_payload(
                freight_zone=1,
                window_start="2026-08-03T08:00:00Z",
                window_end="2026-08-03T10:00:00Z",
                reason=f"maint-{i}",
            ),
            FLEET,
        ))
    set_clock(api, "2026-08-01T09:00:00Z")
    q = create_quote(api, c["id"],
                     [factories.quote_line(v["id"], "PREMIUM", 10)], 10, 0, 0)
    o = accept_quote(api, q["id"])
    assert o["capacity_zone"] == 1
    return o


def test_confirm_past_cutoff_with_full_zone_reports_cutoff(api):
    """PRD §2.9: "The server evaluates twelve tiers in the following sequence and surfaces the first failure:" with "9. **Temporal rules** — delivery date not in the past, quote not expired, confirm before the cutoff, harvest times inside the daylight window, claim inside its thirty-day window; the corresponding error among `ERR_DELIVERY_DATE_TOO_SOON`, `ERR_QUOTE_EXPIRED`, `ERR_CUTOFF_PASSED`, `ERR_HARVEST_WINDOW`, and `ERR_CLAIM_WINDOW_EXPIRED`." evaluated before "12. **Fiscal checks last** — truck capacity, field availability, allocation sufficiency, exact payment amount, settled order; the corresponding error among `ERR_CAPACITY_EXCEEDED`, `ERR_BATCH_YIELD_EXCEEDS_AVAILABLE`, `ERR_ORDER_UNDER_ALLOCATED`, `ERR_PAYMENT_AMOUNT_MISMATCH`, and `ERR_ORDER_NOT_SETTLED`."

    Design: Difficulty/priority_pair_validation_conflict/confirm_temporal_vs_capacity_conflict
    """
    o = _placed_order_behind_full_zone(api)
    set_clock(api, "2026-08-02T15:00:00Z")  # past the 2026-08-02T14:00 cutoff
    resp = api.confirm_order(o["id"], factories.confirm_order_payload(), SALES)
    validate_error(resp, ApiErrorId.ERR_CUTOFF_PASSED, 409)


def test_confirm_before_cutoff_with_full_zone_reports_capacity(api):
    """PRD §2.9: "12. **Fiscal checks last** — truck capacity, field availability, allocation sufficiency, exact payment amount, settled order; the corresponding error among `ERR_CAPACITY_EXCEEDED`, `ERR_BATCH_YIELD_EXCEEDS_AVAILABLE`, `ERR_ORDER_UNDER_ALLOCATED`, `ERR_PAYMENT_AMOUNT_MISMATCH`, and `ERR_ORDER_NOT_SETTLED`."
    PRD §3.5: "When the existing consumer count already equals `zone_truck_capacity` (four by default), the request is rejected with `ERR_CAPACITY_EXCEEDED` — four overlapping consumers may hold capacity at once, and the one that would become the fifth fails."

    Design: Difficulty/priority_pair_validation_conflict/confirm_temporal_vs_capacity_conflict
    """
    o = _placed_order_behind_full_zone(api)
    set_clock(api, "2026-08-01T10:00:00Z")  # comfortably before the cutoff
    resp = api.confirm_order(o["id"], factories.confirm_order_payload(), SALES)
    validate_error(resp, ApiErrorId.ERR_CAPACITY_EXCEEDED, 409)


# ---------------------------------------------------------------------------
# Corner: state_machines / order_confirm_valid_transition_side_effects
# ---------------------------------------------------------------------------

def test_order_confirm_valid_transition_side_effects(api):
    """PRD §3.5: "On success the order becomes `CONFIRMED`, the selected batches take the order's `order_id` (their own status unchanged), and the order's `allocated_sqft` — the summed `sellable_sqft` of its linked, non-cancelled batches — is recomputed."
    PRD §3.5: "A `SalesRep` confirms a `PLACED` order by supplying `delivery_window_start`, which must fall on the order's `delivery_date`, be aligned to the top of an hour, and start no earlier than the card's `delivery_earliest_start_hour` (06:00 by default) and no later than `delivery_latest_start_hour` (16:00 by default); the `delivery_window_end` is derived as the start plus `delivery_window_hours` (two hours by default), so a default booking ends by 18:00."

    Design: Corner/state_machines/order_confirm_valid_transition_side_effects
    """
    create_config(api)
    v = create_variety(api)
    f = create_field(api, v["id"])
    b = create_batch(api, f["id"], pallet_count=3)  # sellable 300
    c = create_customer(api)
    set_clock(api, "2026-08-01T09:00:00Z")
    q = create_quote(api, c["id"],
                     [factories.quote_line(v["id"], "PREMIUM", 2)], 1, 1, 0)
    o = accept_quote(api, q["id"])

    confirmed = confirm_and_validate(api, o["id"])
    assert confirmed["status"] == "CONFIRMED"
    assert_instant_equals(confirmed["delivery_window_end"], "2026-08-03T10:00:00Z")
    assert_money_eq(confirmed["allocated_sqft"], 300,
                    "whole-batch allocation overshoots the 200-sqft line")

    batch_after = get_success_data(api.get_harvest_batch(b["id"], HARVEST))
    assert batch_after["order_id"] == o["id"], "allocation links the batch"
    assert batch_after["status"] == "PENDING", "the batch's own status is unchanged"


# ---------------------------------------------------------------------------
# Corner: errors / allocation_all_stale_returns_batch_not_fresh
# ---------------------------------------------------------------------------

def test_allocation_all_stale_returns_batch_not_fresh(api):
    """PRD §3.5: "When the eligible pool runs out before a line is met, the failure is `ERR_BATCH_NOT_FRESH` if at least one variety- and grade-matched unlinked batch was excluded solely by the freshness projection, and `ERR_ORDER_UNDER_ALLOCATED` otherwise."
    PRD §3.5: "A candidate batch must be `PENDING` or `COMPLETE`, unlinked (its `order_id` null), matching the line's variety and grade, and projected fresh: for a `COMPLETE` batch the projected harvest end is its recorded `actual_harvest_end`, while for a `PENDING` batch it is the batch's `scheduled_date` at 08:00 UTC; the projected freshness is the hours from that projected end to the order's `delivery_window_end`, and the candidate is eligible only when the projection is at least zero and at most the card's `freshness_limit_hours` (24 hours by default) — a projection of exactly the limit remains eligible, while a negative projection (the batch would finish after the window ends) is ineligible."

    Design: Corner/errors/allocation_all_stale_returns_batch_not_fresh
    """
    create_config(api)
    v = create_variety(api)
    f = create_field(api, v["id"])
    b = create_batch(api, f["id"], pallet_count=3, scheduled_date="2026-08-01")
    c = create_customer(api)
    set_clock(api, "2026-08-01T08:30:00Z")
    complete_batch(api, b["id"], start="2026-08-01T06:30:00Z",
                   end="2026-08-01T08:00:00Z")
    set_clock(api, "2026-08-01T09:00:00Z")
    q = create_quote(api, c["id"],
                     [factories.quote_line(v["id"], "PREMIUM", 2)], 1, 1, 0)
    o = accept_quote(api, q["id"])

    # Window end 2026-08-03T10:00 is 50h after the recorded harvest end: the
    # only matched candidate is excluded solely by freshness.
    resp = api.confirm_order(o["id"], factories.confirm_order_payload(), SALES)
    validate_error(resp, ApiErrorId.ERR_BATCH_NOT_FRESH, 422)


# ---------------------------------------------------------------------------
# Corner: errors / confirm_without_any_batches_returns_order_under_allocated
# ---------------------------------------------------------------------------

def test_confirm_without_any_batches_returns_order_under_allocated(api):
    """PRD §3.5: "When the eligible pool runs out before a line is met, the failure is `ERR_BATCH_NOT_FRESH` if at least one variety- and grade-matched unlinked batch was excluded solely by the freshness projection, and `ERR_ORDER_UNDER_ALLOCATED` otherwise."

    Design: Corner/errors/confirm_without_any_batches_returns_order_under_allocated
    """
    create_config(api)
    v = create_variety(api)
    c = create_customer(api)
    set_clock(api, "2026-08-01T09:00:00Z")
    q = create_quote(api, c["id"],
                     [factories.quote_line(v["id"], "PREMIUM", 2)], 1, 1, 0)
    o = accept_quote(api, q["id"])

    resp = api.confirm_order(o["id"], factories.confirm_order_payload(), SALES)
    validate_error(resp, ApiErrorId.ERR_ORDER_UNDER_ALLOCATED, 409)
    after = get_success_data(api.get_order(o["id"], SALES))
    assert after["status"] == "PLACED", "a rejected confirm persists no partial state"


# ---------------------------------------------------------------------------
# Corner: validations / confirm_missing_window_on_cancelled_order_returns_invalid_request
# ---------------------------------------------------------------------------

def test_confirm_missing_window_on_cancelled_order_returns_invalid_request(api):
    """PRD §2.9: "The server evaluates twelve tiers in the following sequence and surfaces the first failure:" with "4. **Request shape** — required fields present, types and ranges valid, windows aligned, uniqueness respected; otherwise `ERR_INVALID_REQUEST`." evaluated before "6. **Terminal guard** — the target entity is not in a terminal state for this action; otherwise `ERR_ALREADY_TERMINAL`."
    PRD §2.9: "The ordering is observable. A confirmation attempt that would fail both the window shape and the truck pool reports the shape error, and a wrong-amount payment against an already-closed order reports the terminal error rather than the payment mismatch."

    Design: Corner/validations/confirm_missing_window_on_cancelled_order_returns_invalid_request
    """
    o = _cancelled_order(api)
    resp = api.confirm_order(o["id"], {}, SALES)  # missing delivery_window_start
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)


# ---------------------------------------------------------------------------
# Corner: validations / existence_beats_all_business_rules_not_found
# ---------------------------------------------------------------------------

def test_existence_beats_all_business_rules_not_found(api):
    """PRD §2.9: "3. **Existence** — path identifiers resolve left-to-right, and body references (`customer_id`, `variety_id`, `field_id`, `crew_id`, and each quote line's `variety_id`) resolve; otherwise `ERR_NOT_FOUND`."
    PRD §2.10: "Paths that address a sub-resource are validated left-to-right: the server resolves the first identifier, then the next, and rejects with `ERR_NOT_FOUND` (404) at the first identifier that does not exist, never reaching deeper validations."

    Design: Corner/validations/existence_beats_all_business_rules_not_found
    """
    create_config(api)
    resp = api.confirm_order(
        NON_EXISTENT_UUID, factories.confirm_order_payload(), SALES
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)


# ---------------------------------------------------------------------------
# Corner: consistency / mutation_responses_reflect_final_state_immediately
# ---------------------------------------------------------------------------

def test_mutation_responses_reflect_final_state_immediately(api):
    """PRD §2.2: "The `data` field contains the resource object or an array of resource objects. For 2xx responses with no data, it contains an empty object. Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field."
    PRD §2.11: "Several writes propagate beyond their primary target, and every cascade commits atomically within the request — there is no eventual-consistency window."

    Design: Corner/consistency/mutation_responses_reflect_final_state_immediately
    """
    create_config(api)
    v = create_variety(api)
    f = create_field(api, v["id"])
    create_batch(api, f["id"], pallet_count=3)
    c = create_customer(api)
    set_clock(api, "2026-08-01T09:00:00Z")
    q = create_quote(api, c["id"],
                     [factories.quote_line(v["id"], "PREMIUM", 2)], 1, 1, 0)
    o = accept_quote(api, q["id"])

    resp_data = confirm_and_validate(api, o["id"])
    assert resp_data["status"] == "CONFIRMED"
    assert_instant_equals(resp_data["delivery_window_end"], "2026-08-03T10:00:00Z")
    assert_money_eq(resp_data["allocated_sqft"], 300, "allocated_sqft in response")

    fetched = get_success_data(api.get_order(o["id"], SALES))
    assert fetched["status"] == "CONFIRMED"
    assert_instant_equals(fetched["delivery_window_end"],
                          resp_data["delivery_window_end"])


# ---------------------------------------------------------------------------
# Corner: calculations / allocation_selector_freshest_first
# Two eligible 500-sqft COMPLETE batches (ends 06:30 vs 06:45); the line
# needs 500 -> only the freshest links.
# ---------------------------------------------------------------------------

def test_allocation_selector_freshest_first(api):
    """PRD §3.5: "Eligible candidates are ranked freshest first — the latest projected harvest end leads — with ties broken toward the smaller `sellable_sqft` to minimize waste, and remaining ties toward the earlier `created_at`. Batches accumulate whole until the cumulative `sellable_sqft` reaches the line's yield; the final batch may overshoot, and partial consumption of a batch is not allowed."
    PRD §3.5: "For a same-day order — `delivery_date` equal to the clock's current date — the confirm cutoff is the order's `created_at` plus `same_day_cutoff_hours` (two hours by default)."

    Design: Corner/calculations/allocation_selector_freshest_first
    """
    create_config(api)
    v = create_variety(api)
    f = create_field(api, v["id"])
    b_old = create_batch(api, f["id"], pallet_count=5)
    b_new = create_batch(api, f["id"], pallet_count=5)
    c = create_customer(api)

    # Same-day order created 05:00 -> cutoff 07:00.
    set_clock(api, "2026-08-03T05:00:00Z")
    q = create_quote(api, c["id"],
                     [factories.quote_line(v["id"], "PREMIUM", 5)], 0, 5, 0)
    o = accept_quote(api, q["id"])

    set_clock(api, "2026-08-03T06:50:00Z")
    complete_batch(api, b_old["id"], start="2026-08-03T06:00:00Z",
                   end="2026-08-03T06:30:00Z")
    complete_batch(api, b_new["id"], start="2026-08-03T06:15:00Z",
                   end="2026-08-03T06:45:00Z")

    set_clock(api, "2026-08-03T06:55:00Z")
    confirmed = confirm_and_validate(api, o["id"])
    assert confirmed["status"] == "CONFIRMED"
    assert_money_eq(confirmed["allocated_sqft"], 500,
                    "the line is met by exactly one whole batch")

    linked, meta = validate_paginated(
        api.list_harvest_batches(FARM, params={"order_id": o["id"]})
    )
    assert len(linked) == 1 and linked[0]["id"] == b_new["id"], (
        "the freshest batch (harvest end 06:45) wins over the 06:30 batch"
    )
    old_after = get_success_data(api.get_harvest_batch(b_old["id"], HARVEST))
    assert old_after["order_id"] is None
