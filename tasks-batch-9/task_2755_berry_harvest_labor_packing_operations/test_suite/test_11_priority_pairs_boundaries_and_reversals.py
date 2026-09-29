"""
Which rule speaks first when two of them are broken at once, what happens at the
exact numeric edge, and how far a reversal is allowed to reach.

These tests exercise PRD section 2.7's global rule ordering, the inclusive
geometric-mean criterion of section 3.1, the empty-set boundary of the period
settlement in section 3.5, and the exact-compensation invariants of sections 3.4,
3.7 and 3.8.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors as e
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as x
from test_helpers import test_users as u


def _confirmed_window_on_a_quarantined_block(api, name):
    """
    A `CONFIRMED` window whose block was quarantined afterwards, so the window
    has already been dragged to `SUSPENDED` by the cascade.

    Returns the block, the crew and the window as it stood before the hold.
    """
    block = x.block_with_provisional_water(api, name=name)
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
    x.quarantine_block(
        api, block["id"], reason_code="IRRIGATION_LINE_CONTAMINATION"
    )
    return block, crew, window


def test_opening_a_suspended_window_reports_the_state_not_the_quarantine(api):
    """
    The open call offends both the window-state rule and the food-safety rule.
    The state rule is numbered lower, so it alone is reported and the safety
    error never surfaces.

    PRD 2.7: "**Rules are evaluated in ascending priority, the first violated rule determines the response, and no side effect of the request is applied once a rule has fired.**"

    PRD 2.7 rule 28: "A window is `PLANNED` when confirmed, `CONFIRMED` when opened, `OPEN` when closed, `SUSPENDED` when resumed, and one of `PLANNED`, `CONFIRMED` or `SUSPENDED` when cancelled, otherwise `ERR_INVALID_WINDOW_STATE`."

    PRD 2.7 rule 38: "The window's block is not `QUARANTINED` when the window is confirmed, opened or resumed, and the traceability block is not `QUARANTINED` when a fruit lot is packed against it; the rejection in all four cases is `ERR_BLOCK_QUARANTINED`."

    Design: Difficulty/priority_pair_validation_conflict/suspended_window_state_error_precedes_block_quarantine_safety_error
    """
    block, crew, window = _confirmed_window_on_a_quarantined_block(api, "BLK-PP1")
    suspended = x.read_window(api, window["id"])
    a.assert_status(suspended, "status", "SUSPENDED")
    a.assert_status(x.read_block(api, block["id"]), "food_safety_posture", "QUARANTINED")

    refused = api.open_harvest_window(window["id"], u.HARVEST_MANAGER)
    body = validate_error(refused, e.ERR_INVALID_WINDOW_STATE, 409)
    assert body["error_id"] != e.ERR_BLOCK_QUARANTINED

    unchanged = x.read_window(api, window["id"])
    a.assert_status(unchanged, "status", "SUSPENDED")
    assert unchanged["suspended_reason_code"] == "BLOCK_QUARANTINE"
    assert unchanged["version"] == suspended["version"]

    a.assert_status(x.read_crew(api, crew["id"]), "status", "CERTIFIED")


def test_resuming_the_same_window_is_state_legal_so_the_quarantine_speaks(api):
    """
    The companion arm: a resume satisfies the state rule that the open call
    broke, so the very same block hold that stayed hidden a moment ago is now
    the reported failure.

    PRD 2.7 rule 28: "A window is `PLANNED` when confirmed, `CONFIRMED` when opened, `OPEN` when closed, `SUSPENDED` when resumed, and one of `PLANNED`, `CONFIRMED` or `SUSPENDED` when cancelled, otherwise `ERR_INVALID_WINDOW_STATE`."

    PRD 3.3: "Recovery is manual: a `HarvestManager` resumes a `SUSPENDED` window once the block's `food_safety_posture` is back to `CLEARED` — a still-quarantined block yields `ERR_BLOCK_QUARANTINED` — and while the logical clock instant is still strictly before the window's `end_at`, failing which the resume yields `ERR_TEMPORAL_ORDER_VIOLATION`."

    Design: Difficulty/priority_pair_validation_conflict/suspended_window_state_error_precedes_block_quarantine_safety_error
    """
    _, crew, window = _confirmed_window_on_a_quarantined_block(api, "BLK-PP1B")

    refused = api.resume_harvest_window(window["id"], u.HARVEST_MANAGER)
    body = validate_error(refused, e.ERR_BLOCK_QUARANTINED, 409)
    assert body["error_id"] != e.ERR_INVALID_WINDOW_STATE

    unchanged = x.read_window(api, window["id"])
    a.assert_status(unchanged, "status", "SUSPENDED")
    assert unchanged["suspended_reason_code"] == "BLOCK_QUARANTINE"
    a.assert_status(x.read_crew(api, crew["id"]), "status", "CERTIFIED")


def _two_blocks_and_a_one_day_window(api):
    """Two blocks of the same variety, with a `PLANNED` window on the first."""
    first = x.register_block(
        api,
        name="BLK-PP2-A",
        variety="STRAWBERRY",
        acres=4.00,
        planting_year=2023,
        irrigation_source_code="WELL-11",
    )
    second = x.register_block(
        api,
        name="BLK-PP2-B",
        variety="STRAWBERRY",
        acres=4.00,
        planting_year=2023,
        irrigation_source_code="WELL-12",
    )
    crew = x.recruit_crew(api, name="CREW-PP2", planned_head_count=1)
    window = x.plan_window(
        api,
        first["id"],
        crew["id"],
        start_at="2026-08-03T05:00:00Z",
        end_at="2026-08-03T17:00:00Z",
        forecast_brix=8.5,
        planned_volume_lbs=150.00,
        piece_rate_cents_per_clamshell=45,
        clamshell_net_weight_lbs=1.00,
    )
    return first, second, window


def test_a_lot_off_the_wrong_block_reports_the_mismatch_not_the_pick_date(api):
    """
    This pack record names the wrong block *and* a pick date six days outside
    the shift. The cross-entity rule is numbered lower than the temporal one, so
    the mismatch is what comes back and no lot is written.

    PRD 2.7 rule 52: "A fruit lot's `block_id` equals the `block_id` of the window named by its `harvest_window_id` — the pack record must trace to the block that was actually picked — otherwise `ERR_LOT_BLOCK_MISMATCH`."

    PRD 2.7 rule 55: "A fruit lot's `pick_date` falls within the calendar dates spanned by its window's `start_at` and `end_at`, inclusive, otherwise `ERR_PICK_DATE_OUTSIDE_WINDOW`."

    PRD 2.7: "A request that offends three rules reports only the lowest-numbered one."

    Design: Difficulty/priority_pair_validation_conflict/lot_block_mismatch_referential_error_precedes_pick_date_temporal_error
    """
    _, other, window = _two_blocks_and_a_one_day_window(api)

    refused = api.create_fruit_lot(
        f.fruit_lot_payload(
            window["id"],
            other["id"],
            variety="STRAWBERRY",
            grade="A",
            clamshell_count=40,
            clamshell_net_weight_lbs=1.00,
            pick_date="2026-08-09",
            pack_completed_at="2026-08-09T06:00:00Z",
            field_pulp_temp_f=64.0,
        ),
        u.PACKHOUSE_OPERATOR,
    )
    body = validate_error(refused, e.ERR_LOT_BLOCK_MISMATCH, 422)
    assert body["error_id"] != e.ERR_PICK_DATE_OUTSIDE_WINDOW

    rows, meta = x.list_lots(api, harvest_window_id=window["id"])
    a.assert_page_meta(meta, expected_total=0)
    assert rows == []
    a.assert_pounds(x.read_window(api, window["id"])["packed_lbs"], 0.00, "window.packed_lbs")


def test_the_same_pick_date_is_reported_once_the_block_finally_matches(api):
    """
    The companion arm: keep the out-of-range pick date but name the window's own
    block, and the temporal rule that had been masked is the one that fires.

    PRD 2.7 rule 55: "A fruit lot's `pick_date` falls within the calendar dates spanned by its window's `start_at` and `end_at`, inclusive, otherwise `ERR_PICK_DATE_OUTSIDE_WINDOW`."

    PRD 3.6: "the `pick_date` must fall within the calendar dates spanned by the window, inclusive, otherwise `ERR_PICK_DATE_OUTSIDE_WINDOW`"

    Design: Difficulty/priority_pair_validation_conflict/lot_block_mismatch_referential_error_precedes_pick_date_temporal_error
    """
    picked, _, window = _two_blocks_and_a_one_day_window(api)

    refused = api.create_fruit_lot(
        f.fruit_lot_payload(
            window["id"],
            picked["id"],
            variety="STRAWBERRY",
            grade="A",
            clamshell_count=40,
            clamshell_net_weight_lbs=1.00,
            pick_date="2026-08-09",
            pack_completed_at="2026-08-09T06:00:00Z",
            field_pulp_temp_f=64.0,
        ),
        u.PACKHOUSE_OPERATOR,
    )
    body = validate_error(refused, e.ERR_PICK_DATE_OUTSIDE_WINDOW, 422)
    assert body["error_id"] != e.ERR_LOT_BLOCK_MISMATCH

    _, meta = x.list_lots(api, harvest_window_id=window["id"])
    a.assert_page_meta(meta, expected_total=0)
    a.assert_pounds(x.read_window(api, window["id"])["packed_lbs"], 0.00, "window.packed_lbs")


def _block_with_two_clean_samples(api, name, irrigation_source_code):
    """A block carrying 63 MPN on 2026-07-20 and 126 MPN on 2026-07-24."""
    block = x.register_block(
        api,
        name=name,
        variety="STRAWBERRY",
        acres=3.00,
        planting_year=2023,
        irrigation_source_code=irrigation_source_code,
    )
    x.record_water_sample(api, block["id"], sample_date="2026-07-20", generic_ecoli_mpn=63)
    x.record_water_sample(api, block["id"], sample_date="2026-07-24", generic_ecoli_mpn=126)
    seeded = x.read_block(api, block["id"])
    assert seeded["water_sample_count"] == 2
    a.assert_status(seeded, "water_status", "PROVISIONAL")
    return block


def test_a_geometric_mean_landing_exactly_on_the_criterion_is_compliant(api):
    """
    63, 126 and 252 multiply to 126 cubed, so the stored mean is exactly 126.0 —
    the criterion itself. The comparison is inclusive, so the block clears.

    PRD 3.1: "`water_geomean_mpn` is the geometric mean of the `generic_ecoli_mpn` values in the window: the product of those values, raised to the power of one divided by the count, then rounded half up to one decimal place."

    PRD 3.1: "Otherwise, if the stored `water_geomean_mpn` is less than or equal to the geometric-mean criterion of 126 MPN per 100 mL, the status is `COMPLIANT`."

    PRD 3.1: "As §2.6 sets out, the comparison against 126 uses the stored one-decimal value, not the raw root."

    Design: Difficulty/boundary_precision_check/water_geometric_mean_exactly_at_limit_is_compliant
    """
    block = _block_with_two_clean_samples(api, "BLK-BP1-A", "CANAL-1")

    sample = validate_success(
        api.create_water_test(
            f.water_test_payload(
                block["id"], sample_date="2026-07-28", generic_ecoli_mpn=252
            ),
            u.FOOD_SAFETY_OFFICER,
        ),
        201,
    )
    assert sample["single_sample_exceedance"] is False
    a.assert_status(sample, "resulting_water_status", "COMPLIANT")

    cleared = x.read_block(api, block["id"])
    assert cleared["water_sample_count"] == 3
    a.assert_geomean(cleared["water_geomean_mpn"], 126.0)
    assert cleared["last_sample_date"] == "2026-07-28"
    a.assert_status(cleared, "water_status", "COMPLIANT")
    a.assert_status(cleared, "food_safety_posture", "CLEARED")
    assert cleared["manual_quarantine_active"] is False
    a.assert_unset(cleared, "quarantine_reason_code", "compliant block")
    assert cleared["version"] == 4


def test_one_more_unit_of_e_coli_pushes_the_mean_off_the_criterion(api):
    """
    Replace that last 252 with 253 and the same three-sample window rounds to
    126.2, one tenth above the criterion, which restricts the block. Nothing
    else about the series changed.

    PRD 3.1: "Otherwise it is `NON_COMPLIANT`."

    PRD 3.1: "Otherwise — that is, for `NO_SAMPLES`, `NON_COMPLIANT` and `FAILED` — the posture is `RESTRICTED`."

    PRD 3.1: "`single_sample_exceedance`, true exactly when this sample's `generic_ecoli_mpn` is strictly greater than the single-sample maximum of 410 MPN per 100 mL"

    Design: Difficulty/boundary_precision_check/water_geometric_mean_exactly_at_limit_is_compliant
    """
    block = _block_with_two_clean_samples(api, "BLK-BP1-B", "CANAL-2")

    sample = validate_success(
        api.create_water_test(
            f.water_test_payload(
                block["id"], sample_date="2026-07-28", generic_ecoli_mpn=253
            ),
            u.FOOD_SAFETY_OFFICER,
        ),
        201,
    )
    assert sample["single_sample_exceedance"] is False
    a.assert_status(sample, "resulting_water_status", "NON_COMPLIANT")

    restricted = x.read_block(api, block["id"])
    assert restricted["water_sample_count"] == 3
    a.assert_geomean(restricted["water_geomean_mpn"], 126.2)
    a.assert_status(restricted, "water_status", "NON_COMPLIANT")
    a.assert_status(restricted, "food_safety_posture", "RESTRICTED")
    assert restricted["manual_quarantine_active"] is False
    a.assert_unset(restricted, "quarantined_by_user_id", "non-compliant block")


def _idle_crew_and_draft_run(api, name):
    """A crew that never worked a day, with a `DRAFT` run over 2026-08-03..09."""
    crew = x.recruit_crew(api, name=name, labor_program="DOMESTIC", planned_head_count=1)
    x.register_picker(api, crew["id"], full_name="Picker Idle")
    run = x.open_payroll_run(
        api,
        crew["id"],
        period_start_date="2026-08-03",
        period_end_date="2026-08-09",
    )
    a.assert_status(run, "status", "DRAFT")
    assert run["bound_session_count"] == 0
    a.assert_unset(run, "period_hours", "draft run")
    return crew, run


def test_locking_a_period_with_no_sessions_binds_an_empty_set_at_zero(api):
    """
    The lock succeeds over an empty stamped set: the counted figures come out at
    zero rather than unset, while the settlement figures stay undetermined.

    PRD 3.5: "From the stamped set the run records `bound_session_count`, `period_hours` as the sum of `hours_worked` to two decimals, `period_piece_cents` as the sum of `piece_cents`, and `accrued_gross_cents` as the sum of `gross_cents` — the per-session figure, captured for comparison."

    PRD 3.5: "A run whose bound set is empty is a legitimate zero-pay period, not an error: every computed figure settles to 0 and the request **succeeds**."

    Design: Difficulty/boundary_precision_check/payroll_settle_with_empty_bound_session_set_succeeds_with_zero_totals
    """
    _, run = _idle_crew_and_draft_run(api, "CREW-BP2")

    locked = validate_success(api.lock_payroll_run(run["id"], u.PAYROLL_CLERK), 200)
    a.assert_object_response(api.get_payroll_run(run["id"], u.PAYROLL_CLERK))
    a.assert_status(locked, "status", "LOCKED")
    assert locked["bound_session_count"] == 0
    a.assert_hours(locked["period_hours"], 0.00, "run.period_hours")
    a.assert_cents(locked["period_piece_cents"], 0, "run.period_piece_cents")
    a.assert_cents(locked["accrued_gross_cents"], 0, "run.accrued_gross_cents")
    assert locked["locked_by_user_id"] == u.CLERK_1
    a.assert_unset(locked, "settled_net_cents", "locked run")
    a.assert_unset(locked, "settled_by_user_id", "locked run")
    assert locked["version"] == 2


def test_settling_that_empty_period_succeeds_with_every_figure_at_zero(api):
    """
    max(0, 0 − 0) is 0, not an error and not a null: the empty period settles to
    a complete row of zeros, including a reconciliation delta of exactly 0.

    PRD 3.5: "`period_makeup_cents` is the amount by which `period_floor_cents` exceeds `period_piece_cents`, or zero."

    PRD 3.5: "`reconciliation_delta_cents` is `settled_net_cents` less the sum of the bound sessions' `net_cents` — the difference between the period view and the per-session accrual."

    PRD 3.5: "A run whose bound set is empty is a legitimate zero-pay period, not an error: every computed figure settles to 0 and the request **succeeds**."

    Design: Difficulty/boundary_precision_check/payroll_settle_with_empty_bound_session_set_succeeds_with_zero_totals
    """
    crew, run = _idle_crew_and_draft_run(api, "CREW-BP2B")
    x.lock_payroll_run(api, run["id"])

    settled = validate_success(api.settle_payroll_run(run["id"], u.PAYROLL_CLERK_2), 200)
    a.assert_status(settled, "status", "SETTLED")
    assert settled["bound_session_count"] == 0
    a.assert_hours(settled["period_hours"], 0.00, "run.period_hours")
    a.assert_cents(settled["period_piece_cents"], 0, "run.period_piece_cents")
    a.assert_cents(settled["period_floor_cents"], 0, "run.period_floor_cents")
    a.assert_cents(settled["period_makeup_cents"], 0, "run.period_makeup_cents")
    a.assert_cents(settled["period_deduction_cents"], 0, "run.period_deduction_cents")
    a.assert_cents(settled["settled_gross_cents"], 0, "run.settled_gross_cents")
    a.assert_cents(settled["settled_net_cents"], 0, "run.settled_net_cents")
    a.assert_cents(settled["accrued_gross_cents"], 0, "run.accrued_gross_cents")
    a.assert_cents(settled["reconciliation_delta_cents"], 0, "run.reconciliation_delta_cents")
    assert settled["settled_by_user_id"] == u.CLERK_2

    ledger = x.read_crew(api, crew["id"])
    a.assert_cents(ledger["accrued_wage_cents"], 0, "crew.accrued_wage_cents")
    a.assert_cents(ledger["settled_wage_cents"], 0, "crew.settled_wage_cents")
    a.assert_cents(ledger["reconciliation_delta_cents"], 0, "crew.reconciliation_delta_cents")


def _two_approved_sessions(api, name):
    """
    One `OPEN` window carrying two `APPROVED` sessions — a light day worth 4950
    and a heavy day worth 9000 — so the crew ledger stands at 13950.

    Returns the crew, the two pickers, the window and the two sessions.
    """
    block = x.block_with_provisional_water(api, name=name, acres=7.00)
    crew, pickers = x.certified_crew(
        api,
        picker_count=2,
        planned_head_count=2,
        supervisor_user_id=u.SUP_1,
        labor_program="DOMESTIC",
        name="CREW-" + name,
    )
    window = x.opened_window(
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
    light = x.approved_session(
        api,
        window["id"],
        pickers[0]["id"],
        u.SUP_1,
        work_date="2026-08-03",
        hours_worked=3.00,
        clamshells_filled=20,
        culled_clamshells=0,
    )
    heavy = x.approved_session(
        api,
        window["id"],
        pickers[1]["id"],
        u.SUP_1,
        work_date="2026-08-03",
        hours_worked=3.00,
        clamshells_filled=200,
        culled_clamshells=0,
    )
    a.assert_cents(light["net_cents"], 4950, "light session.net_cents")
    a.assert_cents(heavy["net_cents"], 9000, "heavy session.net_cents")
    return crew, pickers, window, light, heavy


def test_disputing_one_approved_session_removes_only_its_own_accrual(api):
    """
    Of 13950 accrued across two days, disputing the heavy one leaves exactly
    4950 — the light day's own net. The reversal is neither the whole ledger nor
    nothing, and the disputed row keeps its own money for audit.

    PRD 3.4: "A dispute out of `APPROVED` does considerably more: the crew's `accrued_wage_cents` is reduced by exactly the same stored `net_cents` figure that approval added, `approved_by_user_id` is cleared, the picker's lifetime productivity and the window's `harvested_clamshells` are recomputed over the sessions that remain `APPROVED` or `SETTLED`, and the `version` of the session, crew, picker and window are each incremented by 1."

    PRD 3.8: "Because a reversal always removes precisely the amount its approval added, the ledger returns to its earlier value bit for bit; it is never rebuilt by re-adding all the surviving sessions."

    Design: Difficulty/compensating_invariant/session_dispute_reverses_only_the_disputed_session_wage_accrual
    """
    crew, _, window, light, heavy = _two_approved_sessions(api, "BLK-CI1")
    before = x.read_crew(api, crew["id"])
    a.assert_cents(before["accrued_wage_cents"], 13950, "crew.accrued_wage_cents")
    assert x.read_window(api, window["id"])["harvested_clamshells"] == 220

    disputed = x.dispute_session(api, heavy["id"], reason_code="TALLY_DISPUTED")
    a.assert_status(disputed, "status", "DISPUTED")
    assert disputed["dispute_reason_code"] == "TALLY_DISPUTED"
    a.assert_unset(disputed, "approved_by_user_id", "disputed session")
    a.assert_cents(disputed["net_cents"], 9000, "disputed session.net_cents")
    a.assert_cents(disputed["piece_cents"], 9000, "disputed session.piece_cents")
    a.assert_cents(disputed["makeup_cents"], 0, "disputed session.makeup_cents")
    assert disputed["tally_revision_count"] == 0

    after = x.read_crew(api, crew["id"])
    a.assert_cents(after["accrued_wage_cents"], 4950, "crew.accrued_wage_cents")
    a.assert_cents(after["settled_wage_cents"], 0, "crew.settled_wage_cents")
    a.assert_status(x.read_session(api, light["id"]), "status", "APPROVED")


def test_the_reversal_rolls_back_one_picker_and_leaves_the_other_alone(api):
    """
    The productivity side of the same reversal: the disputing picker's lifetime
    figures drop back to the empty state they held before approval, the other
    picker's are untouched, and the window counts only the surviving day.

    PRD 3.4: "A picker's lifetime figures are a **full recomputation** over that picker's sessions in status `APPROVED` or `SETTLED`, never an incremental delta."

    PRD 3.4: "Sessions that are `OPEN`, `TALLIED`, `DISPUTED` or `VOIDED` contribute nothing, which is what makes a reversal restore the pre-approval figures exactly."

    PRD 3.4: "A window's `harvested_clamshells`, by contrast, is the sum of `clamshells_filled` — the gross tally, culls included — over that window's sessions in status `APPROVED` or `SETTLED`."

    Design: Difficulty/compensating_invariant/session_dispute_reverses_only_the_disputed_session_wage_accrual
    """
    _, pickers, window, _, heavy = _two_approved_sessions(api, "BLK-CI1B")

    x.dispute_session(api, heavy["id"], reason_code="TALLY_DISPUTED")

    rolled_back = x.read_picker(api, pickers[1]["id"])
    assert rolled_back["total_clamshells_lifetime"] == 0
    a.assert_hours(rolled_back["total_hours_lifetime"], 0.00, "picker.total_hours_lifetime")
    a.assert_rate(rolled_back["avg_lbs_per_hour"], 0.00, "picker.avg_lbs_per_hour")

    untouched = x.read_picker(api, pickers[0]["id"])
    assert untouched["total_clamshells_lifetime"] == 20
    a.assert_hours(untouched["total_hours_lifetime"], 3.00, "picker.total_hours_lifetime")
    a.assert_rate(untouched["avg_lbs_per_hour"], 6.67, "picker.avg_lbs_per_hour")

    assert x.read_window(api, window["id"])["harvested_clamshells"] == 20


def _lot_pledged_to_two_lines(api, name):
    """
    A `COOLED` 100.00 lb lot with a 60.00 lb and a 30.00 lb line reserved against
    one 100.00 lb program.

    Returns the lot, the commitment and the two allocation lines.
    """
    block = x.block_with_compliant_water(api, name=name, acres=8.00)
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
    lot = x.cooled_lot(
        api,
        window["id"],
        block["id"],
        tunnel["id"],
        cool_start_at="2026-08-03T08:00:00Z",
        planned_cool_end_at="2026-08-03T12:00:00Z",
        cool_complete_at="2026-08-03T12:00:00Z",
        entry_pulp_temp_f=55.0,
        exit_pulp_temp_f=34.0,
        pallet_slots=2,
        variety="STRAWBERRY",
        grade="A",
        clamshell_count=100,
        clamshell_net_weight_lbs=1.00,
        pick_date="2026-08-03",
        pack_completed_at="2026-08-03T06:00:00Z",
        field_pulp_temp_f=61.0,
    )
    commitment = x.open_commitment(
        api,
        buyer_name="MarketTwo",
        variety="STRAWBERRY",
        volume_commitment_lbs=100.00,
        price_cents_per_lb=500,
        shelf_life_guarantee_days=3,
        window_start_date="2026-08-01",
        window_end_date="2026-08-10",
    )
    first = x.allocate(api, lot["id"], commitment["id"], 60.00)
    second = x.allocate(api, lot["id"], commitment["id"], 30.00)
    return lot, commitment, first, second


def test_releasing_one_of_two_lines_restores_its_pounds_and_no_others(api):
    """
    Letting go of the 60.00 lb line hands back exactly 60.00 lbs on both
    ledgers, and the lot stays `RESERVED` because the 30.00 lb line is still
    live.

    PRD 3.7: "Release requires the commitment to be `OPEN` and is an **exact compensation**, not a recomputation from scratch of anything the line did not touch: the commitment's `committed_lbs` is decremented by precisely that line's `allocated_lbs`, its `open_lbs` and `risk_flag` are recomputed, and its `version` is incremented by 1; the lot's `allocated_lbs` and `available_lbs` are restored to their pre-allocation values and its `version` is incremented by 1; and the lot's `disposition_status` returns from `RESERVED` to `UNCOMMITTED` only when no `RESERVED` or `SHIPPED` line of that lot remains — a lot pledged to two buyers stays `RESERVED` when one of them lets go."

    Design: Difficulty/compensating_invariant/allocation_release_restores_lot_and_commitment_pounds_exactly
    """
    lot, commitment, first, _ = _lot_pledged_to_two_lines(api, "BLK-CI2")
    pledged_lot = x.read_lot(api, lot["id"])
    a.assert_pounds(pledged_lot["net_packed_lbs"], 100.00, "lot.net_packed_lbs")
    a.assert_pounds(pledged_lot["allocated_lbs"], 90.00, "lot.allocated_lbs")
    a.assert_pounds(pledged_lot["available_lbs"], 10.00, "lot.available_lbs")
    a.assert_status(pledged_lot, "disposition_status", "RESERVED")
    pledged_program = x.read_commitment(api, commitment["id"])
    a.assert_commitment_exposure(pledged_program, 90.00, 0.00)
    a.assert_pounds(pledged_program["open_lbs"], 10.00, "commitment.open_lbs")

    released = x.release_allocation(api, first["id"], reason_code="BUYER_CANCELLED")
    a.assert_status(released, "status", "RELEASED")
    assert released["release_reason_code"] == "BUYER_CANCELLED"
    a.assert_pounds(released["allocated_lbs"], 60.00, "allocation.allocated_lbs")

    partly_free = x.read_lot(api, lot["id"])
    a.assert_pounds(partly_free["allocated_lbs"], 30.00, "lot.allocated_lbs")
    a.assert_pounds(partly_free["available_lbs"], 70.00, "lot.available_lbs")
    a.assert_status(partly_free, "disposition_status", "RESERVED")
    a.assert_lot_mass_balance(partly_free)

    partly_open = x.read_commitment(api, commitment["id"])
    a.assert_commitment_exposure(partly_open, 30.00, 0.00)
    a.assert_pounds(partly_open["open_lbs"], 70.00, "commitment.open_lbs")
    a.assert_status(partly_open, "status", "OPEN")


def test_releasing_the_second_line_returns_both_sides_to_the_start(api):
    """
    With the last line gone the lot is `UNCOMMITTED` with all 100.00 lbs
    available again and the program is back to nothing committed — the packed
    pounds and the cold chain having never been part of the reversal.

    PRD 3.7: "`RELEASED` lines are excluded from every subsequent figure — exposure, revenue and fill alike — so a released line leaves no trace."

    PRD 3.8: "A lot's `available_lbs` is always `net_packed_lbs` less its `allocated_lbs`, `repack_out_lbs`, `cull_lbs` and `optical_reject_lbs`, at two decimals — forced to 0.00 by rejection and driven to 0.00 by a repack."

    PRD 3.8: "Releasing a line restores the lot's figures to their pre-allocation values exactly and decrements the commitment's exposure by exactly that line's pledge, so the state after allocate-then-release is indistinguishable from the state before the allocation was ever made."

    Design: Difficulty/compensating_invariant/allocation_release_restores_lot_and_commitment_pounds_exactly
    """
    lot, commitment, first, second = _lot_pledged_to_two_lines(api, "BLK-CI2B")

    x.release_allocation(api, first["id"], reason_code="BUYER_CANCELLED")
    let_go = x.release_allocation(api, second["id"], reason_code="BUYER_CANCELLED")
    a.assert_status(let_go, "status", "RELEASED")

    free = x.read_lot(api, lot["id"])
    a.assert_pounds(free["allocated_lbs"], 0.00, "lot.allocated_lbs")
    a.assert_pounds(free["available_lbs"], 100.00, "lot.available_lbs")
    a.assert_status(free, "disposition_status", "UNCOMMITTED")
    a.assert_pounds(free["net_packed_lbs"], 100.00, "lot.net_packed_lbs")
    a.assert_status(free, "cold_chain_status", "COOLED")
    assert free["food_safety_hold"] is False
    a.assert_lot_mass_balance(free)

    empty = x.read_commitment(api, commitment["id"])
    a.assert_commitment_exposure(empty, 0.00, 0.00)
    a.assert_pounds(empty["open_lbs"], 100.00, "commitment.open_lbs")
    a.assert_ratio(empty["fill_pct"], 0.0000, "commitment.fill_pct")
    a.assert_status(empty, "status", "OPEN")
    a.assert_status(empty, "risk_flag", "ON_TRACK")
