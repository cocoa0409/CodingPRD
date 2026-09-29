"""
The lifecycles of the season: crew recruitment through certification, the
harvest window from planning to closure, the manual food-safety hold, and the
two independent state dimensions a fruit lot carries.

Every test here drives one declared transition — or one declared refusal — of
PRD sections 3.1 through 3.6, and checks the side effects the PRD attaches to
it on the neighbouring resources.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_success,
)

from test_helpers import api_errors as e
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as x
from test_helpers import test_users as u


def test_first_picker_moves_a_recruiting_crew_to_staffed(api):
    """
    The first worker registered onto a fresh crew is what makes it staffed; the
    picker itself inherits the program and a one-year training clock.

    PRD 3.2: "Registering a picker recomputes the crew's `picker_count` and increments the crew's `version` by 1, and when that count moves from zero to one the crew advances `RECRUITING → STAFFED`."

    PRD 3.2: "Two things are derived at registration: the picker's `labor_program` is copied from the parent crew, and `hygiene_training_expires_on` is set to `hygiene_training_on` plus 365 days — one year of validity — remaining unset while `hygiene_training_on` is unset."

    Design: Corner/state_machines/crew_first_picker_moves_recruiting_to_staffed
    """
    crew = x.recruit_crew(
        api,
        name="CREW-SM1",
        labor_program="DOMESTIC",
        supervisor_user_id=u.SUP_1,
        planned_head_count=1,
        contract_start_date="2026-07-01",
        contract_end_date="2026-09-30",
    )
    a.assert_status(crew, "status", "RECRUITING")
    assert crew["picker_count"] == 0
    assert crew["version"] == 1

    response = api.create_picker(
        {
            "crew_id": crew["id"],
            "full_name": "First Picker",
            "hygiene_training_on": "2026-06-01",
        },
        u.CREW_SUPERVISOR,
    )
    picker = validate_success(response, 201)

    a.assert_status(picker, "labor_program", "DOMESTIC")
    assert picker["hygiene_training_on"] == "2026-06-01"
    assert picker["hygiene_training_expires_on"] == "2027-06-01"
    assert picker["version"] == 1

    stored_crew = x.read_crew(api, crew["id"])
    a.assert_status(stored_crew, "status", "STAFFED")
    assert stored_crew["picker_count"] == 1
    assert stored_crew["version"] == 2


def test_certifying_an_h2a_crew_short_of_transport_seats_is_refused(api):
    """
    Housing alone does not complete an H2A support plan: the seats are checked
    for every crew, so a two-bed plan with one seat cannot certify.

    PRD 3.2: "For every crew, `transport_route_code` must be present and `vehicle_seats` must be at least `planned_head_count`."

    PRD 3.2: "Only then is the support-plan gate checked: `support_plan_complete` must be true, otherwise `ERR_SUPPORT_PLAN_INCOMPLETE`."

    Design: Corner/state_machines/crew_certify_without_transport_seats_returns_support_plan_incomplete
    """
    crew = x.recruit_crew(
        api,
        name="CREW-SM2",
        labor_program="H2A",
        supervisor_user_id=u.SUP_1,
        planned_head_count=2,
        contract_start_date="2026-07-01",
        contract_end_date="2026-09-30",
    )
    for full_name in ("Picker SM2 A", "Picker SM2 B"):
        x.register_picker(
            api, crew["id"], full_name=full_name, hygiene_training_on="2026-06-01"
        )
    x.record_support_plan(
        api,
        crew["id"],
        2,
        housing_unit_code="H-SM2",
        beds_confirmed=2,
        transport_route_code="R-SM2",
        vehicle_seats=1,
    )

    response = api.certify_crew(crew["id"], u.HARVEST_MANAGER)
    validate_error(response, e.ERR_SUPPORT_PLAN_INCOMPLETE, 409)

    stored = x.read_crew(api, crew["id"])
    a.assert_status(stored, "status", "STAFFED")
    assert stored["support_plan_complete"] is False
    assert stored["vehicle_seats"] == 1
    assert stored["beds_confirmed"] == 2


def test_opening_a_window_flips_its_certified_crew_to_active(api):
    """
    A crew never becomes active by a call of its own: the first opening of one
    of its windows does it, alongside the window's own staffing figures.

    PRD 3.2: "A certified crew becomes `ACTIVE` the first time one of its harvest windows opens — the `CERTIFIED → ACTIVE` move is a side effect of that opening, not a call of its own, and it increments the crew's `version` by 1."

    PRD 3.3: "Opening increments the window's `version` by 1 and, when the crew was still `CERTIFIED`, advances it to `ACTIVE` and increments the crew's `version` by 1 as well."

    Design: Corner/state_machines/window_open_flips_crew_from_certified_to_active
    """
    block = x.register_block(
        api,
        name="BLK-SM3",
        variety="STRAWBERRY",
        acres=10.00,
        planting_year=2022,
        irrigation_source_code="WELL-SM3",
    )
    x.record_water_sample(
        api, block["id"], sample_date="2026-07-20", generic_ecoli_mpn=40
    )
    crew, _ = x.certified_crew(
        api,
        picker_count=1,
        planned_head_count=1,
        name="CREW-SM3",
        labor_program="DOMESTIC",
        support_plan={
            "housing_unit_code": "H-SM3",
            "beds_confirmed": 1,
            "transport_route_code": "R-SM3",
            "vehicle_seats": 1,
        },
    )
    a.assert_status(crew, "status", "CERTIFIED")

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
    x.confirm_window(api, window["id"])

    opened = validate_success(api.open_harvest_window(window["id"], u.HARVEST_MANAGER), 200)
    a.assert_status(opened, "status", "OPEN")
    assert opened["version"] == 3
    a.assert_hours(opened["window_hours"], 8.00, "window.window_hours")
    a.assert_rate(
        opened["effective_pick_rate_lbs_per_hour"], 22.00, "window.effective_pick_rate"
    )
    assert opened["required_picker_count"] == 1

    stored_crew = x.read_crew(api, crew["id"])
    a.assert_status(stored_crew, "status", "ACTIVE")
    assert stored_crew["version"] == 5


def test_closing_a_planned_window_is_refused_on_state(api):
    """
    Closing is admitted from `OPEN` alone, so a window that never left
    `PLANNED` cannot be closed.

    PRD 2.7 rule 28: "A window is `PLANNED` when confirmed, `CONFIRMED` when opened, `OPEN` when closed, `SUSPENDED` when resumed, and one of `PLANNED`, `CONFIRMED` or `SUSPENDED` when cancelled, otherwise `ERR_INVALID_WINDOW_STATE`."

    Design: Corner/state_machines/window_close_from_planned_returns_invalid_window_state
    """
    block = x.register_block(
        api,
        name="BLK-SM4",
        variety="STRAWBERRY",
        acres=5.00,
        planting_year=2022,
        irrigation_source_code="WELL-SM4",
    )
    crew = x.recruit_crew(api, name="CREW-SM4")
    window = x.plan_window(
        api,
        block["id"],
        crew["id"],
        start_at="2026-08-03T06:00:00Z",
        end_at="2026-08-03T14:00:00Z",
    )

    response = api.close_harvest_window(window["id"], u.HARVEST_MANAGER)
    validate_error(response, e.ERR_INVALID_WINDOW_STATE, 409)

    stored = x.read_window(api, window["id"])
    a.assert_status(stored, "status", "PLANNED")
    assert stored["version"] == 1
    a.assert_pounds(stored["packed_lbs"], 0.00, "window.packed_lbs")


def test_a_new_harvest_window_starts_planned_with_no_staffing_projection(api):
    """
    Planning derives the shift length but not the staffing estimate: both
    staffing fields stay unset until the window is confirmed.

    PRD 3.3: "On creation the window derives `window_hours`, the elapsed time from `start_at` to `end_at` expressed in hours and rounded half up to two decimals, and starts at `PLANNED` with `harvested_clamshells` 0, `packed_lbs` 0.00, no `effective_pick_rate_lbs_per_hour`, no `required_picker_count`, and neither `suspended_reason_code` nor `cancel_reason_code` set."

    Design: Corner/state_machines/harvest_window_starts_planned_with_null_staffing_projections
    """
    block = x.register_block(
        api,
        name="BLK-SM5",
        variety="BLACKBERRY",
        acres=5.00,
        planting_year=2022,
        irrigation_source_code="WELL-SM5",
    )
    crew = x.recruit_crew(api, name="CREW-SM5")

    response = api.create_harvest_window(
        f.harvest_window_payload(
            block["id"],
            crew["id"],
            start_at="2026-08-03T06:00:00Z",
            end_at="2026-08-03T14:00:00Z",
            forecast_brix=9.0,
            planned_volume_lbs=200.00,
            piece_rate_cents_per_clamshell=60,
            clamshell_net_weight_lbs=1.00,
        ),
        u.HARVEST_MANAGER,
    )
    window = validate_success(response, 201)
    a.assert_audit_triple(window, "window")

    a.assert_status(window, "status", "PLANNED")
    assert window["version"] == 1
    a.assert_hours(window["window_hours"], 8.00, "window.window_hours")
    a.assert_unset(window, "effective_pick_rate_lbs_per_hour", "window")
    a.assert_unset(window, "required_picker_count", "window")
    assert window["harvested_clamshells"] == 0
    a.assert_pounds(window["packed_lbs"], 0.00, "window.packed_lbs")
    a.assert_unset(window, "suspended_reason_code", "window")
    a.assert_unset(window, "cancel_reason_code", "window")


def test_cancelling_a_closed_window_is_refused_and_stores_no_reason(api):
    """
    `CLOSED` is terminal, so a late cancellation neither takes effect nor
    records the reason code it carried.

    PRD 3.3: "Cancellation is admitted from `PLANNED`, `CONFIRMED` and `SUSPENDED`, and from no other state."

    PRD 2.7 rule 28: "A window is `PLANNED` when confirmed, `CONFIRMED` when opened, `OPEN` when closed, `SUSPENDED` when resumed, and one of `PLANNED`, `CONFIRMED` or `SUSPENDED` when cancelled, otherwise `ERR_INVALID_WINDOW_STATE`."

    Design: Corner/state_machines/window_cancel_from_closed_is_rejected
    """
    block = x.register_block(
        api,
        name="BLK-SM6",
        variety="STRAWBERRY",
        acres=5.00,
        planting_year=2022,
        irrigation_source_code="WELL-SM6",
    )
    x.record_water_sample(
        api, block["id"], sample_date="2026-07-20", generic_ecoli_mpn=40
    )
    crew, _ = x.certified_crew(api, picker_count=1, name="CREW-SM6")
    window = x.plan_window(
        api,
        block["id"],
        crew["id"],
        start_at="2026-08-03T06:00:00Z",
        end_at="2026-08-03T14:00:00Z",
    )
    x.confirm_window(api, window["id"])
    x.open_window(api, window["id"])
    x.close_window(api, window["id"])

    response = api.cancel_harvest_window(
        window["id"],
        f.cancel_window_payload(cancel_reason_code="LATE_CANCEL"),
        u.HARVEST_MANAGER,
    )
    validate_error(response, e.ERR_INVALID_WINDOW_STATE, 409)

    stored = x.read_window(api, window["id"])
    a.assert_status(stored, "status", "CLOSED")
    a.assert_unset(stored, "cancel_reason_code", "window")
    assert stored["version"] == 4


def test_a_second_quarantine_on_a_held_block_is_refused(api):
    """
    A manual hold cannot be re-imposed: the second officer's reason code never
    displaces the first officer's.

    PRD 2.7 rule 25: "A block is not already under a manual hold when it is quarantined, and *is* under one when it is cleared, otherwise `ERR_INVALID_BLOCK_STATE`."

    PRD 3.1: "The block must not already be under a manual hold."

    Design: Corner/state_machines/second_quarantine_on_a_held_block_returns_invalid_block_state
    """
    block = x.register_block(
        api,
        name="BLK-SM7",
        variety="STRAWBERRY",
        acres=5.00,
        planting_year=2022,
        irrigation_source_code="WELL-SM7",
    )
    x.record_water_sample(
        api, block["id"], sample_date="2026-07-20", generic_ecoli_mpn=40
    )
    x.quarantine_block(api, block["id"], reason_code="WATER_INCIDENT")

    response = api.quarantine_block(
        block["id"],
        f.quarantine_payload(quarantine_reason_code="SECOND_ATTEMPT"),
        u.FOOD_SAFETY_OFFICER_2,
    )
    validate_error(response, e.ERR_INVALID_BLOCK_STATE, 409)

    stored = x.read_block(api, block["id"])
    assert stored["manual_quarantine_active"] is True
    a.assert_status(stored, "food_safety_posture", "QUARANTINED")
    assert stored["quarantined_by_user_id"] == u.FSO_1
    a.assert_status(stored, "quarantine_reason_code", "WATER_INCIDENT")
    assert stored["version"] == 3


def test_rejecting_a_cooling_lot_leaves_the_cold_chain_dimension_untouched(api):
    """
    The two lot dimensions are independent: rejection moves the disposition to
    `REJECTED` while the cold chain stays `COOLING` and the tunnel slots stay
    booked.

    PRD 3.6: "Rejection sets `food_safety_hold` true, drives `available_lbs` to 0.00, moves the lot to `REJECTED`, recomputes the parent window's `packed_lbs`, and increments the lot's and the window's `version` by 1."

    PRD 3.6 admits it from the cold chain mid-run: "A `PackhouseOperator` or `FoodSafetyOfficer` may reject a lot with a `reject_reason_code`, from `disposition_status` `UNCOMMITTED` or `RESERVED` and only while the lot's `cold_chain_status` is not yet `SHIPPED` — fruit already on the truck cannot be rejected."

    Design: Corner/state_machines/lot_reject_while_cooling_leaves_the_cold_chain_dimension_untouched
    """
    block = x.register_block(
        api,
        name="BLK-SM8",
        variety="STRAWBERRY",
        acres=5.00,
        planting_year=2022,
        irrigation_source_code="WELL-SM8",
    )
    crew = x.recruit_crew(api, name="CREW-SM8")
    window = x.plan_window(
        api,
        block["id"],
        crew["id"],
        start_at="2026-08-03T06:00:00Z",
        end_at="2026-08-03T18:00:00Z",
    )
    tunnel = x.register_tunnel(api, name="TUN-SM8", slot_capacity=4, target_pulp_temp_f=34.0)
    lot = x.pack_lot(
        api,
        window["id"],
        block["id"],
        variety="STRAWBERRY",
        grade="A",
        clamshell_count=100,
        clamshell_net_weight_lbs=1.00,
        pick_date="2026-08-03",
        pack_completed_at="2026-08-03T06:00:00Z",
        field_pulp_temp_f=70.0,
    )
    x.start_cooling(
        api,
        lot["id"],
        tunnel["id"],
        expected_version=tunnel["version"],
        cool_start_at="2026-08-03T07:00:00Z",
        planned_cool_end_at="2026-08-03T11:00:00Z",
        entry_pulp_temp_f=62.0,
        pallet_slots=1,
    )

    response = api.reject_fruit_lot(
        lot["id"],
        f.reject_lot_payload(reject_reason_code="SOFT_FRUIT"),
        u.PACKHOUSE_OPERATOR,
    )
    rejected = validate_success(response, 200)

    a.assert_status(rejected, "disposition_status", "REJECTED")
    a.assert_status(rejected, "reject_reason_code", "SOFT_FRUIT")
    a.assert_status(rejected, "cold_chain_status", "COOLING")
    assert rejected["food_safety_hold"] is True
    a.assert_pounds(rejected["available_lbs"], 0.00, "lot.available_lbs")
    a.assert_pounds(rejected["net_packed_lbs"], 100.00, "lot.net_packed_lbs")

    stored_tunnel = x.read_tunnel(api, tunnel["id"])
    assert stored_tunnel["committed_slots"] == 1

    stored_window = x.read_window(api, window["id"])
    a.assert_pounds(stored_window["packed_lbs"], 0.00, "window.packed_lbs")


def test_clearing_a_hold_frees_the_lots_but_leaves_windows_suspended(api):
    """
    Lifting a manual hold is deliberately partial: the lots come off hold, the
    suspended window does not come back on its own.

    PRD 3.1: "Clearing sets `manual_quarantine_active` back to false, recomputes the posture to `CLEARED`, and sets `food_safety_hold` back to false on every lot of the block whose `disposition_status` is `UNCOMMITTED` or `RESERVED`."

    PRD 3.1: "What it emphatically does **not** do is resume the suspended windows: those stay `SUSPENDED` until a `HarvestManager` resumes each one explicitly, because the decision to put a crew back on a previously contaminated block is a human one."

    Design: Corner/state_machines/block_clear_lifts_food_safety_hold_but_leaves_windows_suspended
    """
    block = x.register_block(
        api,
        name="BLK-SM9",
        variety="STRAWBERRY",
        acres=5.00,
        planting_year=2022,
        irrigation_source_code="WELL-SM9",
    )
    x.record_water_sample(
        api, block["id"], sample_date="2026-07-20", generic_ecoli_mpn=40
    )
    crew, _ = x.certified_crew(api, picker_count=1, name="CREW-SM9")
    window = x.plan_window(
        api,
        block["id"],
        crew["id"],
        start_at="2026-08-03T06:00:00Z",
        end_at="2026-08-03T18:00:00Z",
    )
    x.confirm_window(api, window["id"])
    lot = x.pack_lot(
        api,
        window["id"],
        block["id"],
        variety="STRAWBERRY",
        grade="A",
        clamshell_count=50,
        clamshell_net_weight_lbs=1.00,
        pick_date="2026-08-03",
        pack_completed_at="2026-08-03T08:00:00Z",
        field_pulp_temp_f=68.0,
    )
    x.quarantine_block(api, block["id"], reason_code="ADJACENT_LIVESTOCK")
    x.record_water_sample(
        api, block["id"], sample_date="2026-07-26", generic_ecoli_mpn=50
    )

    response = api.clear_block(block["id"], u.FOOD_SAFETY_OFFICER_2)
    cleared = validate_success(response, 200)

    assert cleared["manual_quarantine_active"] is False
    a.assert_status(cleared, "food_safety_posture", "CLEARED")
    a.assert_status(cleared, "water_status", "PROVISIONAL")
    assert cleared["water_sample_count"] == 2

    stored_lot = x.read_lot(api, lot["id"])
    assert stored_lot["food_safety_hold"] is False
    a.assert_status(stored_lot, "disposition_status", "UNCOMMITTED")

    stored_window = x.read_window(api, window["id"])
    a.assert_status(stored_window, "status", "SUSPENDED")
    a.assert_status(stored_window, "suspended_reason_code", "BLOCK_QUARANTINE")


def test_resuming_a_suspended_window_returns_it_to_confirmed(api):
    """
    Recovery from a quarantine suspension lands on `CONFIRMED`, not on `OPEN`,
    and re-derives the staffing requirement on the way.

    PRD 3.3: "Resuming clears `suspended_reason_code`, recomputes `required_picker_count` from the same staffing rule (the forecast may now imply a different crew size), and increments the window's `version` by 1."

    PRD 3.3: "Critically, a resume returns the window to `CONFIRMED` and never straight to `OPEN`: the whole opening gate — block posture, crew status, picker count and the clock — must be passed again."

    Design: Corner/state_machines/window_resume_returns_to_confirmed_and_recomputes_required_picker_count
    """
    block = x.register_block(
        api,
        name="BLK-SM10",
        variety="STRAWBERRY",
        acres=5.00,
        planting_year=2022,
        irrigation_source_code="WELL-SM10",
    )
    x.record_water_sample(
        api, block["id"], sample_date="2026-07-20", generic_ecoli_mpn=40
    )
    crew, _ = x.certified_crew(api, picker_count=1, name="CREW-SM10")
    window = x.plan_window(
        api,
        block["id"],
        crew["id"],
        start_at="2026-08-03T06:00:00Z",
        end_at="2026-08-03T14:00:00Z",
    )
    x.confirm_window(api, window["id"])
    x.quarantine_block(api, block["id"], reason_code="ADJACENT_LIVESTOCK")
    x.record_water_sample(
        api, block["id"], sample_date="2026-07-26", generic_ecoli_mpn=50
    )
    x.clear_block(api, block["id"], u.FOOD_SAFETY_OFFICER_2)

    response = api.resume_harvest_window(window["id"], u.HARVEST_MANAGER)
    resumed = validate_success(response, 200)

    a.assert_status(resumed, "status", "CONFIRMED")
    a.assert_unset(resumed, "suspended_reason_code", "window")
    assert resumed["required_picker_count"] == 1
    a.assert_rate(
        resumed["effective_pick_rate_lbs_per_hour"], 22.00, "window.effective_pick_rate"
    )
    assert resumed["version"] == 4


def test_locking_binds_only_approved_sessions_inside_the_period(api):
    """
    The lock stamps exactly the approved sessions whose work date falls inside
    the period; a sibling day's approved session keeps an empty run reference
    and its money stays on the crew ledger.

    PRD 3.5: "Locking then binds the set: every pick session of that crew whose status is `APPROVED`, whose `work_date` lies inside the inclusive period, and whose `payroll_run_id` is still empty, has its `payroll_run_id` stamped with this run's `id`."

    PRD 3.5: "From the stamped set the run records `bound_session_count`, `period_hours` as the sum of `hours_worked` to two decimals, `period_piece_cents` as the sum of `piece_cents`, and `accrued_gross_cents` as the sum of `gross_cents` — the per-session figure, captured for comparison."

    Design: Corner/state_machines/payroll_lock_binds_only_approved_sessions_inside_the_period
    """
    block_a = x.register_block(
        api,
        name="BLK-SM11A",
        variety="STRAWBERRY",
        acres=5.00,
        planting_year=2022,
        irrigation_source_code="WELL-SM11",
    )
    block_b = x.register_block(
        api,
        name="BLK-SM11B",
        variety="STRAWBERRY",
        acres=5.00,
        planting_year=2022,
        irrigation_source_code="WELL-SM11",
    )
    for block_id in (block_a["id"], block_b["id"]):
        x.record_water_sample(
            api, block_id, sample_date="2026-07-20", generic_ecoli_mpn=40
        )
    crew, pickers = x.certified_crew(
        api, picker_count=2, planned_head_count=2, name="CREW-SM11"
    )
    first_picker, second_picker = pickers

    window_a = x.opened_window(
        api,
        block_a["id"],
        crew["id"],
        start_at="2026-08-03T06:00:00Z",
        end_at="2026-08-03T14:00:00Z",
    )
    window_b = x.opened_window(
        api,
        block_b["id"],
        crew["id"],
        start_at="2026-08-04T06:00:00Z",
        end_at="2026-08-04T14:00:00Z",
    )

    session_one = x.approved_session(
        api,
        window_a["id"],
        first_picker["id"],
        work_date="2026-08-03",
        hours_worked=3.00,
        clamshells_filled=20,
    )
    session_two = x.approved_session(
        api,
        window_a["id"],
        second_picker["id"],
        work_date="2026-08-03",
        hours_worked=3.00,
        clamshells_filled=200,
    )
    session_three = x.approved_session(
        api,
        window_b["id"],
        first_picker["id"],
        work_date="2026-08-04",
        hours_worked=2.00,
        clamshells_filled=10,
    )
    run = x.open_payroll_run(
        api,
        crew["id"],
        period_start_date="2026-08-03",
        period_end_date="2026-08-03",
    )

    response = api.lock_payroll_run(run["id"], u.PAYROLL_CLERK)
    locked = validate_success(response, 200)

    a.assert_status(locked, "status", "LOCKED")
    assert locked["locked_by_user_id"] == u.CLERK_1
    assert locked["bound_session_count"] == 2
    a.assert_hours(locked["period_hours"], 6.00, "run.period_hours")
    a.assert_cents(locked["period_piece_cents"], 9900, "run.period_piece_cents")
    a.assert_cents(locked["accrued_gross_cents"], 13950, "run.accrued_gross_cents")

    assert x.read_session(api, session_one["id"])["payroll_run_id"] == run["id"]
    assert x.read_session(api, session_two["id"])["payroll_run_id"] == run["id"]

    unbound = x.read_session(api, session_three["id"])
    a.assert_unset(unbound, "payroll_run_id", "session")
    a.assert_status(unbound, "status", "APPROVED")
    a.assert_cents(unbound["net_cents"], 3300, "session.net_cents")

    stored_crew = x.read_crew(api, crew["id"])
    a.assert_cents(stored_crew["accrued_wage_cents"], 17250, "crew.accrued_wage_cents")


def test_repacking_emits_a_child_lot_derated_by_one_day(api):
    """
    The sorter creates a child lot that inherits the cooling run but loses a
    day of shelf life for the handling, while the source is retired.

    PRD 3.6: "The child's `verified_shelf_life_days` is **not** recomputed from the decay formula: it is the source lot's verified figure less one day for the handling, floored at 1, and its `shelf_life_expires_on` is the calendar date of the source lot's `cool_complete_at` advanced by the child's own `verified_shelf_life_days`."

    PRD 3.6: "The source lot stamps `repack_out_lbs`, `cull_lbs` and `optical_reject_lbs` from the three counts at the shared clamshell weight, has its `available_lbs` driven to 0.00, moves `disposition_status` `UNCOMMITTED → REPACKED`, and has its `version` incremented by 1."

    Design: Corner/state_machines/fruit_lot_repack_creates_child_lot_derated_by_one_day
    """
    block = x.register_block(
        api,
        name="BLK-SM12",
        variety="STRAWBERRY",
        acres=5.00,
        planting_year=2022,
        irrigation_source_code="WELL-SM12",
    )
    crew = x.recruit_crew(api, name="CREW-SM12")
    window = x.plan_window(
        api,
        block["id"],
        crew["id"],
        start_at="2026-08-03T06:00:00Z",
        end_at="2026-08-03T18:00:00Z",
        clamshell_net_weight_lbs=0.75,
    )
    tunnel = x.register_tunnel(
        api, name="TUN-SM12", slot_capacity=4, target_pulp_temp_f=34.0
    )
    source = x.cooled_lot(
        api,
        window["id"],
        block["id"],
        tunnel["id"],
        cool_start_at="2026-08-03T07:00:00Z",
        planned_cool_end_at="2026-08-03T11:00:00Z",
        cool_complete_at="2026-08-03T11:00:00Z",
        exit_pulp_temp_f=34.0,
        entry_pulp_temp_f=62.0,
        pallet_slots=1,
        variety="STRAWBERRY",
        grade="A",
        clamshell_count=100,
        clamshell_net_weight_lbs=0.75,
        pick_date="2026-08-03",
        pack_completed_at="2026-08-03T06:00:00Z",
        field_pulp_temp_f=70.0,
    )
    assert source["verified_shelf_life_days"] == 7

    response = api.repack_fruit_lot(
        source["id"],
        f.repack_payload(60, 25, 15, output_grade="B"),
        u.PACKHOUSE_OPERATOR,
    )
    child = validate_success(response, 201)
    a.assert_audit_triple(child, "child lot")

    assert child["source_lot_id"] == source["id"]
    a.assert_status(child, "grade", "B")
    assert child["clamshell_count"] == 60
    a.assert_pounds(
        child["clamshell_net_weight_lbs"], 0.75, "child.clamshell_net_weight_lbs"
    )
    a.assert_pounds(child["net_packed_lbs"], 45.00, "child.net_packed_lbs")
    a.assert_pounds(child["available_lbs"], 45.00, "child.available_lbs")
    assert child["verified_shelf_life_days"] == 6
    assert child["shelf_life_expires_on"] == "2026-08-09"
    a.assert_status(child, "cold_chain_status", "COOLED")
    a.assert_status(child, "disposition_status", "UNCOMMITTED")
    a.assert_status(child, "variety", "STRAWBERRY")
    assert child["pick_date"] == "2026-08-03"
    assert child["traceability_code"] == "BLK-SM12-20260803-B-001"

    stored_source = x.read_lot(api, source["id"])
    a.assert_status(stored_source, "disposition_status", "REPACKED")
    assert stored_source["verified_shelf_life_days"] == 7
    a.assert_pounds(stored_source["repack_out_lbs"], 45.00, "source.repack_out_lbs")
    a.assert_pounds(stored_source["cull_lbs"], 18.75, "source.cull_lbs")
    a.assert_pounds(
        stored_source["optical_reject_lbs"], 11.25, "source.optical_reject_lbs"
    )
    a.assert_pounds(stored_source["available_lbs"], 0.00, "source.available_lbs")


def test_releasing_a_crew_that_still_holds_accrued_wages_is_refused(api):
    """
    A quiet schedule is not enough to release a crew: an approved but unsettled
    session leaves money on the ledger, and the release is refused.

    PRD 3.2: "No harvest window of the crew may be `CONFIRMED`, `OPEN` or `SUSPENDED`; no pick session of any of the crew's pickers may be `OPEN`, `TALLIED` or `DISPUTED`; and the crew's `accrued_wage_cents` must be exactly 0."

    PRD 2.7 rule 64: "A crew being released holds no accrued wages, no live window and no unresolved session, otherwise `ERR_CREW_LEDGER_NOT_CLEAR`."

    Design: Corner/state_machines/crew_release_with_accrued_wages_returns_ledger_not_clear
    """
    block = x.register_block(
        api,
        name="BLK-SM13",
        variety="STRAWBERRY",
        acres=5.00,
        planting_year=2022,
        irrigation_source_code="WELL-SM13",
    )
    x.record_water_sample(
        api, block["id"], sample_date="2026-07-20", generic_ecoli_mpn=40
    )
    crew, pickers = x.certified_crew(api, picker_count=1, name="CREW-SM13")
    window = x.opened_window(
        api,
        block["id"],
        crew["id"],
        start_at="2026-08-03T06:00:00Z",
        end_at="2026-08-03T14:00:00Z",
    )
    x.approved_session(
        api,
        window["id"],
        pickers[0]["id"],
        work_date="2026-08-03",
        hours_worked=3.00,
        clamshells_filled=20,
    )
    x.close_window(api, window["id"])

    response = api.release_crew(crew["id"], u.HARVEST_MANAGER)
    validate_error(response, e.ERR_CREW_LEDGER_NOT_CLEAR, 422)

    stored_crew = x.read_crew(api, crew["id"])
    a.assert_status(stored_crew, "status", "ACTIVE")
    a.assert_cents(stored_crew["accrued_wage_cents"], 4950, "crew.accrued_wage_cents")

    stored_window = x.read_window(api, window["id"])
    a.assert_status(stored_window, "status", "CLOSED")
    assert stored_window["harvested_clamshells"] == 20
