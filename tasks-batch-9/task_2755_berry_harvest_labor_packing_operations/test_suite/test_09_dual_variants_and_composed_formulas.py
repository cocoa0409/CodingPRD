"""
Composed arithmetic: two views of one wage, two views of one shelf life, and
the formulas that only come out right when their steps stay in order.

Every test here drives a figure the API builds from several inputs at once — a
period average against per-session floors, a forecast shelf life against a
verified one, a maturity-adjusted picking capacity, a per-line discount rounded
before it is summed, and a housing cap taken after a minimum-wage make-up.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as x
from test_helpers import test_users as u


def _two_work_days(api):
    """
    One `CLEARED` block, one `CERTIFIED` domestic picker and one `OPEN` window
    per work date.

    A window is a single shift, so two work dates need two windows; the second
    starts sixteen hours after the first one ends, which clears the twelve-hour
    block re-entry buffer.
    """
    block = x.block_with_provisional_water(
        api,
        name="BLK-DV1",
        variety="STRAWBERRY",
        acres=9.00,
        planting_year=2021,
        irrigation_source_code="WELL-DV1",
    )
    crew, pickers = x.certified_crew(
        api,
        picker_count=1,
        labor_program="DOMESTIC",
        supervisor_user_id=u.SUP_1,
        name="CREW-DV1",
    )
    shift = {
        "forecast_brix": 8.5,
        "planned_volume_lbs": 150.00,
        "piece_rate_cents_per_clamshell": 45,
        "clamshell_net_weight_lbs": 1.00,
    }
    first_day = x.opened_window(
        api,
        block["id"],
        crew["id"],
        start_at="2026-08-03T06:00:00Z",
        end_at="2026-08-03T14:00:00Z",
        **shift,
    )
    second_day = x.opened_window(
        api,
        block["id"],
        crew["id"],
        start_at="2026-08-04T06:00:00Z",
        end_at="2026-08-04T14:00:00Z",
        **shift,
    )
    return block, crew, pickers[0], first_day, second_day


def test_each_of_the_two_sessions_is_floored_on_its_own_three_hours(api):
    """
    Priced one day at a time, the light-picking day is lifted to its hourly
    floor and the heavy-picking day is not, and the crew ledger carries the sum
    of the two per-session nets.

    PRD 3.4: "`guarantee_floor_cents` is `hours_worked` multiplied by the statutory minimum of 1650 cents per hour — sixteen dollars fifty an hour — rounded half up to a whole cent. `makeup_cents` is the amount by which the floor exceeds the piece earnings, or zero when the piece earnings already meet or beat the floor. `gross_cents` is `piece_cents` plus `makeup_cents`."

    PRD 3.4: "Only one session participates in that arithmetic. No sibling session of the same picker, the same day or the same window contributes anything — which is precisely why the per-session view and the period view of §3.5 can disagree."

    PRD 3.8: "A crew's `accrued_wage_cents` is, at the close of every request, exactly equal to the sum of `net_cents` over that crew's pick sessions currently in status `APPROVED`."

    Design: Difficulty/dual_variant_calc/payroll_period_average_diverges_from_per_session_guarantee
    """
    _, crew, picker, first_day, second_day = _two_work_days(api)

    light = x.tallied_session(
        api,
        first_day["id"],
        picker["id"],
        u.SUP_1,
        work_date="2026-08-03",
        hours_worked=3.00,
        clamshells_filled=20,
        culled_clamshells=0,
    )
    a.assert_ratio(light["cull_rate"], 0.0000, "light.cull_rate")
    a.assert_status(light, "quality_flag", "MEETS_STANDARD")
    a.assert_cents(light["effective_piece_rate_cents"], 45, "light.effective_piece_rate_cents")
    a.assert_cents(light["piece_cents"], 900, "light.piece_cents")
    a.assert_cents(light["guarantee_floor_cents"], 4950, "light.guarantee_floor_cents")
    a.assert_cents(light["makeup_cents"], 4050, "light.makeup_cents")
    a.assert_cents(light["gross_cents"], 4950, "light.gross_cents")
    a.assert_cents(light["housing_deduction_cents"], 0, "light.housing_deduction_cents")
    a.assert_cents(light["net_cents"], 4950, "light.net_cents")
    a.assert_status(light, "status", "TALLIED")

    heavy = x.tallied_session(
        api,
        second_day["id"],
        picker["id"],
        u.SUP_1,
        work_date="2026-08-04",
        hours_worked=3.00,
        clamshells_filled=200,
        culled_clamshells=0,
    )
    a.assert_cents(heavy["piece_cents"], 9000, "heavy.piece_cents")
    a.assert_cents(heavy["guarantee_floor_cents"], 4950, "heavy.guarantee_floor_cents")
    a.assert_cents(heavy["makeup_cents"], 0, "heavy.makeup_cents")
    a.assert_cents(heavy["gross_cents"], 9000, "heavy.gross_cents")
    a.assert_cents(heavy["net_cents"], 9000, "heavy.net_cents")

    x.approve_session(api, light["id"])
    x.approve_session(api, heavy["id"])

    ledger = x.read_crew(api, crew["id"])
    a.assert_cents(ledger["accrued_wage_cents"], 13950, "crew.accrued_wage_cents")
    a.assert_cents(ledger["settled_wage_cents"], 0, "crew.settled_wage_cents")
    a.assert_cents(
        ledger["reconciliation_delta_cents"], 0, "crew.reconciliation_delta_cents"
    )


def test_the_period_average_absorbs_the_shortfall_and_books_a_negative_delta(api):
    """
    Summed first and multiplied once, the same six hours carry a single floor of
    9900 cents, so the settled period pays 4050 cents less than the two
    independently floored sessions accrued.

    PRD 3.5: "`period_hours` is **summed first and multiplied once**: `period_floor_cents` is `period_hours` multiplied by the same minimum of 1650 cents per hour, rounded half up to a whole cent."

    PRD 3.5: "From the stamped set the run records `bound_session_count`, `period_hours` as the sum of `hours_worked` to two decimals, `period_piece_cents` as the sum of `piece_cents`, and `accrued_gross_cents` as the sum of `gross_cents` — the per-session figure, captured for comparison."

    PRD 3.5: "`reconciliation_delta_cents` is `settled_net_cents` less the sum of the bound sessions' `net_cents` — the difference between the period view and the per-session accrual."

    PRD 3.5: "On the period the figures are `period_hours` 6.00, `period_piece_cents` 9900, `period_floor_cents` 9900, `period_makeup_cents` 0, `settled_gross_cents` 9900, `period_deduction_cents` 0 and `settled_net_cents` 9900 — session B's surplus absorbs session A's shortfall entirely — so `reconciliation_delta_cents` is 9900 less 13950, that is −4050."

    Design: Difficulty/dual_variant_calc/payroll_period_average_diverges_from_per_session_guarantee
    """
    _, crew, picker, first_day, second_day = _two_work_days(api)

    light = x.approved_session(
        api,
        first_day["id"],
        picker["id"],
        u.SUP_1,
        work_date="2026-08-03",
        hours_worked=3.00,
        clamshells_filled=20,
        culled_clamshells=0,
    )
    heavy = x.approved_session(
        api,
        second_day["id"],
        picker["id"],
        u.SUP_1,
        work_date="2026-08-04",
        hours_worked=3.00,
        clamshells_filled=200,
        culled_clamshells=0,
    )
    a.assert_cents(light["net_cents"], 4950, "light.net_cents")
    a.assert_cents(heavy["net_cents"], 9000, "heavy.net_cents")

    draft = x.open_payroll_run(
        api,
        crew["id"],
        period_start_date="2026-08-03",
        period_end_date="2026-08-04",
    )
    assert draft["bound_session_count"] == 0
    a.assert_unset(draft, "period_hours", "draft run")
    a.assert_unset(draft, "settled_net_cents", "draft run")
    a.assert_unset(draft, "reconciliation_delta_cents", "draft run")

    locked = x.lock_payroll_run(api, draft["id"], u.PAYROLL_CLERK)
    a.assert_status(locked, "status", "LOCKED")
    assert locked["bound_session_count"] == 2
    a.assert_hours(locked["period_hours"], 6.00, "locked.period_hours")
    a.assert_cents(locked["period_piece_cents"], 9900, "locked.period_piece_cents")
    a.assert_cents(locked["accrued_gross_cents"], 13950, "locked.accrued_gross_cents")
    a.assert_unset(locked, "period_floor_cents", "locked run")
    a.assert_unset(locked, "settled_net_cents", "locked run")
    a.assert_unset(locked, "reconciliation_delta_cents", "locked run")

    settled = x.settle_payroll_run(api, draft["id"], u.PAYROLL_CLERK_2)
    a.assert_status(settled, "status", "SETTLED")
    assert settled["bound_session_count"] == 2
    a.assert_hours(settled["period_hours"], 6.00, "run.period_hours")
    a.assert_cents(settled["period_piece_cents"], 9900, "run.period_piece_cents")
    a.assert_cents(settled["period_floor_cents"], 9900, "run.period_floor_cents")
    a.assert_cents(settled["period_makeup_cents"], 0, "run.period_makeup_cents")
    a.assert_cents(settled["settled_gross_cents"], 9900, "run.settled_gross_cents")
    a.assert_cents(settled["period_deduction_cents"], 0, "run.period_deduction_cents")
    a.assert_cents(settled["settled_net_cents"], 9900, "run.settled_net_cents")
    a.assert_cents(settled["accrued_gross_cents"], 13950, "run.accrued_gross_cents")
    a.assert_cents(
        settled["reconciliation_delta_cents"], -4050, "run.reconciliation_delta_cents"
    )
    assert settled["locked_by_user_id"] == u.CLERK_1
    assert settled["settled_by_user_id"] == u.CLERK_2

    for session_id in (light["id"], heavy["id"]):
        a.assert_status(x.read_session(api, session_id), "status", "SETTLED")

    ledger = x.read_crew(api, crew["id"])
    a.assert_cents(ledger["accrued_wage_cents"], 0, "crew.accrued_wage_cents")
    a.assert_cents(ledger["settled_wage_cents"], 9900, "crew.settled_wage_cents")
    a.assert_cents(
        ledger["reconciliation_delta_cents"], -4050, "crew.reconciliation_delta_cents"
    )


def _lot_in_a_tunnel(api):
    """
    A grade-A strawberry lot whose pack closed at 06:00, plus a tunnel with
    room for it.

    Nothing about the water register matters here: packing and cooling only
    require that the block is not `QUARANTINED`.
    """
    block = x.register_block(
        api,
        name="BLK-DV2",
        variety="STRAWBERRY",
        acres=6.00,
        planting_year=2022,
        irrigation_source_code="WELL-DV2",
    )
    crew = x.recruit_crew(api, name="CREW-DV2")
    window = x.plan_window(
        api,
        block["id"],
        crew["id"],
        start_at="2026-08-03T05:00:00Z",
        end_at="2026-08-03T17:00:00Z",
        forecast_brix=8.5,
        planned_volume_lbs=200.00,
        piece_rate_cents_per_clamshell=45,
        clamshell_net_weight_lbs=1.00,
    )
    tunnel = x.register_tunnel(
        api, name="TUN-DV2", slot_capacity=4, target_pulp_temp_f=34.0
    )
    lot = x.pack_lot(
        api,
        window["id"],
        block["id"],
        variety="STRAWBERRY",
        grade="A",
        clamshell_count=130,
        clamshell_net_weight_lbs=1.00,
        pick_date="2026-08-03",
        pack_completed_at="2026-08-03T06:00:00Z",
        field_pulp_temp_f=68.0,
    )
    return block, window, tunnel, lot


def test_the_forecast_shelf_life_charges_the_field_heat_and_nothing_else(api):
    """
    Stamped when the lot enters the tunnel, the forecast charges the three and
    a half hours of field heat and fixes the exit-temperature penalty at zero,
    because no exit temperature exists yet.

    PRD 3.6: "Shelf life starts from a variety base measured in days — 7 for `STRAWBERRY`, 14 for `BLUEBERRY`, 5 for `RASPBERRY` and 6 for `BLACKBERRY` — and is reduced by four charges."

    PRD 3.6: "The field-heat penalty charges a full day for **any part** of an hour that `field_delay_hours` runs beyond the two-hour tolerance: it is the amount by which the delay exceeds 2.0 hours, floored at zero, then rounded **up** to a whole day."

    PRD 3.6: "The **forecast** stamped at start-cooling measures `cool_hours` against `planned_cool_end_at` and fixes the temperature penalty at 0, because no exit temperature has been measured — it is therefore an upper bound."

    PRD 3.6: "For a grade-A `STRAWBERRY` lot packed at 06:00 and pushed into the tunnel at 09:30, `field_delay_hours` is 3.50 and the field penalty is 2 days; with a planned end of 13:30 the cooling penalty is 0 and the forecast is 7 − 0 − 2 − 0 − 0 = 5 days."

    PRD 3.6: "Starting a run stores the cooling fields, computes `field_delay_hours` as the elapsed hours from `pack_completed_at` to `cool_start_at` rounded half up to two decimals, stamps `forecast_shelf_life_days` from the forecast variant of the shelf-life calculation, increments the tunnel's `committed_slots` by `pallet_slots` and the tunnel's `version` by 1, moves the lot `PACKED → COOLING`, and increments the lot's `version` by 1."

    Design: Difficulty/dual_variant_calc/lot_forecast_shelf_life_diverges_from_verified_shelf_life
    """
    _, _, tunnel, lot = _lot_in_a_tunnel(api)

    cooling = x.start_cooling(
        api,
        lot["id"],
        tunnel["id"],
        cool_start_at="2026-08-03T09:30:00Z",
        planned_cool_end_at="2026-08-03T13:30:00Z",
        entry_pulp_temp_f=60.0,
        pallet_slots=1,
    )

    a.assert_hours(cooling["field_delay_hours"], 3.50, "lot.field_delay_hours")
    assert cooling["forecast_shelf_life_days"] == 5
    a.assert_status(cooling, "cold_chain_status", "COOLING")
    a.assert_status(cooling, "disposition_status", "UNCOMMITTED")
    assert cooling["cooling_tunnel_id"] == tunnel["id"]
    a.assert_temperature(cooling["entry_pulp_temp_f"], 60.0, "lot.entry_pulp_temp_f")
    assert cooling["pallet_slots"] == 1
    a.assert_instant(
        cooling["cool_start_at"], "2026-08-03T09:30:00Z", "lot.cool_start_at"
    )
    a.assert_instant(
        cooling["planned_cool_end_at"], "2026-08-03T13:30:00Z", "lot.planned_cool_end_at"
    )
    assert cooling["version"] == 2

    a.assert_unset(cooling, "cool_hours", "cooling lot")
    a.assert_unset(cooling, "cool_complete_at", "cooling lot")
    a.assert_unset(cooling, "exit_pulp_temp_f", "cooling lot")
    a.assert_unset(cooling, "verified_shelf_life_days", "cooling lot")
    a.assert_unset(cooling, "shelf_life_expires_on", "cooling lot")

    booked = x.read_tunnel(api, tunnel["id"])
    assert booked["committed_slots"] == 1
    assert booked["version"] == 2


def test_the_verified_shelf_life_charges_the_long_run_and_the_warm_exit_too(api):
    """
    Stamped at completion, the verified figure keeps the field-heat charge and
    adds two more — the run that went ninety minutes long and the exit pulp
    three degrees over target — landing three days below the forecast.

    PRD 3.6: "The **verified** figure stamped at completion measures against the actual `cool_complete_at` and computes the temperature penalty from the measured `exit_pulp_temp_f`, so a tunnel that ran long and came out warm is charged twice, once through the cooling penalty and once through the temperature penalty."

    PRD 3.6: "The exit-temperature penalty is charged only for **complete** two-degree steps: the amount by which the exit pulp temperature exceeds the 34.0 °F target, floored at zero, divided by 2.0 and rounded **down** to a whole day."

    PRD 3.6: "If the same lot actually leaves the tunnel at 15:00 at 37.0 °F, `cool_hours` is 5.50 so the cooling penalty is 2, and the temperature penalty is the whole two-degree steps in 3.0 degrees, that is 1, giving a verified figure of 7 − 0 − 2 − 2 − 1 = 2 days."

    PRD 3.6: "`shelf_life_expires_on` is then the calendar date of `cool_complete_at` advanced by `verified_shelf_life_days` days."

    PRD 3.6: "It computes `cool_hours` as the elapsed hours from `cool_start_at` to `cool_complete_at` rounded half up to two decimals, stamps `verified_shelf_life_days` and `shelf_life_expires_on` from the verified variant, releases the slots by decrementing the tunnel's `committed_slots` by the lot's `pallet_slots` and incrementing the tunnel's `version` by 1, moves the lot `COOLING → COOLED`, and increments the lot's `version` by 1."

    Design: Difficulty/dual_variant_calc/lot_forecast_shelf_life_diverges_from_verified_shelf_life
    """
    _, _, tunnel, lot = _lot_in_a_tunnel(api)

    x.start_cooling(
        api,
        lot["id"],
        tunnel["id"],
        cool_start_at="2026-08-03T09:30:00Z",
        planned_cool_end_at="2026-08-03T13:30:00Z",
        entry_pulp_temp_f=60.0,
        pallet_slots=1,
    )
    cooled = x.complete_cooling(
        api,
        lot["id"],
        cool_complete_at="2026-08-03T15:00:00Z",
        exit_pulp_temp_f=37.0,
    )

    a.assert_hours(cooled["cool_hours"], 5.50, "lot.cool_hours")
    a.assert_temperature(cooled["exit_pulp_temp_f"], 37.0, "lot.exit_pulp_temp_f")
    assert cooled["verified_shelf_life_days"] == 2
    assert cooled["shelf_life_expires_on"] == "2026-08-05"
    assert cooled["forecast_shelf_life_days"] == 5
    a.assert_hours(cooled["field_delay_hours"], 3.50, "lot.field_delay_hours")
    a.assert_status(cooled, "cold_chain_status", "COOLED")
    a.assert_status(cooled, "disposition_status", "UNCOMMITTED")
    a.assert_pounds(cooled["net_packed_lbs"], 130.00, "lot.net_packed_lbs")
    a.assert_pounds(cooled["available_lbs"], 130.00, "lot.available_lbs")
    assert cooled["version"] == 3

    released = x.read_tunnel(api, tunnel["id"])
    assert released["committed_slots"] == 0
    assert released["version"] == 3


def _planned_blueberry_window(api, name, forecast_brix, planned_volume_lbs):
    """
    A `PLANNED` seven-and-a-half-hour blueberry window whose maturity reading
    and planned volume the caller chooses.

    The block is never sampled and the crew never staffed: the staffing
    estimate looks at neither.
    """
    block = x.register_block(
        api,
        name=name,
        variety="BLUEBERRY",
        acres=11.00,
        planting_year=2020,
        irrigation_source_code="WELL-" + name,
    )
    crew = x.recruit_crew(api, name="CREW-" + name, planned_head_count=10)
    window = x.plan_window(
        api,
        block["id"],
        crew["id"],
        start_at="2026-08-05T05:00:00Z",
        end_at="2026-08-05T12:30:00Z",
        forecast_brix=forecast_brix,
        planned_volume_lbs=planned_volume_lbs,
        piece_rate_cents_per_clamshell=60,
        clamshell_net_weight_lbs=1.25,
    )
    return block, crew, window


def test_a_brix_below_the_variety_target_leaves_the_base_pick_rate_alone(api):
    """
    At 11.5 degrees a blueberry window misses the 12.0 target, so the base rate
    of 18 is multiplied by 1.00 and 140 planned pounds over a 135-pound capacity
    round up to two pickers.

    PRD 3.3: "On creation the window derives `window_hours`, the elapsed time from `start_at` to `end_at` expressed in hours and rounded half up to two decimals, and starts at `PLANNED` with `harvested_clamshells` 0, `packed_lbs` 0.00, no `effective_pick_rate_lbs_per_hour`, no `required_picker_count`, and neither `suspended_reason_code` nor `cancel_reason_code` set."

    PRD 3.3: "That base is then adjusted for maturity: if the window's `forecast_brix` is at least the variety's *target* brix — 9.0 for `STRAWBERRY`, 12.0 for `BLUEBERRY`, 10.0 for `RASPBERRY` and 10.5 for `BLACKBERRY` — the base is multiplied by 1.10, because riper fruit picks faster; otherwise it is multiplied by 1.00 and left alone."

    PRD 3.3: "The result, rounded half up to two decimals, is stored as `effective_pick_rate_lbs_per_hour`. Crew capacity for the window is that effective rate multiplied by `window_hours`. `required_picker_count` is then `planned_volume_lbs` divided by that capacity, rounded **up** to the next whole picker, and finally raised to a floor of 1 so that a window always needs at least one picker."

    Design: Difficulty/combinatorial_formula/window_crew_requirement_ceiling_over_maturity_adjusted_capacity
    """
    _, _, planned = _planned_blueberry_window(api, "BLK-CB1", 11.5, 140.00)

    a.assert_hours(planned["window_hours"], 7.50, "window.window_hours")
    a.assert_brix(planned["forecast_brix"], 11.5, "window.forecast_brix")
    a.assert_status(planned, "status", "PLANNED")
    a.assert_unset(planned, "effective_pick_rate_lbs_per_hour", "planned window")
    a.assert_unset(planned, "required_picker_count", "planned window")
    assert planned["version"] == 1

    confirmed = x.confirm_window(api, planned["id"])
    a.assert_status(confirmed, "status", "CONFIRMED")
    a.assert_rate(
        confirmed["effective_pick_rate_lbs_per_hour"],
        18.00,
        "window.effective_pick_rate_lbs_per_hour",
    )
    assert confirmed["required_picker_count"] == 2
    a.assert_hours(confirmed["window_hours"], 7.50, "window.window_hours")
    assert confirmed["version"] == 2


def test_a_brix_above_the_variety_target_lifts_the_rate_by_a_tenth(api):
    """
    At 12.5 degrees the same variety clears its 12.0 target, so 18 becomes
    19.80, the seven-and-a-half-hour capacity is 148.50 pounds, and 300 planned
    pounds need three pickers rather than the two a bare division suggests.

    PRD 3.3: "The staffing estimate itself is forward-looking and uses no actuals: no pick session and no picker row participates."

    PRD 3.3: "It begins from a base pick rate in pounds per picker-hour set by the block's variety — 22 for `STRAWBERRY`, 18 for `BLUEBERRY`, 12 for `RASPBERRY` and 14 for `BLACKBERRY`."

    PRD 3.3: "That base is then adjusted for maturity: if the window's `forecast_brix` is at least the variety's *target* brix — 9.0 for `STRAWBERRY`, 12.0 for `BLUEBERRY`, 10.0 for `RASPBERRY` and 10.5 for `BLACKBERRY` — the base is multiplied by 1.10, because riper fruit picks faster; otherwise it is multiplied by 1.00 and left alone."

    PRD 3.3: "The result, rounded half up to two decimals, is stored as `effective_pick_rate_lbs_per_hour`. Crew capacity for the window is that effective rate multiplied by `window_hours`. `required_picker_count` is then `planned_volume_lbs` divided by that capacity, rounded **up** to the next whole picker, and finally raised to a floor of 1 so that a window always needs at least one picker."

    Design: Difficulty/combinatorial_formula/window_crew_requirement_ceiling_over_maturity_adjusted_capacity
    """
    _, crew, planned = _planned_blueberry_window(api, "BLK-CB2", 12.5, 300.00)

    a.assert_hours(planned["window_hours"], 7.50, "window.window_hours")
    a.assert_unset(planned, "effective_pick_rate_lbs_per_hour", "planned window")
    a.assert_unset(planned, "required_picker_count", "planned window")

    confirmed = x.confirm_window(api, planned["id"])
    a.assert_status(confirmed, "status", "CONFIRMED")
    a.assert_rate(
        confirmed["effective_pick_rate_lbs_per_hour"],
        19.80,
        "window.effective_pick_rate_lbs_per_hour",
    )
    assert confirmed["required_picker_count"] == 3
    a.assert_pounds(confirmed["planned_volume_lbs"], 300.00, "window.planned_volume_lbs")
    assert confirmed["harvested_clamshells"] == 0
    a.assert_pounds(confirmed["packed_lbs"], 0.00, "window.packed_lbs")
    assert confirmed["version"] == 2

    unstaffed = x.read_crew(api, crew["id"])
    assert unstaffed["picker_count"] == 0
    a.assert_status(unstaffed, "status", "RECRUITING")


def _two_shipped_lines(api):
    """
    A buyer program of 220.00 pounds at 380 cents with two shipped lines of
    120.50 and 90.30 pounds, drawn on two lots that each verified four days.

    The traceability block carries three passing samples because a ship demands
    a water status of exactly `COMPLIANT`.
    """
    block = x.block_with_compliant_water(
        api,
        name="BLK-CB3",
        variety="STRAWBERRY",
        acres=14.00,
        planting_year=2021,
        irrigation_source_code="WELL-CB3",
    )
    crew = x.recruit_crew(api, name="CREW-CB3")
    window = x.plan_window(
        api,
        block["id"],
        crew["id"],
        start_at="2026-08-03T05:00:00Z",
        end_at="2026-08-03T17:00:00Z",
        forecast_brix=8.5,
        planned_volume_lbs=250.00,
        piece_rate_cents_per_clamshell=45,
        clamshell_net_weight_lbs=1.00,
    )
    tunnel = x.register_tunnel(
        api, name="TUN-CB3", slot_capacity=2, target_pulp_temp_f=34.0
    )
    lots = []
    for clamshell_count in (130, 95):
        lots.append(
            x.cooled_lot(
                api,
                window["id"],
                block["id"],
                tunnel["id"],
                cool_start_at="2026-08-03T08:00:00Z",
                planned_cool_end_at="2026-08-03T12:00:00Z",
                cool_complete_at="2026-08-03T12:00:00Z",
                entry_pulp_temp_f=58.0,
                exit_pulp_temp_f=40.0,
                pallet_slots=1,
                variety="STRAWBERRY",
                grade="A",
                clamshell_count=clamshell_count,
                clamshell_net_weight_lbs=1.00,
                pick_date="2026-08-03",
                pack_completed_at="2026-08-03T07:00:00Z",
                field_pulp_temp_f=66.0,
            )
        )
    for lot in lots:
        assert lot["verified_shelf_life_days"] == 4
        assert lot["shelf_life_expires_on"] == "2026-08-07"

    commitment = x.open_commitment(
        api,
        buyer_name="Coastal Retail CB3",
        buyer_user_id="buyer-cb3",
        variety="STRAWBERRY",
        volume_commitment_lbs=220.00,
        price_cents_per_lb=380,
        shelf_life_guarantee_days=5,
        window_start_date="2026-08-01",
        window_end_date="2026-08-10",
    )
    line_a = x.allocate(api, lots[0]["id"], commitment["id"], 120.50)
    line_b = x.allocate(api, lots[1]["id"], commitment["id"], 90.30)
    x.ship_allocation(api, line_a["id"], "2026-08-04T10:00:00Z")
    x.ship_allocation(api, line_b["id"], "2026-08-04T10:00:00Z")
    return commitment, line_a, line_b


def test_settlement_prices_each_shipped_line_on_its_own_rounded_cent(api):
    """
    Both lots came in a day short of the five-day guarantee, so each line is
    grossed, discounted five percent and rounded by itself: 2290 cents off
    45790 and 1716 off 34314.

    PRD 3.7: "On the settled branch, the shipped lines are priced **one at a time**, processed in ascending `shipped_at` order with ties broken by ascending `created_at`."

    PRD 3.7: "For each line, `shelf_life_shortfall_days` is the amount by which the commitment's `shelf_life_guarantee_days` exceeds the lot's `verified_shelf_life_days`, floored at zero. The discount rate is five percent per shortfall day, capped at thirty percent no matter how short the fruit came in. `line_gross_cents` is `allocated_lbs` multiplied by `price_cents_per_lb`, rounded half up to a whole cent. `line_discount_cents` is `line_gross_cents` multiplied by that discount rate, rounded half up to a whole cent. `line_net_cents` is the gross less the discount."

    PRD 3.7: "With `price_cents_per_lb` 380 and `shelf_life_guarantee_days` 5 against two shipped lines whose lots both verified 4 days — a one-day shortfall, so a five percent discount — line A of 120.50 lbs grosses 45790, discounts 2290 (45790 × 0.05 = 2289.50, rounded half up) and nets 43500, while line B of 90.30 lbs grosses 34314, discounts 1716 (1715.70 rounded half up) and nets 32598, giving `settled_revenue_cents` 76098."

    PRD 3.7: "Settlement stamps the four per-line figures on every shipped allocation and increments each stamped allocation's `version` by 1, stamps the commitment's `settled_revenue_cents`, `shortfall_penalty_cents`, `settled_net_cents`, `fill_pct` and `fill_status`, and increments the commitment's `version` by 1."

    Design: Difficulty/combinatorial_formula/commitment_settlement_rounds_each_shipped_line_before_summing
    """
    commitment, line_a, line_b = _two_shipped_lines(api)

    x.set_clock(api, "2026-08-11T00:00:00Z")
    x.settle_commitment(api, commitment["id"])

    priced_a = x.read_allocation(api, line_a["id"])
    a.assert_status(priced_a, "status", "SHIPPED")
    a.assert_pounds(priced_a["allocated_lbs"], 120.50, "line A.allocated_lbs")
    assert priced_a["shelf_life_shortfall_days"] == 1
    a.assert_cents(priced_a["line_gross_cents"], 45790, "line A.line_gross_cents")
    a.assert_cents(priced_a["line_discount_cents"], 2290, "line A.line_discount_cents")
    a.assert_cents(priced_a["line_net_cents"], 43500, "line A.line_net_cents")
    assert priced_a["version"] == 3

    priced_b = x.read_allocation(api, line_b["id"])
    a.assert_status(priced_b, "status", "SHIPPED")
    a.assert_pounds(priced_b["allocated_lbs"], 90.30, "line B.allocated_lbs")
    assert priced_b["shelf_life_shortfall_days"] == 1
    a.assert_cents(priced_b["line_gross_cents"], 34314, "line B.line_gross_cents")
    a.assert_cents(priced_b["line_discount_cents"], 1716, "line B.line_discount_cents")
    a.assert_cents(priced_b["line_net_cents"], 32598, "line B.line_net_cents")
    assert priced_b["version"] == 3

    assert (
        priced_a["line_gross_cents"] + priced_b["line_gross_cents"] == 80104
    ), "the two line grosses must still sum to the combined gross of the worked example"
    assert priced_a["line_discount_cents"] + priced_b["line_discount_cents"] == 4006, (
        "separately rounded discounts sum to 4006, not the 4005 an aggregate "
        "discount would produce"
    )


def test_the_settled_program_sums_the_rounded_lines_and_clears_the_fill_target(api):
    """
    Summing the two separately rounded nets gives 76098 cents — not the 76099 a
    single aggregate discount yields — and 210.80 of 220.00 pounds clears the
    ninety-five percent target, so no shortfall penalty is charged.

    PRD 3.7: "**Each line is rounded separately and only then summed**: `settled_revenue_cents` is the sum of `line_net_cents` over the shipped lines, and rounding an aggregate discount instead produces a different, wrong number."

    PRD 3.7: "Discounting the combined gross of 80104 instead yields 4005 and a revenue of 76099 — off by a cent, and wrong."

    PRD 3.7: "The third condition decides which branch is taken rather than blocking: `shipped_lbs` greater than zero settles `OPEN → SETTLED`, and `shipped_lbs` of exactly zero settles `OPEN → DEFAULTED`."

    PRD 3.7: "Continuing the example above with a `volume_commitment_lbs` of 220.00 and `shipped_lbs` of 210.80, `fill_pct` is 0.9582, which clears 0.95, so the program is `FILLED`, the penalty is 0 and `settled_net_cents` is 76098."

    Design: Difficulty/combinatorial_formula/commitment_settlement_rounds_each_shipped_line_before_summing
    """
    commitment, _, _ = _two_shipped_lines(api)

    x.set_clock(api, "2026-08-11T00:00:00Z")
    response = api.settle_buyer_commitment(commitment["id"], u.SALES_MANAGER)
    settled = validate_success(response, 200)
    a.assert_object_response(response)

    a.assert_status(settled, "status", "SETTLED")
    a.assert_cents(settled["settled_revenue_cents"], 76098, "settled_revenue_cents")
    assert settled["settled_revenue_cents"] != 76099
    a.assert_cents(settled["shortfall_penalty_cents"], 0, "shortfall_penalty_cents")
    a.assert_cents(settled["settled_net_cents"], 76098, "settled_net_cents")
    a.assert_pounds(settled["shipped_lbs"], 210.80, "commitment.shipped_lbs")
    a.assert_pounds(settled["committed_lbs"], 210.80, "commitment.committed_lbs")
    a.assert_pounds(settled["open_lbs"], 9.20, "commitment.open_lbs")
    a.assert_ratio(settled["fill_pct"], 0.9582, "commitment.fill_pct")
    a.assert_status(settled, "fill_status", "FILLED")
    assert settled["version"] == 6


def _h2a_day(api, name):
    """
    An `H2A` crew with housing on file, one certified picker, and an `OPEN`
    twelve-hour window paying 45 cents a clamshell, with the picker's day
    already opened.
    """
    setup = x.harvest_ready(
        api,
        block_name=name,
        variety="STRAWBERRY",
        picker_count=1,
        labor_program="H2A",
        supervisor_user_id=u.SUP_1,
        crew_overrides={"name": "CREW-" + name},
        start_at="2026-08-03T06:00:00Z",
        end_at="2026-08-03T18:00:00Z",
        forecast_brix=8.5,
        planned_volume_lbs=150.00,
        piece_rate_cents_per_clamshell=45,
        clamshell_net_weight_lbs=1.00,
    )
    a.assert_status(setup["crew"], "labor_program", "H2A")
    assert setup["crew"]["housing_unit_code"] is not None
    session = x.open_session(
        api,
        setup["window"]["id"],
        setup["picker"]["id"],
        u.SUP_1,
        work_date="2026-08-03",
    )
    a.assert_status(session, "quality_flag", "PENDING")
    a.assert_cents(session["net_cents"], 0, "new session.net_cents")
    return setup, session


def test_the_h2a_housing_charge_is_a_tenth_of_the_made_whole_gross(api):
    """
    Two hours for ten clamshells earn 450 cents of piece work against a 3300
    cent floor, and the housing charge is ten percent of the 3300 the make-up
    produced — 330 cents — never a tenth of the 450 that was actually picked.

    PRD 3.4: "`quality_flag` becomes `MEETS_STANDARD` when `cull_rate` is less than or equal to the maximum tolerated cull rate of 0.08 — eight percent of the pack — and `BELOW_STANDARD` otherwise."

    PRD 3.4: "A housing charge is deductible only for a crew whose `labor_program` is `H2A` **and** which has a `housing_unit_code` on file; for every other crew `housing_deduction_cents` is exactly 0. Where it does apply, `housing_deduction_cents` is the lesser of the allowable daily charge of 900 cents — nine dollars a day — and ten percent of `gross_cents` rounded **down** to a whole cent. `net_cents` is `gross_cents` less `housing_deduction_cents`."

    PRD 3.4: "The wage guarantee is satisfied *first*, and only then is the deduction cap taken as a percentage of the resulting `gross_cents`. The deduction may never be applied before the make-up, and the cap may never be computed against `piece_cents` or against `net_cents`."

    PRD 3.4: "An `H2A` picker with housing on file works 2.00 hours, fills 10 clamshells with none culled, at the same 45-cent rate: piece earnings 450 cents, guarantee floor 3300 cents, make-up 2850 cents, gross 3300 cents; the deduction is the lesser of 900 and ten percent of 3300 floored, which is 330 cents, so net is 2970 cents."

    Design: Difficulty/combinatorial_formula/session_housing_deduction_capped_after_minimum_wage_makeup
    """
    _, session = _h2a_day(api, "BLK-CB4")

    response = api.tally_pick_session(
        session["id"],
        f.tally_payload(hours_worked=2.00, clamshells_filled=10, culled_clamshells=0),
        x.supervisor_headers(u.SUP_1),
    )
    tallied = validate_success(response, 200)
    a.assert_object_response(response)

    a.assert_hours(tallied["hours_worked"], 2.00, "session.hours_worked")
    assert tallied["clamshells_filled"] == 10
    assert tallied["culled_clamshells"] == 0
    a.assert_ratio(tallied["cull_rate"], 0.0000, "session.cull_rate")
    a.assert_status(tallied, "quality_flag", "MEETS_STANDARD")
    a.assert_cents(
        tallied["effective_piece_rate_cents"], 45, "session.effective_piece_rate_cents"
    )
    a.assert_cents(tallied["piece_cents"], 450, "session.piece_cents")
    a.assert_cents(tallied["guarantee_floor_cents"], 3300, "session.guarantee_floor_cents")
    a.assert_cents(tallied["makeup_cents"], 2850, "session.makeup_cents")
    a.assert_cents(tallied["gross_cents"], 3300, "session.gross_cents")
    a.assert_cents(
        tallied["housing_deduction_cents"], 330, "session.housing_deduction_cents"
    )
    a.assert_cents(tallied["net_cents"], 2970, "session.net_cents")
    a.assert_status(tallied, "status", "TALLIED")
    assert tallied["tally_revision_count"] == 0
    assert tallied["tallied_by_user_id"] == u.SUP_1

    assert tallied["housing_deduction_cents"] != 45, (
        "a tenth of `piece_cents` would be 45 cents; the cap is taken on the "
        "made-whole gross"
    )


def test_the_flat_daily_housing_charge_caps_the_percentage_on_a_long_day(api):
    """
    Eight hours for the same ten clamshells lift the gross to 13200 cents, where
    ten percent would be 1320 — so the flat 900-cent daily allowance becomes the
    lesser of the two and the worker keeps 12300.

    PRD 3.4: "A housing charge is deductible only for a crew whose `labor_program` is `H2A` **and** which has a `housing_unit_code` on file; for every other crew `housing_deduction_cents` is exactly 0. Where it does apply, `housing_deduction_cents` is the lesser of the allowable daily charge of 900 cents — nine dollars a day — and ten percent of `gross_cents` rounded **down** to a whole cent. `net_cents` is `gross_cents` less `housing_deduction_cents`."

    PRD 3.4: "This is what guarantees that a housing charge can never push a worker below their hourly floor: since the cap is a fraction of a gross that already includes the make-up, and it is floored rather than rounded, no rounding step can ever take more than the permitted share."

    PRD 3.4: "The **ordering of steps 4 and 5 is load-bearing** and is the single most easily mis-implemented rule in this specification."

    Design: Difficulty/combinatorial_formula/session_housing_deduction_capped_after_minimum_wage_makeup
    """
    _, session = _h2a_day(api, "BLK-CB5")

    tallied = x.tally_session(
        api,
        session["id"],
        u.SUP_1,
        hours_worked=8.00,
        clamshells_filled=10,
        culled_clamshells=0,
    )

    a.assert_hours(tallied["hours_worked"], 8.00, "session.hours_worked")
    a.assert_cents(tallied["piece_cents"], 450, "session.piece_cents")
    a.assert_cents(
        tallied["guarantee_floor_cents"], 13200, "session.guarantee_floor_cents"
    )
    a.assert_cents(tallied["makeup_cents"], 12750, "session.makeup_cents")
    a.assert_cents(tallied["gross_cents"], 13200, "session.gross_cents")
    a.assert_cents(
        tallied["housing_deduction_cents"], 900, "session.housing_deduction_cents"
    )
    a.assert_cents(tallied["net_cents"], 12300, "session.net_cents")
    a.assert_status(tallied, "status", "TALLIED")
    a.assert_status(tallied, "quality_flag", "MEETS_STANDARD")

    assert tallied["housing_deduction_cents"] != 1320, (
        "ten percent of the gross is 1320 cents, which the 900-cent daily "
        "allowance caps"
    )
