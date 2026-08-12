"""Routes, stops, aggregate capacity, and stop-window/sequence rules."""
import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    create_catalog_item,
    create_customer,
    create_quoted_reservation,
    create_route,
    create_stop_payload,
    create_unit,
    confirm_reservation,
    deliver_reservation,
    get_reservation,
    get_route,
    get_route_stop,
    get_unit,
    list_lines,
    setup_confirmed_reservation,
    setup_delivered_reservation,
    validate_error,
    validate_success,
)


def _ops():
    return TEST_USERS["ops_admin_headers"]


def _setup_three_confirmed_for_capacity():
    """Two confirmed 12.0 kg reservations + one confirmed 0.5 kg reservation."""
    customer = create_customer()
    cat_heavy = create_catalog_item(weight_kg=12.0)
    cat_light = create_catalog_item(
        name="Toy T",
        category="STROLLER",
        daily_rate_cents=500,
        deposit_amount_cents=1000,
        weight_kg=0.5,
        cleaning_turnaround_hours=0,
    )
    create_unit(cat_heavy["id"])
    create_unit(cat_heavy["id"])
    create_unit(cat_light["id"])
    reservations = []
    for i, cat in enumerate((cat_heavy, cat_heavy, cat_light)):
        reservation = create_quoted_reservation(
            customer["id"],
            lines=[{"catalog_item_id": cat["id"]}],
            delivery_address=f"{16 + i} Palm Ct",
            start_date="2026-06-10",
            end_date="2026-06-12",
        )
        reservations.append(confirm_reservation(reservation["id"], customer["id"]))
    return reservations


def api_add_stop(route_id, reservation, window_start, window_end, address):
    return api_client.add_route_stop(
        route_id,
        create_stop_payload(
            reservation["id"],
            "DELIVERY_SETUP",
            address=address,
            time_window_start=window_start,
            time_window_end=window_end,
        ),
        _ops(),
    )


class TestRouteCapacityExactFit:
    def test_exact_fit_stops_accepted(self, api):
        """PRD 3.5: "a stop's weight is the sum of `weight_kg` over its
        reservation's lines, and adding it must leave the route's aggregate
        `planned_weight_kg` at or below `vehicle_capacity_kg` — an exact fit is
        allowed, any excess is rejected with `ERR_ROUTE_CAPACITY_EXCEEDED`."

        Two 12.0 kg stops on a 24.0 kg vehicle bring the planned weight to
        exactly 24.0 and both are accepted.

        Design: Difficulty/boundary_precision_check/route_capacity_exact_fit_then_overflow
        """
        res1, res2, _ = _setup_three_confirmed_for_capacity()
        route = create_route(
            route_date="2026-06-10", zone_code="Z1", vehicle_capacity_kg=24.0
        )
        validate_success(
            api_add_stop(
                route["id"], res1, "2026-06-10T08:00:00Z", "2026-06-10T09:00:00Z",
                address="16 Palm Ct",
            ),
            201,
        )
        validate_success(
            api_add_stop(
                route["id"], res2, "2026-06-10T09:00:00Z", "2026-06-10T10:00:00Z",
                address="17 Palm Ct",
            ),
            201,
        )
        assert get_route(route["id"])["planned_weight_kg"] == pytest.approx(24.0)

    def test_one_past_capacity_rejected_and_weight_unchanged(self, api):
        """PRD 3.5: "an exact fit is allowed, any excess is rejected with
        `ERR_ROUTE_CAPACITY_EXCEEDED`."

        With the pool already at exactly 24.0 of 24.0 kg, a further 0.5 kg
        stop overflows and is rejected; planned weight stays 24.0.

        Design: Difficulty/boundary_precision_check/route_capacity_exact_fit_then_overflow
        """
        res1, res2, res3 = _setup_three_confirmed_for_capacity()
        route = create_route(
            route_date="2026-06-10", zone_code="Z1", vehicle_capacity_kg=24.0
        )
        validate_success(
            api_add_stop(
                route["id"], res1, "2026-06-10T08:00:00Z", "2026-06-10T09:00:00Z",
                address="16 Palm Ct",
            ),
            201,
        )
        validate_success(
            api_add_stop(
                route["id"], res2, "2026-06-10T09:00:00Z", "2026-06-10T10:00:00Z",
                address="17 Palm Ct",
            ),
            201,
        )
        res = api_add_stop(
            route["id"], res3, "2026-06-10T10:00:00Z", "2026-06-10T11:00:00Z",
            address="18 Palm Ct",
        )
        validate_error(res, "ERR_ROUTE_CAPACITY_EXCEEDED", expected_status=422)
        assert get_route(route["id"])["planned_weight_kg"] == pytest.approx(24.0)


class TestRouteAggregateCapacityOverflow:
    def test_overflow_stop_rejected(self, api):
        """PRD 3.5: "Second, capacity: a stop's weight is the sum of
        `weight_kg` over its reservation's lines, and adding it must leave the
        route's aggregate `planned_weight_kg` at or below
        `vehicle_capacity_kg` — an exact fit is allowed, any excess is rejected
        with `ERR_ROUTE_CAPACITY_EXCEEDED`."

        Route capacity is an aggregate shared pool, not an interval rule:
        24.5 kg of requested load against a 24.0 kg vehicle is refused.

        Design: Difficulty/resource_temporal_overlap/route_aggregate_capacity_overflow_rejection
        """
        res1, res2, res3 = _setup_three_confirmed_for_capacity()
        route = create_route(
            route_date="2026-06-10", zone_code="Z1", vehicle_capacity_kg=24.0
        )
        validate_success(
            api_add_stop(
                route["id"], res1, "2026-06-10T08:00:00Z", "2026-06-10T09:00:00Z",
                address="24 Rose Ave",
            ),
            201,
        )
        validate_success(
            api_add_stop(
                route["id"], res2, "2026-06-10T09:00:00Z", "2026-06-10T10:00:00Z",
                address="25 Rose Ave",
            ),
            201,
        )
        res = api_add_stop(
            route["id"], res3, "2026-06-10T10:00:00Z", "2026-06-10T11:00:00Z",
            address="26 Rose Ave",
        )
        validate_error(res, "ERR_ROUTE_CAPACITY_EXCEEDED", expected_status=422)

    def test_rejected_stop_leaves_route_usable(self, api):
        """PRD 3.5: "A successful add updates the route's `planned_weight_kg`,
        bumps the route's `version`, and assigns the stop its `sequence`"

        A rejected stop is no add at all: the pool total is unchanged and the
        route still dispatches normally with its accepted stops.

        Design: Difficulty/resource_temporal_overlap/route_aggregate_capacity_overflow_rejection
        """
        res1, res2, res3 = _setup_three_confirmed_for_capacity()
        route = create_route(
            route_date="2026-06-10", zone_code="Z1", vehicle_capacity_kg=24.0
        )
        validate_success(
            api_add_stop(
                route["id"], res1, "2026-06-10T08:00:00Z", "2026-06-10T09:00:00Z",
                address="24 Rose Ave",
            ),
            201,
        )
        validate_success(
            api_add_stop(
                route["id"], res2, "2026-06-10T09:00:00Z", "2026-06-10T10:00:00Z",
                address="25 Rose Ave",
            ),
            201,
        )
        res = api_add_stop(
            route["id"], res3, "2026-06-10T10:00:00Z", "2026-06-10T11:00:00Z",
            address="26 Rose Ave",
        )
        validate_error(res, "ERR_ROUTE_CAPACITY_EXCEEDED", expected_status=422)
        route_after = get_route(route["id"])
        assert route_after["planned_weight_kg"] == pytest.approx(24.0)
        assert route_after["status"] == "PLANNED"
        dispatched = validate_success(api.dispatch_route(route["id"], _ops()), 200)
        assert dispatched["status"] == "DISPATCHED"


class TestStopCompleteRequiresRouteDispatched:
    def test_complete_on_planned_route_rejected(self, api):
        """PRD 3.5: "An OperationsAdmin completes a `SCHEDULED` stop only while
        its route is `DISPATCHED`, and only when the referenced reservation is
        in the matching state — `CONFIRMED` for a `DELIVERY_SETUP` stop,
        `DELIVERED` for a `PICKUP` — with any mismatch rejected as
        `ERR_INVALID_STATE`."

        Design: Difficulty/cross_entity_state_dependency/stop_complete_requires_route_dispatched
        """
        ctx = setup_confirmed_reservation()
        route = create_route(route_date="2026-06-10", zone_code="Z1")
        stop = validate_success(
            api.add_route_stop(
                route["id"],
                create_stop_payload(
                    ctx["reservation"]["id"],
                    "DELIVERY_SETUP",
                    address="20 Maple Dr",
                    time_window_start="2026-06-10T08:00:00Z",
                    time_window_end="2026-06-10T10:00:00Z",
                ),
                _ops(),
            ),
            201,
        )
        res = api.complete_route_stop(stop["id"], _ops())
        validate_error(res, "ERR_INVALID_STATE", expected_status=409)
        assert get_route_stop(stop["id"])["status"] == "SCHEDULED"
        assert get_reservation(ctx["reservation"]["id"])["status"] == "CONFIRMED"

    def test_complete_after_dispatch_succeeds(self, api):
        """PRD 3.5: "Completing a `DELIVERY_SETUP` stop moves the reservation
        `CONFIRMED` to `DELIVERED`: every `ALLOCATED` line goes `OUT` and each
        assigned unit goes `RESERVED` to `RENTED_OUT`, versions bumping on
        reservation, lines, and units."

        The same completion that is rejected while the route is PLANNED
        succeeds once the route is DISPATCHED.

        Design: Difficulty/cross_entity_state_dependency/stop_complete_requires_route_dispatched
        """
        ctx = setup_confirmed_reservation()
        delivery = deliver_reservation(ctx["reservation"])
        assert delivery["stop"]["status"] == "COMPLETED"
        assert delivery["reservation"]["status"] == "DELIVERED"


class TestRouteRecall:
    def test_route_recall_reverts_dispatched_to_planned(self, api):
        """PRD 3.5: "Dispatch is reversible: so long as no stop on the route is
        `COMPLETED` yet, the route may be recalled to `PLANNED`."

        Design: Corner/state_machines/route_recall_reverts_dispatched_to_planned
        """
        ctx = setup_confirmed_reservation()
        route = create_route(route_date="2026-06-10", zone_code="Z1")
        validate_success(
            api.add_route_stop(
                route["id"],
                create_stop_payload(
                    ctx["reservation"]["id"],
                    "DELIVERY_SETUP",
                    address="35 Cherry Ct",
                    time_window_start="2026-06-10T08:00:00Z",
                    time_window_end="2026-06-10T10:00:00Z",
                ),
                _ops(),
            ),
            201,
        )
        validate_success(api.dispatch_route(route["id"], _ops()), 200)
        recalled = validate_success(api.recall_route(route["id"], _ops()), 200)
        assert recalled["status"] == "PLANNED"

    def test_route_recall_rejected_after_completed_stop(self, api):
        """PRD 3.5: "Dispatch is reversible: so long as no stop on the route is
        `COMPLETED` yet, the route may be recalled to `PLANNED`."
        PRD 2.8: "State-machine preconditions — the transition must be legal
        from the current state, terminal states are locked, a stop can only
        complete on a `DISPATCHED` route, ... — else `ERR_INVALID_STATE` (409)."

        Once a stop is COMPLETED the recall is refused and the route stays
        DISPATCHED.

        Design: Corner/state_machines/route_recall_rejected_after_completed_stop
        """
        ctx = setup_delivered_reservation()
        route_id = ctx["delivery"]["route"]["id"]
        res = api.recall_route(route_id, _ops())
        validate_error(res, "ERR_INVALID_STATE", expected_status=409)
        assert get_route(route_id)["status"] == "DISPATCHED"


class TestStopValidation:
    def test_duplicate_stop_rejected(self, api):
        """PRD 3.5: "the same reservation and `stop_type` pair may not already
        have a `SCHEDULED` or `COMPLETED` stop on any `PLANNED` or `DISPATCHED`
        route, else `ERR_DUPLICATE_STOP`."

        Design: Corner/validations/duplicate_stop_rejected
        """
        ctx = setup_confirmed_reservation()
        route1 = create_route(route_date="2026-06-10", zone_code="Z1")
        route2 = create_route(route_date="2026-06-10", zone_code="Z1")
        validate_success(
            api.add_route_stop(
                route1["id"],
                create_stop_payload(
                    ctx["reservation"]["id"],
                    "DELIVERY_SETUP",
                    address="48 Osier Ct",
                    time_window_start="2026-06-10T08:00:00Z",
                    time_window_end="2026-06-10T09:00:00Z",
                ),
                _ops(),
            ),
            201,
        )
        res = api.add_route_stop(
            route2["id"],
            create_stop_payload(
                ctx["reservation"]["id"],
                "DELIVERY_SETUP",
                address="48 Osier Ct",
                time_window_start="2026-06-10T09:00:00Z",
                time_window_end="2026-06-10T10:00:00Z",
            ),
            _ops(),
        )
        validate_error(res, "ERR_DUPLICATE_STOP", expected_status=409)

    def test_stop_window_outside_route_date_rejected(self, api):
        """PRD 3.5: "The window must lie within the `route_date` with start
        strictly before end (`ERR_INVALID_DATE_RANGE`), the stop reservation's
        zone must equal the route's zone (`ERR_ZONE_MISMATCH`)"

        A stop windowed on 2026-06-11 cannot be added to a route dated
        2026-06-10.

        Design: Corner/validations/stop_window_outside_route_date_rejected
        """
        ctx = setup_confirmed_reservation()
        route = create_route(route_date="2026-06-10", zone_code="Z1")
        res = api.add_route_stop(
            route["id"],
            create_stop_payload(
                ctx["reservation"]["id"],
                "DELIVERY_SETUP",
                address="49 Rowan Pl",
                time_window_start="2026-06-11T08:00:00Z",
                time_window_end="2026-06-11T09:00:00Z",
            ),
            _ops(),
        )
        validate_error(res, "ERR_INVALID_DATE_RANGE", expected_status=422)


def test_stop_sequence_ordering_by_window_then_created(api):
    """PRD 3.5: "stops not in `SKIPPED` are numbered from 1 in
    `time_window_start` ascending order, ties broken by `created_at` ascending,
    never by id, and the numbering is recomputed whenever a stop is added or
    skipped."

    Stops added out of window order are sequenced by time_window_start: the
    09:00 stop gets sequence 1 even though it was created second.

    Design: Corner/calculations/stop_sequence_ordering_by_window_then_created
    """
    customer = create_customer()
    catalog = create_catalog_item()
    create_unit(catalog["id"])
    create_unit(catalog["id"])
    reservations = []
    for address in ("45 Magnolia Dr", "46 Magnolia Dr"):
        reservation = create_quoted_reservation(
            customer["id"],
            lines=[{"catalog_item_id": catalog["id"]}],
            delivery_address=address,
            start_date="2026-06-10",
            end_date="2026-06-12",
        )
        reservations.append(confirm_reservation(reservation["id"], customer["id"]))
    route = create_route(route_date="2026-06-10", zone_code="Z1")
    stop_late = validate_success(
        api.add_route_stop(
            route["id"],
            create_stop_payload(
                reservations[0]["id"],
                "DELIVERY_SETUP",
                address="45 Magnolia Dr",
                time_window_start="2026-06-10T11:00:00Z",
                time_window_end="2026-06-10T12:00:00Z",
            ),
            _ops(),
        ),
        201,
    )
    stop_early = validate_success(
        api.add_route_stop(
            route["id"],
            create_stop_payload(
                reservations[1]["id"],
                "DELIVERY_SETUP",
                address="46 Magnolia Dr",
                time_window_start="2026-06-10T09:00:00Z",
                time_window_end="2026-06-10T10:00:00Z",
            ),
            _ops(),
        ),
        201,
    )
    assert get_route_stop(stop_early["id"])["sequence"] == 1, (
        "earlier window must sequence first despite later creation"
    )
    assert get_route_stop(stop_late["id"])["sequence"] == 2


def test_delivery_stop_complete_marks_line_out_unit_rented(api):
    """PRD 3.5: "Completing a `DELIVERY_SETUP` stop moves the reservation
    `CONFIRMED` to `DELIVERED`: every `ALLOCATED` line goes `OUT` and each
    assigned unit goes `RESERVED` to `RENTED_OUT`, versions bumping on
    reservation, lines, and units."
    PRD 3.5: "Completion stamps `completed_at` from the current logical clock."

    One completion flips reservation, line, and unit in a single immediate
    read-after-write.

    Design: Corner/endpoints/delivery_stop_complete_marks_line_out_unit_rented
    """
    ctx = setup_confirmed_reservation()
    reservation = ctx["reservation"]
    unit = ctx["units"][0]
    delivery = deliver_reservation(reservation, clock="2026-06-10T09:00:00Z")
    stop = delivery["stop"]
    assert stop["status"] == "COMPLETED"
    assert stop["completed_at"] == "2026-06-10T09:00:00Z"
    assert delivery["reservation"]["status"] == "DELIVERED"
    line = list_lines(reservation["id"])[0]
    assert line["status"] == "OUT"
    assert get_unit(unit["id"])["status"] == "RENTED_OUT"
