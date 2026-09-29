"""Layers that only misbehave together, and one response that must carry it all.

Two version tokens guard the two operations that are legal to repeat, one
counter is maintained by side effects on three different edges, one strike count
is consecutive rather than cumulative, one filtered page must count the filtered
set, and one commit must expose every subsystem's result in a single body.
"""

import test_helpers as H
from test_helpers import factories as F
from test_helpers import fixtures as X

E = H.ApiErrorId

CLOCK_EARLY = "2026-08-01T06:00:00Z"
CLOCK_LUNCH = "2026-08-01T11:00:00Z"
KA = H.KITCHEN_ASSOCIATE_HEADERS
SM = H.STORE_MANAGER_HEADERS


def _plan_by_id(api, store_id: str, plan_id: str, params=None):
    rows, meta = H.validate_paginated(api.list_staffing_plans(store_id, SM, params))
    matches = [row for row in rows if row["id"] == plan_id]
    return matches[0] if matches else None, meta


def test_replaying_the_store_version_token_cannot_supersede_a_plan_twice(api):
    """The second create is refused by the token alone, then succeeds with a fresh one.

    Nothing about the state rejects a second create — "plan creation legitimately
    supersedes any existing draft or published plan for the same store, service
    date and daypart combination" — so the guard is the only line of defence:
    "`POST /stores/{id}/staffing-plans` requires a non-optional
    `expected_store_version` field carrying the client's last observed `version`
    of the target `Store`. If that value does not equal the store's current
    `version`, the request is rejected with `ERR_STALE_STORE_VERSION` and HTTP
    412." The token the client held goes stale because the first create moved the
    store: "the store's `version` is also incremented by the create." Retrying
    with the fresh token performs the supersession that was intended all along,
    where "Any existing plan for that same combination whose status is `DRAFT` or
    `PUBLISHED` transitions to `SUPERSEDED`".

    Design: Corner/cross_cutting_complexity_layers/stale_expected_store_version_on_plan_create_returns_412
    """
    X.set_clock(api, CLOCK_EARLY)
    store = X.create_store(api)
    stale_token = store["version"]

    plan_a = H.get_success_data(
        api.create_staffing_plan(
            store["id"],
            F.staffing_plan_payload(stale_token, daypart="BREAKFAST", forecast_txn_count=300),
            SM,
        ),
        201,
    )

    replayed = api.create_staffing_plan(
        store["id"],
        F.staffing_plan_payload(stale_token, daypart="BREAKFAST", forecast_txn_count=360),
        SM,
    )

    H.validate_error(replayed, E.ERR_STALE_STORE_VERSION.value, 412)

    fresh_token = X.read_store(api, store["id"])["version"]
    assert fresh_token == stale_token + 1

    plan_b = H.get_success_data(
        api.create_staffing_plan(
            store["id"],
            F.staffing_plan_payload(fresh_token, daypart="BREAKFAST", forecast_txn_count=360),
            SM,
        ),
        201,
    )

    assert plan_b["status"] == "DRAFT"
    assert plan_b["forecast_txn_count"] == 360

    superseded, dated_meta = _plan_by_id(
        api, store["id"], plan_a["id"], {"service_date": "2026-08-01"}
    )
    assert superseded["status"] == "SUPERSEDED"
    assert superseded["forecast_txn_count"] == 300
    assert dated_meta["total_count"] == 2

    survivor, draft_meta = _plan_by_id(api, store["id"], plan_b["id"], {"status": "DRAFT"})
    assert survivor is not None
    assert draft_meta["total_count"] == 1


def test_replaying_the_batch_version_token_cannot_write_off_the_same_ten_twice(api):
    """A repeatable write-off is told apart from a double submit, and the 412 is inert.

    "Partial write-offs are repeatable by design — a second discard of the same
    quantity against a batch that still holds units is a legitimate operation
    that no state precondition rejects — so the stale-version comparison is the
    only deterministic guard against writing off units the client never saw",
    and it answers "`ERR_STALE_BATCH_VERSION` and HTTP 412". The rejected replay
    moves nothing: the ledger still reads the single accepted write-off, which
    "subtracts the `qty` from `remaining_qty` and adds it to `discarded_qty`". Only
    once the client re-reads does the second write-off land, and the batch
    survives both because "otherwise — including the case where units are still
    reserved to placed orders — the batch stays in `HOLDING` and the slot count is
    untouched." Twenty units at 40 cents of ingredient reach the operational
    figure, since "The store's `waste_cost_cents_mtd` increases by the record's
    `food_cost_cents`", while the inspector's basis is the retail one.

    Design: Corner/cross_cutting_complexity_layers/stale_expected_batch_version_on_discard_returns_412
    """
    X.set_clock(api, CLOCK_EARLY)
    store = X.create_store(api)
    unit = X.create_bakery_case(api, store["id"])
    pretzel = X.create_pretzel(api)
    pulled = X.create_holding_batch(
        api, store["id"], pretzel["id"], unit["id"], planned_qty=40, bake_start_at=CLOCK_EARLY
    )
    stale_token = pulled["version"]
    assert pulled["remaining_qty"] == 40

    first = H.get_success_data(
        api.discard_production_batch(
            pulled["id"], F.discard_payload(10, "QUALITY_REJECT", stale_token), KA
        )
    )
    assert first["remaining_qty"] == 30
    assert first["discarded_qty"] == 10

    replayed = api.discard_production_batch(
        pulled["id"], F.discard_payload(10, "QUALITY_REJECT", stale_token), KA
    )

    H.validate_error(replayed, E.ERR_STALE_BATCH_VERSION.value, 412)

    midpoint = X.read_batch(api, pulled["id"])
    assert midpoint["remaining_qty"] == 30
    assert midpoint["discarded_qty"] == 10
    assert midpoint["version"] == stale_token + 1

    second = H.get_success_data(
        api.discard_production_batch(
            pulled["id"], F.discard_payload(10, "QUALITY_REJECT", midpoint["version"]), KA
        )
    )
    assert second["remaining_qty"] == 20
    assert second["discarded_qty"] == 20
    assert second["status"] == "HOLDING"

    after_store = X.read_store(api, store["id"])
    assert after_store["waste_cost_cents_mtd"] == 800
    assert after_store["hot_case_slots_used"] == 1
    _, waste_meta = H.validate_paginated(api.list_batch_waste_logs(pulled["id"], SM))
    assert waste_meta["total_count"] == 2
    assert X.read_readiness(api, store["id"])["retail_waste_exposure_cents"] == 3980


def test_a_verified_repair_makes_the_next_failing_probe_the_first_one_again(api):
    """Two failing readings with a sign-off between them leave the case merely impaired.

    The count is consecutive, not cumulative: "The counter is described as the
    number of consecutive failing readings since the last verified corrective
    action, and it returns to zero only when such a verification occurs — not
    merely because a subsequent reading happens to be in range." So the first
    120 °F probe against a 135..185 band is out of band, where "The `in_range`
    flag is true exactly when the `reading_f` is greater than or equal to the
    unit's `min_temp_f` and less than or equal to its `max_temp_f`", and "A unit
    in `OPERATIONAL` goes `OPERATIONAL → IMPAIRED`, and its
    `consecutive_out_of_range_count` increases by one, reaching 1." The
    verification "returns the unit to service" and "resets the unit's
    `consecutive_out_of_range_count` to zero", which is why the second failing
    probe restarts at 1 instead of triggering the escalation that applies when "A
    unit already in `IMPAIRED` goes `IMPAIRED → LOCKED_OUT`". The readiness
    summary agrees, counting "the store's units currently in `IMPAIRED`".

    Design: Corner/cross_cutting_complexity_layers/verified_corrective_action_resets_the_strike_counter
    """
    X.set_clock(api, CLOCK_EARLY)
    store = X.create_store(api)
    unit = X.create_bakery_case(api, store["id"])
    assert unit["consecutive_out_of_range_count"] == 0

    first_failure = X.log_temperature(api, unit["id"], 120, KA)
    assert first_failure["in_range"] is False
    impaired = X.read_holding_unit(api, unit["id"])
    assert impaired["status"] == "IMPAIRED"
    assert impaired["consecutive_out_of_range_count"] == 1

    action = X.open_corrective_action(
        api, first_failure["id"], KA, action_taken="RESET_THE_CASE_AND_REPROBED"
    )
    verified = H.get_success_data(
        api.verify_corrective_action(action["id"], {}, H.FOOD_SAFETY_LEAD_HEADERS)
    )
    assert verified["status"] == "VERIFIED"
    repaired = X.read_holding_unit(api, unit["id"])
    assert repaired["status"] == "OPERATIONAL"
    assert repaired["consecutive_out_of_range_count"] == 0

    X.log_temperature(api, unit["id"], 118, KA)

    restruck = X.read_holding_unit(api, unit["id"])
    assert restruck["status"] == "IMPAIRED"
    assert restruck["consecutive_out_of_range_count"] == 1

    readiness = X.read_readiness(api, store["id"])
    assert readiness["units_impaired_count"] == 1
    assert readiness["units_locked_out_count"] == 0
    _, failing_meta = H.validate_paginated(
        api.list_temperature_logs(unit["id"], SM, {"in_range": "false"})
    )
    assert failing_meta["total_count"] == 2


def test_the_slot_counter_survives_two_bakes_a_top_off_and_one_full_write_off(api):
    """Two physical pans never claim three slots, and only the emptying write-off frees one.

    Planning claims nothing; the oven does: on a bake "the store's
    `hot_case_slots_used` increases by one". The cycle edge is where a naive
    counter breaks, because the top-off bake runs the same transition again:
    "Critically, the store's `hot_case_slots_used` is *unchanged* by a top-off,
    because the batch already occupies its slot and never gave it up", while "The
    top-off adds the `additional_qty` to both `baked_qty` and `remaining_qty`".
    The top-off also "clears the hold clock", so the following pull re-arms it —
    "`hold_expires_at` to that instant advanced by the item's `hold_minutes`" —
    240 minutes past six in the morning. Only the write-off that empties the pan
    releases the slot: "if after the write-off both `remaining_qty` and
    `reserved_qty` are zero, the batch goes `HOLDING → DISCARDED` and the store's
    `hot_case_slots_used` decreases by one". Its 25 units are valued twice, on the
    food-cost basis for the store counter and on the retail basis for the
    inspection summary.

    Design: Corner/cross_cutting_complexity_layers/hot_case_slots_used_reconciles_after_bake_topoff_and_full_discard
    """
    X.set_clock(api, CLOCK_EARLY)
    store = X.create_store(api, hot_case_slot_capacity=4)
    assert store["hot_case_slots_used"] == 0
    unit = X.create_bakery_case(api, store["id"])
    pretzel = X.create_pretzel(api)
    batch_a = X.create_planned_batch(
        api, store["id"], pretzel["id"], unit["id"],
        slot_index=1, planned_qty=20, bake_start_at=CLOCK_EARLY,
    )
    batch_b = X.create_planned_batch(
        api, store["id"], pretzel["id"], unit["id"],
        slot_index=2, planned_qty=10, bake_start_at=CLOCK_EARLY,
    )
    assert X.read_store(api, store["id"])["hot_case_slots_used"] == 0

    baked_a = X.bake_batch(api, batch_a["id"])
    X.bake_batch(api, batch_b["id"])
    assert baked_a["baked_qty"] == 20
    assert baked_a["remaining_qty"] == 20
    assert X.read_store(api, store["id"])["hot_case_slots_used"] == 2

    X.pull_batch(api, batch_a["id"])
    topped_off = X.bake_batch(api, batch_a["id"], additional_qty=5)

    assert topped_off["status"] == "BAKING"
    assert topped_off["baked_qty"] == 25
    assert topped_off["remaining_qty"] == 25
    assert X.read_store(api, store["id"])["hot_case_slots_used"] == 2

    repulled = X.pull_batch(api, batch_a["id"])
    assert repulled["hold_expires_at"] == "2026-08-01T10:00:00Z"

    emptied = H.get_success_data(
        api.discard_production_batch(
            batch_a["id"],
            F.discard_payload(25, "QUALITY_REJECT", repulled["version"]),
            H.SHIFT_LEAD_HEADERS,
        )
    )

    assert emptied["status"] == "DISCARDED"
    assert emptied["remaining_qty"] == 0
    assert emptied["discarded_qty"] == 25
    after = X.read_store(api, store["id"])
    assert after["hot_case_slots_used"] == 1
    assert after["waste_cost_cents_mtd"] == 1000
    assert X.read_batch(api, batch_b["id"])["status"] == "BAKING"
    _, waste_meta = H.validate_paginated(api.list_batch_waste_logs(batch_a["id"], SM))
    assert waste_meta["total_count"] == 1
    readiness = X.read_readiness(api, store["id"])
    assert readiness["retail_waste_exposure_cents"] == 4975
    assert readiness["food_cost_waste_cents_mtd"] == 1000


def test_a_filtered_page_counts_the_filtered_set_and_never_repeats_a_row(api):
    """Five batches, three planned: both pages of a two-at-a-time walk report three.

    "Filter parameters, where an endpoint offers them, narrow the set before
    pagination is applied, so `total_count` reflects the filtered population
    rather than the whole table", and the batch list "may be ... listed with
    filters on `store_id`, `menu_item_id`, `holding_unit_id` and `status`." The
    two pages must partition the filtered population exactly — no row twice and
    none missing — and the flag must follow the same set, since "`has_more`
    indicates whether records remain beyond the current page". The unfiltered read
    shows the page size the client never asked for, because "when omitted it
    defaults to 10, and the accepted range is a minimum of 1 and a maximum of
    100", and an offset past the end returns nothing while still counting the
    population it skipped, since "The `offset` parameter is the number of records
    to skip and defaults to 0." Filters compose — a unit and a status together
    narrow to one row — and a bake between two reads is reflected immediately.

    Design: Corner/cross_cutting_complexity_layers/production_batch_list_filters_by_status_then_paginates
    """
    X.set_clock(api, CLOCK_EARLY)
    store = X.create_store(api, hot_case_slot_capacity=4)
    unit_one = X.create_bakery_case(api, store["id"], unit_code="BC-1")
    unit_two = X.create_bakery_case(api, store["id"], unit_code="BC-2")
    pretzel = X.create_pretzel(api)
    batches = [
        X.create_planned_batch(
            api, store["id"], pretzel["id"], unit_id,
            slot_index=slot, planned_qty=12, bake_start_at=CLOCK_EARLY,
        )
        for unit_id, slot in (
            (unit_one["id"], 1), (unit_one["id"], 2), (unit_one["id"], 3),
            (unit_two["id"], 1), (unit_two["id"], 2),
        )
    ]
    b1, b2, b3, b4, b5 = (batch["id"] for batch in batches)
    X.bake_batch(api, b1)
    X.bake_batch(api, b4)

    everything, all_meta = H.validate_paginated(
        api.list_production_batches(SM, {"store_id": store["id"]})
    )
    assert all_meta["total_count"] == 5
    assert all_meta["has_more"] is False
    assert all_meta["limit"] == 10
    assert all_meta["offset"] == 0
    assert len(everything) == 5

    page_one, page_one_meta = H.validate_paginated(
        api.list_production_batches(
            SM, {"store_id": store["id"], "status": "PLANNED", "limit": 2, "offset": 0}
        )
    )
    assert page_one_meta["total_count"] == 3
    assert page_one_meta["has_more"] is True
    assert len(page_one) == 2

    page_two, page_two_meta = H.validate_paginated(
        api.list_production_batches(
            SM, {"store_id": store["id"], "status": "PLANNED", "limit": 2, "offset": 2}
        )
    )
    assert page_two_meta["total_count"] == 3
    assert page_two_meta["has_more"] is False
    assert len(page_two) == 1

    walked = [row["id"] for row in page_one] + [row["id"] for row in page_two]
    assert len(set(walked)) == 3
    assert set(walked) == {b2, b3, b5}

    baking, baking_meta = H.validate_paginated(
        api.list_production_batches(SM, {"store_id": store["id"], "status": "BAKING"})
    )
    assert baking_meta["total_count"] == 2
    assert baking_meta["has_more"] is False
    assert {row["id"] for row in baking} == {b1, b4}

    narrowed, narrowed_meta = H.validate_paginated(
        api.list_production_batches(SM, {"holding_unit_id": unit_two["id"], "status": "PLANNED"})
    )
    assert narrowed_meta["total_count"] == 1
    assert narrowed[0]["id"] == b5

    X.bake_batch(api, b2)

    remaining, remaining_meta = H.validate_paginated(
        api.list_production_batches(SM, {"store_id": store["id"], "status": "PLANNED"})
    )
    assert remaining_meta["total_count"] == 2
    assert remaining_meta["has_more"] is False
    assert {row["id"] for row in remaining} == {b3, b5}

    past_the_end, past_meta = H.validate_paginated(
        api.list_production_batches(
            SM, {"store_id": store["id"], "status": "PLANNED", "offset": 99}
        )
    )
    assert past_the_end == []
    assert past_meta["total_count"] == 2
    assert past_meta["has_more"] is False
    assert X.read_store(api, store["id"])["hot_case_slots_used"] == 3


def test_one_place_response_already_carries_every_subsystem_s_result(api):
    """Pricing, promotion, reservation, ticketing and points all land in the same body.

    A commit fans out, and the response is expected to be final rather than
    eventual. The gross subtotal is "the sum of the `line_gross_cents` of all its
    lines"; the single `ACTIVE` rule whose "`valid_dayparts` contains the store's
    `current_daypart`" wins the pool; and the discount is per line, "**rounded
    half up per line**", so 899 gives 90 and 398 gives 40 for 130 — a per-order
    shortcut would agree on the total and disagree on the lines, since "The
    identity that the per-line discounts sum to the order's discount always
    holds" and "Each line's `line_net_cents` is finally its `line_gross_cents`
    minus its `line_discount_cents`." The fee stays out of the way because
    "The order's `service_fee_cents` is 0 for a `TOUCHSCREEN` or `MOBILE_PREORDER`
    order", leaving `total_cents` at 1167 and, at "10000 basis points at `BASIC`"
    with the remainder "**discarded**", 11 points. Reservation writes both sides —
    "the line's `reserved_qty` is set to the line's `qty`, and on the batch the
    same quantity is subtracted from `remaining_qty` and added to `reserved_qty`"
    — the par-baked line cuts no ticket, and "The order's `expected_ready_at` is
    the latest `promised_ready_at` among the tickets this commit created".

    Design: Corner/consistency_model/place_response_carries_totals_promotion_tickets_and_points_at_once
    """
    store = X.setup_store_open_for_lunch(api, clock=CLOCK_LUNCH)
    unit = X.create_bakery_case(api, store["id"])
    hoagie = X.create_hoagie(api)
    pretzel = X.create_pretzel(api)
    batch = X.create_holding_batch(
        api, store["id"], pretzel["id"], unit["id"], planned_qty=40, bake_start_at=CLOCK_LUNCH
    )
    assert batch["hold_expires_at"] == "2026-08-01T15:00:00Z"
    promotion = X.create_promotion_rule(
        api, code="LUNCH10", discount_bp=1000, max_discount_cents=100000, stacking_rank=1
    )
    member = X.create_loyalty_account(api, member_code="M-A", email="a@example.com")
    assert member["tier"] == "BASIC"
    order = X.create_draft_order(api, store["id"], loyalty_account_id=member["id"])
    hoagie_line = X.add_order_line(api, order["id"], hoagie["id"], 1)
    pretzel_line = X.add_order_line(api, order["id"], pretzel["id"], 2)
    assert hoagie_line["line_gross_cents"] == 899
    assert hoagie_line["line_net_cents"] == 0
    assert pretzel_line["line_gross_cents"] == 398
    assert pretzel_line["reserved_qty"] == 0

    placed = H.get_success_data(api.place_order(order["id"], {}, H.STORE_TERMINAL_HEADERS))

    assert placed["subtotal_gross_cents"] == 1297
    assert placed["promo_discount_cents"] == 130
    assert placed["applied_promotion_id"] == promotion["id"]
    assert placed["service_fee_cents"] == 0
    assert placed["total_cents"] == 1167
    assert placed["points_provisional"] == 11
    assert placed["daypart_at_placement"] == "LUNCH"
    assert placed["expected_ready_at"] == "2026-08-01T11:03:00Z"
    assert placed["production_status"] == "PLACED"
    assert placed["settlement_status"] == "UNPAID"

    priced_hoagie = X.read_order_line(api, hoagie_line["id"])
    priced_pretzel = X.read_order_line(api, pretzel_line["id"])
    assert priced_hoagie["line_discount_cents"] == 90
    assert priced_hoagie["line_net_cents"] == 809
    assert priced_hoagie["fulfillment_batch_id"] is None
    assert priced_pretzel["line_discount_cents"] == 40
    assert priced_pretzel["line_net_cents"] == 358
    assert priced_pretzel["reserved_qty"] == 2
    assert priced_pretzel["fulfillment_batch_id"] == batch["id"]

    reserved = X.read_batch(api, batch["id"])
    assert reserved["remaining_qty"] == 38
    assert reserved["reserved_qty"] == 2

    account = X.read_loyalty_account(api, member["id"])
    assert account["points_balance"] == 11
    assert account["lifetime_points_earned"] == 11

    tickets, ticket_meta = H.validate_paginated(
        api.list_kitchen_tickets(KA, {"order_id": order["id"]})
    )
    assert ticket_meta["total_count"] == 1
    assert tickets[0]["station"] == "SANDWICH"

    reread = X.read_order(api, order["id"])
    for field in (
        "subtotal_gross_cents", "promo_discount_cents", "service_fee_cents",
        "total_cents", "points_provisional", "expected_ready_at",
    ):
        assert reread[field] == placed[field]
