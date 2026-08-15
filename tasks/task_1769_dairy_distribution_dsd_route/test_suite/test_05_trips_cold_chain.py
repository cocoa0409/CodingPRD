"""Trip lifecycle gates, temperature-reading rules, cold-chain excursion math,
and driver window overlap (PRD §2.4, §2.9, §3.4)."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_reading,
    cancel_order,
    complete_trip_at,
    confirm_order,
    create_driver,
    create_trip,
    deliver_order,
    delivered_line,
    get_trip,
    make_distributor_owner_headers,
    make_driver_headers,
    precool_and_depart,
    run_trip_readings,
    set_clock,
    setup_planned_order,
    setup_route_with_store,
    validate_error,
    validate_paginated,
    validate_success,
)

TM = TEST_USERS["territory_manager_headers"]
QI = TEST_USERS["quality_inspector_headers"]


def test_temperature_reading_append_only_order(api, territory_manager_headers):
    """PRD §2.4: "Two event-log entities are the exception:
    `TemperatureReading` and `CrateTransaction` are immutable once created and
    carry only `id` and `created_at`; both `updated_at` and `version` are
    absent from them."
    PRD §4: "List readings of a trip, recorded_at ascending"

    Design: Corner/entities/temperature_reading_append_only_order
    """
    refs = setup_planned_order(prefix="Z", quantity_units=1)
    t1 = refs["trip"]["id"]
    dr1 = refs["driver"]["id"]
    set_clock("2026-08-10T04:30:00Z")
    add_reading(t1, dr1, "2026-08-10T04:30:00Z", 380, "BOX")
    set_clock("2026-08-10T04:45:00Z")
    add_reading(t1, dr1, "2026-08-10T04:45:00Z", 375, "CAB")

    readings, _ = validate_paginated(
        api.list_temperature_readings(t1, territory_manager_headers)
    )
    assert len(readings) == 2
    assert readings[0]["temp_tenths_f"] == 380, "recorded_at ascending"
    assert readings[1]["temp_tenths_f"] == 375
    for item in readings:
        assert item["id"] and item["created_at"]
        assert "version" not in item, "event log must not expose version"
        assert "updated_at" not in item, "event log must not expose updated_at"


def test_cab_zone_excluded_from_excursion(api):
    """PRD §2.9: "Two independent triggers set the trip's `cold_chain_breach`
    flag: cumulative accrual reaching at least 45.0 minutes (the boundary is
    inclusive), or any single `BOX` reading above 50.0°F — the instantaneous
    spike rule."
    PRD §3.4: "Only `BOX` readings feed this math; `CAB` readings are inert."

    Design: Corner/calculations/cab_zone_excluded_from_excursion
    """
    refs = setup_planned_order(prefix="BA", quantity_units=1)
    t1 = refs["trip"]["id"]
    dr1 = refs["driver"]["id"]
    cancel_order(refs["order"]["id"], refs["distributor"]["id"])
    precool_and_depart(t1, dr1, "2026-08-10")
    run_trip_readings(t1, dr1, [
        ("2026-08-10T10:00:00Z", 500, "CAB"),
        ("2026-08-10T10:00:30Z", 385, "BOX"),
        ("2026-08-10T10:30:00Z", 510, "CAB"),
    ])
    trip = complete_trip_at(t1, dr1, "2026-08-10T12:00:00Z")
    assert trip["excursion_minutes"] == pytest.approx(0.0, abs=0.001), (
        "CAB readings excluded; BOX readings never exceeded 40.0F"
    )
    assert trip["cold_chain_breach"] is False, (
        "even a 51.0F CAB spike must not trigger the instantaneous breach"
    )


def test_reading_out_of_order_and_future_rejected(api):
    """PRD §3.4: "The `recorded_at` must be strictly greater than the previous
    reading's `recorded_at` on the same trip and no later than the current
    logical clock; violations are `ERR_READING_OUT_OF_ORDER`."

    Design: Corner/validations/reading_out_of_order_and_future_rejected
    """
    refs = setup_planned_order(prefix="CF", quantity_units=1)
    t1 = refs["trip"]["id"]
    dr1 = refs["driver"]["id"]
    cancel_order(refs["order"]["id"], refs["distributor"]["id"])
    precool_and_depart(t1, dr1, "2026-08-10")
    run_trip_readings(t1, dr1, [("2026-08-10T10:00:00Z", 385, "BOX")])
    set_clock("2026-08-10T10:30:00Z")

    err1 = api.add_temperature_reading(
        t1,
        {"recorded_at": "2026-08-10T10:00:00Z", "temp_tenths_f": 386, "zone": "BOX"},
        make_driver_headers(dr1),
    )
    validate_error(err1, ApiErrorId.ERR_READING_OUT_OF_ORDER)

    err2 = api.add_temperature_reading(
        t1,
        {"recorded_at": "2026-08-10T11:00:00Z", "temp_tenths_f": 386, "zone": "BOX"},
        make_driver_headers(dr1),
    )
    validate_error(err2, ApiErrorId.ERR_READING_OUT_OF_ORDER)


def test_trip_depart_gates(api):
    """PRD §3.4: "the **pre-cool check** requires at least one `BOX`-zone
    reading at or below 40.0°F recorded while the trip was `PLANNED` — without
    it, departure fails with `ERR_COLD_CHAIN_PRECOOL_REQUIRED` (HTTP 409) —
    and every order on the trip must already be `CONFIRMED` or `CANCELLED`,
    because a `PLANNED` order blocks departure with
    `ERR_ORDER_NOT_CONFIRMABLE`."
    PRD §2.5: "Within a single state-machine transition, preconditions
    evaluate in the order the workflow narrative lists them, and the first
    failing precondition's error is the one returned."

    Design: Corner/state_machines/trip_depart_gates
    """
    refs = setup_planned_order(prefix="AC", quantity_units=1)
    d_id = refs["distributor"]["id"]
    t1 = refs["trip"]["id"]
    dr1 = refs["driver"]["id"]
    set_clock("2026-08-10T04:30:00Z")

    err1 = api.depart_trip(t1, make_driver_headers(dr1))
    validate_error(err1, ApiErrorId.ERR_COLD_CHAIN_PRECOOL_REQUIRED)

    add_reading(t1, dr1, "2026-08-10T04:30:00Z", 380, "BOX")
    err2 = api.depart_trip(t1, make_driver_headers(dr1))
    validate_error(err2, ApiErrorId.ERR_ORDER_NOT_CONFIRMABLE)

    cancel_order(refs["order"]["id"], d_id)
    trip = validate_success(api.depart_trip(t1, make_driver_headers(dr1)), 200)
    assert trip["status"] == "DEPARTED"


def test_trip_complete_requires_all_delivered_and_reading_gates(api):
    """PRD §3.4: "The trip itself completes when every order on it is
    `DELIVERED`: the trip must be `DEPARTED` (else `ERR_TRIP_NOT_DEPARTED`),
    the caller must be its driver, and any order not yet `DELIVERED` blocks
    completion with `ERR_ORDER_NOT_DELIVERABLE`."
    PRD §3.4: "While a trip is `PLANNED` or `DEPARTED`, the assigned
    `RouteDriver` appends temperature readings; a reading attempted in any
    other trip state is rejected with `ERR_READINGS_NOT_ACCEPTED`."
    PRD §3.4: "The inspector submits a `verdict` of `CLEAR` or
    `CONFIRM_BREACH`; any other value is `ERR_INVALID_REQUEST`, and the trip
    must be in `QA_REVIEW` (else `ERR_TRIP_NOT_IN_QA_REVIEW`)."

    Design: Corner/state_machines/trip_complete_requires_all_delivered_and_reading_gates
    """
    refs = setup_planned_order(prefix="AD", quantity_units=2)
    t1 = refs["trip"]["id"]
    dr1 = refs["driver"]["id"]
    confirm_order(refs["order"]["id"], refs["distributor"]["id"])
    precool_and_depart(t1, dr1, "2026-08-10")

    err1 = api.complete_trip(t1, make_driver_headers(dr1))
    validate_error(err1, ApiErrorId.ERR_ORDER_NOT_DELIVERABLE)

    set_clock("2026-08-10T09:00:00Z")
    deliver_order(refs["order"]["id"], dr1,
                  [delivered_line(refs["product"]["id"], 2, "2026-09-01")])
    trip = validate_success(api.complete_trip(t1, make_driver_headers(dr1)), 200)
    assert trip["status"] == "COMPLETED"

    err2 = api.add_temperature_reading(
        t1,
        {"recorded_at": "2026-08-10T09:30:00Z", "temp_tenths_f": 380, "zone": "BOX"},
        make_driver_headers(dr1),
    )
    validate_error(err2, ApiErrorId.ERR_READINGS_NOT_ACCEPTED)

    err3 = api.adjudicate_trip(t1, {"verdict": "CLEAR"}, QI)
    validate_error(err3, ApiErrorId.ERR_TRIP_NOT_IN_QA_REVIEW)


def test_trip_qa_review_requires_breach_and_clear_path(api):
    """PRD §3.4: "A `QualityInspector` opens that review on a `COMPLETED` trip
    whose flag is true, moving it to `QA_REVIEW` (any other state, or a clean
    trip, is `ERR_TRIP_NOT_COMPLETED`)."
    PRD §3.4: "A `CLEAR` verdict moves the trip to `RECONCILED`, resets
    `cold_chain_breach` to false, and fires no order or return cascade."

    Design: Corner/state_machines/trip_qa_review_requires_breach_and_clear_path
    """
    refs = setup_planned_order(prefix="AE", quantity_units=1)
    d_id = refs["distributor"]["id"]
    cancel_order(refs["order"]["id"], d_id)
    t1 = refs["trip"]["id"]
    dr1 = refs["driver"]["id"]

    # T1: clean trip.
    precool_and_depart(t1, dr1, "2026-08-10")
    complete_trip_at(t1, dr1, "2026-08-10T12:00:00Z")

    # T2: single BOX spike of 51.0F breaches instantly.
    trip2 = create_trip(refs["route"]["id"], dr1, d_id, service_date="2026-08-11")
    precool_and_depart(trip2["id"], dr1, "2026-08-11")
    run_trip_readings(trip2["id"], dr1, [
        ("2026-08-11T10:00:00Z", 510, "BOX"),
        ("2026-08-11T10:01:00Z", 380, "BOX"),
    ])
    t2 = complete_trip_at(trip2["id"], dr1, "2026-08-11T12:00:00Z")
    assert t2["cold_chain_breach"] is True
    assert t2["excursion_minutes"] == pytest.approx(1.0, abs=0.001)

    err1 = api.qa_review_trip(t1, QI)
    validate_error(err1, ApiErrorId.ERR_TRIP_NOT_COMPLETED)

    qa = validate_success(api.qa_review_trip(trip2["id"], QI), 200)
    assert qa["status"] == "QA_REVIEW"
    final = validate_success(
        api.adjudicate_trip(trip2["id"], {"verdict": "CLEAR"}, QI), 200
    )
    assert final["status"] == "RECONCILED"
    assert final["cold_chain_breach"] is False

    returns, _ = validate_paginated(
        api.list_returns(TM, params={"pickup_trip_id": trip2["id"]})
    )
    assert returns == [], "CLEAR fires no order or return cascade"


def test_trip_depart_twice_and_deliver_before_depart(api):
    """PRD §3.4: "The order must be `CONFIRMED` (else
    `ERR_ORDER_NOT_DELIVERABLE`), the trip must be `DEPARTED` (else
    `ERR_TRIP_NOT_DEPARTED`), and the caller must be the trip's driver (else
    `ERR_OWNERSHIP_MISMATCH`)."
    PRD §3.4: "The trip must be `PLANNED` (else `ERR_TRIP_NOT_PLANNED`)"

    Design: Corner/state_machines/trip_depart_twice_and_deliver_before_depart
    """
    refs = setup_planned_order(prefix="AN", quantity_units=1)
    t1 = refs["trip"]["id"]
    dr1 = refs["driver"]["id"]
    confirm_order(refs["order"]["id"], refs["distributor"]["id"])
    set_clock("2026-08-10T04:30:00Z")
    add_reading(t1, dr1, "2026-08-10T04:30:00Z", 380, "BOX")

    err1 = api.deliver_order(
        refs["order"]["id"],
        {"delivered_lines": [delivered_line(refs["product"]["id"], 1, "2026-09-01")]},
        make_driver_headers(dr1),
    )
    validate_error(err1, ApiErrorId.ERR_TRIP_NOT_DEPARTED)

    validate_success(api.depart_trip(t1, make_driver_headers(dr1)), 200)
    err2 = api.depart_trip(t1, make_driver_headers(dr1))
    validate_error(err2, ApiErrorId.ERR_TRIP_NOT_PLANNED)


class TestExcursion45MinuteBreachBoundary:
    def _run_trip_with_excursion(self, api, prefix, service_date, hold_until):
        """Depart after pre-cool, hold BOX at 41.0F from 10:00 to
        `hold_until`, then complete at 11:00 with the trailing reading below
        threshold."""
        refs = setup_planned_order(prefix=prefix, quantity_units=1,
                                   service_date=service_date)
        cancel_order(refs["order"]["id"], refs["distributor"]["id"])
        t_id = refs["trip"]["id"]
        dr = refs["driver"]["id"]
        precool_and_depart(t_id, dr, service_date)
        run_trip_readings(t_id, dr, [
            (f"{service_date}T10:00:00Z", 410, "BOX"),
            (f"{service_date}T{hold_until}Z", 390, "BOX"),
        ])
        return refs, complete_trip_at(t_id, dr, f"{service_date}T11:00:00Z")

    def test_44_9_minutes_stays_below_breach_and_reconciles(self, api):
        """PRD §2.9: "Two independent triggers set the trip's
        `cold_chain_breach` flag: cumulative accrual reaching at least 45.0
        minutes (the boundary is inclusive), or any single `BOX` reading above
        50.0°F — the instantaneous spike rule."
        PRD §3.4: "After completion, a `DistributorOwner` may reconcile the
        trip directly when `cold_chain_breach` is false, moving it `COMPLETED`
        → `RECONCILED`"

        Design: Difficulty/boundary_precision_check/excursion_45_minutes_breach_boundary
        """
        refs, trip = self._run_trip_with_excursion(
            api, "L", "2026-08-10", "10:44:54"
        )
        assert trip["excursion_minutes"] == pytest.approx(44.9, abs=0.001), (
            "44min54s above 40.0F is below the threshold"
        )
        assert trip["cold_chain_breach"] is False

        owner = make_distributor_owner_headers(refs["distributor"]["id"])
        reconciled = validate_success(api.reconcile_trip(refs["trip"]["id"], owner), 200)
        assert reconciled["status"] == "RECONCILED"

    def test_45_0_minutes_breaches_and_blocks_direct_reconcile(self, api):
        """PRD §2.9: "cumulative accrual reaching at least 45.0 minutes (the
        boundary is inclusive)"
        PRD §3.4: "attempting reconciliation from any other state, or when the
        flag is true, fails with `ERR_TRIP_NOT_COMPLETED` — a breached trip
        must instead go through QA."

        Design: Difficulty/boundary_precision_check/excursion_45_minutes_breach_boundary
        """
        refs, trip = self._run_trip_with_excursion(
            api, "L2", "2026-08-11", "10:45:00"
        )
        assert trip["excursion_minutes"] == pytest.approx(45.0, abs=0.001)
        assert trip["cold_chain_breach"] is True, (
            "exactly 45.0 minutes is an inclusive breach"
        )

        owner = make_distributor_owner_headers(refs["distributor"]["id"])
        err = api.reconcile_trip(refs["trip"]["id"], owner)
        validate_error(err, ApiErrorId.ERR_TRIP_NOT_COMPLETED)

        qa = validate_success(api.qa_review_trip(refs["trip"]["id"], QI), 200)
        assert qa["status"] == "QA_REVIEW"


class TestDriverTripsHalfOpenAdjacency:
    def test_back_to_back_allowed_and_overlap_rejected(self, api):
        """PRD §3.4: "A driver may not be double-booked: if the driver already
        holds a non-`CANCELLED` trip whose half-open window from
        `planned_depart_at` up to but not including `planned_return_at`
        overlaps the new trip's window, creation fails with
        `ERR_TRIP_WINDOW_CONFLICT`; because the interval is half-open,
        back-to-back trips are allowed."

        Design: Difficulty/resource_temporal_overlap/driver_trips_half_open_adjacency
        """
        refs = setup_route_with_store(prefix="P")
        d_id = refs["distributor"]["id"]
        driver = create_driver(d_id, name="Pat Driver")
        owner = make_distributor_owner_headers(d_id)
        create_trip(
            refs["route"]["id"], driver["id"], d_id,
            planned_depart_at="2026-08-10T05:00:00Z",
            planned_return_at="2026-08-10T12:00:00Z",
        )

        ok = api.create_trip(
            {
                "route_id": refs["route"]["id"], "driver_id": driver["id"],
                "service_date": "2026-08-10", "truck_plate": "TK-2",
                "case_capacity": 100,
                "planned_depart_at": "2026-08-10T12:00:00Z",
                "planned_return_at": "2026-08-10T17:00:00Z",
            },
            owner,
        )
        validate_success(ok, 201)

        err = api.create_trip(
            {
                "route_id": refs["route"]["id"], "driver_id": driver["id"],
                "service_date": "2026-08-10", "truck_plate": "TK-3",
                "case_capacity": 100,
                "planned_depart_at": "2026-08-10T11:59:00Z",
                "planned_return_at": "2026-08-10T13:00:00Z",
            },
            owner,
        )
        validate_error(err, ApiErrorId.ERR_TRIP_WINDOW_CONFLICT)

    def test_cancelled_trip_does_not_block_reuse(self, api):
        """PRD §3.4: "if the driver already holds a non-`CANCELLED` trip whose
        half-open window from `planned_depart_at` up to but not including
        `planned_return_at` overlaps the new trip's window, creation fails
        with `ERR_TRIP_WINDOW_CONFLICT`"

        Design: Difficulty/resource_temporal_overlap/driver_trips_half_open_adjacency
        """
        refs = setup_route_with_store(prefix="P2")
        d_id = refs["distributor"]["id"]
        driver = create_driver(d_id, name="Pat Driver")
        owner = make_distributor_owner_headers(d_id)
        trip = create_trip(
            refs["route"]["id"], driver["id"], d_id,
            planned_depart_at="2026-08-10T05:00:00Z",
            planned_return_at="2026-08-10T12:00:00Z",
        )
        validate_success(api.cancel_trip(trip["id"], owner), 200)

        reused = api.create_trip(
            {
                "route_id": refs["route"]["id"], "driver_id": driver["id"],
                "service_date": "2026-08-10", "truck_plate": "TK-2",
                "case_capacity": 100,
                "planned_depart_at": "2026-08-10T08:00:00Z",
                "planned_return_at": "2026-08-10T13:00:00Z",
            },
            owner,
        )
        validate_success(reused, 201)
