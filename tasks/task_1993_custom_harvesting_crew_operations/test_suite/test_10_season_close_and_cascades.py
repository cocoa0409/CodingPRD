"""Season settlement-window cascade, close preconditions, season OCC, and
the harvested-acres conservation invariant."""
from test_helpers import (
    ApiErrorId,
    activate_season,
    add_machine,
    create_active_season,
    create_committed_contract,
    create_route_stop,
    create_season,
    drive_stop_to_cutting,
    get_assignment,
    get_contract,
    get_machine,
    get_season,
    get_stop,
    open_settlement_window,
    reserve_machine,
    set_actual_acres,
    complete_stop,
    setup_issued_settlement,
    skip_stop,
    validate_error,
    validate_success,
)


def test_open_settlement_with_running_stops_blocked(api, harvest_operator_headers):
    """PRD section 3.8: "The season must be `ACTIVE` (otherwise
    `ERR_SEASON_NOT_ACTIVE`), and no route stop in the season may still be in
    `EN_ROUTE`, `CUTTING`, or `PAUSED_WEATHER` (otherwise
    `ERR_STOPS_STILL_RUNNING`, HTTP 409)."

    Design: Corner/validations/open_settlement_with_running_stops_blocked
    """
    ctx = create_active_season()
    contract = create_committed_contract(ctx["season"]["id"])
    stop = create_route_stop(contract["id"], sequence_index=1)
    drive_stop_to_cutting(stop["id"], ctx["machine"]["id"])

    resp = api.open_settlement(ctx["season"]["id"], harvest_operator_headers)
    validate_error(resp, ApiErrorId.ERR_STOPS_STILL_RUNNING)


def test_open_settlement_cascades(api, harvest_operator_headers):
    """PRD section 3.8: "Opening settlement force-resolves the stragglers:
    every stop still in `SCHEDULED` transitions to `SKIPPED`, each such
    stop's `RESERVED` assignments transition to `CANCELLED`, and each machine
    those assignments held returns to `AVAILABLE` if it was `ASSIGNED` and is
    not allocated to any other `RESERVED` or `DEPLOYED` assignment."

    Design: Difficulty/transitive_cascade/open_settlement_cascades_season_stop_assignment_machine
    """
    ctx = create_active_season(num_combines=2)
    m1, m2 = ctx["machines"][0], ctx["machines"][1]
    contract = create_committed_contract(ctx["season"]["id"], committed_acres=200)

    stop1 = create_route_stop(contract["id"], sequence_index=1,
                              planned_start_date="2026-08-05", planned_end_date="2026-08-06")
    drive_stop_to_cutting(stop1["id"], m1["id"],
                          assigned_start_date="2026-08-05", assigned_end_date="2026-08-07")
    set_actual_acres(stop1["id"], 100)
    complete_stop(stop1["id"])

    stop2 = create_route_stop(contract["id"], sequence_index=2,
                              planned_start_date="2026-08-10", planned_end_date="2026-08-11")
    asg2 = reserve_machine(stop2["id"], m2["id"],
                           assigned_start_date="2026-08-10", assigned_end_date="2026-08-12")

    season_now = validate_success(api.open_settlement(ctx["season"]["id"], harvest_operator_headers))
    assert season_now["status"] == "SETTLING", (
        f"season must enter SETTLING, got {season_now['status']!r}"
    )
    assert get_stop(stop2["id"])["status"] == "SKIPPED"
    assert get_assignment(asg2["id"])["status"] == "CANCELLED", (
        "the skipped stop's RESERVED assignment must cascade to CANCELLED"
    )
    assert get_machine(m2["id"])["status"] == "AVAILABLE", (
        "the cancelled assignment's machine must return to AVAILABLE"
    )


def test_open_settlement_cascade_preserves_completed_stops(api, harvest_operator_headers):
    """PRD section 3.8: "Opening settlement force-resolves the stragglers:
    every stop still in `SCHEDULED` transitions to `SKIPPED`" — only stops
    still in `SCHEDULED` move; a stop already `COMPLETED` keeps its state and
    its recorded acres.
    PRD section 3.1: "`harvested_acres_total`, the sum of `actual_acres`
    across route stops whose status is `COMPLETED`".

    Design: Difficulty/transitive_cascade/open_settlement_cascades_season_stop_assignment_machine
    """
    ctx = create_active_season(num_combines=2)
    m1, m2 = ctx["machines"][0], ctx["machines"][1]
    contract = create_committed_contract(ctx["season"]["id"], committed_acres=200)

    stop1 = create_route_stop(contract["id"], sequence_index=1,
                              planned_start_date="2026-08-05", planned_end_date="2026-08-06")
    drive_stop_to_cutting(stop1["id"], m1["id"],
                          assigned_start_date="2026-08-05", assigned_end_date="2026-08-07")
    set_actual_acres(stop1["id"], 100)
    complete_stop(stop1["id"])

    stop2 = create_route_stop(contract["id"], sequence_index=2,
                              planned_start_date="2026-08-10", planned_end_date="2026-08-11")
    reserve_machine(stop2["id"], m2["id"],
                    assigned_start_date="2026-08-10", assigned_end_date="2026-08-12")

    validate_success(api.open_settlement(ctx["season"]["id"], harvest_operator_headers))

    stop1_now = get_stop(stop1["id"])
    assert stop1_now["status"] == "COMPLETED", (
        f"a COMPLETED stop must be untouched by the cascade, got {stop1_now['status']!r}"
    )
    season_now = get_season(ctx["season"]["id"])
    assert season_now["harvested_acres_total"] == 100, (
        f"harvested_acres_total must remain 100, got {season_now['harvested_acres_total']!r}"
    )


def test_season_close_blocked_by_unresolved_settlements(api, harvest_operator_headers):
    """PRD section 3.8: "The season must be `SETTLING` (otherwise
    `ERR_SEASON_NOT_SETTLING`), and every settlement whose contract belongs
    to the season must be in `PAID` or `RESOLVED` (otherwise
    `ERR_UNRESOLVED_SETTLEMENTS_EXIST`, HTTP 409)."

    Design: Corner/state_machines/season_close_blocked_by_unresolved_settlements
    """
    ctx = setup_issued_settlement()
    season_now = get_season(ctx["season"]["id"])

    resp = api.close_season(
        ctx["season"]["id"],
        {"expected_season_version": season_now["version"]},
        harvest_operator_headers,
    )
    validate_error(resp, ApiErrorId.ERR_UNRESOLVED_SETTLEMENTS_EXIST)


def test_occ_season_close_stale_version_rejected(api, harvest_operator_headers):
    """PRD section 2.7: "A close-season request must carry
    `expected_season_version`, a non-optional field holding the `version` of
    the harvest season as the client last observed it. If the season's
    current `version` does not match, the request is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_season_close_stale_version_rejected
    """
    season = create_season()
    add_machine(season["id"])
    activate_season(season["id"])
    observed_version = get_season(season["id"])["version"]
    # Opening the settlement window advances the season past the observation.
    open_settlement_window(season["id"])

    resp = api.close_season(
        season["id"], {"expected_season_version": observed_version}, harvest_operator_headers
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


def test_contract_harvested_acres_sum_of_completed(api):
    """PRD section 3.4: "the parent contract's `harvested_acres` is recomputed
    as the sum of `actual_acres` over its `COMPLETED` stops; if every stop of
    the parent contract has reached `COMPLETED` or `SKIPPED`, the contract
    auto-transitions `IN_PROGRESS → HARVESTED`".

    Design: Difficulty/compensating_invariant/contract_harvested_acres_equals_sum_of_completed_stop_acres
    """
    ctx = create_active_season()
    contract = create_committed_contract(ctx["season"]["id"], committed_acres=200)

    stop1 = create_route_stop(contract["id"], sequence_index=1, planned_acres=60,
                              planned_start_date="2026-08-05", planned_end_date="2026-08-06")
    drive_stop_to_cutting(stop1["id"], ctx["machine"]["id"],
                          assigned_start_date="2026-08-05", assigned_end_date="2026-08-07")
    set_actual_acres(stop1["id"], 60)
    complete_stop(stop1["id"])

    stop2 = create_route_stop(contract["id"], sequence_index=2, planned_acres=40,
                              planned_start_date="2026-08-10", planned_end_date="2026-08-11")
    drive_stop_to_cutting(stop2["id"], ctx["machine"]["id"],
                          assigned_start_date="2026-08-10", assigned_end_date="2026-08-12")
    set_actual_acres(stop2["id"], 40)
    complete_stop(stop2["id"])

    contract_now = get_contract(contract["id"])
    assert contract_now["harvested_acres"] == 100, (
        f"harvested_acres must equal 60 + 40 = 100, got {contract_now['harvested_acres']!r}"
    )
    assert contract_now["status"] == "HARVESTED", (
        f"all stops terminal must auto-harvest the contract, got {contract_now['status']!r}"
    )


def test_contract_harvested_acres_excludes_skipped(api):
    """PRD section 3.2: "The contract's read-only `harvested_acres` field
    tracks the sum of `actual_acres` over its completed stops".
    PRD section 3.1: "`harvested_acres_total`, the sum of `actual_acres`
    across route stops whose status is `COMPLETED`".

    Design: Difficulty/compensating_invariant/contract_harvested_acres_equals_sum_of_completed_stop_acres
    """
    ctx = create_active_season()
    contract = create_committed_contract(ctx["season"]["id"], committed_acres=200)

    stop1 = create_route_stop(contract["id"], sequence_index=1, planned_acres=60,
                              planned_start_date="2026-08-05", planned_end_date="2026-08-06")
    drive_stop_to_cutting(stop1["id"], ctx["machine"]["id"],
                          assigned_start_date="2026-08-05", assigned_end_date="2026-08-07")
    set_actual_acres(stop1["id"], 60)
    complete_stop(stop1["id"])

    stop2 = create_route_stop(contract["id"], sequence_index=2, planned_acres=40,
                              planned_start_date="2026-08-10", planned_end_date="2026-08-11")
    skip_stop(stop2["id"])

    contract_now = get_contract(contract["id"])
    assert contract_now["harvested_acres"] == 60, (
        f"skipped stops contribute nothing: expected 60, got {contract_now['harvested_acres']!r}"
    )
    season_now = get_season(ctx["season"]["id"])
    assert season_now["harvested_acres_total"] == 60, (
        f"season harvested total must match completed stops only, got {season_now['harvested_acres_total']!r}"
    )
