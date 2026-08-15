"""Route-stop execution: departure gates, the weather pause/resume cycle,
completion guards, and season-state gating of stop transitions."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_machine,
    assert_version_incremented,
    complete_stop,
    create_active_season,
    create_committed_contract,
    create_route_stop,
    create_season,
    drive_stop_to_cutting,
    drive_stop_to_en_route,
    get_stop,
    open_settlement_window,
    pause_stop,
    reserve_machine,
    set_actual_acres,
    setup_cutting_stop,
    validate_error,
    validate_success,
)

OPERATOR = TEST_USERS["harvest_operator_headers"]


def test_pause_resume_pause_cycle(api, crew_boss_headers):
    """PRD section 3.4: "From `CUTTING`, the crew boss may pause for weather
    (`CUTTING → PAUSED_WEATHER`; a stop not in `CUTTING` yields
    `ERR_STOP_NOT_CUTTING`, HTTP 409), and from `PAUSED_WEATHER` may resume
    (`PAUSED_WEATHER → CUTTING`; a stop not paused yields
    `ERR_STOP_NOT_PAUSED`, HTTP 409)."

    Design: Difficulty/non_linear_state_machine/route_stop_cutting_paused_cutting_cycle_on_weather
    """
    ctx = setup_cutting_stop()
    stop_id = ctx["stop"]["id"]

    paused = validate_success(api.pause_weather(stop_id, crew_boss_headers))
    assert paused["status"] == "PAUSED_WEATHER", (
        f"first pause must yield PAUSED_WEATHER, got {paused['status']!r}"
    )
    resumed = validate_success(api.resume_route_stop(stop_id, crew_boss_headers))
    assert resumed["status"] == "CUTTING", (
        f"resume must return the stop to CUTTING, got {resumed['status']!r}"
    )
    paused_again = validate_success(api.pause_weather(stop_id, crew_boss_headers))
    assert paused_again["status"] == "PAUSED_WEATHER", (
        f"second pause must yield PAUSED_WEATHER again, got {paused_again['status']!r}"
    )


def test_actual_acres_editable_while_paused(api, crew_boss_headers):
    """PRD section 3.4: "While paused or cutting, the crew boss continues to
    update `actual_acres` as the acres accumulate."
    PRD section 3.2: "Stops also record `actual_acres`, the acres actually
    cut, which starts at 0 and is editable by the `CrewBoss` only while the
    stop is `CUTTING` or `PAUSED_WEATHER`; each edit increments the stop's
    `version`."

    Design: Difficulty/non_linear_state_machine/route_stop_cutting_paused_cutting_cycle_on_weather
    """
    ctx = setup_cutting_stop()
    stop_id = ctx["stop"]["id"]
    pause_stop(stop_id)
    before = get_stop(stop_id)

    updated = validate_success(
        api.update_route_stop(stop_id, {"actual_acres": 25}, crew_boss_headers)
    )
    assert updated["status"] == "PAUSED_WEATHER"
    assert updated["actual_acres"] == 25, (
        f"actual_acres edit while paused must stick, got {updated['actual_acres']!r}"
    )
    assert_version_incremented(updated["version"], before["version"])


def test_depart_out_of_sequence_blocked(api, crew_boss_headers):
    """PRD section 3.4: "no other stop in the same season with a strictly
    smaller `sequence_index` is still in `SCHEDULED`, `EN_ROUTE`, `CUTTING`,
    or `PAUSED_WEATHER` (otherwise `ERR_OUT_OF_SEQUENCE`, HTTP 409) — the
    route runs in order, and an earlier-indexed stop still in any active state
    blocks later departures."

    Design: Corner/validations/depart_out_of_sequence_blocked
    """
    ctx = create_active_season(num_combines=2)
    contract = create_committed_contract(ctx["season"]["id"], committed_acres=200)
    create_route_stop(contract["id"], sequence_index=1,
                      planned_start_date="2026-08-05", planned_end_date="2026-08-06")
    stop2 = create_route_stop(contract["id"], sequence_index=2,
                              planned_start_date="2026-08-08", planned_end_date="2026-08-09")
    reserve_machine(stop2["id"], ctx["machines"][1]["id"],
                    assigned_start_date="2026-08-08", assigned_end_date="2026-08-10")

    resp = api.depart_route_stop(stop2["id"], crew_boss_headers)
    validate_error(resp, ApiErrorId.ERR_OUT_OF_SEQUENCE)


def test_depart_without_combine_assigned_blocked(api, crew_boss_headers):
    """PRD section 3.4: "the stop has at least one machine assignment in
    `RESERVED` or `DEPLOYED` whose machine is of kind `COMBINE` (otherwise
    `ERR_NO_COMBINE_ASSIGNED`, HTTP 409)".

    Design: Corner/validations/depart_without_combine_assigned_blocked
    """
    season = create_season()
    add_machine(season["id"], machine_kind="COMBINE", label="C1")
    cart = add_machine(season["id"], machine_kind="GRAIN_CART", label="GC1",
                       daily_capacity_acres=500)
    validate_success(api.activate_season(season["id"], OPERATOR))
    contract = create_committed_contract(season["id"])
    stop = create_route_stop(contract["id"], sequence_index=1)
    reserve_machine(stop["id"], cart["id"])

    resp = api.depart_route_stop(stop["id"], crew_boss_headers)
    validate_error(resp, ApiErrorId.ERR_NO_COMBINE_ASSIGNED)


def test_second_depart_rejected_not_scheduled(api, crew_boss_headers):
    """PRD section 3.4: "the stop is `SCHEDULED` (otherwise
    `ERR_STOP_NOT_SCHEDULED`, HTTP 409)".
    PRD section 2.6: "When several checks could reject the same request, the
    system evaluates them in a fixed order so that the returned error is
    deterministic." (state legality is evaluated before business rules).

    Design: Difficulty/priority_pair_validation_conflict/state_before_business_temporal_on_depart
    """
    ctx = create_active_season()
    contract = create_committed_contract(ctx["season"]["id"])
    stop = create_route_stop(contract["id"], sequence_index=1)
    drive_stop_to_en_route(stop["id"], ctx["machine"]["id"])

    resp = api.depart_route_stop(stop["id"], crew_boss_headers)
    validate_error(resp, ApiErrorId.ERR_STOP_NOT_SCHEDULED)


def test_depart_completed_stop_rejected_not_scheduled(api, crew_boss_headers):
    """PRD section 3.4: "the stop is `SCHEDULED` (otherwise
    `ERR_STOP_NOT_SCHEDULED`, HTTP 409)" — a stop that has already reached
    `COMPLETED` is no longer `SCHEDULED`, so departure is rejected with the
    state error.

    Design: Difficulty/priority_pair_validation_conflict/state_before_business_temporal_on_depart
    """
    ctx = create_active_season()
    contract = create_committed_contract(ctx["season"]["id"])
    stop = create_route_stop(contract["id"], sequence_index=1)
    drive_stop_to_cutting(stop["id"], ctx["machine"]["id"])
    set_actual_acres(stop["id"], 100)
    complete_stop(stop["id"])

    resp = api.depart_route_stop(stop["id"], crew_boss_headers)
    validate_error(resp, ApiErrorId.ERR_STOP_NOT_SCHEDULED)


def test_complete_on_scheduled_stop_rejected_not_cutting(api, crew_boss_headers):
    """PRD section 3.4: "The stop must be `CUTTING` (otherwise
    `ERR_STOP_NOT_CUTTING`), `actual_acres` must be greater than zero, and
    `actual_acres` must not exceed one hundred ten percent of `planned_acres`
    — an overrun beyond that ceiling is rejected with `ERR_ACRES_OVERRUN`
    (HTTP 422)."
    PRD section 2.6: "When several checks could reject the same request, the
    system evaluates them in a fixed order so that the returned error is
    deterministic." (state legality is evaluated before business rules).

    Design: Difficulty/priority_pair_validation_conflict/business_temporal_before_business_constraint_on_complete
    """
    ctx = create_active_season()
    contract = create_committed_contract(ctx["season"]["id"])
    stop = create_route_stop(contract["id"], sequence_index=1)

    resp = api.complete_route_stop(stop["id"], crew_boss_headers)
    validate_error(resp, ApiErrorId.ERR_STOP_NOT_CUTTING)


def test_complete_on_en_route_stop_rejected_not_cutting(api, crew_boss_headers):
    """PRD section 3.4: "The stop must be `CUTTING` (otherwise
    `ERR_STOP_NOT_CUTTING`)" — an `EN_ROUTE` stop has not begun cutting, so
    completion is rejected with the state error.

    Design: Difficulty/priority_pair_validation_conflict/business_temporal_before_business_constraint_on_complete
    """
    ctx = create_active_season()
    contract = create_committed_contract(ctx["season"]["id"])
    stop = create_route_stop(contract["id"], sequence_index=1)
    drive_stop_to_en_route(stop["id"], ctx["machine"]["id"])

    resp = api.complete_route_stop(stop["id"], crew_boss_headers)
    validate_error(resp, ApiErrorId.ERR_STOP_NOT_CUTTING)


def test_route_stop_resume_from_cutting_returns_not_paused(api, crew_boss_headers):
    """PRD section 3.4: "from `PAUSED_WEATHER` may resume
    (`PAUSED_WEATHER → CUTTING`; a stop not paused yields
    `ERR_STOP_NOT_PAUSED`, HTTP 409)".

    Design: Corner/state_machines/route_stop_resume_from_cutting_returns_not_paused
    """
    ctx = setup_cutting_stop()
    resp = api.resume_route_stop(ctx["stop"]["id"], crew_boss_headers)
    validate_error(resp, ApiErrorId.ERR_STOP_NOT_PAUSED)


def test_complete_overrun_acres_rejected(api, crew_boss_headers):
    """PRD section 3.4: "`actual_acres` must not exceed one hundred ten
    percent of `planned_acres` — an overrun beyond that ceiling is rejected
    with `ERR_ACRES_OVERRUN` (HTTP 422)."

    Design: Corner/validations/complete_overrun_acres_rejected
    """
    ctx = setup_cutting_stop(planned_acres=100)
    stop_id = ctx["stop"]["id"]
    set_actual_acres(stop_id, 120)

    resp = api.complete_route_stop(stop_id, crew_boss_headers)
    validate_error(resp, ApiErrorId.ERR_ACRES_OVERRUN)


def test_depart_after_open_settlement_cascade_rejected(api, crew_boss_headers):
    """PRD section 3.8: "Opening settlement force-resolves the stragglers:
    every stop still in `SCHEDULED` transitions to `SKIPPED`".
    PRD section 3.4: "the stop is `SCHEDULED` (otherwise
    `ERR_STOP_NOT_SCHEDULED`, HTTP 409)".

    Design: Difficulty/cross_entity_state_dependency/route_stop_complete_requires_season_active_not_settling
    """
    ctx = create_active_season()
    contract = create_committed_contract(ctx["season"]["id"], committed_acres=200)
    stop1 = create_route_stop(contract["id"], sequence_index=1,
                              planned_start_date="2026-08-05", planned_end_date="2026-08-06")
    drive_stop_to_cutting(stop1["id"], ctx["machine"]["id"],
                          assigned_start_date="2026-08-05", assigned_end_date="2026-08-07")
    set_actual_acres(stop1["id"], 100)
    complete_stop(stop1["id"])
    stop2 = create_route_stop(contract["id"], sequence_index=2,
                              planned_start_date="2026-08-10", planned_end_date="2026-08-11")

    open_settlement_window(ctx["season"]["id"])

    stop2_now = get_stop(stop2["id"])
    assert stop2_now["status"] == "SKIPPED", (
        f"open-settlement must cascade a still-SCHEDULED stop to SKIPPED, got {stop2_now['status']!r}"
    )
    resp = api.depart_route_stop(stop2["id"], crew_boss_headers)
    validate_error(resp, ApiErrorId.ERR_STOP_NOT_SCHEDULED)


def test_depart_requires_active_season(api, crew_boss_headers):
    """PRD section 3.4: "the parent season is `ACTIVE` (otherwise
    `ERR_SEASON_NOT_ACTIVE`, HTTP 409)".

    Design: Difficulty/cross_entity_state_dependency/route_stop_complete_requires_season_active_not_settling
    """
    season = create_season()
    machine = add_machine(season["id"])
    contract = create_committed_contract(season["id"])
    stop = create_route_stop(contract["id"], sequence_index=1)
    reserve_machine(stop["id"], machine["id"])

    resp = api.depart_route_stop(stop["id"], crew_boss_headers)
    validate_error(resp, ApiErrorId.ERR_SEASON_NOT_ACTIVE)
