"""Derived reads, list filters, pagination and the detection sweep.

Every test builds its own preconditions through the PRD's own endpoints, because
the server is restarted and the database wiped before every test.
"""
import pytest

from test_helpers import (
    ADMIN,
    ALLOCATOR,
    DEFAULT_CLOCK_UTC,
    MANAGER,
    STORE_SPECS_FOUR,
    api_client,
    assert_assortment_action,
    create_receipt,
    line_for_store,
    make_store_operator_headers,
    set_clock,
    setup_network,
    units_by_size,
    validate_paginated,
    validate_success,
)

# --------------------------------------------------------------------------- #
# Network descriptions for the sweep dataset
# --------------------------------------------------------------------------- #

# 0101 and 0102 both get capacity 48 / pmin 12, so 0102 has real headroom.
SWEEP_FIXTURE_SPECS = {
    "0101": {
        "fixture_count": 4,
        "facings_per_fixture": 3,
        "units_per_facing": 4,
        "presentation_min_units": 12,
    },
    "0102": {
        "fixture_count": 4,
        "facings_per_fixture": 3,
        "units_per_facing": 4,
        "presentation_min_units": 12,
    },
    "0103": {
        "fixture_count": 1,
        "facings_per_fixture": 4,
        "units_per_facing": 5,
        "presentation_min_units": 8,
    },
    "0104": {
        "fixture_count": 1,
        "facings_per_fixture": 4,
        "units_per_facing": 5,
        "presentation_min_units": 6,
    },
}

SWEEP_POSITION_SPECS = {
    # 4 units, S and XL out -> BROKEN
    "0101": {
        "on_hand_units": 4,
        "size_on_hand": [
            {"size_code": "M", "units": 3},
            {"size_code": "L", "units": 1},
        ],
        "min_units": 12,
        "max_units": 48,
        "weekly_forecast_units": 9,
        "trailing_4wk_sales_units": 30,
    },
    # 20 units of all four sizes -> COMPLETE, headroom 48 - 20 = 28
    "0102": {
        "on_hand_units": 20,
        "size_on_hand": [
            {"size_code": "S", "units": 5},
            {"size_code": "M", "units": 7},
            {"size_code": "L", "units": 6},
            {"size_code": "XL", "units": 2},
        ],
        "min_units": 8,
        "max_units": 48,
        "weekly_forecast_units": 5,
        "trailing_4wk_sales_units": 16,
    },
    # 2 units, S, L and XL out -> BROKEN
    "0103": {
        "on_hand_units": 2,
        "size_on_hand": [{"size_code": "M", "units": 2}],
        "min_units": 8,
        "max_units": 20,
        "weekly_forecast_units": 3,
        "trailing_4wk_sales_units": 6,
    },
    # 3 units, XL out -> SIZE_OUT_RISK
    "0104": {
        "on_hand_units": 3,
        "size_on_hand": [
            {"size_code": "S", "units": 1},
            {"size_code": "M", "units": 1},
            {"size_code": "L", "units": 1},
        ],
        "min_units": 6,
        "max_units": 20,
        "weekly_forecast_units": 2,
        "trailing_4wk_sales_units": 5,
    },
}


def _sweep_network():
    """Four stores where 0101 and 0103 are degraded, 0102 is the only healthy
    consolidation target, 0103 is REMODEL and 0104 is CLOSING."""
    scenario = setup_network(
        store_specs=STORE_SPECS_FOUR,
        fixture_specs=SWEEP_FIXTURE_SPECS,
        position_specs=SWEEP_POSITION_SPECS,
    )
    validate_success(
        api_client.set_store_status(
            scenario["stores"]["0103"]["id"], {"target_status": "REMODEL"}, ADMIN
        )
    )
    validate_success(
        api_client.set_store_status(
            scenario["stores"]["0104"]["id"], {"target_status": "CLOSING"}, ADMIN
        )
    )
    return scenario


def _actions_for_store(store_id, status=None):
    params = {"store_id": store_id, "limit": 100}
    if status is not None:
        params["status"] = status
    data, meta = validate_paginated(
        api_client.list_assortment_actions(MANAGER, params=params)
    )
    return data, meta


def test_the_sweep_raises_one_action_per_degraded_position_in_store_code_order():
    """
    "The sweep scans every store position of the program looking for degraded assortment health and raises exactly one `PENDING` **assortment action** per newly degraded position."
    "Positions in stores whose `status` is neither `ACTIVE` nor `REMODEL` are skipped."
    "The actions the sweep returns are ordered by the store's `store_code` ascending and then by the SKU's `sku_code` ascending"
    "their headroom — the greater of zero and their in-effect shelf plan's `capacity_units` less their `available_units` less their `in_transit_units` — is greater than or equal to the degraded position's `available_units`, so the target can physically absorb the whole move"
    "When at least one candidate survives, the action's `action_type` is `CONSOLIDATION` and its `consolidation_target_store_id` is the first candidate's store."
    "It snapshots two figures from the position at detection time and then never changes them: `broken_size_count`, copied from the position's own count, and `units_at_detection`, copied from the position's `available_units`, which later becomes the unit count of the consolidation transfer if one is created."
    "A `CONSOLIDATION` action leaves `markdown_pct_bp` null."

    Design: Corner/endpoints/detection_sweep_is_idempotent_per_position_and_re_arms_after_a_cancel
    """
    set_clock(DEFAULT_CLOCK_UTC)
    scenario = _sweep_network()
    stores = scenario["stores"]
    target_id = stores["0102"]["id"]

    raised = validate_success(
        api_client.run_assortment_detection(
            {"program_id": scenario["program"]["id"]}, MANAGER
        )
    )
    assert len(raised) == 2, "only 0101 and 0103 are both degraded and scannable"
    assert raised[0]["store_id"] == stores["0101"]["id"]
    assert raised[1]["store_id"] == stores["0103"]["id"]

    for action, units, broken in ((raised[0], 4, 2), (raised[1], 2, 3)):
        assert_assortment_action(action)
        assert action["status"] == "PENDING"
        assert action["trigger_reason"] == "BROKEN_ASSORTMENT"
        assert action["action_type"] == "CONSOLIDATION"
        assert action["consolidation_target_store_id"] == target_id
        assert action["units_at_detection"] == units
        assert action["broken_size_count"] == broken
        assert action["markdown_pct_bp"] is None
        assert action["detected_at"].startswith("2026-08-01T00:00:00")

    # The CLOSING store is not scanned at all, even though a core size is out.
    _, closing_meta = _actions_for_store(stores["0104"]["id"])
    assert closing_meta["total_count"] == 0
    # The healthy target is never itself an action subject.
    _, target_meta = _actions_for_store(target_id)
    assert target_meta["total_count"] == 0

    # Detection recommends; it does not move units.
    _, transfer_meta = validate_paginated(
        api_client.list_transfer_recommendations(
            MANAGER, params={"program_id": scenario["program"]["id"]}
        )
    )
    assert transfer_meta["total_count"] == 0

    item = validate_success(api_client.get_item(scenario["item"]["id"], ADMIN))
    assert item["lifecycle_state"] == "BROKEN"
    assert item["broken_store_count"] == 2
    assert item["size_out_store_count"] == 1


def test_a_second_sweep_over_an_unchanged_dataset_creates_nothing():
    """
    "Either an `Allocator` or an `AllocationManager` may run a detection sweep over one program, supplying the `program_id`; the program must be `ACTIVE`, or the sweep is refused with `ERR_PROGRAM_LOCKED`."
    "A position that already has a `PENDING` assortment action for the same SKU-and-store pair is skipped, so re-running the sweep never duplicates work."
    "`version` is an integer that begins at 1 when the resource is created and increases by exactly 1 on each mutation."

    Design: Corner/endpoints/detection_sweep_is_idempotent_per_position_and_re_arms_after_a_cancel
    """
    set_clock(DEFAULT_CLOCK_UTC)
    scenario = _sweep_network()
    program_id = scenario["program"]["id"]
    item_id = scenario["item"]["id"]

    first = validate_success(
        api_client.run_assortment_detection({"program_id": program_id}, MANAGER)
    )
    assert len(first) == 2
    before = {action["id"]: action["version"] for action in first}

    # The other authorised role sees exactly the same emptiness.
    second = validate_success(
        api_client.run_assortment_detection({"program_id": program_id}, ALLOCATOR)
    )
    assert second == []

    data, meta = validate_paginated(
        api_client.list_assortment_actions(
            MANAGER, params={"item_id": item_id, "limit": 100}
        )
    )
    assert meta["total_count"] == 2
    for action in data:
        assert action["status"] == "PENDING"
        assert action["version"] == before[action["id"]]


def test_cancelling_an_action_re_arms_only_that_pair_on_the_next_sweep():
    """
    "A position that already has a `PENDING` assortment action for the same SKU-and-store pair is skipped, so re-running the sweep never duplicates work."
    "An `AllocationManager` may instead waive the remedy, taking the action `PENDING → CANCELLED`, which is terminal and advances `version` by one."
    "Actions are discovered through their filtered list view, which filters on `item_id`, `store_id`, `consolidation_target_store_id`, `action_type` and `status`, and that list is the only channel through which sweep-raised actions can be found."

    Design: Corner/endpoints/detection_sweep_is_idempotent_per_position_and_re_arms_after_a_cancel
    """
    set_clock(DEFAULT_CLOCK_UTC)
    scenario = _sweep_network()
    program_id = scenario["program"]["id"]
    item_id = scenario["item"]["id"]
    stores = scenario["stores"]

    first = validate_success(
        api_client.run_assortment_detection({"program_id": program_id}, MANAGER)
    )
    action_0101, action_0103 = first

    cancelled = validate_success(
        api_client.cancel_assortment_action(action_0101["id"], MANAGER)
    )
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["version"] == action_0101["version"] + 1

    rearmed = validate_success(
        api_client.run_assortment_detection({"program_id": program_id}, MANAGER)
    )
    assert len(rearmed) == 1, "only the pair whose action was waived is re-armed"
    fresh = rearmed[0]
    assert fresh["store_id"] == stores["0101"]["id"]
    assert fresh["id"] != action_0101["id"]
    assert fresh["status"] == "PENDING"
    assert fresh["action_type"] == "CONSOLIDATION"
    assert fresh["consolidation_target_store_id"] == stores["0102"]["id"]
    assert fresh["units_at_detection"] == 4
    assert fresh["broken_size_count"] == 2

    # The skip is keyed on a PENDING action, not on history.
    _, all_meta = validate_paginated(
        api_client.list_assortment_actions(
            MANAGER, params={"item_id": item_id, "limit": 100}
        )
    )
    assert all_meta["total_count"] == 3
    pending, pending_meta = validate_paginated(
        api_client.list_assortment_actions(
            MANAGER, params={"item_id": item_id, "status": "PENDING", "limit": 100}
        )
    )
    assert pending_meta["total_count"] == 2
    assert {action["store_id"] for action in pending} == {
        stores["0101"]["id"],
        stores["0103"]["id"],
    }

    untouched = validate_success(
        api_client.get_assortment_action(action_0103["id"], MANAGER)
    )
    assert untouched["status"] == "PENDING"
    assert untouched["version"] == action_0103["version"]


# --------------------------------------------------------------------------- #
# Derived reads
# --------------------------------------------------------------------------- #

READ_FIXTURE_SPECS = {
    "0101": {
        "fixture_count": 4,
        "facings_per_fixture": 3,
        "units_per_facing": 4,
        "presentation_min_units": 12,
    },
    "0102": {
        "fixture_count": 2,
        "facings_per_fixture": 3,
        "units_per_facing": 4,
        "presentation_min_units": 8,
    },
}

READ_POSITION_SPECS = {
    "0101": {
        "on_hand_units": 6,
        "size_on_hand": [
            {"size_code": "M", "units": 4},
            {"size_code": "L", "units": 2},
        ],
        "on_order_units": 4,
        "min_units": 12,
        "max_units": 48,
        "weekly_forecast_units": 9,
        "trailing_4wk_sales_units": 30,
    },
    "0102": {
        "on_hand_units": 2,
        "size_on_hand": [
            {"size_code": "M", "units": 1},
            {"size_code": "L", "units": 1},
        ],
        "min_units": 8,
        "max_units": 24,
        "weekly_forecast_units": 3,
        "trailing_4wk_sales_units": 6,
    },
}


def _shipped_read_scenario():
    """Two stores whose needs of 26 and 10 exactly consume a 36-unit receipt; the
    run is committed and only the 0101 line has been released from the DC."""
    scenario = setup_network(
        store_specs=STORE_SPECS_FOUR[:2],
        fixture_specs=READ_FIXTURE_SPECS,
        position_specs=READ_POSITION_SPECS,
    )
    scenario["receipt"] = create_receipt(
        scenario["program"]["id"],
        scenario["item"]["id"],
        reference="ASN-E201",
        units_received=36,
        size_received=[
            {"size_code": "S", "units": 7},
            {"size_code": "M", "units": 14},
            {"size_code": "L", "units": 11},
            {"size_code": "XL", "units": 4},
        ],
    )
    run = validate_success(
        api_client.create_allocation_run(
            scenario["receipt"]["id"],
            {
                "method": "DEMAND_DRIVEN",
                "need_basis": "FORWARD_LOOKING",
                "expected_receipt_version": scenario["receipt"]["version"],
            },
            ALLOCATOR,
        ),
        201,
    )
    validate_success(api_client.propose_run(run["id"], ALLOCATOR))
    scenario["line_0101"] = line_for_store(run["id"], scenario["stores"]["0101"]["id"])
    scenario["line_0102"] = line_for_store(run["id"], scenario["stores"]["0102"]["id"])
    scenario["run"] = validate_success(api_client.commit_run(run["id"], MANAGER))
    validate_success(api_client.ship_line(scenario["line_0101"]["id"], MANAGER))
    return scenario


def test_a_shipped_position_reads_the_same_derived_numbers_from_every_channel():
    """
    "`available_units` is `on_hand_units` minus `reserved_out_units`"
    "otherwise, when `available_units` is greater than 0 and strictly less than `min_units` it is `LOW`"
    "otherwise `broken_size_count` is 2 or more and the position is `BROKEN`"
    "The release adds the line's `units_allocated` to the destination position's `in_transit_units` and re-derives that position's `stock_status`; the line's `version` advances by one."
    "A single position may be read by any of the three planning roles, and by the owning `StoreOperator` for its own store only. The list view filters on `store_id`, `item_id`, `stock_status` and `assortment_status` — either dimension independently"

    Design: Corner/endpoints/reads_expose_the_same_derived_values_singly_listed_and_paginated
    """
    set_clock(DEFAULT_CLOCK_UTC)
    scenario = _shipped_read_scenario()
    position_id = scenario["positions"]["0101"]["id"]
    store_id = scenario["stores"]["0101"]["id"]

    def check(row):
        assert row["on_hand_units"] == 6
        assert row["in_transit_units"] == 26
        assert row["reserved_out_units"] == 0
        assert row["on_order_units"] == 4
        # The 26 in-transit units are on a truck, not on the shelf.
        assert row["available_units"] == 6
        assert row["stock_status"] == "LOW"
        assert row["broken_size_count"] == 2
        assert row["assortment_status"] == "BROKEN"

    single = validate_success(
        api_client.get_store_position(position_id, ALLOCATOR)
    )
    check(single)

    scoped = validate_success(
        api_client.get_store_position(
            position_id, make_store_operator_headers(store_id)
        )
    )
    check(scoped)

    listed, listed_meta = validate_paginated(
        api_client.list_store_positions(ALLOCATOR, params={"store_id": store_id})
    )
    assert listed_meta["total_count"] == 1
    check(listed[0])

    # The filter reads the computed band, and shipping did not lift 0101 out of LOW.
    low, low_meta = validate_paginated(
        api_client.list_store_positions(ALLOCATOR, params={"stock_status": "LOW"})
    )
    assert low_meta["total_count"] == 2
    assert {row["id"] for row in low} == {
        position_id,
        scenario["positions"]["0102"]["id"],
    }

    # No read mutated anything.
    final = validate_success(api_client.get_store_position(position_id, ALLOCATOR))
    assert final["version"] == single["version"]


def test_line_run_receipt_program_and_item_reads_agree_across_pages_and_filters():
    """
    "Each line also carries a `size_breakdown`, an array of `size_code` and `units` entries produced by splitting the line's `units_proposed` along the SKU's size curve."
    "a `presentation_gap_units` figure computed as the greater of zero and the store's in-effect `presentation_min_units` less the sum of the position's `available_units`, its `in_transit_units` and the line's `units_proposed`"
    "That gap is **recorded at proposal time but not enforced there**"
    "`limit` controls page size: it defaults to 10 when omitted, its minimum accepted value is 1 and its maximum accepted value is 100."
    "`total_count` giving the number of records matching the filters before pagination is applied, and `has_more`, which is true exactly when `offset` plus the number of records in `data` is less than `total_count`"
    "a `SEASONAL` SKU to `DEMAND_DRIVEN`"

    Design: Corner/endpoints/reads_expose_the_same_derived_values_singly_listed_and_paginated
    """
    set_clock(DEFAULT_CLOCK_UTC)
    scenario = _shipped_read_scenario()
    run_id = scenario["run"]["id"]

    line_one = validate_success(
        api_client.get_allocation_line(scenario["line_0101"]["id"], ALLOCATOR)
    )
    assert line_one["need_units"] == 26
    assert line_one["units_proposed"] == 26
    assert line_one["units_allocated"] == 26
    assert line_one["capacity_capped_units"] == 0
    assert line_one["fulfillment_status"] == "SHIPPED"
    assert units_by_size(line_one["size_breakdown"]) == {
        "S": 5,
        "M": 10,
        "L": 8,
        "XL": 3,
    }
    # Frozen at propose time from 6 + 0 + 26 against a presentation minimum of 12.
    assert line_one["presentation_gap_units"] == 0

    line_two = validate_success(
        api_client.get_allocation_line(scenario["line_0102"]["id"], ALLOCATOR)
    )
    assert line_two["need_units"] == 10
    assert line_two["units_allocated"] == 10
    assert line_two["fulfillment_status"] == "PENDING"
    assert line_two["presentation_gap_units"] == 0
    assert units_by_size(line_two["size_breakdown"]) == {
        "S": 2,
        "M": 4,
        "L": 3,
        "XL": 1,
    }

    first_page, first_meta = validate_paginated(
        api_client.list_allocation_lines(
            ALLOCATOR, params={"run_id": run_id, "limit": 1, "offset": 0}
        )
    )
    assert len(first_page) == 1
    assert first_meta["total_count"] == 2
    assert first_meta["has_more"] is True
    second_page, second_meta = validate_paginated(
        api_client.list_allocation_lines(
            ALLOCATOR, params={"run_id": run_id, "limit": 1, "offset": 1}
        )
    )
    assert len(second_page) == 1
    assert second_meta["total_count"] == 2
    assert second_meta["has_more"] is False
    assert first_page[0]["id"] != second_page[0]["id"]

    shipped, shipped_meta = validate_paginated(
        api_client.list_allocation_lines(
            ALLOCATOR, params={"fulfillment_status": "SHIPPED"}
        )
    )
    assert shipped_meta["total_count"] == 1
    assert shipped[0]["id"] == scenario["line_0101"]["id"]

    run = validate_success(api_client.get_allocation_run(run_id, ALLOCATOR))
    assert run["status"] == "COMMITTED"
    assert run["units_proposed"] == 36
    assert run["units_committed"] == 36
    assert run["eligible_store_count"] == 2
    assert run["unallocated_remainder_units"] == 0

    receipt = validate_success(
        api_client.get_receipt(scenario["receipt"]["id"], ALLOCATOR)
    )
    assert receipt["status"] == "ALLOCATED"
    assert receipt["units_committed"] == 36
    assert receipt["units_unallocated"] == 0

    program = validate_success(
        api_client.get_program(scenario["program"]["id"], ADMIN)
    )
    assert program["total_units_received"] == 36
    assert program["total_units_committed"] == 36
    assert program["open_reserve_units"] == 0

    item = validate_success(api_client.get_item(scenario["item"]["id"], ADMIN))
    assert item["replenishment_model"] == "DEMAND_DRIVEN"
    assert item["lifecycle_state"] == "BROKEN"


# --------------------------------------------------------------------------- #
# Patches
# --------------------------------------------------------------------------- #

PATCH_FIXTURE_SPECS = {
    "0101": {
        "fixture_count": 4,
        "facings_per_fixture": 3,
        "units_per_facing": 4,
        "presentation_min_units": 12,
    },
}

PATCH_POSITION_SPECS = {
    "0101": {
        "on_hand_units": 6,
        "size_on_hand": [
            {"size_code": "M", "units": 4},
            {"size_code": "L", "units": 2},
        ],
        "on_order_units": 0,
        "min_units": 12,
        "max_units": 48,
        "weekly_forecast_units": 9,
        "trailing_4wk_sales_units": 30,
    },
}


def _patch_scenario():
    """One store holding 6 units of two sizes: LOW on the stock dimension and
    BROKEN on the assortment dimension at the same time."""
    return setup_network(
        store_specs=STORE_SPECS_FOUR[:1],
        fixture_specs=PATCH_FIXTURE_SPECS,
        position_specs=PATCH_POSITION_SPECS,
    )


def test_patching_planning_inputs_walks_stock_status_and_never_touches_assortment():
    """
    "A `PlanningAdmin` or `Allocator` may later patch `min_units`, `max_units`, `weekly_forecast_units`, `trailing_4wk_sales_units` or `on_order_units`; such a patch re-derives the position's stock dimension, leaves its assortment dimension entirely alone because the two are independent, and advances `version` by one."
    "otherwise, when `available_units` is greater than or equal to `min_units` and less than or equal to `max_units` it is `IN_STOCK`; otherwise, `available_units` exceeds `max_units` and the position is `OVERSTOCK`"
    "`on_order_units` records units sitting on an open purchase order that have not yet reached the DC; it defaults to 0 when omitted, and it is visible to exactly one of the two need bases"
    "Because the dimensions are orthogonal, a position may perfectly legitimately be `OVERSTOCK` and `BROKEN` at the same time — drowning in the wrong sizes."
    "The list view filters on `store_id`, `item_id`, `stock_status` and `assortment_status` — either dimension independently"

    Design: Corner/endpoints/patch_re_derives_the_stock_dimension_and_leaves_the_assortment_dimension_alone
    """
    set_clock(DEFAULT_CLOCK_UTC)
    scenario = _patch_scenario()
    position_id = scenario["positions"]["0101"]["id"]

    baseline = validate_success(api_client.get_store_position(position_id, ALLOCATOR))
    assert baseline["available_units"] == 6
    assert baseline["stock_status"] == "LOW"
    assert baseline["broken_size_count"] == 2
    assert baseline["assortment_status"] == "BROKEN"
    assert baseline["version"] == 1

    # 5 <= 6 <= 48
    lowered_floor = validate_success(
        api_client.patch_store_position(position_id, {"min_units": 5}, ADMIN)
    )
    assert lowered_floor["stock_status"] == "IN_STOCK"
    assert lowered_floor["version"] == 2
    assert lowered_floor["assortment_status"] == "BROKEN"
    assert lowered_floor["broken_size_count"] == 2

    # 6 > 5: the same derived field moved twice, driven by two different inputs.
    lowered_ceiling = validate_success(
        api_client.patch_store_position(position_id, {"max_units": 5}, ALLOCATOR)
    )
    assert lowered_ceiling["stock_status"] == "OVERSTOCK"
    assert lowered_ceiling["version"] == 3
    assert lowered_ceiling["assortment_status"] == "BROKEN"
    assert lowered_ceiling["broken_size_count"] == 2

    # On-order units never enter available_units, so no band moves.
    on_order = validate_success(
        api_client.patch_store_position(position_id, {"on_order_units": 10}, ALLOCATOR)
    )
    assert on_order["on_order_units"] == 10
    assert on_order["available_units"] == 6
    assert on_order["stock_status"] == "OVERSTOCK"
    assert on_order["version"] == 4
    assert on_order["assortment_status"] == "BROKEN"

    # Demand inputs are read at proposal time, so nothing derived moves here either.
    demand = validate_success(
        api_client.patch_store_position(
            position_id,
            {"weekly_forecast_units": 12, "trailing_4wk_sales_units": 40},
            ALLOCATOR,
        )
    )
    assert demand["weekly_forecast_units"] == 12
    assert demand["trailing_4wk_sales_units"] == 40
    assert demand["version"] == 5
    assert demand["available_units"] == 6
    assert demand["stock_status"] == "OVERSTOCK"
    assert demand["assortment_status"] == "BROKEN"
    assert demand["broken_size_count"] == 2
    assert demand["on_hand_units"] == 6
    assert units_by_size(demand["size_on_hand"]) == {"M": 4, "L": 2}

    overstock, overstock_meta = validate_paginated(
        api_client.list_store_positions(
            ALLOCATOR, params={"stock_status": "OVERSTOCK"}
        )
    )
    assert overstock_meta["total_count"] == 1
    assert overstock[0]["id"] == position_id
    broken, broken_meta = validate_paginated(
        api_client.list_store_positions(
            ALLOCATOR, params={"assortment_status": "BROKEN"}
        )
    )
    assert broken_meta["total_count"] == 1
    assert broken[0]["id"] == position_id


def test_re_ticketing_a_sku_changes_no_computed_model():
    """
    "A `PlanningAdmin` may patch a SKU to change `replenishment_model_override`, to re-ticket `retail_price_usd`, or both; the patch re-runs resolution and advances the SKU's `version` by one."
    "When `replenishment_model_override` is null — its default — the resolved `replenishment_model` follows the type: a `BASIC` SKU resolves to `MIN_MAX`, a `SEASONAL` SKU to `DEMAND_DRIVEN`, and a `FASHION` SKU to `PUSH`."
    "if `broken_store_count` is at least 1 the SKU becomes `BROKEN`"

    Design: Corner/endpoints/patch_re_derives_the_stock_dimension_and_leaves_the_assortment_dimension_alone
    """
    set_clock(DEFAULT_CLOCK_UTC)
    scenario = _patch_scenario()
    item_id = scenario["item"]["id"]

    before = validate_success(api_client.get_item(item_id, ADMIN))
    assert before["replenishment_model"] == "DEMAND_DRIVEN"
    assert before["replenishment_model_override"] is None
    assert before["lifecycle_state"] == "BROKEN"
    assert before["broken_store_count"] == 1

    patched = validate_success(
        api_client.patch_item(item_id, {"retail_price_usd": 42.00}, ADMIN)
    )
    assert patched["retail_price_usd"] == pytest.approx(42.00, abs=0.01)
    assert patched["version"] == before["version"] + 1
    assert patched["replenishment_model"] == "DEMAND_DRIVEN"
    assert patched["replenishment_model_override"] is None
    assert patched["lifecycle_state"] == "BROKEN"
    assert patched["broken_store_count"] == 1
