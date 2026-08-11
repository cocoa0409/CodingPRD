"""Home pickup workflow and courier-zone capacity: window validation,
aggregate capacity gate, demand vs confirmed load divergence, retry-exhaustion
filtering, attempt-count boundary, and temporal guards."""
from test_helpers import (
    ApiErrorId,
    book_pickup,
    create_order,
    create_pickup_appointment_payload,
    create_return_item_line,
    create_zone,
    reschedule_pickup_payload,
    set_clock,
    setup_commercial_spine,
    validate_error,
    validate_success,
)


def _pickup_spine(email, capacity=10):
    spine = setup_commercial_spine(shopper_email=email, with_zone=False)
    zone = create_zone(zone_code="Z-" + email.split("@")[0].upper(),
                       window_capacity=capacity)
    return spine, zone


def _pickup_order(spine, sku="PK"):
    return create_order(spine, method="HOME_PICKUP", boxless=True,
                        items=[create_return_item_line(sku=sku)])


class TestPickupWindows:

    def test_error_pickup_window_past(self, api):
        """PRD §3.6: "The window must lie in the future — a `window_start`
        preceding the current logical instant is rejected with
        `ERR_PICKUP_WINDOW_PAST`".

        Design: Corner/errors/error_pickup_window_past
        """
        spine, zone = _pickup_spine("spp@x.com")
        order = _pickup_order(spine, sku="PP")
        resp = api.create_pickup_appointment(
            create_pickup_appointment_payload(
                order["id"], zone["id"],
                window_start="2026-04-30T09:00:00Z",
                window_end="2026-04-30T11:00:00Z",
            ),
            spine["shopper_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_PICKUP_WINDOW_PAST)

    def test_error_pickup_too_early_start(self, api):
        """PRD §3.6: "Starting the run moves `SCHEDULED` → `EN_ROUTE`, but not
        earlier than one hour before `window_start` — an earlier attempt is
        rejected with `ERR_PICKUP_TOO_EARLY`."

        Design: Corner/errors/error_pickup_too_early_start
        """
        from test_helpers import TEST_USERS, api_client
        spine, zone = _pickup_spine("spe@x.com")
        order = _pickup_order(spine, sku="PE")
        appointment = book_pickup(
            order, zone,
            window_start="2026-05-02T09:00:00Z",
            window_end="2026-05-02T11:00:00Z",
        )
        # Clock is still 2026-05-01T00:00:00Z — far before window_start - 1h.
        resp = api_client.start_pickup(
            appointment["id"], TEST_USERS["platform_admin_headers"]
        )
        validate_error(resp, ApiErrorId.ERR_PICKUP_TOO_EARLY)

    def test_pickup_create_state_beats_temporal(self, api):
        """PRD §2.8: priority 6 (state legality, `ERR_INVALID_STATE`) is
        evaluated before priority 10 (clock-relative rules,
        `ERR_PICKUP_WINDOW_PAST`); "an early failure always masks later
        ones".
        PRD §3.6: "A **PickupAppointment** is booked by the shopper for an
        order that must be `INITIATED` with method `HOME_PICKUP`".

        Design: Difficulty/priority_pair_validation_conflict/pickup_create_state_beats_temporal
        """
        spine, zone = _pickup_spine("stm@x.com")
        order = _pickup_order(spine, sku="TP")
        validate_success(api.cancel_return_order(order["id"], spine["shopper_headers"]))

        # The order is terminal AND the window is in the past; P6 wins.
        resp = api.create_pickup_appointment(
            create_pickup_appointment_payload(
                order["id"], zone["id"],
                window_start="2026-04-01T09:00:00Z",
                window_end="2026-04-01T11:00:00Z",
            ),
            spine["shopper_headers"],
        )
        # A cancelled (terminal) order rejects everything; PRD §2.8 P6 names
        # both state-legality ids for terminal resources without pinning one.
        from test_helpers import validate_error_is_one_of
        validate_error_is_one_of(
            resp, [ApiErrorId.ERR_INVALID_STATE.value,
                   ApiErrorId.ERR_ALREADY_TERMINAL.value],
        )


class TestZoneCapacity:

    def test_zone_window_aggregate_capacity_overlap(self, api):
        """PRD §3.6: "Zone capacity is an aggregate gate, not an exclusive
        lock: two windows overlap when each starts before the other ends, and
        the booking is rejected with `ERR_PICKUP_WINDOW_FULL` only when the
        zone's count of `SCHEDULED` or `EN_ROUTE` appointments overlapping the
        requested window has already reached `window_capacity` — up to that
        many overlapping windows are admitted, and the next one is refused."

        Design: Difficulty/resource_temporal_overlap/zone_window_aggregate_capacity_overlap
        """
        spine, zone = _pickup_spine("sag@x.com", capacity=2)
        order1 = _pickup_order(spine, sku="A1")
        order2 = _pickup_order(spine, sku="A2")
        order3 = _pickup_order(spine, sku="A3")

        ap1 = book_pickup(order1, zone, window_start="2026-05-01T01:00:00Z",
                          window_end="2026-05-01T03:00:00Z")
        assert ap1["status"] == "SCHEDULED"
        ap2 = book_pickup(order2, zone, window_start="2026-05-01T02:00:00Z",
                          window_end="2026-05-01T04:00:00Z")
        assert ap2["status"] == "SCHEDULED"

        # Third overlapping window: load 2 >= capacity 2 -> refused.
        blocked = api.create_pickup_appointment(
            create_pickup_appointment_payload(
                order3["id"], zone["id"],
                window_start="2026-05-01T02:30:00Z",
                window_end="2026-05-01T03:30:00Z",
            ),
            spine["shopper_headers"],
        )
        validate_error(blocked, ApiErrorId.ERR_PICKUP_WINDOW_FULL)

        # Disjoint window is always free.
        ap3 = validate_success(
            api.create_pickup_appointment(
                create_pickup_appointment_payload(
                    order3["id"], zone["id"],
                    window_start="2026-05-01T05:00:00Z",
                    window_end="2026-05-01T06:00:00Z",
                ),
                spine["shopper_headers"],
            ),
            expected_status=201,
        )
        assert ap3["status"] == "SCHEDULED"

    def test_zone_load_confirmed_vs_demand_projection_divergence(self, api):
        """PRD §3.6: "`confirmed_load` counts the zone's appointments in
        `SCHEDULED` or `EN_ROUTE` status whose window contains the current
        clock instant. `demand_load` adds to that the `FAILED` appointments
        with `attempt_count` below three whose window contains now — the
        expected reschedules — so the demand gauge is always at least the
        confirmed one and is strictly larger whenever a retryable failure
        overlaps the present."

        Design: Difficulty/dual_variant_calc/zone_load_confirmed_vs_demand_projection_divergence
        """
        from test_helpers import TEST_USERS, api_client
        spine, zone = _pickup_spine("sz@x.com", capacity=5)

        order1 = _pickup_order(spine, sku="Z1")
        book_pickup(order1, zone, window_start="2026-05-01T00:30:00Z",
                    window_end="2026-05-01T02:30:00Z")
        order2 = _pickup_order(spine, sku="Z2")
        book_pickup(order2, zone, window_start="2026-05-01T01:00:00Z",
                    window_end="2026-05-01T03:00:00Z")
        order3 = _pickup_order(spine, sku="Z3")
        ap3 = book_pickup(order3, zone, window_start="2026-05-01T00:30:00Z",
                          window_end="2026-05-01T01:30:00Z")

        # Drive appointment 3 EN_ROUTE -> FAILED (attempt_count becomes 1 < 3).
        admin = TEST_USERS["platform_admin_headers"]
        validate_success(api_client.start_pickup(ap3["id"], admin))
        failed = validate_success(api_client.fail_pickup(ap3["id"], admin))
        assert failed["attempt_count"] == 1

        set_clock("2026-05-01T01:00:00Z")  # inside all three windows

        zone_after = validate_success(api_client.get_courier_zone(zone["id"], admin))
        assert zone_after["confirmed_load"] == 2
        assert zone_after["demand_load"] == 3
        assert zone_after["demand_load"] - zone_after["confirmed_load"] == 1

    def test_demand_load_excludes_exhausted_failed(self, api):
        """PRD §3.6: "`demand_load` adds to that the `FAILED` appointments
        with `attempt_count` below three whose window contains now". A FAILED
        appointment whose attempt_count reached three is no longer retryable
        and is excluded.

        Design: Corner/calculations/demand_load_excludes_exhausted_failed
        """
        from test_helpers import TEST_USERS, api_client
        spine, zone = _pickup_spine("sde@x.com", capacity=5)
        order_x = _pickup_order(spine, sku="DX")
        book_pickup(order_x, zone)

        order_y = _pickup_order(spine, sku="DY")
        apy = book_pickup(order_y, zone)

        admin = TEST_USERS["platform_admin_headers"]
        # Drive the appointment to attempt_count == 3 (fail x3 with
        # reschedules between).
        for _ in range(3):
            validate_success(api_client.start_pickup(apy["id"], admin))
            failed = validate_success(api_client.fail_pickup(apy["id"], admin))
            if failed["attempt_count"] < 3:
                validate_success(
                    api_client.reschedule_pickup(
                        apy["id"], reschedule_pickup_payload(),
                        spine["shopper_headers"],
                    )
                )
        assert failed["attempt_count"] == 3

        set_clock("2026-05-01T01:00:00Z")  # inside both windows
        zone_after = validate_success(api_client.get_courier_zone(zone["id"], admin))
        assert zone_after["confirmed_load"] == 1
        assert zone_after["demand_load"] == 1


class TestPickupAttempts:

    def test_pickup_reschedule_attempt_boundary(self, api):
        """PRD §3.6: "The shopper (or a `PlatformAdmin`) may reschedule a
        `FAILED` appointment back to `SCHEDULED` by supplying a fresh
        `window_start` and `window_end`, but only while `attempt_count`
        remains below three — a third-strike reschedule is refused with
        `ERR_PICKUP_MAX_ATTEMPTS`".

        Design: Corner/state_machines/pickup_reschedule_attempt_boundary
        """
        from test_helpers import TEST_USERS, api_client
        spine, zone = _pickup_spine("spa@x.com")
        order = _pickup_order(spine, sku="PA")
        appointment = book_pickup(order, zone)
        admin = TEST_USERS["platform_admin_headers"]

        # attempt_count 1: reschedule succeeds.
        validate_success(api_client.start_pickup(appointment["id"], admin))
        validate_success(api_client.fail_pickup(appointment["id"], admin))
        r1 = validate_success(
            api_client.reschedule_pickup(
                appointment["id"], reschedule_pickup_payload(),
                spine["shopper_headers"],
            )
        )
        assert r1["status"] == "SCHEDULED"
        assert r1["attempt_count"] == 1

        # attempt_count 2: reschedule still succeeds.
        validate_success(api_client.start_pickup(appointment["id"], admin))
        validate_success(api_client.fail_pickup(appointment["id"], admin))
        r2 = validate_success(
            api_client.reschedule_pickup(
                appointment["id"], reschedule_pickup_payload(),
                spine["shopper_headers"],
            )
        )
        assert r2["status"] == "SCHEDULED"
        assert r2["attempt_count"] == 2

        # attempt_count 3: reschedule refused.
        validate_success(api_client.start_pickup(appointment["id"], admin))
        validate_success(api_client.fail_pickup(appointment["id"], admin))
        blocked = api_client.reschedule_pickup(
            appointment["id"], reschedule_pickup_payload(),
            spine["shopper_headers"],
        )
        validate_error(blocked, ApiErrorId.ERR_PICKUP_MAX_ATTEMPTS)
