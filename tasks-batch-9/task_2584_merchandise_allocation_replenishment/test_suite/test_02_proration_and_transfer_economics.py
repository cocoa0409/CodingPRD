"""Composed formulas: the four-step proration waterfall and transfer economics."""
import pytest

from test_helpers import (
    FIXTURE_SPECS_FOUR,
    assert_cost_precision,
    create_active_promo_event,
    current_position_version,
    line_for_store,
    setup_network_with_staged_receipt,
    setup_rebalance_network,
    setup_receipt_network,
    units_by_size,
    validate_success,
)


def _network_with_two_active_events_and_a_tiny_fourth_store():
    """Four graded stores where 0104's shelf plan holds only 6 units, plus two
    ACTIVE events over the 2026-08-01 clock: a STORE-scope 11000 lift on 0101 and
    a wider CLUSTER-scope 12500 lift on URBAN. A 60-unit receipt is STAGED."""
    fixture_specs = {code: dict(spec) for code, spec in FIXTURE_SPECS_FOUR.items()}
    fixture_specs["0104"] = {
        "fixture_count": 1,
        "facings_per_fixture": 2,
        "units_per_facing": 3,
        "presentation_min_units": 4,
    }
    network = setup_receipt_network(fixture_specs=fixture_specs)
    program_id = network["program"]["id"]
    create_active_promo_event(
        program_id,
        event_code="BTS-STORE-0101",
        scope="STORE",
        store_id=network["stores"]["0101"]["id"],
        item_class="APPAREL_TOP",
        start_date="2026-07-25T00:00:00Z",
        end_date="2026-08-15T00:00:00Z",
        lift_factor_bp=11000,
    )
    create_active_promo_event(
        program_id,
        event_code="BTS-URBAN",
        scope="CLUSTER",
        cluster_code="URBAN",
        item_class="APPAREL_TOP",
        start_date="2026-07-25T00:00:00Z",
        end_date="2026-08-15T00:00:00Z",
        lift_factor_bp=12500,
    )
    return setup_network_with_staged_receipt(
        units_received=60, network=network
    )


def _propose(api, scenario, headers):
    receipt = scenario["receipt"]
    run = validate_success(
        api.create_allocation_run(
            receipt["id"],
            {
                "method": "DEMAND_DRIVEN",
                "need_basis": "FORWARD_LOOKING",
                "expected_receipt_version": receipt["version"],
            },
            headers,
        ),
        201,
    )
    return run, validate_success(api.propose_run(run["id"], headers))


def test_need_ceiling_clips_the_proportional_floor_share_before_capacity_is_considered(
    api, allocator_headers
):
    """PRD §3.6: "**Step one** gives each store a proportional floor share: the pool
    multiplied by that store's need, divided by the total need across the set,
    truncated down to a whole number of units." "**Step two** applies the need
    ceiling, taking the lesser of the floor share and the store's own need."
    PRD §3.5: "Specificity outranks magnitude, and that is the intended behaviour:
    a store-scoped event at 11000 basis points beats a cluster-scoped event at
    20000 basis points for the stores it covers."

    Store 0101 takes the narrower 11000 lift for a need of 30, and although its
    floor share of a 60-unit pool against a network need of 52 is 34, the need
    ceiling hands it exactly 30.

    Design: Difficulty/combinatorial_formula/proration_nested_min_max_with_lift_and_capacity_cap
    """
    scenario = _network_with_two_active_events_and_a_tiny_fourth_store()
    stores = scenario["stores"]

    run, proposed = _propose(api, scenario, allocator_headers)

    first = line_for_store(run["id"], stores["0101"]["id"])
    assert first["need_units"] == 30
    assert first["units_proposed"] == 30
    assert first["capacity_capped_units"] == 0

    second = line_for_store(run["id"], stores["0102"]["id"])
    assert second["need_units"] == 4
    assert second["units_proposed"] == 4

    third = line_for_store(run["id"], stores["0103"]["id"])
    assert third["need_units"] == 10
    assert third["units_proposed"] == 10

    assert proposed["units_proposed"] == 50
    assert proposed["eligible_store_count"] == 4


def test_capacity_ceiling_clips_the_need_and_records_the_units_it_took_away(
    api, allocator_headers
):
    """PRD §3.6: "**Step three** applies the fixture capacity ceiling: the store's
    headroom is the greater of zero and the in-effect shelf plan's `capacity_units`
    less the position's `available_units` less its `in_transit_units`, and the
    store's allocation becomes the lesser of its step-two figure and that
    headroom." "The units lost specifically to capacity at this step — the step-two
    figure minus the step-three figure — are recorded on the line as
    `capacity_capped_units`, so an allocator can see why a store was
    short-changed."

    Store 0104 needs 8 units but its shelf plan holds only 6, so it is allocated 6
    and the line reports the 2 units capacity took.

    Design: Difficulty/combinatorial_formula/proration_nested_min_max_with_lift_and_capacity_cap
    """
    scenario = _network_with_two_active_events_and_a_tiny_fourth_store()

    run, _ = _propose(api, scenario, allocator_headers)

    line = line_for_store(run["id"], scenario["stores"]["0104"]["id"])
    assert line["need_units"] == 8
    assert line["units_proposed"] == 6
    assert line["capacity_capped_units"] == 2
    assert units_by_size(line["size_breakdown"]) == {"S": 1, "M": 3, "L": 2, "XL": 0}
    assert line["presentation_gap_units"] == 0


def test_remainder_loop_strands_units_when_every_store_already_sits_at_its_ceiling(
    api, allocator_headers
):
    """PRD §3.6: "While units remain, the eligible set is every store whose current
    allocation is still strictly below the lesser of its need and its headroom; if
    that set is empty the loop stops immediately and the leftover units stay
    unplaced." "Whatever is still unplaced when the loop finishes becomes the run's
    `unallocated_remainder_units` — units the proration could not place because
    every eligible store had hit either its need or its capacity ceiling."

    All four stores end step three at the lesser of their need and their headroom,
    so the 10 units left of the 60-unit pool are stranded rather than pushed onto
    store 0101, whose 42 units of headroom could physically have absorbed them.

    Design: Difficulty/combinatorial_formula/proration_nested_min_max_with_lift_and_capacity_cap
    """
    scenario = _network_with_two_active_events_and_a_tiny_fourth_store()

    run, proposed = _propose(api, scenario, allocator_headers)

    assert proposed["unallocated_remainder_units"] == 10
    assert proposed["units_proposed"] == 50
    first = line_for_store(run["id"], scenario["stores"]["0101"]["id"])
    assert first["units_proposed"] == 30
    assert units_by_size(first["size_breakdown"]) == {"S": 6, "M": 11, "L": 9, "XL": 4}
    assert first["presentation_gap_units"] == 0


def _propose_six_unit_rebalance(api, headers):
    """0102 is OVERSTOCK at 30 units, 0101 is LOW at 4 with no S and no XL on hand,
    so a six-unit rebalance from 0102 to 0101 has two candidate size lines."""
    scenario = setup_rebalance_network()
    donor = scenario["positions"]["0102"]
    transfer = validate_success(
        api.create_transfer_recommendation(
            {
                "program_id": scenario["program"]["id"],
                "from_store_id": scenario["stores"]["0102"]["id"],
                "to_store_id": scenario["stores"]["0101"]["id"],
                "item_id": scenario["item"]["id"],
                "units": 6,
                "expected_from_position_version": current_position_version(donor["id"]),
            },
            headers,
        ),
        201,
    )
    return scenario, transfer


def test_rebalance_size_split_fills_only_core_sizes_the_receiver_has_none_of(
    api, allocator_headers
):
    """PRD §3.8: "For a `REBALANCE` transfer the goal is to fill holes: the
    candidate sizes are the SKU's **CORE** sizes for which the receiving position
    shows zero units on hand and the donor position shows more than zero, and each
    candidate's weight is its `share_bp` from the size curve."

    The receiver holds M and L but no S and no XL, so only S at 2000 basis points
    and XL at 1500 are candidates, and the six units split 4 and 2 with the single
    leftover unit going to the heavier weight.

    Design: Difficulty/combinatorial_formula/transfer_benefit_per_size_line_rounding_before_summation
    """
    _, transfer = _propose_six_unit_rebalance(api, allocator_headers)

    assert units_by_size(transfer["size_split"]) == {"S": 4, "XL": 2}
    assert sum(entry["units"] for entry in transfer["size_split"]) == 6


def test_transfer_benefit_rounds_each_size_line_to_cents_before_summing_them(
    api, allocator_headers
):
    """PRD §3.8: "Rounding happens **per size line**: for each entry of
    `size_split`, that entry's `units` multiplied by the realised per-unit margin
    is rounded half up to two decimals, and `benefit_usd` is the sum of those
    rounded per-size figures." "Fourth and last, `benefit_ratio_bp` is
    `benefit_usd` divided by `landed_cost_usd`, multiplied by 10000, rounded half
    up to a whole number of basis points."

    The realised per-unit margin is 13.04875, so the S line of 4 rounds 52.195 to
    52.20 and the XL line of 2 rounds 26.0975 to 26.10 for a total of 78.30 — one
    cent above the 78.29 a single rounding of 78.2925 would produce, which also
    lifts the ratio from 15534 to 15536.

    Design: Difficulty/combinatorial_formula/transfer_benefit_per_size_line_rounding_before_summation
    """
    _, transfer = _propose_six_unit_rebalance(api, allocator_headers)

    assert transfer["benefit_usd"] == pytest.approx(78.30)
    assert_cost_precision(transfer["benefit_usd"])
    assert transfer["benefit_ratio_bp"] == 15536


def test_transfer_benefit_accrues_at_the_receiving_stores_sell_through(
    api, allocator_headers
):
    """PRD §3.8: "That margin is then multiplied by the **receiving** store's
    `historical_sell_through_bp` as a fraction of 10000 — the donor's sell-through
    is never used — and again kept exact and unrounded, giving a realised per-unit
    margin."

    Store 0101 receives at 6500 basis points while donor 0102 sells through at
    5800, and the frozen benefit follows the receiver.

    Design: Difficulty/combinatorial_formula/transfer_benefit_per_size_line_rounding_before_summation
    """
    scenario, transfer = _propose_six_unit_rebalance(api, allocator_headers)

    assert scenario["stores"]["0101"]["historical_sell_through_bp"] == 6500
    assert scenario["stores"]["0102"]["historical_sell_through_bp"] == 5800
    assert transfer["benefit_usd"] == pytest.approx(78.30)
    assert transfer["benefit_usd"] > 70.00


def test_freight_takes_the_forty_five_dollar_floor_before_any_handling_tier_is_read(
    api, allocator_headers
):
    """PRD §3.8: "Step one is freight: the donor store's `freight_flat_usd` plus 85
    cents per unit moved, that sum rounded half up to two decimals, and the result
    taken as the greater of itself and a floor of 45 dollars — so a tiny transfer
    from a cheap donor still costs 45.00 — and stored as `freight_cost_usd`."

    Donor 0102 charges 38.00 flat and six units add 5.10, so the computed 43.10
    loses to the 45.00 floor.

    Design: Difficulty/combinatorial_formula/landed_cost_handling_tier_keyed_on_freight_not_on_landed_total
    """
    _, transfer = _propose_six_unit_rebalance(api, allocator_headers)

    assert transfer["freight_cost_usd"] == pytest.approx(45.00)
    assert_cost_precision(transfer["freight_cost_usd"])


def test_handling_tier_is_keyed_on_the_freight_figure_and_never_on_the_landed_total(
    api, allocator_headers
):
    """PRD §3.8: "Step two is the handling fee, whose rate tier is selected **on the
    freight figure and never on the landed figure**: a `freight_cost_usd` below
    50.00 attracts 1200 basis points, a figure from 50.00 inclusive up to but not
    including 150.00 attracts 900 basis points, and a figure of 150.00 or above
    attracts 600 basis points." "Keying the tier on landed cost instead of freight
    is the classic wrong answer: a freight of 45.00 lands at 50.40, which would flip
    the tier and change the fee."

    Freight of 45.00 sits below the 50.00 boundary, so handling is 1200 basis
    points for 5.40 and the landed total is 50.40 — not the 4.05 fee and 49.05
    total that reading the tier off the landed figure would produce.

    Design: Difficulty/combinatorial_formula/landed_cost_handling_tier_keyed_on_freight_not_on_landed_total
    """
    _, transfer = _propose_six_unit_rebalance(api, allocator_headers)

    assert transfer["handling_fee_usd"] == pytest.approx(5.40)
    assert transfer["landed_cost_usd"] == pytest.approx(50.40)
    assert_cost_precision(transfer["handling_fee_usd"])
    assert_cost_precision(transfer["landed_cost_usd"])


def test_landed_cost_is_the_exact_sum_of_the_two_rounded_components(
    api, allocator_headers
):
    """PRD §3.8: "Step three is `landed_cost_usd`, the exact sum of the two-decimal
    `freight_cost_usd` and the two-decimal `handling_fee_usd`, with no further
    rounding."

    The 45.00 freight and the 5.40 handling fee sum to 50.40, against which the
    78.30 benefit reports 15536 basis points rather than the 15963 a 49.05 landed
    cost would have reported.

    Design: Difficulty/combinatorial_formula/landed_cost_handling_tier_keyed_on_freight_not_on_landed_total
    """
    _, transfer = _propose_six_unit_rebalance(api, allocator_headers)

    assert transfer["landed_cost_usd"] == pytest.approx(
        transfer["freight_cost_usd"] + transfer["handling_fee_usd"]
    )
    assert transfer["benefit_ratio_bp"] == 15536
