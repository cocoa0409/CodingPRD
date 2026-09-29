"""
The refusal tiers of PRD section 2.7 as they apply to the labour half of the
season: authorization ahead of existence, body ranges ahead of referential
lookups, the maturity gate, the hygiene clocks, and the state preconditions that
guard sessions and pay periods.

Every test here drives a request that offends a known rule and pins both the
error identifier and the fact that nothing was written.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as e
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as x
from test_helpers import test_users as u


def test_a_picker_reading_an_unknown_block_learns_only_that_it_is_forbidden(api):
    """
    The role check runs before the path lookup, so an unauthorised caller cannot
    probe which block identifiers exist.

    PRD 2.7: "**Rules are evaluated in ascending priority, the first violated rule determines the response, and no side effect of the request is applied once a rule has fired.**"

    PRD 2.7 rule 3: "The acting role appears on the target endpoint's authorized list, otherwise `ERR_FORBIDDEN_ROLE`, on every endpoint."

    PRD 2.7 rule 5: "`block_id` in the path resolves to a `Block`, otherwise `ERR_BLOCK_NOT_FOUND`."

    Design: Corner/validations/role_check_precedes_path_existence_and_returns_forbidden_role
    """
    response = api.get_block(
        NON_EXISTENT_UUID, u.make_picker_headers(NON_EXISTENT_UUID)
    )
    validate_error(response, e.ERR_FORBIDDEN_ROLE, 403)

    body = response.json()
    assert body["response_type"] == "error"
    assert body["data"]["error_id"] != e.ERR_BLOCK_NOT_FOUND
    assert body["data"]["error_id"] != e.ERR_UNAUTHENTICATED


def test_a_zero_mpn_sample_reports_the_range_failure_not_the_missing_block(api):
    """
    A doubly wrong water sample — an out-of-range count against a block that
    does not exist — answers with the cheap body-range failure.

    PRD 2.7 rule 12: "Numeric body fields respect their declared ranges, otherwise `ERR_VALUE_OUT_OF_RANGE`, on every write endpoint: `acres` greater than zero; `generic_ecoli_mpn` at least 1; `hours_worked` greater than zero and at most 16.00; `clamshells_filled` and `culled_clamshells` each zero or greater; `piece_rate_cents_per_clamshell` at least 1; `clamshell_net_weight_lbs` greater than zero; `clamshell_count` at least 1; `pallet_slots` at least 1; `slot_capacity` at least 1; `allocated_lbs` greater than zero; `volume_commitment_lbs` greater than zero; `price_cents_per_lb` at least 1; `shelf_life_guarantee_days` at least 1; `planned_head_count` at least 1; and `vehicle_seats` and `beds_confirmed` each zero or greater."

    PRD 2.7 rule 16: "A body `block_id` resolves to a `Block` (`ERR_BLOCK_NOT_FOUND`) on water-sample recording, window planning and fruit-lot creation."

    Design: Corner/validations/body_range_check_precedes_body_foreign_key_existence_rejected
    """
    response = api.create_water_test(
        f.water_test_payload(
            NON_EXISTENT_UUID, sample_date="2026-07-20", generic_ecoli_mpn=0
        ),
        u.FOOD_SAFETY_OFFICER,
    )
    validate_error(response, e.ERR_VALUE_OUT_OF_RANGE, 400)
    assert response.json()["data"]["error_id"] != e.ERR_BLOCK_NOT_FOUND

    _, meta = validate_paginated(api.list_water_tests(u.FOOD_SAFETY_OFFICER))
    a.assert_page_meta(meta, expected_total=0)


def test_a_window_a_tenth_below_the_variety_brix_minimum_cannot_confirm(api):
    """
    Strawberries demand 7.0 brix, so a window forecast at 6.9 is refused at
    confirmation and keeps both staffing projections undetermined.

    PRD 3.3: "The block must not be `QUARANTINED`, and the window's `forecast_brix` must be at least the minimum brix the block's variety demands — 7.0 for `STRAWBERRY`, 10.0 for `BLUEBERRY`, 8.0 for `RASPBERRY` and 8.5 for `BLACKBERRY` — compared inclusively, so a window sitting exactly on the minimum confirms while one below it is refused with `ERR_BRIX_BELOW_MINIMUM`."

    PRD 3.3: "On creation the window derives `window_hours`, the elapsed time from `start_at` to `end_at` expressed in hours and rounded half up to two decimals, and starts at `PLANNED` with `harvested_clamshells` 0, `packed_lbs` 0.00, no `effective_pick_rate_lbs_per_hour`, no `required_picker_count`, and neither `suspended_reason_code` nor `cancel_reason_code` set."

    Design: Corner/validations/window_confirm_below_variety_brix_minimum_returns_brix_below_minimum
    """
    block = x.register_block(
        api,
        name="BLK-V3",
        variety="STRAWBERRY",
        acres=8.00,
        planting_year=2021,
        irrigation_source_code="WELL-V3",
    )
    crew = x.recruit_crew(api, name="CREW-V3")
    window = x.plan_window(
        api,
        block["id"],
        crew["id"],
        start_at="2026-08-03T06:00:00Z",
        end_at="2026-08-03T14:00:00Z",
        forecast_brix=6.9,
        planned_volume_lbs=150.00,
        piece_rate_cents_per_clamshell=45,
        clamshell_net_weight_lbs=1.00,
    )

    response = api.confirm_harvest_window(window["id"], u.HARVEST_MANAGER)
    validate_error(response, e.ERR_BRIX_BELOW_MINIMUM, 422)

    stored = x.read_window(api, window["id"])
    a.assert_status(stored, "status", "PLANNED")
    assert stored["version"] == 1
    a.assert_unset(stored, "effective_pick_rate_lbs_per_hour", "window")
    a.assert_unset(stored, "required_picker_count", "window")


def test_a_window_sitting_exactly_on_the_brix_minimum_confirms(api):
    """
    The maturity comparison is inclusive: 7.0 brix on a strawberry block
    confirms and mints the unadjusted base rate, because 7.0 is far below the
    9.0 ripeness target.

    PRD 3.3: "The block must not be `QUARANTINED`, and the window's `forecast_brix` must be at least the minimum brix the block's variety demands — 7.0 for `STRAWBERRY`, 10.0 for `BLUEBERRY`, 8.0 for `RASPBERRY` and 8.5 for `BLACKBERRY` — compared inclusively, so a window sitting exactly on the minimum confirms while one below it is refused with `ERR_BRIX_BELOW_MINIMUM`."

    PRD 3.3: "It begins from a base pick rate in pounds per picker-hour set by the block's variety — 22 for `STRAWBERRY`, 18 for `BLUEBERRY`, 12 for `RASPBERRY` and 14 for `BLACKBERRY`."

    Design: Corner/validations/window_confirm_at_exactly_the_brix_minimum_succeeds
    """
    block = x.register_block(
        api,
        name="BLK-V4",
        variety="STRAWBERRY",
        acres=8.00,
        planting_year=2021,
        irrigation_source_code="WELL-V4",
    )
    crew = x.recruit_crew(api, name="CREW-V4")
    window = x.plan_window(
        api,
        block["id"],
        crew["id"],
        start_at="2026-08-03T06:00:00Z",
        end_at="2026-08-03T14:00:00Z",
        forecast_brix=7.0,
        planned_volume_lbs=150.00,
        piece_rate_cents_per_clamshell=45,
        clamshell_net_weight_lbs=1.00,
    )

    response = api.confirm_harvest_window(window["id"], u.HARVEST_MANAGER)
    confirmed = validate_success(response, 200)
    a.assert_object_response(response)

    a.assert_status(confirmed, "status", "CONFIRMED")
    assert confirmed["version"] == 2
    a.assert_rate(
        confirmed["effective_pick_rate_lbs_per_hour"],
        22.00,
        "window.effective_pick_rate_lbs_per_hour",
    )
    assert confirmed["required_picker_count"] == 1
    a.assert_hours(confirmed["window_hours"], 8.00, "window.window_hours")


def test_training_that_is_valid_at_certification_can_still_be_stale_on_the_day(api):
    """
    The two hygiene rules read different reference dates: an expiry of
    2026-08-04 clears certification at clock 2026-08-01 but is not strictly
    after a work date of 2026-08-04, so only the session create is refused.

    PRD 2.7 rule 42: "Every picker of the crew has a `hygiene_training_expires_on` that is present and strictly after the current logical clock date when the crew is certified, otherwise `ERR_HYGIENE_TRAINING_INVALID`."

    PRD 2.7 rule 43: "The picker's `hygiene_training_expires_on` is present and strictly after the session's `work_date` when a pick session is created, otherwise `ERR_HYGIENE_TRAINING_INVALID`."

    Design: Corner/validations/pick_session_create_with_expired_hygiene_training_rejected
    """
    block = x.register_block(
        api,
        name="BLK-V5",
        variety="STRAWBERRY",
        acres=8.00,
        planting_year=2021,
        irrigation_source_code="WELL-V5",
    )
    x.record_water_sample(
        api, block["id"], sample_date="2026-07-20", generic_ecoli_mpn=40
    )
    crew, pickers = x.certified_crew(
        api,
        picker_count=1,
        name="CREW-V5",
        hygiene_training_on="2025-08-04",
        support_plan={
            "housing_unit_code": "H-V5",
            "beds_confirmed": 1,
            "transport_route_code": "R-V5",
            "vehicle_seats": 1,
        },
    )
    picker = pickers[0]
    window = x.opened_window(
        api,
        block["id"],
        crew["id"],
        start_at="2026-08-04T06:00:00Z",
        end_at="2026-08-04T14:00:00Z",
        piece_rate_cents_per_clamshell=45,
        clamshell_net_weight_lbs=1.00,
        planned_volume_lbs=150.00,
    )

    response = api.create_pick_session(
        f.pick_session_payload(window["id"], picker["id"], work_date="2026-08-04"),
        u.CREW_SUPERVISOR,
    )
    validate_error(response, e.ERR_HYGIENE_TRAINING_INVALID, 409)

    stored_picker = x.read_picker(api, picker["id"])
    assert stored_picker["hygiene_training_expires_on"] == "2026-08-04"

    a.assert_status(x.read_crew(api, crew["id"]), "status", "ACTIVE")
    a.assert_status(x.read_window(api, window["id"]), "status", "OPEN")

    _, meta = x.list_sessions(api, harvest_window_id=window["id"])
    a.assert_page_meta(meta, expected_total=0)


def test_a_quarantined_block_admits_no_new_pack_record(api):
    """
    Every field of the pack request is valid and the window itself is fine; the
    state of a different entity — the traceability block — is what refuses it.

    PRD 2.7 rule 38: "The window's block is not `QUARANTINED` when the window is confirmed, opened or resumed, and the traceability block is not `QUARANTINED` when a fruit lot is packed against it; the rejection in all four cases is `ERR_BLOCK_QUARANTINED`."

    PRD 3.1: "If `manual_quarantine_active` is true, the posture is `QUARANTINED`. Otherwise, if `water_status` is `PROVISIONAL` or `COMPLIANT`, the posture is `CLEARED`."

    Design: Corner/validations/fruit_lot_create_against_a_quarantined_block_rejected
    """
    block = x.register_block(
        api,
        name="BLK-V6",
        variety="STRAWBERRY",
        acres=8.00,
        planting_year=2021,
        irrigation_source_code="WELL-V6",
    )
    x.record_water_sample(
        api, block["id"], sample_date="2026-07-20", generic_ecoli_mpn=40
    )
    crew = x.recruit_crew(api, name="CREW-V6")
    window = x.plan_window(
        api,
        block["id"],
        crew["id"],
        start_at="2026-08-03T06:00:00Z",
        end_at="2026-08-03T18:00:00Z",
    )
    x.quarantine_block(api, block["id"], reason_code="ADJACENT_LIVESTOCK")

    response = api.create_fruit_lot(
        f.fruit_lot_payload(
            window["id"],
            block["id"],
            variety="STRAWBERRY",
            grade="A",
            clamshell_count=40,
            clamshell_net_weight_lbs=1.00,
            pick_date="2026-08-03",
            pack_completed_at="2026-08-03T09:00:00Z",
            field_pulp_temp_f=68.0,
        ),
        u.PACKHOUSE_OPERATOR,
    )
    validate_error(response, e.ERR_BLOCK_QUARANTINED, 409)

    a.assert_status(
        x.read_block(api, block["id"]), "food_safety_posture", "QUARANTINED"
    )
    _, meta = x.list_lots(api, block_id=block["id"])
    a.assert_page_meta(meta, expected_total=0)
    a.assert_pounds(
        x.read_window(api, window["id"])["packed_lbs"], 0.00, "window.packed_lbs"
    )


def test_a_lot_stamped_a_day_after_its_window_is_refused(api):
    """
    A shift window spans one calendar date, so fruit stamped the following day
    cannot be traced through it.

    PRD 2.7 rule 55: "A fruit lot's `pick_date` falls within the calendar dates spanned by its window's `start_at` and `end_at`, inclusive, otherwise `ERR_PICK_DATE_OUTSIDE_WINDOW`."

    PRD 3.6: "the `pick_date` must fall within the calendar dates spanned by the window, inclusive, otherwise `ERR_PICK_DATE_OUTSIDE_WINDOW`"

    Design: Corner/validations/fruit_lot_pick_date_outside_its_window_span_rejected
    """
    block = x.register_block(
        api,
        name="BLK-V7",
        variety="STRAWBERRY",
        acres=8.00,
        planting_year=2021,
        irrigation_source_code="WELL-V7",
    )
    x.record_water_sample(
        api, block["id"], sample_date="2026-07-20", generic_ecoli_mpn=40
    )
    crew = x.recruit_crew(api, name="CREW-V7")
    window = x.plan_window(
        api,
        block["id"],
        crew["id"],
        start_at="2026-08-03T06:00:00Z",
        end_at="2026-08-03T14:00:00Z",
    )

    response = api.create_fruit_lot(
        f.fruit_lot_payload(
            window["id"],
            block["id"],
            variety="STRAWBERRY",
            grade="A",
            clamshell_count=40,
            clamshell_net_weight_lbs=1.00,
            pick_date="2026-08-04",
            pack_completed_at="2026-08-04T09:00:00Z",
            field_pulp_temp_f=68.0,
        ),
        u.PACKHOUSE_OPERATOR,
    )
    validate_error(response, e.ERR_PICK_DATE_OUTSIDE_WINDOW, 422)

    _, meta = x.list_lots(api, harvest_window_id=window["id"])
    a.assert_page_meta(meta, expected_total=0)


def test_one_open_session_is_refused_four_different_ways(api):
    """
    Approving before any tally, a tally with more culls than clamshells, a
    duplicate session and a work date past the window all fail differently, and
    the session is left untouched throughout.

    PRD 2.7 rule 30: "A session's `quality_flag` is not `PENDING` when it is approved, otherwise `ERR_SESSION_NOT_TALLIED` — and note that this precedes the session status check, so approving a never-tallied `OPEN` session reports the missing tally rather than the wrong status."

    PRD 2.7 rule 13: "On a tally, `culled_clamshells` is not greater than `clamshells_filled`, otherwise `ERR_CULL_EXCEEDS_TALLY`."

    PRD 2.7 rule 51: "Uniqueness holds, otherwise `ERR_DUPLICATE_RECORD`: a `Block` `name` is unique, a `CoolingTunnel` `name` is unique, a `PickSession` is unique per combination of `harvest_window_id`, `picker_id` and `work_date`, and a `PayrollRun` is unique per combination of `crew_id`, `period_start_date` and `period_end_date`."

    PRD 2.7 rule 56: "A pick session's `work_date` falls within the calendar dates spanned by its window, inclusive, otherwise `ERR_WORK_DATE_OUTSIDE_WINDOW`."

    Design: Corner/validations/open_window_session_writes_are_rejected_four_ways
    """
    block = x.register_block(
        api,
        name="BLK-V8",
        variety="STRAWBERRY",
        acres=8.00,
        planting_year=2021,
        irrigation_source_code="WELL-V8",
    )
    x.record_water_sample(
        api, block["id"], sample_date="2026-07-20", generic_ecoli_mpn=40
    )
    crew, pickers = x.certified_crew(
        api, picker_count=2, planned_head_count=2, name="CREW-V8"
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
    session = x.open_session(
        api, window["id"], pickers[0]["id"], work_date="2026-08-03"
    )

    validate_error(
        api.approve_pick_session(session["id"], u.PAYROLL_CLERK),
        e.ERR_SESSION_NOT_TALLIED,
        409,
    )
    validate_error(
        api.tally_pick_session(
            session["id"],
            f.tally_payload(hours_worked=3.00, clamshells_filled=10, culled_clamshells=11),
            u.CREW_SUPERVISOR,
        ),
        e.ERR_CULL_EXCEEDS_TALLY,
        400,
    )
    validate_error(
        api.create_pick_session(
            f.pick_session_payload(
                window["id"], pickers[0]["id"], work_date="2026-08-03"
            ),
            u.CREW_SUPERVISOR,
        ),
        e.ERR_DUPLICATE_RECORD,
        409,
    )
    validate_error(
        api.create_pick_session(
            f.pick_session_payload(
                window["id"], pickers[1]["id"], work_date="2026-08-05"
            ),
            u.CREW_SUPERVISOR,
        ),
        e.ERR_WORK_DATE_OUTSIDE_WINDOW,
        422,
    )

    stored = x.read_session(api, session["id"])
    a.assert_status(stored, "status", "OPEN")
    a.assert_status(stored, "quality_flag", "PENDING")
    a.assert_hours(stored["hours_worked"], 0.00, "session.hours_worked")
    assert stored["clamshells_filled"] == 0
    assert stored["culled_clamshells"] == 0
    assert stored["tally_revision_count"] == 0

    _, meta = x.list_sessions(api, harvest_window_id=window["id"])
    a.assert_page_meta(meta, expected_total=1)


def test_a_locked_run_freezes_its_session_its_crew_and_its_own_settlement(api):
    """
    Locking is a three-way freeze: the bound session can no longer be disputed,
    the crew cannot lock a second run even for a disjoint period, and that
    second run cannot be settled while it is still a draft.

    PRD 2.7 rule 32: "A session's `payroll_run_id` is still empty when it is disputed, otherwise `ERR_SESSION_PAYROLL_LOCKED`."

    PRD 2.7 rule 45: "No other payroll run of the same crew is already `LOCKED` when a run is locked, otherwise `ERR_CREW_RUN_ALREADY_LOCKED`."

    PRD 2.7 rule 33: "A payroll run is `DRAFT` when locked and `LOCKED` when settled, otherwise `ERR_INVALID_PAYROLL_STATE`."

    Design: Corner/validations/locked_payroll_run_blocks_dispute_second_lock_and_early_settle
    """
    block = x.register_block(
        api,
        name="BLK-V9",
        variety="STRAWBERRY",
        acres=8.00,
        planting_year=2021,
        irrigation_source_code="WELL-V9",
    )
    x.record_water_sample(
        api, block["id"], sample_date="2026-07-20", generic_ecoli_mpn=40
    )
    crew, pickers = x.certified_crew(api, picker_count=1, name="CREW-V9")
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
    first_run = x.open_payroll_run(
        api,
        crew["id"],
        period_start_date="2026-08-03",
        period_end_date="2026-08-03",
    )
    x.lock_payroll_run(api, first_run["id"])
    second_run = x.open_payroll_run(
        api,
        crew["id"],
        period_start_date="2026-08-04",
        period_end_date="2026-08-04",
    )

    validate_error(
        api.dispute_pick_session(
            session["id"],
            f.dispute_payload(dispute_reason_code="PICKER_CONTESTS_COUNT"),
            u.CREW_SUPERVISOR,
        ),
        e.ERR_SESSION_PAYROLL_LOCKED,
        409,
    )
    validate_error(
        api.lock_payroll_run(second_run["id"], u.PAYROLL_CLERK),
        e.ERR_CREW_RUN_ALREADY_LOCKED,
        409,
    )
    validate_error(
        api.settle_payroll_run(second_run["id"], u.PAYROLL_CLERK_2),
        e.ERR_INVALID_PAYROLL_STATE,
        409,
    )

    stored_session = x.read_session(api, session["id"])
    a.assert_status(stored_session, "status", "APPROVED")
    assert stored_session["payroll_run_id"] == first_run["id"]
    a.assert_cents(stored_session["net_cents"], 4950, "session.net_cents")

    stored_first = x.read_payroll_run(api, first_run["id"])
    a.assert_status(stored_first, "status", "LOCKED")
    assert stored_first["bound_session_count"] == 1

    stored_second = x.read_payroll_run(api, second_run["id"])
    a.assert_status(stored_second, "status", "DRAFT")
    assert stored_second["bound_session_count"] == 0
    a.assert_unset(stored_second, "settled_net_cents", "payroll_run")

    stored_crew = x.read_crew(api, crew["id"])
    a.assert_cents(stored_crew["accrued_wage_cents"], 4950, "crew.accrued_wage_cents")
    a.assert_cents(stored_crew["settled_wage_cents"], 0, "crew.settled_wage_cents")


def test_one_unresolved_session_blocks_the_whole_period_lock(api):
    """
    The quiet-period rule is an aggregate over the crew's sessions inside the
    period, so a single still-tallied row refuses the lock; and the disputed
    sibling cannot be re-approved back into the ledger.

    PRD 2.7 rule 34: "No session of the crew whose `work_date` falls inside the run's period is `OPEN`, `TALLIED` or `DISPUTED` at lock time, otherwise `ERR_PERIOD_HAS_UNRESOLVED_SESSIONS`."

    PRD 2.7 rule 31: "A session is `OPEN` or `DISPUTED` when tallied, `TALLIED` when approved, and `TALLIED` or `APPROVED` when disputed, otherwise `ERR_INVALID_SESSION_STATE`."

    PRD 3.4: "A dispute out of `APPROVED` does considerably more: the crew's `accrued_wage_cents` is reduced by exactly the same stored `net_cents` figure that approval added, `approved_by_user_id` is cleared, the picker's lifetime productivity and the window's `harvested_clamshells` are recomputed over the sessions that remain `APPROVED` or `SETTLED`, and the `version` of the session, crew, picker and window are each incremented by 1."

    Design: Corner/validations/unresolved_period_sessions_block_the_lock_and_a_disputed_session_cannot_be_approved
    """
    block = x.register_block(
        api,
        name="BLK-V10",
        variety="STRAWBERRY",
        acres=8.00,
        planting_year=2021,
        irrigation_source_code="WELL-V10",
    )
    x.record_water_sample(
        api, block["id"], sample_date="2026-07-20", generic_ecoli_mpn=40
    )
    crew, pickers = x.certified_crew(
        api, picker_count=2, planned_head_count=2, name="CREW-V10"
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
    tallied = x.tallied_session(
        api,
        window["id"],
        pickers[0]["id"],
        work_date="2026-08-03",
        hours_worked=3.00,
        clamshells_filled=20,
        culled_clamshells=0,
    )
    disputed = x.approved_session(
        api,
        window["id"],
        pickers[1]["id"],
        work_date="2026-08-03",
        hours_worked=3.00,
        clamshells_filled=20,
        culled_clamshells=0,
    )
    x.dispute_session(api, disputed["id"], reason_code="SUPERVISOR_RECOUNT")
    run = x.open_payroll_run(
        api,
        crew["id"],
        period_start_date="2026-08-03",
        period_end_date="2026-08-03",
    )

    validate_error(
        api.lock_payroll_run(run["id"], u.PAYROLL_CLERK),
        e.ERR_PERIOD_HAS_UNRESOLVED_SESSIONS,
        409,
    )
    validate_error(
        api.approve_pick_session(disputed["id"], u.PAYROLL_CLERK_2),
        e.ERR_INVALID_SESSION_STATE,
        409,
    )

    stored_run = x.read_payroll_run(api, run["id"])
    a.assert_status(stored_run, "status", "DRAFT")
    assert stored_run["bound_session_count"] == 0

    stored_tallied = x.read_session(api, tallied["id"])
    a.assert_status(stored_tallied, "status", "TALLIED")
    a.assert_unset(stored_tallied, "payroll_run_id", "session")

    stored_disputed = x.read_session(api, disputed["id"])
    a.assert_status(stored_disputed, "status", "DISPUTED")
    a.assert_cents(stored_disputed["net_cents"], 4950, "session.net_cents")

    stored_crew = x.read_crew(api, crew["id"])
    a.assert_cents(stored_crew["accrued_wage_cents"], 0, "crew.accrued_wage_cents")
