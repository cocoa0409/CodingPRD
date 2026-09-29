"""
The arithmetic of the season: the rolling water geometric mean, the staffing
estimate, the piece-rate and guarantee ladder, lifetime productivity, tunnel
occupancy, shelf-life decay, traceability sequencing and the exposure figures a
buyer program carries.

Each test pins one calculation of PRD sections 3.1 through 3.7 at a boundary or
across a filtered input set, using the literal figures the PRD's own rules
produce.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as x
from test_helpers import test_users as u


def test_a_411_mpn_sample_fails_and_auto_quarantines_the_block(api):
    """
    The single-sample maximum is compared strictly, so 411 MPN fails and holds
    the block while a following 410 MPN sample is clean — yet the hold the
    exceedance raised keeps the posture quarantined.

    PRD 3.1: "It also stores two derived facts about itself: `single_sample_exceedance`, true exactly when this sample's `generic_ecoli_mpn` is strictly greater than the single-sample maximum of 410 MPN per 100 mL, and `resulting_water_status`, a snapshot of the parent block's `water_status` as it stood immediately after this sample was folded in."

    PRD 3.1: "There is a deliberate interlock here: a `FAILED` water status *also* sets `manual_quarantine_active` to true inside the very same sample-recording call, with `quarantine_reason_code` set to `SINGLE_SAMPLE_EXCEEDANCE` and `quarantined_by_user_id` set to the recording officer."

    Design: Corner/calculations/single_sample_exceedance_at_411_forces_failed_and_quarantine
    """
    block = x.register_block(
        api,
        name="BLK-C1",
        variety="STRAWBERRY",
        acres=8.00,
        planting_year=2021,
        irrigation_source_code="CANAL-C1",
    )

    first = x.record_water_sample(
        api, block["id"], sample_date="2026-07-10", generic_ecoli_mpn=411
    )
    assert first["single_sample_exceedance"] is True
    a.assert_status(first, "resulting_water_status", "FAILED")

    second = x.record_water_sample(
        api, block["id"], sample_date="2026-07-11", generic_ecoli_mpn=410
    )
    assert second["single_sample_exceedance"] is False
    a.assert_status(second, "resulting_water_status", "PROVISIONAL")

    stored = x.read_block(api, block["id"])
    assert stored["water_sample_count"] == 2
    a.assert_geomean(stored["water_geomean_mpn"], 410.5)
    assert stored["last_sample_date"] == "2026-07-11"
    a.assert_status(stored, "water_status", "PROVISIONAL")
    assert stored["manual_quarantine_active"] is True
    a.assert_status(stored, "quarantine_reason_code", "SINGLE_SAMPLE_EXCEEDANCE")
    assert stored["quarantined_by_user_id"] == u.FSO_1
    a.assert_status(stored, "food_safety_posture", "QUARANTINED")


def test_a_sixth_sample_pushes_the_oldest_out_of_the_rolling_window(api):
    """
    Only the trailing five samples count, so a sixth clean reading evicts the
    400 MPN outlier and the block turns compliant with the count still at five.

    PRD 3.1: "The block's samples are ordered by `sample_date` ascending and, within a shared date, by `created_at` ascending; only the **last five** rows of that ordering participate."

    PRD 3.1: "`water_geomean_mpn` is the geometric mean of the `generic_ecoli_mpn` values in the window: the product of those values, raised to the power of one divided by the count, then rounded half up to one decimal place."

    Design: Corner/calculations/water_rolling_window_drops_the_oldest_sample_beyond_five
    """
    block = x.register_block(
        api,
        name="BLK-C2",
        variety="STRAWBERRY",
        acres=8.00,
        planting_year=2021,
        irrigation_source_code="CANAL-C2",
    )
    x.water_series(
        api,
        block["id"],
        [
            ("2026-07-01", 400),
            ("2026-07-02", 100),
            ("2026-07-03", 100),
            ("2026-07-04", 100),
            ("2026-07-05", 100),
        ],
    )

    before = x.read_block(api, block["id"])
    assert before["water_sample_count"] == 5
    a.assert_geomean(before["water_geomean_mpn"], 132.0)
    a.assert_status(before, "water_status", "NON_COMPLIANT")
    a.assert_status(before, "food_safety_posture", "RESTRICTED")

    sixth = x.record_water_sample(
        api, block["id"], sample_date="2026-07-06", generic_ecoli_mpn=100
    )
    a.assert_status(sixth, "resulting_water_status", "COMPLIANT")
    assert sixth["single_sample_exceedance"] is False

    after = x.read_block(api, block["id"])
    assert after["water_sample_count"] == 5
    a.assert_geomean(after["water_geomean_mpn"], 100.0)
    a.assert_status(after, "water_status", "COMPLIANT")
    a.assert_status(after, "food_safety_posture", "CLEARED")
    assert after["last_sample_date"] == "2026-07-06"
    assert after["manual_quarantine_active"] is False


def test_one_tenth_of_a_brix_point_is_a_whole_extra_picker(api):
    """
    The ripeness multiplier turns on an inclusive comparison against the target
    brix, so 12.0 earns the 1.10 uplift on a blueberry block and 11.9 does not —
    two pickers against three for the identical volume.

    PRD 3.3: "That base is then adjusted for maturity: if the window's `forecast_brix` is at least the variety's *target* brix — 9.0 for `STRAWBERRY`, 12.0 for `BLUEBERRY`, 10.0 for `RASPBERRY` and 10.5 for `BLACKBERRY` — the base is multiplied by 1.10, because riper fruit picks faster; otherwise it is multiplied by 1.00 and left alone."

    PRD 3.3: "`required_picker_count` is then `planned_volume_lbs` divided by that capacity, rounded **up** to the next whole picker, and finally raised to a floor of 1 so that a window always needs at least one picker."

    Design: Corner/calculations/window_crew_requirement_ripe_multiplier_at_exact_brix_target
    """
    ripe_block = x.register_block(
        api,
        name="BLK-C4R",
        variety="BLUEBERRY",
        acres=8.00,
        planting_year=2021,
        irrigation_source_code="WELL-C4",
    )
    unripe_block = x.register_block(
        api,
        name="BLK-C4S",
        variety="BLUEBERRY",
        acres=8.00,
        planting_year=2021,
        irrigation_source_code="WELL-C4",
    )
    crew = x.recruit_crew(api, name="CREW-C4", planned_head_count=3)

    ripe_window = x.plan_window(
        api,
        ripe_block["id"],
        crew["id"],
        start_at="2026-08-03T06:00:00Z",
        end_at="2026-08-03T13:30:00Z",
        forecast_brix=12.0,
        planned_volume_lbs=280.00,
        piece_rate_cents_per_clamshell=60,
        clamshell_net_weight_lbs=1.00,
    )
    unripe_window = x.plan_window(
        api,
        unripe_block["id"],
        crew["id"],
        start_at="2026-08-03T06:00:00Z",
        end_at="2026-08-03T13:30:00Z",
        forecast_brix=11.9,
        planned_volume_lbs=280.00,
        piece_rate_cents_per_clamshell=60,
        clamshell_net_weight_lbs=1.00,
    )

    ripe = x.confirm_window(api, ripe_window["id"])
    unripe = x.confirm_window(api, unripe_window["id"])

    a.assert_status(ripe, "status", "CONFIRMED")
    a.assert_hours(ripe["window_hours"], 7.50, "ripe.window_hours")
    a.assert_rate(
        ripe["effective_pick_rate_lbs_per_hour"], 19.80, "ripe.effective_pick_rate"
    )
    assert ripe["required_picker_count"] == 2

    a.assert_status(unripe, "status", "CONFIRMED")
    a.assert_hours(unripe["window_hours"], 7.50, "unripe.window_hours")
    a.assert_rate(
        unripe["effective_pick_rate_lbs_per_hour"], 18.00, "unripe.effective_pick_rate"
    )
    assert unripe["required_picker_count"] == 3


def test_a_cull_rate_exactly_at_the_ceiling_still_meets_standard(api):
    """
    Eight culls in a hundred is exactly the tolerated rate and keeps the full
    piece rate; nine culls derate the rate by a fifth and drop the piece
    earnings under the hourly floor, where the make-up catches them.

    PRD 3.4: "`quality_flag` becomes `MEETS_STANDARD` when `cull_rate` is less than or equal to the maximum tolerated cull rate of 0.08 — eight percent of the pack — and `BELOW_STANDARD` otherwise."

    PRD 3.4: "When it is `BELOW_STANDARD`, the window rate is derated by twenty percent — that is, multiplied by the remaining eighty percent — and rounded half up to a whole cent."

    Design: Corner/calculations/session_cull_rate_at_exactly_the_ceiling_meets_standard
    """
    block = x.register_block(
        api,
        name="BLK-C5",
        variety="STRAWBERRY",
        acres=8.00,
        planting_year=2021,
        irrigation_source_code="WELL-C5",
    )
    x.record_water_sample(
        api, block["id"], sample_date="2026-07-20", generic_ecoli_mpn=40
    )
    crew, pickers = x.certified_crew(
        api, picker_count=2, planned_head_count=2, name="CREW-C5"
    )
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
    at_ceiling = x.open_session(
        api, window["id"], pickers[0]["id"], work_date="2026-08-03"
    )
    over_ceiling = x.open_session(
        api, window["id"], pickers[1]["id"], work_date="2026-08-03"
    )

    priced_at = x.tally_session(
        api,
        at_ceiling["id"],
        hours_worked=2.00,
        clamshells_filled=100,
        culled_clamshells=8,
    )
    priced_over = x.tally_session(
        api,
        over_ceiling["id"],
        hours_worked=2.00,
        clamshells_filled=100,
        culled_clamshells=9,
    )

    a.assert_ratio(priced_at["cull_rate"], 0.0800, "at.cull_rate")
    a.assert_status(priced_at, "quality_flag", "MEETS_STANDARD")
    a.assert_cents(priced_at["effective_piece_rate_cents"], 45, "at.effective_rate")
    a.assert_cents(priced_at["piece_cents"], 4140, "at.piece_cents")
    a.assert_cents(priced_at["guarantee_floor_cents"], 3300, "at.guarantee_floor_cents")
    a.assert_cents(priced_at["makeup_cents"], 0, "at.makeup_cents")
    a.assert_cents(priced_at["gross_cents"], 4140, "at.gross_cents")
    a.assert_cents(priced_at["net_cents"], 4140, "at.net_cents")
    a.assert_cents(priced_at["housing_deduction_cents"], 0, "at.housing_deduction_cents")

    a.assert_ratio(priced_over["cull_rate"], 0.0900, "over.cull_rate")
    a.assert_status(priced_over, "quality_flag", "BELOW_STANDARD")
    a.assert_cents(priced_over["effective_piece_rate_cents"], 36, "over.effective_rate")
    a.assert_cents(priced_over["piece_cents"], 3276, "over.piece_cents")
    a.assert_cents(
        priced_over["guarantee_floor_cents"], 3300, "over.guarantee_floor_cents"
    )
    a.assert_cents(priced_over["makeup_cents"], 24, "over.makeup_cents")
    a.assert_cents(priced_over["gross_cents"], 3300, "over.gross_cents")
    a.assert_cents(priced_over["net_cents"], 3300, "over.net_cents")
    a.assert_cents(
        priced_over["housing_deduction_cents"], 0, "over.housing_deduction_cents"
    )


def test_lifetime_productivity_weighs_each_session_by_its_own_pack_format(api):
    """
    Paid pounds are not paid clamshells: a day at one pound per clamshell and a
    day at half a pound combine to 32.00 lbs over 5.00 hours, and the culled
    clamshells never count.

    PRD 3.4: "`total_clamshells_lifetime` is the sum, over those sessions, of `clamshells_filled` less `culled_clamshells` — the paid, saleable clamshells only."

    PRD 3.4: "`avg_lbs_per_hour` divides paid pounds by paid hours: paid pounds are the sum, over those sessions, of the saleable clamshell count multiplied by the `clamshell_net_weight_lbs` of *that session's own window*, and the quotient is rounded half up to two decimals; when `total_hours_lifetime` is zero the average is exactly 0.00 rather than undefined."

    Design: Corner/calculations/picker_productivity_full_recompute_across_two_pack_formats
    """
    block_a = x.register_block(
        api,
        name="BLK-C6A",
        variety="STRAWBERRY",
        acres=8.00,
        planting_year=2021,
        irrigation_source_code="WELL-C6",
    )
    block_b = x.register_block(
        api,
        name="BLK-C6B",
        variety="STRAWBERRY",
        acres=8.00,
        planting_year=2021,
        irrigation_source_code="WELL-C6",
    )
    for block_id in (block_a["id"], block_b["id"]):
        x.record_water_sample(
            api, block_id, sample_date="2026-07-20", generic_ecoli_mpn=40
        )
    crew, pickers = x.certified_crew(api, picker_count=1, name="CREW-C6")
    picker = pickers[0]

    window_a = x.opened_window(
        api,
        block_a["id"],
        crew["id"],
        start_at="2026-08-03T06:00:00Z",
        end_at="2026-08-03T14:00:00Z",
        piece_rate_cents_per_clamshell=45,
        clamshell_net_weight_lbs=1.00,
    )
    window_b = x.opened_window(
        api,
        block_b["id"],
        crew["id"],
        start_at="2026-08-04T06:00:00Z",
        end_at="2026-08-04T14:00:00Z",
        piece_rate_cents_per_clamshell=50,
        clamshell_net_weight_lbs=0.50,
    )

    x.approved_session(
        api,
        window_a["id"],
        picker["id"],
        work_date="2026-08-03",
        hours_worked=3.00,
        clamshells_filled=20,
        culled_clamshells=0,
    )
    session_b = x.tallied_session(
        api,
        window_b["id"],
        picker["id"],
        work_date="2026-08-04",
        hours_worked=2.00,
        clamshells_filled=30,
        culled_clamshells=6,
    )

    response = api.approve_pick_session(session_b["id"], u.PAYROLL_CLERK)
    approved_b = validate_success(response, 200)

    a.assert_ratio(approved_b["cull_rate"], 0.2000, "session_b.cull_rate")
    a.assert_status(approved_b, "quality_flag", "BELOW_STANDARD")
    a.assert_cents(
        approved_b["effective_piece_rate_cents"], 40, "session_b.effective_rate"
    )
    a.assert_cents(approved_b["piece_cents"], 960, "session_b.piece_cents")
    a.assert_cents(
        approved_b["guarantee_floor_cents"], 3300, "session_b.guarantee_floor_cents"
    )
    a.assert_cents(approved_b["makeup_cents"], 2340, "session_b.makeup_cents")
    a.assert_cents(approved_b["net_cents"], 3300, "session_b.net_cents")

    stored_picker = x.read_picker(api, picker["id"])
    assert stored_picker["total_clamshells_lifetime"] == 44
    a.assert_hours(
        stored_picker["total_hours_lifetime"], 5.00, "picker.total_hours_lifetime"
    )
    a.assert_rate(stored_picker["avg_lbs_per_hour"], 6.40, "picker.avg_lbs_per_hour")

    stored_crew = x.read_crew(api, crew["id"])
    a.assert_cents(stored_crew["accrued_wage_cents"], 8250, "crew.accrued_wage_cents")


def test_completed_cooling_frees_the_slot_for_an_overlapping_interval(api):
    """
    Occupancy counts only lots that are still cooling, so a run that finished
    early leaves a single-slot tunnel free for a request whose stored interval
    still overlaps it.

    PRD 3.6: "Only lots currently in `cold_chain_status` `COOLING` in that tunnel are counted; lots that have completed cooling, been rejected or shipped occupy nothing."

    PRD 3.6: "It computes `cool_hours` as the elapsed hours from `cool_start_at` to `cool_complete_at` rounded half up to two decimals, stamps `verified_shelf_life_days` and `shelf_life_expires_on` from the verified variant, releases the slots by decrementing the tunnel's `committed_slots` by the lot's `pallet_slots` and incrementing the tunnel's `version` by 1, moves the lot `COOLING → COOLED`, and increments the lot's `version` by 1."

    Design: Corner/calculations/tunnel_occupancy_frees_slots_once_the_occupant_completes_cooling
    """
    block = x.register_block(
        api,
        name="BLK-C7",
        variety="STRAWBERRY",
        acres=8.00,
        planting_year=2021,
        irrigation_source_code="WELL-C7",
    )
    crew = x.recruit_crew(api, name="CREW-C7")
    window = x.plan_window(
        api,
        block["id"],
        crew["id"],
        start_at="2026-08-03T06:00:00Z",
        end_at="2026-08-03T18:00:00Z",
    )
    tunnel = x.register_tunnel(
        api, name="TUN-C7", slot_capacity=1, target_pulp_temp_f=34.0
    )
    first = x.pack_lot(
        api,
        window["id"],
        block["id"],
        variety="STRAWBERRY",
        grade="A",
        clamshell_count=40,
        clamshell_net_weight_lbs=1.00,
        pick_date="2026-08-03",
        pack_completed_at="2026-08-03T08:00:00Z",
        field_pulp_temp_f=68.0,
    )
    second = x.pack_lot(
        api,
        window["id"],
        block["id"],
        variety="STRAWBERRY",
        grade="B",
        clamshell_count=30,
        clamshell_net_weight_lbs=1.00,
        pick_date="2026-08-03",
        pack_completed_at="2026-08-03T09:30:00Z",
        field_pulp_temp_f=68.0,
    )
    x.start_cooling(
        api,
        first["id"],
        tunnel["id"],
        expected_version=tunnel["version"],
        cool_start_at="2026-08-03T09:00:00Z",
        planned_cool_end_at="2026-08-03T13:00:00Z",
        entry_pulp_temp_f=60.0,
        pallet_slots=1,
    )
    cooled_first = x.complete_cooling(
        api,
        first["id"],
        cool_complete_at="2026-08-03T12:00:00Z",
        exit_pulp_temp_f=34.0,
    )

    response = api.start_cooling(
        second["id"],
        f.start_cooling_payload(
            tunnel["id"],
            x.tunnel_version(api, tunnel["id"]),
            cool_start_at="2026-08-03T10:00:00Z",
            planned_cool_end_at="2026-08-03T14:00:00Z",
            entry_pulp_temp_f=60.0,
            pallet_slots=1,
        ),
        u.PACKHOUSE_OPERATOR,
    )
    cooling_second = validate_success(response, 200)

    a.assert_status(cooled_first, "cold_chain_status", "COOLED")
    a.assert_hours(cooled_first["cool_hours"], 3.00, "first.cool_hours")
    a.assert_hours(cooled_first["field_delay_hours"], 1.00, "first.field_delay_hours")
    assert cooled_first["verified_shelf_life_days"] == 7
    assert cooled_first["shelf_life_expires_on"] == "2026-08-10"

    a.assert_status(cooling_second, "cold_chain_status", "COOLING")
    assert cooling_second["pallet_slots"] == 1
    assert cooling_second["forecast_shelf_life_days"] == 6

    stored_tunnel = x.read_tunnel(api, tunnel["id"])
    assert stored_tunnel["committed_slots"] == 1
    assert stored_tunnel["version"] == 4


def test_a_cancelled_window_stops_holding_its_block_for_re_entry(api):
    """
    The twelve-hour re-entry buffer is measured only against live windows, so a
    cancelled morning window lets an afternoon window start at the very instant
    the cancelled one would have ended.

    PRD 3.3: "Windows on other blocks never conflict, and windows that are `CLOSED` or `CANCELLED` are ignored entirely, which is what makes cancelling a window free its slot immediately."

    PRD 3.3: "The candidate conflicts with an existing window when the candidate's `start_at` is strictly earlier than that window's `end_at` advanced by twelve hours **and** the candidate's `end_at` advanced by twelve hours is strictly later than that window's `start_at`."

    Design: Corner/calculations/block_separation_ignores_cancelled_windows
    """
    block = x.register_block(
        api,
        name="BLK-C8",
        variety="RASPBERRY",
        acres=8.00,
        planting_year=2021,
        irrigation_source_code="WELL-C8",
    )
    crew = x.recruit_crew(api, name="CREW-C8")
    morning = x.plan_window(
        api,
        block["id"],
        crew["id"],
        start_at="2026-08-03T06:00:00Z",
        end_at="2026-08-03T14:00:00Z",
        forecast_brix=9.0,
        planned_volume_lbs=100.00,
        piece_rate_cents_per_clamshell=70,
        clamshell_net_weight_lbs=0.50,
    )
    x.cancel_window(api, morning["id"], reason_code="WEATHER")

    response = api.create_harvest_window(
        f.harvest_window_payload(
            block["id"],
            crew["id"],
            start_at="2026-08-03T14:00:00Z",
            end_at="2026-08-03T20:00:00Z",
            forecast_brix=9.0,
            planned_volume_lbs=100.00,
            piece_rate_cents_per_clamshell=70,
            clamshell_net_weight_lbs=0.50,
        ),
        u.HARVEST_MANAGER,
    )
    afternoon = validate_success(response, 201)

    a.assert_status(afternoon, "status", "PLANNED")
    assert afternoon["block_id"] == block["id"]
    a.assert_hours(afternoon["window_hours"], 6.00, "afternoon.window_hours")

    stored_morning = x.read_window(api, morning["id"])
    a.assert_status(stored_morning, "status", "CANCELLED")
    a.assert_status(stored_morning, "cancel_reason_code", "WEATHER")


def test_the_exit_temperature_penalty_only_counts_whole_two_degree_steps(api):
    """
    A tenth of a degree short of the second step costs nothing; landing exactly
    on 36.0 °F costs a whole day of shelf life and pulls the expiry date back.

    PRD 3.6: "The exit-temperature penalty is charged only for **complete** two-degree steps: the amount by which the exit pulp temperature exceeds the 34.0 °F target, floored at zero, divided by 2.0 and rounded **down** to a whole day."

    PRD 3.6: "`shelf_life_expires_on` is then the calendar date of `cool_complete_at` advanced by `verified_shelf_life_days` days."

    Design: Corner/calculations/lot_shelf_life_temp_penalty_uses_full_two_degree_steps
    """
    block = x.register_block(
        api,
        name="BLK-C9",
        variety="STRAWBERRY",
        acres=8.00,
        planting_year=2021,
        irrigation_source_code="WELL-C9",
    )
    crew = x.recruit_crew(api, name="CREW-C9")
    window = x.plan_window(
        api,
        block["id"],
        crew["id"],
        start_at="2026-08-03T06:00:00Z",
        end_at="2026-08-03T18:00:00Z",
    )
    tunnel = x.register_tunnel(
        api, name="TUN-C9", slot_capacity=2, target_pulp_temp_f=34.0
    )

    lots = x.lots_on_block(
        api,
        window["id"],
        block["id"],
        [
            {
                "variety": "STRAWBERRY",
                "grade": "A",
                "clamshell_count": 20,
                "clamshell_net_weight_lbs": 1.00,
                "pick_date": "2026-08-03",
                "pack_completed_at": "2026-08-03T08:00:00Z",
                "field_pulp_temp_f": 66.0,
            },
            {
                "variety": "STRAWBERRY",
                "grade": "A",
                "clamshell_count": 20,
                "clamshell_net_weight_lbs": 1.00,
                "pick_date": "2026-08-03",
                "pack_completed_at": "2026-08-03T08:00:00Z",
                "field_pulp_temp_f": 66.0,
            },
        ],
    )
    just_under, on_the_step = lots

    cooling_under = x.start_cooling(
        api,
        just_under["id"],
        tunnel["id"],
        expected_version=tunnel["version"],
        cool_start_at="2026-08-03T10:00:00Z",
        planned_cool_end_at="2026-08-03T14:00:00Z",
        entry_pulp_temp_f=60.0,
        pallet_slots=1,
    )
    cooling_step = x.start_cooling(
        api,
        on_the_step["id"],
        tunnel["id"],
        expected_version=x.tunnel_version(api, tunnel["id"]),
        cool_start_at="2026-08-03T10:00:00Z",
        planned_cool_end_at="2026-08-03T14:00:00Z",
        entry_pulp_temp_f=60.0,
        pallet_slots=1,
    )
    assert cooling_under["forecast_shelf_life_days"] == 7
    assert cooling_step["forecast_shelf_life_days"] == 7

    verified_under = x.complete_cooling(
        api,
        just_under["id"],
        cool_complete_at="2026-08-03T14:00:00Z",
        exit_pulp_temp_f=35.9,
    )
    verified_step = x.complete_cooling(
        api,
        on_the_step["id"],
        cool_complete_at="2026-08-03T14:00:00Z",
        exit_pulp_temp_f=36.0,
    )

    a.assert_hours(verified_under["field_delay_hours"], 2.00, "under.field_delay_hours")
    a.assert_hours(verified_under["cool_hours"], 4.00, "under.cool_hours")
    assert verified_under["verified_shelf_life_days"] == 7
    assert verified_under["shelf_life_expires_on"] == "2026-08-10"

    a.assert_hours(verified_step["field_delay_hours"], 2.00, "step.field_delay_hours")
    a.assert_hours(verified_step["cool_hours"], 4.00, "step.cool_hours")
    assert verified_step["verified_shelf_life_days"] == 6
    assert verified_step["shelf_life_expires_on"] == "2026-08-09"

    stored_tunnel = x.read_tunnel(api, tunnel["id"])
    assert stored_tunnel["committed_slots"] == 0


def test_a_program_that_shipped_nothing_defaults_on_its_whole_volume(api):
    """
    Zero shipped pounds routes settlement into the defaulted branch, where the
    fifteen percent penalty is charged against the entire contracted volume and
    the net settlement is wholly negative.

    PRD 3.7: "The third condition decides which branch is taken rather than blocking: `shipped_lbs` greater than zero settles `OPEN → SETTLED`, and `shipped_lbs` of exactly zero settles `OPEN → DEFAULTED`."

    PRD 3.7: "`settled_revenue_cents` is 0, `fill_pct` is 0.0000, `fill_status` is `SHORTFALL`, and `shortfall_penalty_cents` is charged against the **entire** contracted volume: `volume_commitment_lbs` multiplied by `price_cents_per_lb` multiplied by the fifteen percent rate, rounded half up."

    Design: Corner/calculations/commitment_with_no_shipped_pounds_defaults_with_fifteen_percent_penalty
    """
    commitment = x.open_commitment(
        api,
        buyer_name="Northgate Produce",
        buyer_user_id="buyer-9",
        variety="STRAWBERRY",
        volume_commitment_lbs=220.00,
        price_cents_per_lb=380,
        shelf_life_guarantee_days=5,
        window_start_date="2026-08-01",
        window_end_date="2026-08-05",
    )
    x.set_clock(api, "2026-08-06T00:00:00Z")

    response = api.settle_buyer_commitment(commitment["id"], u.SALES_MANAGER)
    settled = validate_success(response, 200)

    a.assert_status(settled, "status", "DEFAULTED")
    a.assert_status(settled, "fill_status", "SHORTFALL")
    a.assert_pounds(settled["shipped_lbs"], 0.00, "commitment.shipped_lbs")
    a.assert_pounds(settled["committed_lbs"], 0.00, "commitment.committed_lbs")
    a.assert_ratio(settled["fill_pct"], 0.0000, "commitment.fill_pct")
    a.assert_cents(settled["settled_revenue_cents"], 0, "settled_revenue_cents")
    a.assert_cents(settled["shortfall_penalty_cents"], 12540, "shortfall_penalty_cents")
    a.assert_cents(settled["settled_net_cents"], -12540, "settled_net_cents")
    assert settled["version"] == 2


def test_the_trace_code_sequence_restarts_per_pick_date_and_grade(api):
    """
    Three grade-A lots off one block on one day number 001, 002, 003; the same
    day's grade-B lot starts its own family at 001, and the next pick date
    restarts grade A at 001 again.

    PRD 3.6: "The sequence is one greater than the number of lots that already share the same `block_id`, `pick_date` and `grade`, counted in `created_at` ascending order, so the day's second grade-A lot off the same block is `-002`."

    PRD 3.6: "Its `traceability_code` is composed as the block's `block_name`, the `pick_date` rendered as eight digits in year-month-day order, the `grade`, and a three-digit zero-padded sequence, joined by hyphens — for example `NORTH-FIELD-1-20260801-A-001`."

    Design: Corner/calculations/traceability_code_sequence_increments_within_block_pick_date_and_grade
    """
    block = x.register_block(
        api,
        name="BLK-C11",
        variety="BLACKBERRY",
        acres=8.00,
        planting_year=2021,
        irrigation_source_code="WELL-C11",
    )
    crew = x.recruit_crew(api, name="CREW-C11")
    first_day = x.plan_window(
        api,
        block["id"],
        crew["id"],
        start_at="2026-08-03T06:00:00Z",
        end_at="2026-08-03T18:00:00Z",
        forecast_brix=10.5,
    )
    second_day = x.plan_window(
        api,
        block["id"],
        crew["id"],
        start_at="2026-08-04T06:00:00Z",
        end_at="2026-08-04T18:00:00Z",
        forecast_brix=10.5,
    )

    day_one = x.lots_on_block(
        api,
        first_day["id"],
        block["id"],
        [
            {
                "variety": "BLACKBERRY",
                "grade": "A",
                "clamshell_count": 10,
                "clamshell_net_weight_lbs": 1.00,
                "pick_date": "2026-08-03",
                "pack_completed_at": "2026-08-03T09:00:00Z",
                "field_pulp_temp_f": 66.0,
            },
            {
                "variety": "BLACKBERRY",
                "grade": "A",
                "clamshell_count": 10,
                "clamshell_net_weight_lbs": 1.00,
                "pick_date": "2026-08-03",
                "pack_completed_at": "2026-08-03T10:00:00Z",
                "field_pulp_temp_f": 66.0,
            },
            {
                "variety": "BLACKBERRY",
                "grade": "A",
                "clamshell_count": 10,
                "clamshell_net_weight_lbs": 1.00,
                "pick_date": "2026-08-03",
                "pack_completed_at": "2026-08-03T11:00:00Z",
                "field_pulp_temp_f": 66.0,
            },
            {
                "variety": "BLACKBERRY",
                "grade": "B",
                "clamshell_count": 10,
                "clamshell_net_weight_lbs": 1.00,
                "pick_date": "2026-08-03",
                "pack_completed_at": "2026-08-03T12:00:00Z",
                "field_pulp_temp_f": 66.0,
            },
        ],
    )
    day_two = x.lots_on_block(
        api,
        second_day["id"],
        block["id"],
        [
            {
                "variety": "BLACKBERRY",
                "grade": "A",
                "clamshell_count": 10,
                "clamshell_net_weight_lbs": 1.00,
                "pick_date": "2026-08-04",
                "pack_completed_at": "2026-08-04T09:00:00Z",
                "field_pulp_temp_f": 66.0,
            }
        ],
    )

    assert day_one[0]["traceability_code"] == "BLK-C11-20260803-A-001"
    assert day_one[1]["traceability_code"] == "BLK-C11-20260803-A-002"
    assert day_one[2]["traceability_code"] == "BLK-C11-20260803-A-003"
    assert day_one[3]["traceability_code"] == "BLK-C11-20260803-B-001"
    assert day_two[0]["traceability_code"] == "BLK-C11-20260804-A-001"

    first_lot = x.read_lot(api, day_one[0]["id"])
    a.assert_pounds(first_lot["net_packed_lbs"], 10.00, "lot.net_packed_lbs")
    a.assert_pounds(first_lot["available_lbs"], 10.00, "lot.available_lbs")
    a.assert_pounds(first_lot["allocated_lbs"], 0.00, "lot.allocated_lbs")


def test_reserving_pounds_moves_them_out_of_available_and_out_of_open(api):
    """
    Sixty of a hundred pounds pledged leaves forty available on the lot and
    reduces the program's open pounds by exactly sixty, while nothing is shipped
    yet so the fill percentage stays at zero.

    PRD 3.7: "An accepted allocation is created in status `RESERVED`, moves the lot's `disposition_status` to `RESERVED` if it was `UNCOMMITTED`, recomputes the lot's `allocated_lbs` and `available_lbs`, recomputes the commitment's `committed_lbs`, `open_lbs`, `fill_pct`, coverage and `risk_flag`, and increments the `version` of the lot and the commitment by 1."

    PRD 3.7: "The exposure figures are always recomputed from the surviving allocation rows rather than nudged: `committed_lbs` is the sum of `allocated_lbs` over the commitment's `RESERVED` and `SHIPPED` lines, `shipped_lbs` the sum over the `SHIPPED` lines alone, and `open_lbs` is `volume_commitment_lbs` less `committed_lbs`, floored at 0.00 and carried to two decimals."

    Design: Corner/calculations/allocation_reserve_updates_lot_available_and_commitment_open_lbs
    """
    block = x.register_block(
        api,
        name="BLK-C12",
        variety="STRAWBERRY",
        acres=8.00,
        planting_year=2021,
        irrigation_source_code="WELL-C12",
    )
    crew = x.recruit_crew(api, name="CREW-C12")
    window = x.plan_window(
        api,
        block["id"],
        crew["id"],
        start_at="2026-08-03T06:00:00Z",
        end_at="2026-08-03T18:00:00Z",
    )
    lot = x.pack_lot(
        api,
        window["id"],
        block["id"],
        variety="STRAWBERRY",
        grade="A",
        clamshell_count=100,
        clamshell_net_weight_lbs=1.00,
        pick_date="2026-08-03",
        pack_completed_at="2026-08-03T08:00:00Z",
        field_pulp_temp_f=68.0,
    )
    commitment = x.open_commitment(
        api,
        buyer_name="Harborline Grocers",
        buyer_user_id="buyer-12",
        variety="STRAWBERRY",
        volume_commitment_lbs=220.00,
        price_cents_per_lb=380,
        shelf_life_guarantee_days=5,
        window_start_date="2026-08-01",
        window_end_date="2026-08-10",
    )

    response = api.create_lot_allocation(
        f.lot_allocation_payload(
            lot["id"], commitment["id"], 60.00, commitment["version"]
        ),
        u.SALES_MANAGER,
    )
    allocation = validate_success(response, 201)

    a.assert_status(allocation, "status", "RESERVED")
    a.assert_pounds(allocation["allocated_lbs"], 60.00, "allocation.allocated_lbs")
    a.assert_unset(allocation, "shipped_at", "allocation")

    stored_lot = x.read_lot(api, lot["id"])
    a.assert_status(stored_lot, "disposition_status", "RESERVED")
    a.assert_pounds(stored_lot["allocated_lbs"], 60.00, "lot.allocated_lbs")
    a.assert_pounds(stored_lot["available_lbs"], 40.00, "lot.available_lbs")
    a.assert_pounds(stored_lot["net_packed_lbs"], 100.00, "lot.net_packed_lbs")

    stored_commitment = x.read_commitment(api, commitment["id"])
    a.assert_pounds(stored_commitment["committed_lbs"], 60.00, "commitment.committed_lbs")
    a.assert_pounds(stored_commitment["open_lbs"], 160.00, "commitment.open_lbs")
    a.assert_pounds(stored_commitment["shipped_lbs"], 0.00, "commitment.shipped_lbs")
    a.assert_ratio(stored_commitment["fill_pct"], 0.0000, "commitment.fill_pct")
    a.assert_status(stored_commitment, "risk_flag", "ON_TRACK")
    a.assert_status(stored_commitment, "status", "OPEN")
    assert stored_commitment["version"] == 2


def test_the_traceability_roll_up_counts_rejected_and_held_lots_separately(api):
    """
    The roll-up walks every lot of the block regardless of status, so a rejected
    lot still contributes its pounds to the total while showing up in both the
    held and the rejected counts.

    PRD 3.1: "It walks every fruit lot whose traceability block is this block, in ascending `pick_date` and then ascending `created_at` order, and regardless of status — including lots that have been repacked away and the child lots those repacks produced, since a child carries the same traceability block."

    PRD 3.6: "Rejection sets `food_safety_hold` true, drives `available_lbs` to 0.00, moves the lot to `REJECTED`, recomputes the parent window's `packed_lbs`, and increments the lot's and the window's `version` by 1."

    Design: Corner/calculations/block_traceability_summary_aggregates_by_pick_date_and_hold_state
    """
    block = x.register_block(
        api,
        name="BLK-C13",
        variety="STRAWBERRY",
        acres=8.00,
        planting_year=2021,
        irrigation_source_code="WELL-C13",
    )
    x.record_water_sample(
        api, block["id"], sample_date="2026-07-20", generic_ecoli_mpn=40
    )
    crew = x.recruit_crew(api, name="CREW-C13")
    first_day = x.plan_window(
        api,
        block["id"],
        crew["id"],
        start_at="2026-08-03T06:00:00Z",
        end_at="2026-08-03T18:00:00Z",
    )
    second_day = x.plan_window(
        api,
        block["id"],
        crew["id"],
        start_at="2026-08-04T06:00:00Z",
        end_at="2026-08-04T18:00:00Z",
    )

    day_one = x.lots_on_block(
        api,
        first_day["id"],
        block["id"],
        [
            {
                "variety": "STRAWBERRY",
                "grade": "A",
                "clamshell_count": 60,
                "clamshell_net_weight_lbs": 1.00,
                "pick_date": "2026-08-03",
                "pack_completed_at": "2026-08-03T09:00:00Z",
                "field_pulp_temp_f": 66.0,
            },
            {
                "variety": "STRAWBERRY",
                "grade": "B",
                "clamshell_count": 40,
                "clamshell_net_weight_lbs": 1.00,
                "pick_date": "2026-08-03",
                "pack_completed_at": "2026-08-03T10:00:00Z",
                "field_pulp_temp_f": 66.0,
            },
        ],
    )
    x.lots_on_block(
        api,
        second_day["id"],
        block["id"],
        [
            {
                "variety": "STRAWBERRY",
                "grade": "A",
                "clamshell_count": 50,
                "clamshell_net_weight_lbs": 1.00,
                "pick_date": "2026-08-04",
                "pack_completed_at": "2026-08-04T09:00:00Z",
                "field_pulp_temp_f": 66.0,
            }
        ],
    )
    x.reject_lot(api, day_one[1]["id"], reason_code="MOLD")

    response = api.get_traceability_summary(block["id"], u.FOOD_SAFETY_OFFICER)
    summary = validate_success(response, 200)
    a.assert_object_response(response)

    assert summary["block_id"] == block["id"]
    assert summary["block_name"] == "BLK-C13"
    a.assert_status(summary, "variety", "STRAWBERRY")
    assert summary["lot_count"] == 3
    assert summary["pick_date_count"] == 2
    a.assert_pounds(summary["total_packed_lbs"], 150.00, "summary.total_packed_lbs")
    a.assert_pounds(summary["shipped_lbs"], 0.00, "summary.shipped_lbs")
    assert summary["held_lot_count"] == 1
    assert summary["rejected_lot_count"] == 1
    assert summary["earliest_pick_date"] == "2026-08-03"
    assert summary["latest_pick_date"] == "2026-08-04"
    a.assert_status(summary, "water_status", "PROVISIONAL")
    a.assert_status(summary, "food_safety_posture", "CLEARED")
