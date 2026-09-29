"""Running the day: starting, completing, counting riders and declaring misses."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_single_departure_route,
    assert_ridership_count,
    assign_trip,
    complete_trip,
    create_active_contract,
    create_driver,
    create_on_demand_request,
    create_report,
    create_vehicle,
    list_credit_memos,
    make_driver_headers,
    mark_trip_missed,
    match_on_demand_request,
    set_clock,
    setup_assigned_trip,
    setup_completed_trip,
    setup_missed_trip_with_memo,
    setup_published_route,
    start_trip,
    submit_report,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["contract_admin_headers"]
LIAISON = TEST_USERS["client_liaison_headers"]
PLANNER = TEST_USERS["ops_planner_headers"]


def _two_axis_scenario():
    """Two trips on 2026-09-02: the first completed, the second missed for
    OPERATOR_FAULT so a memo is minted against it."""
    base = setup_published_route(
        clock="2026-09-01T06:00:00Z",
        service_date="2026-09-02",
        contract_overrides={"client_name": "Two Axis Hotel"},
        route_overrides={
            "name": "Two Trip Loop", "loop_minutes": 48, "headway_minutes": 12,
            "service_window_start_min": 420, "service_window_end_min": 432,
            "demand_forecast_pax_per_hour": 0, "reference_seat_capacity": 20,
        },
    )
    vehicle = create_vehicle(odometer_km=5_000)
    driver = create_driver(full_name="Iris Nakamura")
    trips = base["trips"]
    assign_trip(trips[0]["id"], vehicle["id"], driver["id"])
    start_trip(trips[0]["id"], driver["id"], 423)
    complete_trip(trips[0]["id"], driver["id"], 470, boarded=6, alighted=6, ada_boardings=0)
    mark_trip_missed(trips[1]["id"], "OPERATOR_FAULT")
    memos = list_credit_memos(trip_id=trips[1]["id"])
    return {
        "contract": base["contract"],
        "completed_trip": trips[0],
        "missed_trip": trips[1],
        "memo": memos[0],
    }


# ─── Driver-owned transitions ─────────────────────────────────────────────────

def test_completing_a_trip_that_never_started_is_rejected(api):
    """PRD §3.4: "Closing the loop moves the trip `IN_SERVICE` → `COMPLETED`; from
    any other dispatch state the request fails with `ERR_TRIP_NOT_IN_SERVICE`."
    PRD §3.4: "Completion stores `actual_completion_min`, appends a ridership row
    carrying those three counts with `source` `DRIVER_TALLY` and the next
    `sequence_no` for that trip, recomputes `counted_boardings` and
    `counted_ada_boardings`, and increments the trip's `version` by one."

    Design: Corner/state_machines/complete_before_start_returns_trip_not_in_service
    """
    scenario = setup_assigned_trip(
        contract_overrides={"client_name": "Complete Guard"},
        vehicle_overrides={"odometer_km": 500},
        driver_overrides={"full_name": "Guard Driver"},
    )

    response = api.complete_trip(
        scenario["trip"]["id"],
        {"actual_completion_min": 470, "boarded": 3, "alighted": 3, "ada_boardings": 0},
        make_driver_headers(scenario["driver"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_TRIP_NOT_IN_SERVICE.value, 409)

    trip = validate_success(api.get_trip(scenario["trip"]["id"], PLANNER))
    assert trip["dispatch_status"] == "ASSIGNED"
    assert trip["counted_boardings"] == 0

    _, meta = validate_paginated(
        api.list_trip_ridership_counts(scenario["trip"]["id"], PLANNER)
    )
    assert meta["total_count"] == 0, "a rejected completion appends no ridership row"


def test_driver_cannot_start_another_drivers_trip(api):
    """PRD §2.1: "Whenever the caller's role is `DriverUser`, the caller's
    `X-User-ID` must equal the `driver_id` of the trip being acted upon; for serving
    an on-demand request, it must equal the `driver_id` of the trip named by the
    request's `matched_trip_id`. A `DriverUser` who fails this test is rejected with
    `ERR_DRIVER_NOT_ASSIGNED` and HTTP 403."
    PRD §3.4: "A `DriverUser` whose `X-User-ID` equals the trip's `driver_id` pulls
    out by supplying `actual_departure_min`, moving the trip `ASSIGNED` →
    `IN_SERVICE`; from any other dispatch state the request fails with
    `ERR_TRIP_NOT_ASSIGNED`, and a driver acting on someone else's trip fails with
    `ERR_DRIVER_NOT_ASSIGNED`."

    Design: Corner/rbac/driver_cannot_start_a_trip_assigned_to_another_driver
    """
    scenario = setup_assigned_trip(
        contract_overrides={"client_name": "Identity Campus", "site_type": "CAMPUS"},
        vehicle_overrides={"odometer_km": 1_000},
        driver_overrides={"full_name": "Driver A"},
    )
    other_driver = create_driver(full_name="Driver B")

    refused = api.start_trip(
        scenario["trip"]["id"], {"actual_departure_min": 421},
        make_driver_headers(other_driver["id"]),
    )
    validate_error(refused, ApiErrorId.ERR_DRIVER_NOT_ASSIGNED.value, 403)

    accepted = validate_success(
        api.start_trip(
            scenario["trip"]["id"], {"actual_departure_min": 421},
            make_driver_headers(scenario["driver"]["id"]),
        )
    )
    assert accepted["dispatch_status"] == "IN_SERVICE"

    trip = validate_success(api.get_trip(scenario["trip"]["id"], PLANNER))
    assert trip["actual_departure_min"] == 421


# ─── Ridership counting ───────────────────────────────────────────────────────

def test_completion_appends_an_append_only_driver_tally(api):
    """PRD §3.6: "Each is stamped with `recorded_by_user_id`, holding the
    `X-User-ID` of whoever appended it, and with `sequence_no`, a per-trip monotonic
    counter that starts at 1 for a trip's first row and increases by exactly one for
    each row appended to that same trip afterwards."
    PRD §2.4: "It has no `updated_at` field and no `version` field, and neither
    should appear in its response payload."

    Design: Corner/entities/ridership_count_rows_are_append_only_with_sequence_numbers
    """
    scenario = setup_completed_trip(
        actual_departure_min=421, actual_completion_min=469,
        boarded=7, alighted=7, ada_boardings=0,
        contract_overrides={"client_name": "Append Only Campus", "site_type": "CAMPUS"},
        vehicle_overrides={"odometer_km": 200},
        driver_overrides={"full_name": "Tally Driver"},
    )

    rows, meta = validate_paginated(
        api.list_trip_ridership_counts(scenario["trip"]["id"], PLANNER)
    )
    assert meta["total_count"] == 1
    row = rows[0]
    assert row["sequence_no"] == 1
    assert row["source"] == "DRIVER_TALLY"
    assert row["boarded"] == 7
    assert row["trip_id"] == scenario["trip"]["id"]
    assert row["recorded_by_user_id"] == scenario["driver"]["id"], (
        "the driver who completed the trip is stamped onto the row"
    )
    assert_ridership_count(row)


def test_sensor_row_outranks_every_driver_tally(api):
    """PRD §3.6: "Automatic passenger counters outrank human tallies
    unconditionally: if any row for the trip has `source` `APC_SENSOR`, the one
    among them with the greatest `sequence_no` is chosen. Only when there is no
    sensor row at all does the system fall back to the `DRIVER_TALLY` row with the
    greatest `sequence_no`. The trip's `counted_boardings` is then the chosen row's
    `boarded` and its `counted_ada_boardings` is that same row's `ada_boardings`;
    when the trip has no ridership rows whatsoever, both read 0."

    Design: Corner/calculations/apc_sensor_row_outranks_every_driver_tally
    """
    scenario = setup_completed_trip(
        actual_departure_min=421, actual_completion_min=469,
        boarded=7, alighted=7, ada_boardings=0,
        contract_overrides={"client_name": "Counting Campus", "site_type": "CAMPUS"},
        vehicle_overrides={"odometer_km": 1_300},
        driver_overrides={"full_name": "Counting Driver"},
    )
    trip_id = scenario["trip"]["id"]

    second = validate_success(
        api.create_ridership_count(
            {"trip_id": trip_id, "boarded": 21, "alighted": 21,
             "ada_boardings": 3, "source": "APC_SENSOR"},
            PLANNER,
        ),
        expected_status=201,
    )
    third = validate_success(
        api.create_ridership_count(
            {"trip_id": trip_id, "boarded": 19, "alighted": 19,
             "ada_boardings": 1, "source": "APC_SENSOR"},
            PLANNER,
        ),
        expected_status=201,
    )
    assert second["sequence_no"] == 2
    assert third["sequence_no"] == 3

    trip = validate_success(api.get_trip(trip_id, PLANNER))
    assert trip["counted_boardings"] == 19, (
        "the sensor row with the greatest sequence_no wins, not the largest number"
    )
    assert trip["counted_ada_boardings"] == 1

    rows, meta = validate_paginated(api.list_trip_ridership_counts(trip_id, PLANNER))
    assert meta["total_count"] == 3
    assert [r["sequence_no"] for r in rows] == [1, 2, 3]

    tallies, tally_meta = validate_paginated(
        api.list_trip_ridership_counts(trip_id, PLANNER, params={"source": "DRIVER_TALLY"})
    )
    assert tally_meta["total_count"] == 1
    assert tallies[0]["boarded"] == 7


# ─── Missed trips and the settlement branch ───────────────────────────────────

def test_operator_fault_credits_the_trip_and_mints_the_memo(api):
    """PRD §3.7: "With `OPERATOR_FAULT`, the trip's `settlement_status` moves
    `UNBILLED` → `CREDITED`, and because it did, a credit memo is minted
    automatically: `contract_id` taken from the trip's `contract_id`, `trip_id` set
    to the trip, `reason` `MISSED_TRIP`, `status` `ISSUED`, and `amount_cents` set
    to the contract's `penalty_rate_cents_per_missed_trip`."

    Design: Difficulty/transitive_cascade/missed_trip_mints_memo_and_moves_contract_balance
    """
    scenario = setup_missed_trip_with_memo(
        contract_overrides={"client_name": "Missed Trip Campus", "site_type": "CAMPUS"}
    )
    assert scenario["trip"]["settlement_status"] == "CREDITED"

    trip = validate_success(api.get_trip(scenario["trip"]["id"], PLANNER))
    assert trip["dispatch_status"] == "MISSED"
    assert trip["missed_reason"] == "OPERATOR_FAULT"

    memos, meta = validate_paginated(
        api.list_credit_memos(ADMIN, params={"contract_id": scenario["contract"]["id"]})
    )
    assert meta["total_count"] == 1, "exactly one memo is minted"
    memo = memos[0]
    assert memo["trip_id"] == trip["id"]
    assert memo["reason"] == "MISSED_TRIP"
    assert memo["status"] == "ISSUED"
    assert memo["amount_cents"] == 4_500


def test_minted_memo_moves_the_contract_credit_balance(api):
    """PRD §3.7: "Because that memo became `ISSUED`, the contract's
    `credit_balance_cents` is recomputed and the contract's `version` increments by
    one."
    PRD §3.1: "That figure is the sum of `amount_cents` over every credit memo of
    this contract whose `status` is `ISSUED`; memos that have been applied to a
    report or voided are excluded, so the balance always reads as outstanding,
    not-yet-settled credit."

    Design: Difficulty/transitive_cascade/missed_trip_mints_memo_and_moves_contract_balance
    """
    scenario = setup_missed_trip_with_memo(
        contract_overrides={"client_name": "Missed Trip Campus", "site_type": "CAMPUS"}
    )

    contract = validate_success(api.get_contract(scenario["contract"]["id"], ADMIN))
    assert contract["credit_balance_cents"] == 4_500, (
        f"the ISSUED memo drives the balance from 0 to 4500, got "
        f"{contract['credit_balance_cents']}"
    )
    assert contract["version"] > scenario["contract"]["version"], (
        "minting a memo moves the owning contract's version"
    )


def test_client_request_waives_the_trip_without_minting_a_memo(api):
    """PRD §3.7: "With `CLIENT_REQUEST`, the trip's `settlement_status` moves
    `UNBILLED` → `WAIVED`: no memo is minted, `credit_balance_cents` is unchanged,
    and — as §3.8 explains — the trip leaves both the on-time denominator and the
    missed-trip count entirely."
    PRD §3.8: "`waived_trip_count` counts those whose `dispatch_status` is `MISSED`
    and whose `settlement_status` is `WAIVED`."
    PRD §3.8: "`on_time_pct` is 100.00 when `countable_trip_count` is 0, and
    otherwise is 100 multiplied by `on_time_trip_count`, divided by
    `countable_trip_count`, rounded half up to two decimal places."
    PRD §3.8: "Both variants exclude `MISSED` and `CANCELLED` trips entirely."

    Design: Corner/state_machines/mark_missed_with_client_request_waives_without_minting_a_memo
    """
    set_clock("2026-09-01T06:00:00Z")
    contract = create_active_contract(client_name="Waiver Hotel")
    built = add_single_departure_route(contract["id"], 420, loop_minutes=48, name="Waiver Loop")
    report = create_report(
        contract["id"], period_start_date="2026-09-01", period_end_date="2026-09-30"
    )

    waived = validate_success(
        api.mark_trip_missed(built["trip"]["id"], {"reason": "CLIENT_REQUEST"}, PLANNER)
    )
    assert waived["settlement_status"] == "WAIVED"
    assert waived["dispatch_status"] == "MISSED"
    assert waived["missed_reason"] == "CLIENT_REQUEST"

    _, memo_meta = validate_paginated(
        api.list_credit_memos(ADMIN, params={"contract_id": contract["id"]})
    )
    assert memo_meta["total_count"] == 0, "the waiver branch mints nothing"

    reread = validate_success(api.get_contract(contract["id"], ADMIN))
    assert reread["credit_balance_cents"] == 0

    submitted = submit_report(report["id"], "liaison-w")
    assert submitted["waived_trip_count"] == 1
    assert submitted["countable_trip_count"] == 0
    assert submitted["missed_trip_count"] == 0
    assert submitted["on_time_pct"] == 100.00
    assert submitted["gross_amount_cents"] == 0
    assert submitted["net_amount_cents"] == 0


def test_weather_miss_denies_the_matched_rider_and_leaves_settlement_alone(api):
    """PRD §3.7: "Every on-demand request whose `matched_trip_id` named this trip
    and whose `status` is `MATCHED` moves to `DENIED` with `matched_trip_id`
    cleared."
    PRD §3.7: "With `WEATHER`, `settlement_status` is left exactly as it was; a
    weather-missed trip remains `UNBILLED` and still counts against the operator's
    on-time percentage."
    PRD §3.7: "where the trip had been `ASSIGNED` its `vehicle_id` and `driver_id`
    are cleared with `committed_block_minutes` and
    `assigned_duty_minutes_current_date` recomputed on the released bus and driver"

    Design: Corner/state_machines/mark_missed_denies_the_matched_on_demand_request
    """
    base = setup_published_route(
        clock="2026-09-01T06:00:00Z",
        service_date="2026-09-02",
        contract_overrides={"client_name": "Weather Campus", "site_type": "CAMPUS"},
        route_overrides={
            "name": "Weather Loop", "loop_minutes": 48, "headway_minutes": 12,
            "service_window_start_min": 420, "service_window_end_min": 432,
            "demand_forecast_pax_per_hour": 0, "reference_seat_capacity": 20,
        },
    )
    vehicle = create_vehicle(odometer_km=1_200)
    driver = create_driver(full_name="Weather Driver")
    trip = base["trips"][0]
    assign_trip(trip["id"], vehicle["id"], driver["id"])
    request = create_on_demand_request(
        base["contract"]["id"], service_date="2026-09-02",
        requested_pickup_min=420, party_size=1, requires_ada=False,
    )
    match_on_demand_request(request["id"])

    missed = validate_success(
        api.mark_trip_missed(trip["id"], {"reason": "WEATHER"}, PLANNER)
    )
    assert missed["settlement_status"] == "UNBILLED"

    reread_trip = validate_success(api.get_trip(trip["id"], PLANNER))
    assert reread_trip["dispatch_status"] == "MISSED"
    assert reread_trip["missed_reason"] == "WEATHER"
    assert reread_trip.get("vehicle_id") is None

    reread_request = validate_success(api.get_on_demand_request(request["id"], LIAISON))
    assert reread_request["status"] == "DENIED"
    assert reread_request.get("matched_trip_id") is None

    _, memo_meta = validate_paginated(
        api.list_credit_memos(ADMIN, params={"contract_id": base["contract"]["id"]})
    )
    assert memo_meta["total_count"] == 0

    bus = validate_success(api.get_vehicle(vehicle["id"], PLANNER))
    assert bus["committed_block_minutes"] == 0


# ─── The two independent axes of a trip ───────────────────────────────────────

def test_void_walks_settlement_back_while_dispatch_stays_missed(api):
    """PRD §3.7: "When the voided memo names a trip and its `reason` is
    `MISSED_TRIP`, the void additionally walks the trip's financial axis back:
    `settlement_status` moves `CREDITED` → `UNBILLED` and the trip's `version`
    increments by one."
    PRD §3.7: "A trip carries two statuses that move independently of one another.
    `dispatch_status` is the operational axis described in §3.4;
    `settlement_status` is the financial axis, which begins at `UNBILLED` and ends
    at either `BILLED` or `WAIVED`."

    Design: Difficulty/non_linear_state_machine/trip_parallel_dispatch_and_settlement_axes
    """
    scenario = _two_axis_scenario()

    validate_success(
        api.void_credit_memo(
            scenario["memo"]["id"], {"voided_reason": "raised against the wrong trip"}, ADMIN
        )
    )

    missed = validate_success(api.get_trip(scenario["missed_trip"]["id"], PLANNER))
    assert missed["dispatch_status"] == "MISSED", "the operational axis does not move"
    assert missed["missed_reason"] == "OPERATOR_FAULT"
    assert missed["settlement_status"] == "UNBILLED", "the financial axis walks back"

    memo = validate_success(api.get_credit_memo(scenario["memo"]["id"], ADMIN))
    assert memo["status"] == "VOIDED"

    contract = validate_success(api.get_contract(scenario["contract"]["id"], ADMIN))
    assert contract["credit_balance_cents"] == 0


def test_completed_trip_stays_unbilled_on_the_financial_axis(api):
    """PRD §3.7: "A trip that has been completed operationally stays `UNBILLED`
    financially until a report is approved, and a trip that has been credited can be
    walked back to `UNBILLED` if the credit is reversed. The two axes never
    constrain each other directly; they are joined only through the specific rules
    below."

    Design: Difficulty/non_linear_state_machine/trip_parallel_dispatch_and_settlement_axes
    """
    scenario = _two_axis_scenario()

    completed = validate_success(api.get_trip(scenario["completed_trip"]["id"], PLANNER))
    assert completed["dispatch_status"] == "COMPLETED"
    assert completed["settlement_status"] == "UNBILLED", (
        "operational completion alone never moves the financial axis"
    )
    assert completed["actual_departure_min"] == 423
    assert completed["actual_completion_min"] == 470
