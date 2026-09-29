"""
The refusal tiers of PRD section 2.7 as they apply to the packhouse and the
buyer programs: the commercial quota rules that guard an allocation, the food
safety hold that follows a lot around, the terminal states of a shipped line and
a defaulted program, and the temporal and mass-balance rules of cooling.

Every test drives a request that offends a known rule and pins both the error
identifier and the fact that nothing moved.
"""

from prd_bench_local_runner.testing import validate_error

from test_helpers import api_errors as e
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as x
from test_helpers import test_users as u


def _packable_block(api, name: str, acres: float = 8.00):
    """A sampled block, a crew and a planned window able to carry pack records."""
    block = x.register_block(
        api,
        name=name,
        variety="STRAWBERRY",
        acres=acres,
        planting_year=2021,
        irrigation_source_code="WELL-" + name,
    )
    x.record_water_sample(
        api, block["id"], sample_date="2026-07-20", generic_ecoli_mpn=40
    )
    crew = x.recruit_crew(api, name="CREW-" + name)
    window = x.plan_window(
        api,
        block["id"],
        crew["id"],
        start_at="2026-08-03T06:00:00Z",
        end_at="2026-08-03T18:00:00Z",
        forecast_brix=8.5,
        planned_volume_lbs=150.00,
        piece_rate_cents_per_clamshell=45,
        clamshell_net_weight_lbs=1.00,
    )
    return block, crew, window


def test_three_allocation_quotas_fail_in_three_distinguishable_ways(api):
    """
    Variety, lot volume and program capacity are three separate refusals: the
    wrong berry, more pounds than the lot holds, and more pounds than the
    program still has room for.

    PRD 2.7 rule 53: "A fruit lot's `variety` equals its block's `variety`, and an allocated lot's `variety` equals the buyer commitment's `variety`; both failures report `ERR_VARIETY_MISMATCH`."

    PRD 2.7 rule 62: "`allocated_lbs` does not exceed the lot's `available_lbs`, otherwise `ERR_LOT_VOLUME_EXCEEDED`."

    PRD 2.7 rule 63: "`allocated_lbs` does not exceed the commitment's `open_lbs`, otherwise `ERR_COMMITMENT_OVERBOOKED`."

    Design: Corner/validations/allocation_refusals_separate_variety_lot_volume_and_commitment_capacity
    """
    block, _, window = _packable_block(api, "BLK-V11")
    lot = x.pack_lot(
        api,
        window["id"],
        block["id"],
        variety="STRAWBERRY",
        grade="A",
        clamshell_count=100,
        clamshell_net_weight_lbs=1.00,
        pick_date="2026-08-03",
        pack_completed_at="2026-08-03T12:00:00Z",
        field_pulp_temp_f=62.0,
    )
    small = x.open_commitment(
        api,
        buyer_name="PROGRAM-V11-SMALL",
        variety="STRAWBERRY",
        volume_commitment_lbs=60.00,
        price_cents_per_lb=400,
        window_start_date="2026-08-01",
        window_end_date="2026-08-10",
    )
    other_variety = x.open_commitment(
        api,
        buyer_name="PROGRAM-V11-BLUE",
        variety="BLUEBERRY",
        volume_commitment_lbs=200.00,
        price_cents_per_lb=500,
        shelf_life_guarantee_days=10,
        window_start_date="2026-08-01",
        window_end_date="2026-08-10",
    )
    large = x.open_commitment(
        api,
        buyer_name="PROGRAM-V11-LARGE",
        variety="STRAWBERRY",
        volume_commitment_lbs=300.00,
        price_cents_per_lb=380,
        window_start_date="2026-08-01",
        window_end_date="2026-08-10",
    )

    validate_error(
        api.create_lot_allocation(
            f.lot_allocation_payload(lot["id"], other_variety["id"], 50.00, 1),
            u.SALES_MANAGER,
        ),
        e.ERR_VARIETY_MISMATCH,
        422,
    )
    validate_error(
        api.create_lot_allocation(
            f.lot_allocation_payload(lot["id"], large["id"], 150.00, 1),
            u.SALES_MANAGER,
        ),
        e.ERR_LOT_VOLUME_EXCEEDED,
        422,
    )
    validate_error(
        api.create_lot_allocation(
            f.lot_allocation_payload(lot["id"], small["id"], 80.00, 1),
            u.SALES_MANAGER,
        ),
        e.ERR_COMMITMENT_OVERBOOKED,
        422,
    )

    stored_lot = x.read_lot(api, lot["id"])
    a.assert_pounds(stored_lot["available_lbs"], 100.00, "lot.available_lbs")
    a.assert_pounds(stored_lot["allocated_lbs"], 0.00, "lot.allocated_lbs")
    a.assert_status(stored_lot, "disposition_status", "UNCOMMITTED")
    assert stored_lot["version"] == 1

    stored_small = x.read_commitment(api, small["id"])
    a.assert_pounds(stored_small["committed_lbs"], 0.00, "commitment.committed_lbs")
    a.assert_pounds(stored_small["shipped_lbs"], 0.00, "commitment.shipped_lbs")
    a.assert_status(stored_small, "status", "OPEN")
    assert stored_small["version"] == 1
    assert x.read_commitment(api, large["id"])["version"] == 1

    _, meta = x.list_allocations(api, fruit_lot_id=lot["id"])
    a.assert_page_meta(meta, expected_total=0)


def test_a_held_lot_is_frozen_but_a_rejected_lot_answers_on_its_disposition(api):
    """
    A quarantine cascade puts the block's live lots on hold, which stops both
    cooling and allocation; the already-rejected lot answers with its terminal
    disposition instead, because that check sits in an earlier rule tier.

    PRD 3.1: "Independently of the window chain, every fruit lot whose traceability block is this block and whose `disposition_status` is `UNCOMMITTED` or `RESERVED` has `food_safety_hold` set to true."

    PRD 2.7 rule 36: "A lot's `disposition_status` is `UNCOMMITTED` or `RESERVED` when cooling starts, `UNCOMMITTED` when it is repacked, and neither `DELIVERED` nor `REJECTED` nor `REPACKED` when it is rejected or allocated, otherwise `ERR_INVALID_DISPOSITION_STATE`."

    PRD 2.7 rule 40: "The lot is not under a food safety hold when cooling starts, when it is repacked, or when it is allocated; the rejection in all three cases is `ERR_LOT_ON_FOOD_SAFETY_HOLD`."

    Design: Corner/validations/food_safety_hold_blocks_cooling_and_allocation_but_disposition_is_checked_first
    """
    block, _, window = _packable_block(api, "BLK-V12")
    tunnel = x.register_tunnel(api, name="TUN-V12", slot_capacity=4)
    live_lot = x.pack_lot(
        api,
        window["id"],
        block["id"],
        variety="STRAWBERRY",
        grade="A",
        clamshell_count=50,
        clamshell_net_weight_lbs=1.00,
        pick_date="2026-08-03",
        pack_completed_at="2026-08-03T09:00:00Z",
        field_pulp_temp_f=62.0,
    )
    rejected_lot = x.cooled_lot(
        api,
        window["id"],
        block["id"],
        tunnel["id"],
        variety="STRAWBERRY",
        grade="A",
        clamshell_count=50,
        clamshell_net_weight_lbs=1.00,
        pick_date="2026-08-03",
        pack_completed_at="2026-08-03T09:00:00Z",
        field_pulp_temp_f=62.0,
    )
    x.reject_lot(api, rejected_lot["id"], reason_code="OPTICAL_DEFECT_RATE")
    x.quarantine_block(api, block["id"], reason_code="ADJACENT_ANIMAL_INTRUSION")
    commitment = x.open_commitment(
        api,
        buyer_name="PROGRAM-V12",
        variety="STRAWBERRY",
        volume_commitment_lbs=300.00,
        price_cents_per_lb=400,
        window_start_date="2026-08-01",
        window_end_date="2026-08-10",
    )

    validate_error(
        api.start_cooling(
            live_lot["id"],
            f.start_cooling_payload(tunnel["id"], x.tunnel_version(api, tunnel["id"])),
            u.PACKHOUSE_OPERATOR,
        ),
        e.ERR_LOT_ON_FOOD_SAFETY_HOLD,
        409,
    )
    validate_error(
        api.create_lot_allocation(
            f.lot_allocation_payload(live_lot["id"], commitment["id"], 40.00, 1),
            u.SALES_MANAGER,
        ),
        e.ERR_LOT_ON_FOOD_SAFETY_HOLD,
        409,
    )
    validate_error(
        api.repack_fruit_lot(
            rejected_lot["id"], f.repack_payload(30, 10, 10, "B"), u.PACKHOUSE_OPERATOR
        ),
        e.ERR_INVALID_DISPOSITION_STATE,
        409,
    )

    stored_live = x.read_lot(api, live_lot["id"])
    assert stored_live["food_safety_hold"] is True
    a.assert_status(stored_live, "cold_chain_status", "PACKED")
    a.assert_unset(stored_live, "cooling_tunnel_id", "lot")

    stored_rejected = x.read_lot(api, rejected_lot["id"])
    a.assert_status(stored_rejected, "disposition_status", "REJECTED")
    assert stored_rejected["food_safety_hold"] is True
    a.assert_pounds(stored_rejected["available_lbs"], 0.00, "lot.available_lbs")

    assert x.read_tunnel(api, tunnel["id"])["committed_slots"] == 0

    _, child_meta = x.list_lots(api, source_lot_id=rejected_lot["id"])
    a.assert_page_meta(child_meta, expected_total=0)
    _, alloc_meta = x.list_allocations(api, buyer_commitment_id=commitment["id"])
    a.assert_page_meta(alloc_meta, expected_total=0)


def test_a_shipped_line_is_terminal_and_a_late_pickup_leaves_the_program_window(api):
    """
    Once a line has shipped it cannot be released back to inventory, and its
    still-reserved sibling cannot be picked up after the program's delivery
    window has closed.

    PRD 2.7 rule 37: "An allocation line is `RESERVED` when shipped or released, otherwise `ERR_INVALID_ALLOCATION_STATE`; and a buyer commitment is `OPEN` when allocated against, shipped from, released from or settled, otherwise `ERR_INVALID_COMMITMENT_STATE`."

    PRD 2.7 rule 59: "On a ship, the `shipped_at` date falls inside the commitment's delivery window inclusive **and** the current logical clock date is not after the lot's `shelf_life_expires_on`, otherwise `ERR_SHIP_OUTSIDE_PROGRAM_WINDOW`."

    PRD 3.7: "Shipping stores `shipped_at`, moves the lot's `cold_chain_status` `COOLED → SHIPPED` and its `disposition_status` `RESERVED → DELIVERED`, increases the commitment's `shipped_lbs` by the line's `allocated_lbs` and recomputes `fill_pct`, and increments the `version` of the allocation, the lot and the commitment each by 1."

    Design: Corner/validations/shipped_line_cannot_be_released_and_late_shipment_leaves_the_program_window
    """
    block = x.register_block(
        api,
        name="BLK-V13",
        variety="STRAWBERRY",
        acres=8.00,
        planting_year=2021,
        irrigation_source_code="WELL-V13",
    )
    x.water_series(
        api,
        block["id"],
        [("2026-07-10", 40), ("2026-07-15", 50), ("2026-07-20", 60)],
    )
    crew = x.recruit_crew(api, name="CREW-V13")
    window = x.plan_window(
        api,
        block["id"],
        crew["id"],
        start_at="2026-08-03T06:00:00Z",
        end_at="2026-08-03T18:00:00Z",
        forecast_brix=8.5,
        planned_volume_lbs=150.00,
        piece_rate_cents_per_clamshell=45,
        clamshell_net_weight_lbs=1.00,
    )
    tunnel = x.register_tunnel(api, name="TUN-V13", slot_capacity=4)
    lot_spec = dict(
        variety="STRAWBERRY",
        grade="A",
        clamshell_count=50,
        clamshell_net_weight_lbs=1.00,
        pick_date="2026-08-03",
        pack_completed_at="2026-08-03T09:00:00Z",
        field_pulp_temp_f=62.0,
    )
    first_lot = x.cooled_lot(api, window["id"], block["id"], tunnel["id"], **lot_spec)
    second_lot = x.cooled_lot(api, window["id"], block["id"], tunnel["id"], **lot_spec)
    commitment = x.open_commitment(
        api,
        buyer_name="PROGRAM-V13",
        variety="STRAWBERRY",
        volume_commitment_lbs=200.00,
        price_cents_per_lb=400,
        window_start_date="2026-08-01",
        window_end_date="2026-08-10",
    )
    shipped_line = x.allocate(api, first_lot["id"], commitment["id"], 50.00)
    reserved_line = x.allocate(api, second_lot["id"], commitment["id"], 50.00)
    x.ship_allocation(api, shipped_line["id"], shipped_at="2026-08-05T09:00:00Z")

    validate_error(
        api.release_lot_allocation(
            shipped_line["id"],
            f.release_payload(release_reason_code="BUYER_CANCELLED"),
            u.SALES_MANAGER,
        ),
        e.ERR_INVALID_ALLOCATION_STATE,
        409,
    )
    validate_error(
        api.ship_lot_allocation(
            reserved_line["id"], f.ship_payload("2026-08-15T09:00:00Z"), u.SALES_MANAGER
        ),
        e.ERR_SHIP_OUTSIDE_PROGRAM_WINDOW,
        422,
    )

    stored_shipped = x.read_allocation(api, shipped_line["id"])
    a.assert_status(stored_shipped, "status", "SHIPPED")
    a.assert_unset(stored_shipped, "release_reason_code", "allocation")

    stored_reserved = x.read_allocation(api, reserved_line["id"])
    a.assert_status(stored_reserved, "status", "RESERVED")
    a.assert_unset(stored_reserved, "shipped_at", "allocation")

    stored_first = x.read_lot(api, first_lot["id"])
    a.assert_status(stored_first, "cold_chain_status", "SHIPPED")
    a.assert_status(stored_first, "disposition_status", "DELIVERED")
    a.assert_pounds(stored_first["available_lbs"], 0.00, "lot.available_lbs")

    stored_second = x.read_lot(api, second_lot["id"])
    a.assert_status(stored_second, "cold_chain_status", "COOLED")
    a.assert_status(stored_second, "disposition_status", "RESERVED")
    # PRD 3.6: base 7 (STRAWBERRY) − 0 (grade A) − 2 (field_delay_hours 4.00
    # exceeds the 2.0 h tolerance by 2.0, rounded up) − 0 (cool_hours 4.00 is
    # exactly the 4.0 h target) − 0 (exit 34.0 °F is exactly the target) = 5,
    # and `shelf_life_expires_on` is the date of `cool_complete_at` advanced by
    # `verified_shelf_life_days`: 2026-08-03 + 5 days.
    assert stored_second["verified_shelf_life_days"] == 5
    assert stored_second["shelf_life_expires_on"] == "2026-08-08"

    stored_commitment = x.read_commitment(api, commitment["id"])
    a.assert_status(stored_commitment, "status", "OPEN")
    a.assert_commitment_exposure(stored_commitment, 100.00, 50.00)


def test_provisional_water_may_pack_and_cool_fruit_but_may_not_ship_it(api):
    """
    A single passing sample clears the block for picking and cooling, yet the
    shipping gate demands a fully compliant sampling record.

    PRD 2.7 rule 41: "The traceability block of a shipping lot has a `water_status` of `COMPLIANT`, otherwise `ERR_BLOCK_WATER_NOT_COMPLIANT`."

    PRD 3.7: "The `water_status` of the lot's traceability block must be exactly `COMPLIANT` — not `PROVISIONAL`, not `FAILED`, not `NON_COMPLIANT` — otherwise `ERR_BLOCK_WATER_NOT_COMPLIANT`; a block whose sampling record is merely provisional may pack and cool fruit but may not ship it."

    Design: Corner/validations/ship_from_a_provisional_water_block_returns_water_not_compliant
    """
    block, _, window = _packable_block(api, "BLK-V14")
    tunnel = x.register_tunnel(api, name="TUN-V14", slot_capacity=4)
    lot = x.cooled_lot(
        api,
        window["id"],
        block["id"],
        tunnel["id"],
        variety="STRAWBERRY",
        grade="A",
        clamshell_count=50,
        clamshell_net_weight_lbs=1.00,
        pick_date="2026-08-03",
        pack_completed_at="2026-08-03T09:00:00Z",
        field_pulp_temp_f=62.0,
    )
    commitment = x.open_commitment(
        api,
        buyer_name="PROGRAM-V14",
        variety="STRAWBERRY",
        volume_commitment_lbs=200.00,
        price_cents_per_lb=400,
        window_start_date="2026-08-01",
        window_end_date="2026-08-10",
    )
    line = x.allocate(api, lot["id"], commitment["id"], 50.00)

    validate_error(
        api.ship_lot_allocation(
            line["id"], f.ship_payload("2026-08-05T09:00:00Z"), u.SALES_MANAGER
        ),
        e.ERR_BLOCK_WATER_NOT_COMPLIANT,
        409,
    )

    stored_block = x.read_block(api, block["id"])
    a.assert_status(stored_block, "water_status", "PROVISIONAL")
    assert stored_block["water_sample_count"] == 1
    a.assert_status(stored_block, "food_safety_posture", "CLEARED")

    stored_line = x.read_allocation(api, line["id"])
    a.assert_status(stored_line, "status", "RESERVED")
    a.assert_unset(stored_line, "shipped_at", "allocation")

    stored_lot = x.read_lot(api, lot["id"])
    a.assert_status(stored_lot, "cold_chain_status", "COOLED")
    a.assert_status(stored_lot, "disposition_status", "RESERVED")

    stored_commitment = x.read_commitment(api, commitment["id"])
    a.assert_pounds(stored_commitment["shipped_lbs"], 0.00, "commitment.shipped_lbs")
    a.assert_ratio(stored_commitment["fill_pct"], 0.0000, "commitment.fill_pct")


def test_a_defaulted_program_accepts_no_further_pounds(api):
    """
    A program that reached its end date with nothing shipped settles straight to
    `DEFAULTED`, which is terminal, so a late allocation carrying the correct
    version guard is still refused on state.

    PRD 2.7 rule 37: "An allocation line is `RESERVED` when shipped or released, otherwise `ERR_INVALID_ALLOCATION_STATE`; and a buyer commitment is `OPEN` when allocated against, shipped from, released from or settled, otherwise `ERR_INVALID_COMMITMENT_STATE`."

    PRD 3.7: "On the defaulted branch nothing was shipped, so there are no lines to price. `settled_revenue_cents` is 0, `fill_pct` is 0.0000, `fill_status` is `SHORTFALL`, and `shortfall_penalty_cents` is charged against the **entire** contracted volume: `volume_commitment_lbs` multiplied by `price_cents_per_lb` multiplied by the fifteen percent rate, rounded half up."

    Design: Corner/validations/allocate_against_a_defaulted_commitment_returns_invalid_commitment_state
    """
    block, _, window = _packable_block(api, "BLK-V15")
    lot = x.pack_lot(
        api,
        window["id"],
        block["id"],
        variety="STRAWBERRY",
        grade="A",
        clamshell_count=50,
        clamshell_net_weight_lbs=1.00,
        pick_date="2026-08-03",
        pack_completed_at="2026-08-03T09:00:00Z",
        field_pulp_temp_f=62.0,
    )
    commitment = x.open_commitment(
        api,
        buyer_name="PROGRAM-V15",
        variety="STRAWBERRY",
        volume_commitment_lbs=100.00,
        price_cents_per_lb=400,
        window_start_date="2026-08-01",
        window_end_date="2026-08-02",
    )
    x.set_clock(api, "2026-08-05T00:00:00Z")
    settled = x.settle_commitment(api, commitment["id"])

    validate_error(
        api.create_lot_allocation(
            f.lot_allocation_payload(
                lot["id"], commitment["id"], 50.00, settled["version"]
            ),
            u.SALES_MANAGER,
        ),
        e.ERR_INVALID_COMMITMENT_STATE,
        409,
    )

    stored_commitment = x.read_commitment(api, commitment["id"])
    a.assert_status(stored_commitment, "status", "DEFAULTED")
    a.assert_status(stored_commitment, "fill_status", "SHORTFALL")
    a.assert_ratio(stored_commitment["fill_pct"], 0.0000, "commitment.fill_pct")
    a.assert_cents(
        stored_commitment["settled_revenue_cents"], 0, "settled_revenue_cents"
    )
    a.assert_cents(
        stored_commitment["shortfall_penalty_cents"], 6000, "shortfall_penalty_cents"
    )
    a.assert_cents(stored_commitment["settled_net_cents"], -6000, "settled_net_cents")
    a.assert_pounds(stored_commitment["committed_lbs"], 0.00, "commitment.committed_lbs")
    assert stored_commitment["version"] == 2

    stored_lot = x.read_lot(api, lot["id"])
    a.assert_status(stored_lot, "disposition_status", "UNCOMMITTED")
    a.assert_pounds(stored_lot["available_lbs"], 50.00, "lot.available_lbs")

    _, meta = x.list_allocations(api, fruit_lot_id=lot["id"])
    a.assert_page_meta(meta, expected_total=0)


def test_cooling_before_the_pack_is_finished_and_a_repack_that_loses_a_clamshell(api):
    """
    A cooling run cannot start before the fruit was packed, and a repack whose
    three output counts do not add back to the source is refused; neither
    request leaves a mark on the lot or on the tunnel.

    PRD 2.7 rule 58: "The logical clock instant is strictly before the window's `end_at` when the window is opened or resumed; `cool_start_at` is not earlier than `pack_completed_at`; `cool_complete_at` is strictly after `cool_start_at`; and a buyer commitment settles only after its `window_end_date` has passed. All four failures report `ERR_TEMPORAL_ORDER_VIOLATION`."

    PRD 2.7 rule 50: "The three repack output counts balance the source lot exactly and the output count is at least 1, otherwise `ERR_REPACK_MASS_BALANCE`."

    PRD 3.6: "Starting a run stores the cooling fields, computes `field_delay_hours` as the elapsed hours from `pack_completed_at` to `cool_start_at` rounded half up to two decimals, stamps `forecast_shelf_life_days` from the forecast variant of the shelf-life calculation, increments the tunnel's `committed_slots` by `pallet_slots` and the tunnel's `version` by 1, moves the lot `PACKED → COOLING`, and increments the lot's `version` by 1."

    Design: Corner/validations/cooling_and_repack_reject_bad_timestamps_and_unbalanced_counts
    """
    block, _, window = _packable_block(api, "BLK-V16")
    tunnel = x.register_tunnel(api, name="TUN-V16", slot_capacity=4)
    packed_lot = x.pack_lot(
        api,
        window["id"],
        block["id"],
        variety="STRAWBERRY",
        grade="A",
        clamshell_count=50,
        clamshell_net_weight_lbs=1.00,
        pick_date="2026-08-03",
        pack_completed_at="2026-08-03T12:00:00Z",
        field_pulp_temp_f=62.0,
    )
    cooled = x.cooled_lot(
        api,
        window["id"],
        block["id"],
        tunnel["id"],
        variety="STRAWBERRY",
        grade="A",
        clamshell_count=50,
        clamshell_net_weight_lbs=1.00,
        pick_date="2026-08-03",
        pack_completed_at="2026-08-03T09:00:00Z",
        field_pulp_temp_f=62.0,
    )
    tunnel_version_before = x.read_tunnel(api, tunnel["id"])["version"]

    validate_error(
        api.start_cooling(
            packed_lot["id"],
            f.start_cooling_payload(
                tunnel["id"],
                tunnel_version_before,
                cool_start_at="2026-08-03T11:00:00Z",
                planned_cool_end_at="2026-08-03T15:00:00Z",
            ),
            u.PACKHOUSE_OPERATOR,
        ),
        e.ERR_TEMPORAL_ORDER_VIOLATION,
        422,
    )
    validate_error(
        api.repack_fruit_lot(
            cooled["id"], f.repack_payload(30, 10, 9, "B"), u.PACKHOUSE_OPERATOR
        ),
        e.ERR_REPACK_MASS_BALANCE,
        422,
    )

    stored_packed = x.read_lot(api, packed_lot["id"])
    a.assert_status(stored_packed, "cold_chain_status", "PACKED")
    a.assert_unset(stored_packed, "cooling_tunnel_id", "lot")
    a.assert_unset(stored_packed, "cool_start_at", "lot")
    a.assert_unset(stored_packed, "forecast_shelf_life_days", "lot")

    stored_cooled = x.read_lot(api, cooled["id"])
    a.assert_status(stored_cooled, "disposition_status", "UNCOMMITTED")
    a.assert_pounds(stored_cooled["repack_out_lbs"], 0.00, "lot.repack_out_lbs")
    a.assert_pounds(stored_cooled["available_lbs"], 50.00, "lot.available_lbs")

    stored_tunnel = x.read_tunnel(api, tunnel["id"])
    assert stored_tunnel["committed_slots"] == 0
    assert stored_tunnel["version"] == tunnel_version_before

    _, meta = x.list_lots(api, source_lot_id=cooled["id"])
    a.assert_page_meta(meta, expected_total=0)


def test_a_released_crew_takes_no_window_and_a_certified_crew_no_new_housing(api):
    """
    Release is terminal for scheduling, and certification freezes the support
    plan: the two refusals come from different rule tiers and carry different
    identifiers.

    PRD 2.7 rule 54: "A payroll run's `crew_id` equals the crew of every session it would bind, and a planned window does not name a `RELEASED` crew; both failures report `ERR_CREW_MISMATCH`."

    PRD 2.7 rule 27: "A crew is `RECRUITING` or `STAFFED` when its support plan is recorded — housing and transport cannot be re-cut after certification — otherwise `ERR_INVALID_CREW_STATE`."

    PRD 3.2: "The support plan may only be recorded while the crew is `RECRUITING` or `STAFFED`; once a crew has been certified, its housing and transport cannot be re-cut, and a later attempt is refused with `ERR_INVALID_CREW_STATE`."

    Design: Corner/validations/crew_lifecycle_blocks_released_crew_windows_and_late_support_plans
    """
    block = x.register_block(
        api,
        name="BLK-V17",
        variety="STRAWBERRY",
        acres=8.00,
        planting_year=2021,
        irrigation_source_code="WELL-V17",
    )
    released_crew, _ = x.certified_crew(
        api,
        picker_count=1,
        labor_program="H2A",
        name="CREW-V17R",
        support_plan={
            "housing_unit_code": "H-V17R",
            "beds_confirmed": 1,
            "transport_route_code": "R-V17R",
            "vehicle_seats": 1,
        },
    )
    x.release_crew(api, released_crew["id"])
    live_crew, _ = x.certified_crew(
        api,
        picker_count=1,
        supervisor_user_id=u.SUP_2,
        name="CREW-V17C",
        support_plan={
            "housing_unit_code": "H-V17C",
            "beds_confirmed": 1,
            "transport_route_code": "R-V17C",
            "vehicle_seats": 1,
        },
    )

    validate_error(
        api.create_harvest_window(
            f.harvest_window_payload(
                block["id"],
                released_crew["id"],
                start_at="2026-08-03T06:00:00Z",
                end_at="2026-08-03T14:00:00Z",
            ),
            u.HARVEST_MANAGER,
        ),
        e.ERR_CREW_MISMATCH,
        422,
    )
    validate_error(
        api.record_support_plan(
            live_crew["id"],
            f.support_plan_payload(
                4,
                housing_unit_code="H-V17C2",
                beds_confirmed=4,
                transport_route_code="R-V17C2",
                vehicle_seats=4,
            ),
            u.HARVEST_MANAGER,
        ),
        e.ERR_INVALID_CREW_STATE,
        409,
    )

    stored_released = x.read_crew(api, released_crew["id"])
    a.assert_status(stored_released, "status", "RELEASED")
    a.assert_cents(
        stored_released["accrued_wage_cents"], 0, "crew.accrued_wage_cents"
    )

    stored_live = x.read_crew(api, live_crew["id"])
    a.assert_status(stored_live, "status", "CERTIFIED")
    assert stored_live["housing_unit_code"] == "H-V17C"
    assert stored_live["beds_confirmed"] == 1
    assert stored_live["vehicle_seats"] == 1

    _, meta = x.list_windows(api, crew_id=released_crew["id"])
    a.assert_page_meta(meta, expected_total=0)


def test_a_window_needing_three_pickers_will_not_open_for_a_crew_of_one(api):
    """
    The staffing estimate is forward-looking, so a confirmed window can demand
    more pickers than the crew actually holds; the shortfall surfaces only at
    the opening gate.

    PRD 2.7 rule 60: "The crew has at least the window's `required_picker_count` pickers when the window is opened, and `required_picker_count` does not exceed the crew cap of 60 when the window is confirmed; both failures report `ERR_INSUFFICIENT_PICKERS`."

    PRD 3.3: "The crew's `picker_count` must be at least the window's `required_picker_count`, otherwise `ERR_INSUFFICIENT_PICKERS`."

    Design: Corner/validations/open_a_window_with_fewer_pickers_than_required_returns_insufficient_pickers
    """
    block = x.register_block(
        api,
        name="BLK-V18",
        variety="STRAWBERRY",
        acres=20.00,
        planting_year=2021,
        irrigation_source_code="WELL-V18",
    )
    x.record_water_sample(
        api, block["id"], sample_date="2026-07-20", generic_ecoli_mpn=40
    )
    crew, _ = x.certified_crew(
        api, picker_count=1, planned_head_count=6, name="CREW-V18"
    )
    window = x.confirmed_window(
        api,
        block["id"],
        crew["id"],
        start_at="2026-08-03T06:00:00Z",
        end_at="2026-08-03T14:00:00Z",
        forecast_brix=8.5,
        planned_volume_lbs=400.00,
        piece_rate_cents_per_clamshell=45,
        clamshell_net_weight_lbs=1.00,
    )

    validate_error(
        api.open_harvest_window(window["id"], u.HARVEST_MANAGER),
        e.ERR_INSUFFICIENT_PICKERS,
        422,
    )

    stored_window = x.read_window(api, window["id"])
    a.assert_status(stored_window, "status", "CONFIRMED")
    assert stored_window["required_picker_count"] == 3
    a.assert_rate(
        stored_window["effective_pick_rate_lbs_per_hour"],
        22.00,
        "window.effective_pick_rate_lbs_per_hour",
    )
    a.assert_hours(stored_window["window_hours"], 8.00, "window.window_hours")

    stored_crew = x.read_crew(api, crew["id"])
    a.assert_status(stored_crew, "status", "CERTIFIED")
    assert stored_crew["picker_count"] == 1
    assert stored_crew["planned_head_count"] == 6


def test_a_closed_window_admits_no_re_tally(api):
    """
    Once the window is closed the tally channel shuts with it, and the window
    check answers ahead of the session's own status check.

    PRD 2.7 rule 29: "The window of a session is `OPEN` when the session is created, tallied or disputed; a `SUSPENDED`, `CLOSED`, `CONFIRMED` or `CANCELLED` window admits none of the three, and the rejection is `ERR_WINDOW_NOT_OPEN`."

    PRD 3.4: "the window must be `OPEN`, so a `SUSPENDED`, `CLOSED`, `CONFIRMED` or `CANCELLED` window admits nothing and yields `ERR_WINDOW_NOT_OPEN`"

    Design: Corner/validations/tally_on_a_closed_window_returns_window_not_open
    """
    block = x.register_block(
        api,
        name="BLK-V19",
        variety="STRAWBERRY",
        acres=8.00,
        planting_year=2021,
        irrigation_source_code="WELL-V19",
    )
    x.record_water_sample(
        api, block["id"], sample_date="2026-07-20", generic_ecoli_mpn=40
    )
    crew, pickers = x.certified_crew(api, picker_count=1, name="CREW-V19")
    window = x.opened_window(
        api,
        block["id"],
        crew["id"],
        start_at="2026-08-03T06:00:00Z",
        end_at="2026-08-03T14:00:00Z",
        piece_rate_cents_per_clamshell=45,
        clamshell_net_weight_lbs=1.00,
        planned_volume_lbs=150.00,
    )
    session = x.approved_session(
        api,
        window["id"],
        pickers[0]["id"],
        work_date="2026-08-03",
        hours_worked=3.00,
        clamshells_filled=20,
        culled_clamshells=0,
    )
    x.close_window(api, window["id"])

    validate_error(
        api.tally_pick_session(
            session["id"],
            f.tally_payload(
                hours_worked=4.00, clamshells_filled=26, culled_clamshells=0
            ),
            u.CREW_SUPERVISOR,
        ),
        e.ERR_WINDOW_NOT_OPEN,
        409,
    )

    stored_window = x.read_window(api, window["id"])
    a.assert_status(stored_window, "status", "CLOSED")
    assert stored_window["harvested_clamshells"] == 20

    stored_session = x.read_session(api, session["id"])
    a.assert_status(stored_session, "status", "APPROVED")
    a.assert_hours(stored_session["hours_worked"], 3.00, "session.hours_worked")
    assert stored_session["clamshells_filled"] == 20
    a.assert_cents(stored_session["net_cents"], 4950, "session.net_cents")
    assert stored_session["tally_revision_count"] == 0

    stored_crew = x.read_crew(api, crew["id"])
    a.assert_cents(stored_crew["accrued_wage_cents"], 4950, "crew.accrued_wage_cents")
