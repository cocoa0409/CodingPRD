"""
Transitions that read another entity's state before they move, and the two
opposite interval conventions the schedule is built on.

These tests exercise the block-posture gate on opening a window and the
cold-chain gate on shipping a line (PRD sections 3.3, 3.6 and 3.7), together
with the twelve-hour block re-entry buffer of section 3.3 and the half-open
tunnel occupancy check of section 3.6 that deliberately disagrees with it.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors as e
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as x
from test_helpers import test_users as u


def _confirmed_window_on_an_unsampled_block(api, name):
    """
    A `CONFIRMED` window whose block has never been sampled, so the block is
    `RESTRICTED` while the window itself is perfectly ready.

    Returns the block, the crew and the confirmed window.
    """
    block = x.register_block(
        api,
        name=name,
        variety="STRAWBERRY",
        acres=6.00,
        planting_year=2022,
        irrigation_source_code="WELL-13",
    )
    crew, _ = x.certified_crew(
        api,
        picker_count=1,
        planned_head_count=1,
        supervisor_user_id=u.SUP_1,
        labor_program="DOMESTIC",
        name="CREW-" + name,
    )
    window = x.confirmed_window(
        api,
        block["id"],
        crew["id"],
        start_at="2026-08-03T06:00:00Z",
        end_at="2026-08-03T14:00:00Z",
        forecast_brix=8.5,
        planned_volume_lbs=150.00,
        piece_rate_cents_per_clamshell=45,
        clamshell_net_weight_lbs=1.00,
    )
    a.assert_status(window, "status", "CONFIRMED")
    assert window["required_picker_count"] == 1
    a.assert_rate(
        window["effective_pick_rate_lbs_per_hour"], 22.00, "window.effective_pick_rate_lbs_per_hour"
    )
    return block, crew, window


def test_a_window_cannot_open_over_a_block_that_has_never_been_sampled(api):
    """
    The window is confirmed, the crew is certified and large enough, and the
    clock is early — yet the open is refused, because the gate reads a field on
    the block rather than on the window.

    PRD 3.3: "The block's `food_safety_posture` must be exactly `CLEARED`; a `RESTRICTED` block — whether because it has never been sampled or because its water has gone `NON_COMPLIANT` — is refused with `ERR_BLOCK_NOT_CLEARED`, and a `QUARANTINED` block is refused with `ERR_BLOCK_QUARANTINED`."

    PRD 2.7: "**Rules are evaluated in ascending priority, the first violated rule determines the response, and no side effect of the request is applied once a rule has fired.**"

    Design: Difficulty/cross_entity_state_dependency/window_open_requires_block_food_safety_posture_cleared
    """
    block, crew, window = _confirmed_window_on_an_unsampled_block(api, "BLK-CE1")
    unsampled = x.read_block(api, block["id"])
    a.assert_status(unsampled, "water_status", "NO_SAMPLES")
    a.assert_status(unsampled, "food_safety_posture", "RESTRICTED")
    assert unsampled["manual_quarantine_active"] is False

    refused = api.open_harvest_window(window["id"], u.HARVEST_MANAGER)
    body = validate_error(refused, e.ERR_BLOCK_NOT_CLEARED, 409)
    assert body["error_id"] != e.ERR_BLOCK_QUARANTINED

    stalled = x.read_window(api, window["id"])
    a.assert_status(stalled, "status", "CONFIRMED")
    assert stalled["version"] == window["version"]
    a.assert_status(x.read_crew(api, crew["id"]), "status", "CERTIFIED")


def test_one_passing_sample_on_the_block_lets_the_same_call_through(api):
    """
    Nothing about the window changes between the two attempts: a single clean
    water reading flips the block to `CLEARED` and the identical open now
    succeeds, taking the crew active with it.

    PRD 3.1: "Otherwise, if fewer than three samples are in the window, the status is `PROVISIONAL`, because one or two readings are not enough evidence of compliance."

    PRD 3.1: "Otherwise, if `water_status` is `PROVISIONAL` or `COMPLIANT`, the posture is `CLEARED`."

    PRD 3.3: "Opening increments the window's `version` by 1 and, when the crew was still `CERTIFIED`, advances it to `ACTIVE` and increments the crew's `version` by 1 as well."

    Design: Difficulty/cross_entity_state_dependency/window_open_requires_block_food_safety_posture_cleared
    """
    block, crew, window = _confirmed_window_on_an_unsampled_block(api, "BLK-CE1B")
    validate_error(
        api.open_harvest_window(window["id"], u.HARVEST_MANAGER),
        e.ERR_BLOCK_NOT_CLEARED,
        409,
    )

    x.record_water_sample(
        api, block["id"], sample_date="2026-07-30", generic_ecoli_mpn=40
    )
    cleared = x.read_block(api, block["id"])
    assert cleared["water_sample_count"] == 1
    a.assert_status(cleared, "water_status", "PROVISIONAL")
    a.assert_status(cleared, "food_safety_posture", "CLEARED")

    opened = validate_success(api.open_harvest_window(window["id"], u.HARVEST_MANAGER), 200)
    a.assert_status(opened, "status", "OPEN")
    assert opened["required_picker_count"] == 1
    a.assert_rate(
        opened["effective_pick_rate_lbs_per_hour"], 22.00, "window.effective_pick_rate_lbs_per_hour"
    )
    a.assert_unset(opened, "suspended_reason_code", "opened window")
    assert opened["version"] == window["version"] + 1

    a.assert_status(x.read_crew(api, crew["id"]), "status", "ACTIVE")


def _reserved_line_on_a_cooling_lot(api, name):
    """
    An 80.00 lb line reserved against a lot that is still inside the tunnel.

    Returns the lot, the tunnel, the commitment and the allocation line.
    """
    block = x.block_with_compliant_water(api, name=name, acres=9.00)
    crew = x.recruit_crew(api, name="CREW-" + name, planned_head_count=1)
    window = x.plan_window(
        api,
        block["id"],
        crew["id"],
        start_at="2026-08-03T05:00:00Z",
        end_at="2026-08-03T17:00:00Z",
        forecast_brix=8.5,
        planned_volume_lbs=150.00,
        piece_rate_cents_per_clamshell=45,
        clamshell_net_weight_lbs=1.00,
    )
    tunnel = x.register_tunnel(api, name="TUN-" + name, slot_capacity=4, target_pulp_temp_f=34.0)
    lot = x.pack_lot(
        api,
        window["id"],
        block["id"],
        variety="STRAWBERRY",
        grade="A",
        clamshell_count=80,
        clamshell_net_weight_lbs=1.00,
        pick_date="2026-08-03",
        pack_completed_at="2026-08-03T06:00:00Z",
        field_pulp_temp_f=60.0,
    )
    x.start_cooling(
        api,
        lot["id"],
        tunnel["id"],
        cool_start_at="2026-08-03T08:00:00Z",
        planned_cool_end_at="2026-08-03T12:00:00Z",
        entry_pulp_temp_f=56.0,
        pallet_slots=1,
    )
    commitment = x.open_commitment(
        api,
        buyer_name="MarketThree",
        variety="STRAWBERRY",
        volume_commitment_lbs=80.00,
        price_cents_per_lb=450,
        shelf_life_guarantee_days=3,
        window_start_date="2026-08-01",
        window_end_date="2026-08-10",
    )
    line = x.allocate(api, lot["id"], commitment["id"], 80.00)
    return lot, tunnel, commitment, line


def test_a_line_drawn_on_a_cooling_lot_cannot_ship(api):
    """
    The line itself is perfectly `RESERVED` and the delivery window is open, but
    the fruit is still in the tunnel and has no verified shelf life to sell
    against, so the ship is refused and the program's shipped pounds stay at
    zero.

    PRD 3.7: "The lot's `cold_chain_status` must be exactly `COOLED` — fruit that is still `PACKED` or `COOLING` has no verified shelf life to sell against, and the rejection is `ERR_INVALID_COLD_CHAIN_STATE`."

    PRD 2.7 rule 35: "A lot's `cold_chain_status` is `PACKED` when cooling starts, `COOLING` when cooling completes, `COOLED` when it is repacked, and `COOLED` when an allocation line drawn on it is shipped, otherwise `ERR_INVALID_COLD_CHAIN_STATE`."

    Design: Difficulty/cross_entity_state_dependency/allocation_ship_requires_lot_cold_chain_cooled
    """
    lot, tunnel, commitment, line = _reserved_line_on_a_cooling_lot(api, "BLK-CE2")
    a.assert_status(x.read_lot(api, lot["id"]), "cold_chain_status", "COOLING")

    refused = api.ship_lot_allocation(
        line["id"], f.ship_payload(shipped_at="2026-08-03T14:00:00Z"), u.SALES_MANAGER
    )
    validate_error(refused, e.ERR_INVALID_COLD_CHAIN_STATE, 409)

    held = x.read_allocation(api, line["id"])
    a.assert_status(held, "status", "RESERVED")
    a.assert_unset(held, "shipped_at", "reserved line")
    assert held["version"] == line["version"]

    waiting = x.read_commitment(api, commitment["id"])
    a.assert_commitment_exposure(waiting, 80.00, 0.00)
    a.assert_ratio(waiting["fill_pct"], 0.0000, "commitment.fill_pct")

    still_cooling = x.read_lot(api, lot["id"])
    a.assert_status(still_cooling, "cold_chain_status", "COOLING")
    a.assert_status(still_cooling, "disposition_status", "RESERVED")
    a.assert_unset(still_cooling, "verified_shelf_life_days", "cooling lot")
    assert x.read_tunnel(api, tunnel["id"])["committed_slots"] == 1


def test_the_same_line_ships_the_moment_the_lot_leaves_the_tunnel(api):
    """
    Completing the run stamps a verified shelf life and the identical ship call
    goes through, moving both of the lot's dimensions and filling the program
    to the pound.

    PRD 3.6: "It computes `cool_hours` as the elapsed hours from `cool_start_at` to `cool_complete_at` rounded half up to two decimals, stamps `verified_shelf_life_days` and `shelf_life_expires_on` from the verified variant, releases the slots by decrementing the tunnel's `committed_slots` by the lot's `pallet_slots` and incrementing the tunnel's `version` by 1, moves the lot `COOLING → COOLED`, and increments the lot's `version` by 1."

    PRD 3.7: "Shipping stores `shipped_at`, moves the lot's `cold_chain_status` `COOLED → SHIPPED` and its `disposition_status` `RESERVED → DELIVERED`, increases the commitment's `shipped_lbs` by the line's `allocated_lbs` and recomputes `fill_pct`, and increments the `version` of the allocation, the lot and the commitment each by 1."

    Design: Difficulty/cross_entity_state_dependency/allocation_ship_requires_lot_cold_chain_cooled
    """
    lot, tunnel, commitment, line = _reserved_line_on_a_cooling_lot(api, "BLK-CE2B")
    validate_error(
        api.ship_lot_allocation(
            line["id"], f.ship_payload(shipped_at="2026-08-03T14:00:00Z"), u.SALES_MANAGER
        ),
        e.ERR_INVALID_COLD_CHAIN_STATE,
        409,
    )

    cooled = x.complete_cooling(
        api, lot["id"], cool_complete_at="2026-08-03T12:00:00Z", exit_pulp_temp_f=34.0
    )
    a.assert_status(cooled, "cold_chain_status", "COOLED")
    a.assert_hours(cooled["cool_hours"], 4.00, "lot.cool_hours")
    assert cooled["verified_shelf_life_days"] == 7
    assert cooled["shelf_life_expires_on"] == "2026-08-10"
    assert x.read_tunnel(api, tunnel["id"])["committed_slots"] == 0

    shipped = validate_success(
        api.ship_lot_allocation(
            line["id"], f.ship_payload(shipped_at="2026-08-03T14:00:00Z"), u.SALES_MANAGER
        ),
        200,
    )
    a.assert_status(shipped, "status", "SHIPPED")
    a.assert_instant(shipped["shipped_at"], "2026-08-03T14:00:00Z", "allocation.shipped_at")

    delivered = x.read_lot(api, lot["id"])
    a.assert_status(delivered, "cold_chain_status", "SHIPPED")
    a.assert_status(delivered, "disposition_status", "DELIVERED")

    filled = x.read_commitment(api, commitment["id"])
    a.assert_commitment_exposure(filled, 80.00, 80.00)
    a.assert_ratio(filled["fill_pct"], 1.0000, "commitment.fill_pct")
    a.assert_pounds(filled["open_lbs"], 0.00, "commitment.open_lbs")
    a.assert_status(filled, "status", "OPEN")
    a.assert_status(filled, "fill_status", "PENDING")


def _block_with_one_live_window(api, name):
    """A block carrying one live `PLANNED` window over 06:00 to 14:00."""
    block = x.register_block(
        api,
        name=name,
        variety="STRAWBERRY",
        acres=14.00,
        planting_year=2020,
        irrigation_source_code="WELL-15",
    )
    crew = x.recruit_crew(api, name="CREW-" + name, planned_head_count=1)
    window = x.plan_window(
        api,
        block["id"],
        crew["id"],
        start_at="2026-08-03T06:00:00Z",
        end_at="2026-08-03T14:00:00Z",
        forecast_brix=8.5,
        planned_volume_lbs=150.00,
        piece_rate_cents_per_clamshell=45,
        clamshell_net_weight_lbs=1.00,
    )
    a.assert_status(window, "status", "PLANNED")
    return block, crew, window


def test_a_second_window_starting_where_the_first_ended_is_a_reentry_conflict(api):
    """
    Back-to-back picking on one block is refused: the candidate starts exactly
    at the live window's `end_at`, and the twelve-hour buffer makes that
    adjacency a conflict.

    PRD 3.3: "The candidate conflicts with an existing window when the candidate's `start_at` is strictly earlier than that window's `end_at` advanced by twelve hours **and** the candidate's `end_at` advanced by twelve hours is strictly later than that window's `start_at`."

    PRD 3.3: "Instants are compared at second resolution, and the buffer makes adjacency a conflict: a candidate that starts exactly at another window's `end_at` is rejected, and so is one that starts eleven hours, fifty-nine minutes and fifty-nine seconds after it."

    PRD 2.7 rule 57: "A candidate harvest window clears the twelve-hour block re-entry separation against every live window of the same block, otherwise `ERR_BLOCK_REENTRY_CONFLICT`; this is checked both when the window is planned and again when it is confirmed."

    Design: Difficulty/resource_temporal_overlap/block_reentry_buffer_rejects_adjacent_harvest_window
    """
    block, crew, live = _block_with_one_live_window(api, "BLK-RT1")

    refused = api.create_harvest_window(
        f.harvest_window_payload(
            block["id"],
            crew["id"],
            start_at="2026-08-03T14:00:00Z",
            end_at="2026-08-03T20:00:00Z",
            forecast_brix=8.5,
            planned_volume_lbs=100.00,
            piece_rate_cents_per_clamshell=45,
            clamshell_net_weight_lbs=1.00,
        ),
        u.HARVEST_MANAGER,
    )
    validate_error(refused, e.ERR_BLOCK_REENTRY_CONFLICT, 409)

    rows, meta = x.list_windows(api, block_id=block["id"])
    a.assert_page_meta(meta, expected_total=1)
    assert a.ids_of(rows) == [live["id"]]
    untouched = x.read_window(api, live["id"])
    a.assert_status(untouched, "status", "PLANNED")
    assert untouched["version"] == live["version"]


def test_a_window_starting_exactly_twelve_hours_later_is_admitted(api):
    """
    Move the same candidate to precisely twelve hours after the live window's
    end and the separation is satisfied — the comparison is strict, so the
    buffer's own edge is legal.

    PRD 3.3: "A picked block needs a worker re-entry and spray interval before it is walked again, and that interval is twelve hours."

    PRD 3.3: "The candidate conflicts with an existing window when the candidate's `start_at` is strictly earlier than that window's `end_at` advanced by twelve hours **and** the candidate's `end_at` advanced by twelve hours is strictly later than that window's `start_at`."

    PRD 3.3: "On creation the window derives `window_hours`, the elapsed time from `start_at` to `end_at` expressed in hours and rounded half up to two decimals, and starts at `PLANNED` with `harvested_clamshells` 0, `packed_lbs` 0.00, no `effective_pick_rate_lbs_per_hour`, no `required_picker_count`, and neither `suspended_reason_code` nor `cancel_reason_code` set."

    Design: Difficulty/resource_temporal_overlap/block_reentry_buffer_rejects_adjacent_harvest_window
    """
    block, crew, live = _block_with_one_live_window(api, "BLK-RT1B")

    admitted = validate_success(
        api.create_harvest_window(
            f.harvest_window_payload(
                block["id"],
                crew["id"],
                start_at="2026-08-04T02:00:00Z",
                end_at="2026-08-04T10:00:00Z",
                forecast_brix=8.5,
                planned_volume_lbs=100.00,
                piece_rate_cents_per_clamshell=45,
                clamshell_net_weight_lbs=1.00,
            ),
            u.HARVEST_MANAGER,
        ),
        201,
    )
    a.assert_status(admitted, "status", "PLANNED")
    a.assert_hours(admitted["window_hours"], 8.00, "window.window_hours")
    assert admitted["harvested_clamshells"] == 0
    a.assert_pounds(admitted["packed_lbs"], 0.00, "window.packed_lbs")
    a.assert_unset(admitted, "required_picker_count", "planned window")
    assert admitted["version"] == 1

    rows, meta = x.list_windows(api, block_id=block["id"])
    a.assert_page_meta(meta, expected_total=2)
    assert set(a.ids_of(rows)) == {live["id"], admitted["id"]}
    a.assert_status(x.read_window(api, live["id"]), "status", "PLANNED")


def _tunnel_holding_every_slot(api, name):
    """
    A three-slot tunnel entirely booked by one `COOLING` lot over 09:00 to
    13:00, with a second lot packed at 06:00 still waiting outside.

    Returns the tunnel, the occupying lot and the waiting lot.
    """
    block = x.register_block(
        api,
        name=name,
        variety="STRAWBERRY",
        acres=9.50,
        planting_year=2021,
        irrigation_source_code="WELL-16",
    )
    crew = x.recruit_crew(api, name="CREW-" + name, planned_head_count=1)
    window = x.plan_window(
        api,
        block["id"],
        crew["id"],
        start_at="2026-08-03T05:00:00Z",
        end_at="2026-08-03T18:00:00Z",
        forecast_brix=8.5,
        planned_volume_lbs=150.00,
        piece_rate_cents_per_clamshell=45,
        clamshell_net_weight_lbs=1.00,
    )
    tunnel = x.register_tunnel(api, name="TUN-" + name, slot_capacity=3, target_pulp_temp_f=34.0)
    occupant = x.pack_lot(
        api,
        window["id"],
        block["id"],
        variety="STRAWBERRY",
        grade="A",
        clamshell_count=60,
        clamshell_net_weight_lbs=1.00,
        pick_date="2026-08-03",
        pack_completed_at="2026-08-03T06:00:00Z",
        field_pulp_temp_f=62.0,
    )
    waiting = x.pack_lot(
        api,
        window["id"],
        block["id"],
        variety="STRAWBERRY",
        grade="A",
        clamshell_count=40,
        clamshell_net_weight_lbs=1.00,
        pick_date="2026-08-03",
        pack_completed_at="2026-08-03T06:00:00Z",
        field_pulp_temp_f=62.0,
    )
    booked = x.start_cooling(
        api,
        occupant["id"],
        tunnel["id"],
        cool_start_at="2026-08-03T09:00:00Z",
        planned_cool_end_at="2026-08-03T13:00:00Z",
        entry_pulp_temp_f=56.0,
        pallet_slots=3,
    )
    assert booked["forecast_shelf_life_days"] == 6
    assert x.read_tunnel(api, tunnel["id"])["committed_slots"] == 3
    return tunnel, occupant, waiting


def test_a_run_overlapping_a_full_tunnel_by_one_hour_is_refused(api):
    """
    Twelve o'clock still falls inside the occupant's half-open booking, so one
    more pallet slot would put the aggregate at four against a capacity of
    three. Nothing is written and the tunnel keeps its three committed slots.

    PRD 3.6: "Occupancy is checked as an aggregate over a half-open interval. The candidate's booked interval runs from `cool_start_at` up to but **not including** `planned_cool_end_at`."

    PRD 3.6: "For every instant the candidate interval touches, the sum of the overlapping lots' `pallet_slots` plus the candidate's `pallet_slots` must not exceed the tunnel's `slot_capacity`; the practical test is to take, over the candidate's interval, the maximum concurrent committed slots and check that headroom remains."

    Design: Difficulty/resource_temporal_overlap/tunnel_slot_capacity_aggregate_over_half_open_intervals_admits_adjacency
    """
    tunnel, _, waiting = _tunnel_holding_every_slot(api, "BLK-RT2")
    guard = x.tunnel_version(api, tunnel["id"])
    assert guard == 2

    refused = api.start_cooling(
        waiting["id"],
        f.start_cooling_payload(
            tunnel["id"],
            guard,
            cool_start_at="2026-08-03T12:00:00Z",
            planned_cool_end_at="2026-08-03T16:00:00Z",
            entry_pulp_temp_f=56.0,
            pallet_slots=1,
        ),
        u.PACKHOUSE_OPERATOR,
    )
    validate_error(refused, e.ERR_TUNNEL_CAPACITY_EXCEEDED, 422)

    outside = x.read_lot(api, waiting["id"])
    a.assert_status(outside, "cold_chain_status", "PACKED")
    a.assert_unset(outside, "cooling_tunnel_id", "refused lot")
    a.assert_unset(outside, "cool_start_at", "refused lot")
    a.assert_unset(outside, "forecast_shelf_life_days", "refused lot")
    assert outside["version"] == waiting["version"]

    register = x.read_tunnel(api, tunnel["id"])
    assert register["committed_slots"] == 3
    assert register["version"] == guard


def test_a_run_starting_exactly_at_the_occupant_s_planned_end_is_admitted(api):
    """
    Shift the same request one hour later, onto the occupant's own
    `planned_cool_end_at`, and the half-open interval no longer overlaps: the
    run is admitted on the unchanged version guard and the counter simply adds
    the slot.

    PRD 3.6: "Because the interval is half-open, **back-to-back runs are legal**: a lot booking from an instant exactly equal to another lot's `planned_cool_end_at` does not overlap it and needs no headroom against it."

    PRD 3.6: "This is deliberately the opposite of the block re-entry rule of §3.3, which adds a twelve-hour buffer and therefore treats adjacency as a conflict; the two must not be implemented with a shared comparison."

    PRD 3.6: "Starting a run stores the cooling fields, computes `field_delay_hours` as the elapsed hours from `pack_completed_at` to `cool_start_at` rounded half up to two decimals, stamps `forecast_shelf_life_days` from the forecast variant of the shelf-life calculation, increments the tunnel's `committed_slots` by `pallet_slots` and the tunnel's `version` by 1, moves the lot `PACKED → COOLING`, and increments the lot's `version` by 1."

    Design: Difficulty/resource_temporal_overlap/tunnel_slot_capacity_aggregate_over_half_open_intervals_admits_adjacency
    """
    tunnel, occupant, waiting = _tunnel_holding_every_slot(api, "BLK-RT2B")
    guard = x.tunnel_version(api, tunnel["id"])

    validate_error(
        api.start_cooling(
            waiting["id"],
            f.start_cooling_payload(
                tunnel["id"],
                guard,
                cool_start_at="2026-08-03T12:00:00Z",
                planned_cool_end_at="2026-08-03T16:00:00Z",
                entry_pulp_temp_f=56.0,
                pallet_slots=1,
            ),
            u.PACKHOUSE_OPERATOR,
        ),
        e.ERR_TUNNEL_CAPACITY_EXCEEDED,
        422,
    )

    admitted = validate_success(
        api.start_cooling(
            waiting["id"],
            f.start_cooling_payload(
                tunnel["id"],
                guard,
                cool_start_at="2026-08-03T13:00:00Z",
                planned_cool_end_at="2026-08-03T17:00:00Z",
                entry_pulp_temp_f=56.0,
                pallet_slots=1,
            ),
            u.PACKHOUSE_OPERATOR,
        ),
        200,
    )
    a.assert_status(admitted, "cold_chain_status", "COOLING")
    assert admitted["cooling_tunnel_id"] == tunnel["id"]
    a.assert_hours(admitted["field_delay_hours"], 7.00, "lot.field_delay_hours")
    assert admitted["forecast_shelf_life_days"] == 2
    a.assert_unset(admitted, "verified_shelf_life_days", "cooling lot")

    register = x.read_tunnel(api, tunnel["id"])
    assert register["committed_slots"] == 4
    assert register["version"] == guard + 1

    assert x.read_lot(api, occupant["id"])["forecast_shelf_life_days"] == 6
