"""The warehouse, the allocation pass and the inventory pull lifecycle."""

from test_helpers import (
    WAREHOUSE,
    ApiErrorId,
    assert_inventory_item,
    assert_money,
    assert_pull,
    assert_pull_line,
    assert_warehouse_conservation,
    make_seller_headers,
    new_item,
    setup_clock_only,
    setup_one_owned_item,
    setup_three_owned_items,
    setup_vacant_project_draft,
    setup_vacant_project_staged,
    setup_vacant_pull_committed,
    setup_vacant_pull_draft,
    setup_vacant_pull_exactly_seventy_percent,
    setup_vacant_pull_partial_sixty_percent,
    setup_vacant_three_owned_lines_submitted,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_repair_out_on_an_available_unit_is_an_invalid_item_state(api):
    """PRD §2.7: "Rung 22: the inventory item's `status` is a legal origin for the requested
    transition; otherwise `ERR_ITEM_INVALID_STATE`, HTTP 409."
    PRD §3.4: "The repair loop runs `DEPLOYED → IN_REPAIR → AVAILABLE`: a repair-disposition
    damage finalization sends a deployed unit to the bench and degrades its
    `condition_grade` one step, `A` becoming `B`, `B` becoming `C`, and `C` staying `C`; a
    repair-out returns it to stock."

    Design: Corner/state_machines/repair_out_from_available_rejected_as_item_invalid_state
    """
    ctx = setup_one_owned_item()

    resp = api.repair_out_item(ctx["item_a"], WAREHOUSE)

    validate_error(resp, ApiErrorId.ERR_ITEM_INVALID_STATE.value, 409)
    item = validate_success(api.get_inventory_item(ctx["item_a"], WAREHOUSE))
    assert item["status"] == "AVAILABLE"
    assert item["version"] == 1


def test_a_written_off_unit_is_terminal_but_still_counted_on_hand(api):
    """PRD §3.4: "`WRITTEN_OFF` is terminal, and a written-off unit is still counted in
    `on_hand_total` forever."
    PRD §2.11: "A written-off unit remains counted in the total forever; it simply stops
    being available."

    Design: Corner/state_machines/written_off_item_is_terminal_and_rejects_repair_in
    """
    ctx = setup_one_owned_item()
    validate_success(api.write_off_item(ctx["item_a"], "Frame cracked in transit", WAREHOUSE))

    resp = api.repair_in_item(ctx["item_a"], WAREHOUSE)

    validate_error(resp, ApiErrorId.ERR_ITEM_INVALID_STATE.value, 409)
    item = validate_success(api.get_inventory_item(ctx["item_a"], WAREHOUSE))
    assert item["status"] == "WRITTEN_OFF"
    summary = validate_success(api.get_inventory_summary(WAREHOUSE))
    assert summary["on_hand_total"] == 1
    assert summary["written_off"] == 1
    assert_warehouse_conservation(summary)


def test_repair_loop_returns_the_unit_to_available_without_deploying_it(api):
    """PRD §3.4: "The repair loop runs `DEPLOYED → IN_REPAIR → AVAILABLE`: a
    repair-disposition damage finalization sends a deployed unit to the bench and degrades
    its `condition_grade` one step, `A` becoming `B`, `B` becoming `C`, and `C` staying `C`;
    a repair-out returns it to stock."
    PRD §3.4: "An `AVAILABLE` unit may be sent to the bench directly."

    Design: Difficulty/non_linear_state_machine/inventory_item_repair_reentry_loop_returns_to_available
    """
    ctx = setup_one_owned_item()
    validate_success(api.repair_in_item(ctx["item_a"], WAREHOUSE))

    resp = api.repair_out_item(ctx["item_a"], WAREHOUSE)

    validate_success(resp)
    item = validate_success(api.get_inventory_item(ctx["item_a"], WAREHOUSE))
    assert_inventory_item(item)
    assert item["status"] == "AVAILABLE"
    assert item["times_deployed"] == 0
    assert item["condition_grade"] == "A"


def test_the_repair_loop_bumps_the_units_version_once_per_hop(api):
    """PRD §2.4: "`version` is an integer that begins at 1 when the row is created and
    increments by exactly 1 on every mutation of that row."
    PRD §3.4: "An `AVAILABLE` unit may be sent to the bench directly."

    Design: Difficulty/non_linear_state_machine/inventory_item_repair_reentry_loop_returns_to_available
    """
    ctx = setup_one_owned_item()

    validate_success(api.repair_in_item(ctx["item_a"], WAREHOUSE))
    validate_success(api.repair_out_item(ctx["item_a"], WAREHOUSE))

    item = validate_success(api.get_inventory_item(ctx["item_a"], WAREHOUSE))
    assert item["version"] == 3, "creation, repair-in and repair-out are three row states"


def test_submitting_a_committed_pull_again_is_an_invalid_pull_state(api):
    """PRD §2.7: "Rung 21: the pull's `state` is a legal origin for the requested transition,
    and the pull is `COMMITTED` before an install may start; otherwise
    `ERR_PULL_INVALID_STATE`, HTTP 409."
    PRD §3.4: "A `PARTIAL` pull may be re-submitted, which increments `resubmit_count` and
    re-runs the pass over the `UNFILLED` lines only, moving any line for which a candidate
    now exists `UNFILLED → ALLOCATED`; the retry is refused once `resubmit_count` has
    reached 2, with `ERR_PULL_RESUBMIT_LIMIT`."

    Design: Corner/state_machines/pull_submit_after_commit_rejected_as_pull_invalid_state
    """
    ctx = setup_vacant_project_staged()

    resp = api.submit_pull(ctx["pull_id"], WAREHOUSE)

    validate_error(resp, ApiErrorId.ERR_PULL_INVALID_STATE.value, 409)
    pull = validate_success(api.get_pull(ctx["pull_id"], WAREHOUSE))
    assert_pull(pull)
    assert pull["state"] == "COMMITTED"
    assert pull["requested_unit_count"] == 13
    assert pull["filled_unit_count"] == 13
    assert float(pull["fill_rate"]) == 1.0
    assert pull["resubmit_count"] == 0


def test_a_committed_vendor_line_keeps_its_derived_monthly_rate(api):
    """PRD §3.4: "Every allocated line's `monthly_rate` is derived at that moment: an owned
    line takes the allocated unit's own `monthly_rate` and ignores `quantity` entirely,
    while a vendor line takes 85.00 multiplied by the vendor's `rate_multiplier` multiplied
    by the line's `quantity`; either way the result is rounded half-up to two decimal
    places."
    PRD §3.4: "A commit stamps `committed_at` with the logical clock, drops every
    still-`UNFILLED` line to `DROPPED`, and bumps both the pull's and the project's
    `version`."

    Design: Corner/state_machines/unfilled_lines_are_dropped_by_the_commit
    """
    ctx = setup_vacant_pull_committed()

    rows, meta = validate_paginated(api.list_pull_lines(
        WAREHOUSE, params={"pull_id": ctx["pull_id"]}))

    pull = validate_success(api.get_pull(ctx["pull_id"], WAREHOUSE))
    assert pull["state"] == "COMMITTED"
    assert pull["requested_unit_count"] == 4
    assert pull["filled_unit_count"] == 4
    assert float(pull["fill_rate"]) == 1.0
    line = next(row for row in rows if row["id"] == ctx["line_v"])
    assert_pull_line(line)
    assert line["state"] == "ALLOCATED"
    assert_money(line["monthly_rate"], 459.00, "pull line.monthly_rate")


def test_an_allocation_pass_that_fills_nothing_reports_insufficient_inventory(api):
    """PRD §2.7: "Rung 53: at least one inventory item with `status` `AVAILABLE` and the
    matching `category` exists for every `OWNED` line before a pull may be committed at full
    fill; otherwise `ERR_INSUFFICIENT_INVENTORY`, HTTP 409."
    PRD §2.7: "The error catalogue characterises the same code from the pass's point of
    view, as an allocation pass that filled zero units because no line on the pull could be
    satisfied from owned stock or a placed vendor order; both statements are recorded here
    as given."

    Design: Corner/errors/pull_that_fills_nothing_returns_insufficient_inventory
    """
    ctx = setup_vacant_project_draft()
    validate_success(api.authorize_project(
        ctx["proj_id"], make_seller_headers(ctx["seller_id"])))
    pull = validate_success(api.open_pull(ctx["proj_id"], WAREHOUSE), 201)
    validate_success(api.add_pull_line(
        pull["id"], {"source": "OWNED", "category": "SOFA",
                     "room_label": "Living", "quantity": 1}, WAREHOUSE), 201)

    resp = api.submit_pull(pull["id"], WAREHOUSE)

    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_INVENTORY.value, 409)
    stored = validate_success(api.get_pull(pull["id"], WAREHOUSE))
    assert stored["state"] == "DRAFT"
    assert float(stored["fill_rate"]) == 0.0


def test_a_commit_below_the_fill_rate_floor_is_refused(api):
    """PRD §2.7: "Rung 54: the pull's `fill_rate` is greater than or equal to 0.70, the
    comparison being inclusive so that exactly 0.7000 commits; otherwise
    `ERR_FILL_RATE_BELOW_MINIMUM`, HTTP 409."
    PRD §3.4: "The pull lands in `SUBMITTED`, and immediately falls to `PARTIAL` when
    `filled_unit_count` is smaller than `requested_unit_count`."

    Design: Corner/errors/commit_below_the_fill_rate_floor_is_refused
    """
    ctx = setup_vacant_pull_partial_sixty_percent()

    resp = api.commit_pull(ctx["pull_id"], ctx["proj_v"], WAREHOUSE)

    validate_error(resp, ApiErrorId.ERR_FILL_RATE_BELOW_MINIMUM.value, 409)
    pull = validate_success(api.get_pull(ctx["pull_id"], WAREHOUSE))
    assert pull["requested_unit_count"] == 10
    assert pull["filled_unit_count"] == 6
    assert float(pull["fill_rate"]) == 0.6
    assert pull["state"] == "PARTIAL"


def test_the_third_resubmit_of_a_partial_pull_is_refused(api):
    """PRD §2.7: "Rung 55: the pull's `resubmit_count` is strictly less than 2 before a
    `PARTIAL` pull may be re-submitted; otherwise `ERR_PULL_RESUBMIT_LIMIT`, HTTP 409."
    PRD §3.4: "A `PARTIAL` pull may be re-submitted, which increments `resubmit_count` and
    re-runs the pass over the `UNFILLED` lines only, moving any line for which a candidate
    now exists `UNFILLED → ALLOCATED`; the retry is refused once `resubmit_count` has
    reached 2, with `ERR_PULL_RESUBMIT_LIMIT`."

    Design: Corner/errors/third_pull_resubmit_hits_the_resubmit_limit
    """
    ctx = setup_vacant_pull_partial_sixty_percent()
    validate_success(api.submit_pull(ctx["pull_id"], WAREHOUSE))
    validate_success(api.submit_pull(ctx["pull_id"], WAREHOUSE))

    resp = api.submit_pull(ctx["pull_id"], WAREHOUSE)

    validate_error(resp, ApiErrorId.ERR_PULL_RESUBMIT_LIMIT.value, 409)
    pull = validate_success(api.get_pull(ctx["pull_id"], WAREHOUSE))
    assert pull["resubmit_count"] == 2
    assert pull["state"] == "PARTIAL"
    assert float(pull["fill_rate"]) == 0.6


def test_a_pull_line_naming_an_unscoped_room_is_refused(api):
    """PRD §2.7: "Rung 52: a pull line's `room_label` matches the `room_label` of some scope
    item on the project's consultation; otherwise `ERR_SCOPE_ITEM_NOT_FOUND`, HTTP 404."
    PRD §3.4: "Lines are then added to a `DRAFT` or `PARTIAL` pull, each naming a `source`
    of `OWNED` or `VENDOR`, a `category`, a `room_label` that must match a scope item's
    `room_label` on the project's consultation, a `quantity`, and — for vendor lines — the
    `rental_order_id` the line will draw against."

    Design: Corner/validations/pull_line_room_label_outside_the_scope_rejected
    """
    ctx = setup_vacant_pull_draft()

    resp = api.add_pull_line(
        ctx["pull_id"], {"source": "OWNED", "category": "SOFA",
                         "room_label": "Sunroom", "quantity": 1}, WAREHOUSE)

    validate_error(resp, ApiErrorId.ERR_SCOPE_ITEM_NOT_FOUND.value, 404)
    pull = validate_success(api.get_pull(ctx["pull_id"], WAREHOUSE))
    assert pull["requested_unit_count"] == 4


def test_the_allocation_pass_takes_the_oldest_available_unit(api):
    """PRD §3.4: "For an owned line the candidate set is every inventory item whose `status`
    is `AVAILABLE` and whose `category` matches the line's; candidates are ranked by
    `acquired_at` ascending with creation timestamp ascending as the tie-break, and the
    first is taken."
    PRD §3.4: "That item's `inventory_item_id` is written onto the line, the item moves
    `AVAILABLE → RESERVED`, and the line moves `REQUESTED → ALLOCATED`."
    PRD §3.4: "Every allocated line's `monthly_rate` is derived at that moment: an owned
    line takes the allocated unit's own `monthly_rate` and ignores `quantity` entirely,
    while a vendor line takes 85.00 multiplied by the vendor's `rate_multiplier` multiplied
    by the line's `quantity`; either way the result is rounded half-up to two decimal
    places."

    Design: Corner/calculations/oldest_available_unit_wins_the_allocation_ranking
    """
    ctx = setup_vacant_project_draft()
    validate_success(api.authorize_project(
        ctx["proj_id"], make_seller_headers(ctx["seller_id"])))
    it_new = new_item({"sku": "SOFA-NEW", "category": "SOFA",
                       "acquired_at": "2025-09-01T00:00:00Z",
                       "replacement_value": 900.00, "monthly_rate": 180.00})
    it_old = new_item({"sku": "SOFA-OLD", "category": "SOFA",
                       "acquired_at": "2019-02-01T00:00:00Z",
                       "replacement_value": 1500.00, "monthly_rate": 300.00})
    it_mid = new_item({"sku": "SOFA-MID", "category": "SOFA",
                       "acquired_at": "2024-01-05T00:00:00Z",
                       "replacement_value": 1200.00, "monthly_rate": 240.00})
    pull = validate_success(api.open_pull(ctx["proj_id"], WAREHOUSE), 201)
    line = validate_success(api.add_pull_line(
        pull["id"], {"source": "OWNED", "category": "SOFA",
                     "room_label": "Living", "quantity": 1}, WAREHOUSE), 201)

    validate_success(api.submit_pull(pull["id"], WAREHOUSE))

    stored_line = validate_success(api.get_pull_line(line["id"], WAREHOUSE))
    assert stored_line["inventory_item_id"] == it_old["id"]
    assert_money(stored_line["monthly_rate"], 300.00, "pull line.monthly_rate")
    assert validate_success(
        api.get_inventory_item(it_old["id"], WAREHOUSE))["status"] == "RESERVED"
    assert validate_success(
        api.get_inventory_item(it_mid["id"], WAREHOUSE))["status"] == "AVAILABLE"
    assert validate_success(
        api.get_inventory_item(it_new["id"], WAREHOUSE))["status"] == "AVAILABLE"
    assert float(validate_success(api.get_pull(pull["id"], WAREHOUSE))["fill_rate"]) == 1.0


def test_a_pull_cancellation_returns_every_reserved_unit_to_stock(api):
    """PRD §2.11: "The compensating pair is a pull submission moving units from `AVAILABLE`
    to `RESERVED` against a pull cancellation moving them back from `RESERVED` to
    `AVAILABLE`."
    PRD §3.4: "A pull may instead be cancelled from `DRAFT`, `SUBMITTED` or `PARTIAL`, which
    returns every allocated line's item `RESERVED → AVAILABLE` and drops every line."

    Design: Difficulty/compensating_invariant/pull_submit_then_cancel_conserves_warehouse_on_hand
    """
    ctx = setup_vacant_three_owned_lines_submitted()

    validate_success(api.cancel_pull(ctx["pull_id"], WAREHOUSE))

    for key in ("item_a", "item_b", "item_c"):
        item = validate_success(api.get_inventory_item(ctx[key], WAREHOUSE))
        assert item["status"] == "AVAILABLE", f"{key} must return to stock"
    pull = validate_success(api.get_pull(ctx["pull_id"], WAREHOUSE))
    assert pull["state"] == "CANCELLED"


def test_the_warehouse_summary_balances_after_the_submit_cancel_round_trip(api):
    """PRD §2.11: "The total number of owned units on hand equals the number of items in
    `AVAILABLE` plus those in `RESERVED` plus those in `DEPLOYED` plus those in `IN_REPAIR`
    plus those in `WRITTEN_OFF`."
    PRD §2.11: "The identity is observable through the warehouse summary view, whose
    response reports `on_hand_total`, `available`, `reserved`, `deployed`, `in_repair` and
    `written_off`, optionally narrowed by `category`."

    Design: Difficulty/compensating_invariant/pull_submit_then_cancel_conserves_warehouse_on_hand
    """
    ctx = setup_vacant_three_owned_lines_submitted()
    validate_success(api.cancel_pull(ctx["pull_id"], WAREHOUSE))

    summary = validate_success(api.get_inventory_summary(WAREHOUSE))

    assert summary["on_hand_total"] == 3
    assert summary["available"] == 3
    assert summary["reserved"] == 0
    assert summary["deployed"] == 0
    assert summary["in_repair"] == 0
    assert summary["written_off"] == 0
    assert_warehouse_conservation(summary)


def test_a_fill_rate_of_exactly_seventy_percent_commits(api):
    """PRD §2.7: "Rung 54: the pull's `fill_rate` is greater than or equal to 0.70, the
    comparison being inclusive so that exactly 0.7000 commits; otherwise
    `ERR_FILL_RATE_BELOW_MINIMUM`, HTTP 409."
    PRD §3.4: "At the end of the pass the pull's `filled_unit_count` is recomputed as the
    sum of `quantity` over lines in `ALLOCATED`, `DEPLOYED` or `RETURNED`, and `fill_rate`
    is `filled_unit_count` divided by `requested_unit_count`, rounded half-up to **four**
    decimal places, or exactly 0.0000 when nothing was requested."

    Design: Difficulty/boundary_precision_check/fill_rate_exactly_seventy_percent_commits
    """
    ctx = setup_vacant_pull_exactly_seventy_percent()

    resp = api.commit_pull(ctx["pull_id"], ctx["proj_v"], WAREHOUSE)

    validate_success(resp)
    pull = validate_success(api.get_pull(ctx["pull_id"], WAREHOUSE))
    assert pull["requested_unit_count"] == 10
    assert pull["filled_unit_count"] == 7
    assert float(pull["fill_rate"]) == 0.7
    assert pull["state"] == "COMMITTED"


def test_the_commit_at_the_floor_drops_the_lines_that_never_filled(api):
    """PRD §3.4: "A commit stamps `committed_at` with the logical clock, drops every
    still-`UNFILLED` line to `DROPPED`, and bumps both the pull's and the project's
    `version`."
    PRD §3.4: "An empty candidate set leaves the line `UNFILLED` instead."

    Design: Difficulty/boundary_precision_check/fill_rate_exactly_seventy_percent_commits
    """
    ctx = setup_vacant_pull_exactly_seventy_percent()

    validate_success(api.commit_pull(ctx["pull_id"], ctx["proj_v"], WAREHOUSE))

    dropped = validate_success(api.get_pull_line(ctx["line_o1"], WAREHOUSE))
    assert dropped["state"] == "DROPPED"
    vendor_line = validate_success(api.get_pull_line(ctx["line_v"], WAREHOUSE))
    assert vendor_line["state"] == "ALLOCATED"


def test_the_warehouse_summary_keeps_a_retired_unit_in_the_total(api):
    """PRD §2.11: "The identity is observable through the warehouse summary view, whose
    response reports `on_hand_total`, `available`, `reserved`, `deployed`, `in_repair` and
    `written_off`, optionally narrowed by `category`."
    PRD §2.11: "A written-off unit remains counted in the total forever; it simply stops
    being available."

    Design: Corner/endpoints/inventory_summary_is_a_computed_read_over_the_five_buckets
    """
    ctx = setup_three_owned_items()
    validate_success(api.repair_in_item(ctx["item_c"], WAREHOUSE))
    validate_success(api.write_off_item(ctx["item_c"], "Beyond economical repair", WAREHOUSE))

    summary = validate_success(api.get_inventory_summary(WAREHOUSE))

    assert summary["on_hand_total"] == 3
    assert summary["available"] == 2
    assert summary["reserved"] == 0
    assert summary["deployed"] == 0
    assert summary["in_repair"] == 0
    assert summary["written_off"] == 1
    assert_warehouse_conservation(summary)


def test_the_inventory_listing_honours_limit_and_offset(api):
    """PRD §2.3: "`limit` defaults to 10 when it is not supplied, may not be smaller than 1,
    and may not be larger than 100."
    PRD §2.3: "`total_count` is the number of records matching the filters before
    pagination is applied, and `has_more` is true exactly when `offset` plus the number of
    returned records is smaller than `total_count`."

    Design: Corner/endpoints/inventory_list_honours_limit_and_offset
    """
    setup_three_owned_items()

    rows, meta = validate_paginated(api.list_inventory_items(
        WAREHOUSE, params={"limit": 2, "offset": 2}))

    assert meta["total_count"] == 3
    assert meta["has_more"] is False
    assert len(rows) == 1
    unfiltered, unfiltered_meta = validate_paginated(api.list_inventory_items(WAREHOUSE))
    assert unfiltered_meta["total_count"] == 3, "only this test's three units may exist"
    assert len(unfiltered) == 3


def test_a_unit_created_in_one_call_is_listed_by_the_next(api):
    """PRD §2.3: "The `meta` block of every list response carries `limit`, `offset`,
    `total_count` and `has_more`; `total_count` is the number of records matching the
    filters before pagination is applied, and `has_more` is true exactly when `offset` plus
    the number of returned records is smaller than `total_count`."
    PRD §3.4: "Every item is created with `condition_grade` `A`, `status` `AVAILABLE` and
    `times_deployed` 0."

    Design: Corner/consistency_model/list_endpoint_reflects_a_creation_made_in_the_previous_call
    """
    setup_clock_only()
    item = validate_success(api.create_inventory_item(
        {"sku": "RUG-1", "category": "RUG", "acquired_at": "2025-01-01T00:00:00Z",
         "replacement_value": 400.00, "monthly_rate": 60.00}, WAREHOUSE), 201)

    rows, meta = validate_paginated(api.list_inventory_items(
        WAREHOUSE, params={"category": "RUG"}))

    assert api.list_inventory_items(WAREHOUSE).json()["response_type"] == "array"
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert rows[0]["id"] == item["id"]
    assert rows[0]["status"] == "AVAILABLE"


def test_a_vendor_line_is_reachable_through_the_rental_order_filter(api):
    """PRD §3.4: "Each line is created in state `REQUESTED` with `monthly_rate` 0, a null
    `inventory_item_id` and a null `rental_order_id` on owned lines."
    PRD §3.4: "Every allocated line's `monthly_rate` is derived at that moment: an owned
    line takes the allocated unit's own `monthly_rate` and ignores `quantity` entirely,
    while a vendor line takes 85.00 multiplied by the vendor's `rate_multiplier` multiplied
    by the line's `quantity`; either way the result is rounded half-up to two decimal
    places."

    Design: Corner/endpoints/pull_lines_are_discoverable_through_the_rental_order_filter
    """
    ctx = setup_vacant_project_staged()

    rows, meta = validate_paginated(api.list_pull_lines(
        WAREHOUSE, params={"rental_order_id": ctx["ro_id"]}))

    assert meta["total_count"] == 1
    assert rows[0]["id"] == ctx["line_v"]
    assert rows[0]["source"] == "VENDOR"
    assert rows[0]["inventory_item_id"] is None
    assert_money(rows[0]["monthly_rate"], 1147.50, "pull line.monthly_rate")
