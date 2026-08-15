"""Meter exchange scheduling: windows, crew buffers, and the fail cycle."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_customer_account,
    assert_instant_equal,
    assert_meter_exchange,
    create_meter_exchange_payload,
    drive_to_screen_passed,
    get_account,
    get_application,
    get_success_data,
    make_technician_headers,
    setup_program_with_grid,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["program_administrator_headers"]
TECHNICIAN = TEST_USERS["technician_headers"]


def _screen_passed(name):
    sc = setup_program_with_grid(name)
    ctx = add_customer_account(sc, "1")
    app = drive_to_screen_passed(sc, ctx, size=10_000, production=15_000_000)
    return sc, ctx, app


class TestFailRescheduleCycle:
    def test_fail_reschedule_complete_cycle(self, api):
        """PRD §3.7: "A failed visit moves the exchange to `FAILED` with a
        `fail_reason`, and the technician may reschedule a failed exchange with
        a fresh `window_start` and `window_end` — revalidated against the
        window-ordering and crew-buffer rules — returning it to `SCHEDULED` and
        clearing the `fail_reason`."
        PRD §3.7: "Completion moves the exchange to `COMPLETED`, records the
        `installed_meter_serial` and the acting technician's identity in
        `technician_user_id`, and copies the serial onto the account's
        `meter_serial`."

        Design: Difficulty/non_linear_state_machine/nsm_meter_exchange_fail_reschedule_cycle
        """
        sc, ctx, app = _screen_passed("MX")
        exchange = get_success_data(api.create_meter_exchange(
            create_meter_exchange_payload(
                app["id"], crew_id="crew-7",
                window_start="2026-08-10T09:00:00Z",
                window_end="2026-08-10T11:00:00Z"), TECHNICIAN))

        exchange = validate_success(api.fail_meter_exchange(
            exchange["id"], "gate locked", TECHNICIAN))
        assert exchange["exchange_status"] == "FAILED"
        assert exchange["fail_reason"] == "gate locked"

        exchange = validate_success(api.reschedule_meter_exchange(
            exchange["id"], "2026-08-12T13:00:00Z", "2026-08-12T15:00:00Z",
            TECHNICIAN))
        assert exchange["exchange_status"] == "SCHEDULED"
        assert_instant_equal(exchange["window_start"], "2026-08-12T13:00:00Z",
                             "rescheduled window_start")
        assert_instant_equal(exchange["window_end"], "2026-08-12T15:00:00Z",
                             "rescheduled window_end")
        assert exchange["fail_reason"] is None, "reschedule clears fail_reason"

        exchange = validate_success(api.complete_meter_exchange(
            exchange["id"], "MTR-77", make_technician_headers("tech-7")))
        assert exchange["exchange_status"] == "COMPLETED"
        assert exchange["technician_user_id"] == "tech-7"
        assert get_account(ctx["account"]["id"])["meter_serial"] == "MTR-77"
        assert (get_application(app["id"])["application_status"]
                == "SCREEN_PASSED"), "the exchange cycle never moves the application"

    def test_reschedule_revalidates_window_rules(self, api):
        """PRD §3.7: "the technician may reschedule a failed exchange with a
        fresh `window_start` and `window_end` — revalidated against the
        window-ordering and crew-buffer rules — returning it to `SCHEDULED` and
        clearing the `fail_reason`."
        PRD §3.7: "an end that is not strictly after the start is rejected with
        `ERR_EXCHANGE_WINDOW_INVALID`."

        Design: Difficulty/non_linear_state_machine/nsm_meter_exchange_fail_reschedule_cycle
        """
        sc, ctx, app = _screen_passed("MX2")
        exchange = get_success_data(api.create_meter_exchange(
            create_meter_exchange_payload(app["id"], crew_id="crew-8"),
            TECHNICIAN))
        exchange = validate_success(api.fail_meter_exchange(
            exchange["id"], "no access", TECHNICIAN))

        resp = api.reschedule_meter_exchange(
            exchange["id"], "2026-08-12T13:00:00Z", "2026-08-12T13:00:00Z",
            TECHNICIAN)
        validate_error(resp, ApiErrorId.ERR_EXCHANGE_WINDOW_INVALID, 422)

        exchange = validate_success(api.reschedule_meter_exchange(
            exchange["id"], "2026-08-12T13:00:00Z", "2026-08-12T15:00:00Z",
            TECHNICIAN))
        assert exchange["exchange_status"] == "SCHEDULED"
        assert exchange["fail_reason"] is None


class TestRescheduleStateGate:
    def test_reschedule_from_scheduled_rejected(self, api):
        """PRD §3.7: "the technician may reschedule a failed exchange with a
        fresh `window_start` and `window_end`"
        PRD §2.10: "Eighth, the primary resource being in a state that permits
        the requested transition (`ERR_INVALID_STATE`, or
        `ERR_ESTIMATE_NOT_ISSUED` for estimate accept and decline)."

        Design: Corner/state_machines/sm_exchange_reschedule_from_scheduled_rejected
        """
        sc, ctx, app = _screen_passed("SX")
        exchange = get_success_data(api.create_meter_exchange(
            create_meter_exchange_payload(
                app["id"], crew_id="crew-1",
                window_start="2026-08-10T09:00:00Z",
                window_end="2026-08-10T11:00:00Z"), TECHNICIAN))

        resp = api.reschedule_meter_exchange(
            exchange["id"], "2026-08-11T09:00:00Z", "2026-08-11T11:00:00Z",
            TECHNICIAN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
        exchange_after = validate_success(
            api.get_meter_exchange(exchange["id"], ADMIN))
        assert_instant_equal(exchange_after["window_start"],
                             "2026-08-10T09:00:00Z",
                             "rejected reschedule leaves the window unchanged")


class TestOneActiveExchange:
    def test_second_scheduled_exchange_rejected(self, api):
        """PRD §3.7: "Only one active exchange may exist per application — a
        second `SCHEDULED` exchange is rejected with
        `ERR_EXCHANGE_ALREADY_ACTIVE`"

        Design: Corner/errors/err_exchange_already_active_blocks_second
        """
        sc, ctx, app = _screen_passed("XA")
        get_success_data(api.create_meter_exchange(
            create_meter_exchange_payload(
                app["id"], crew_id="crew-1",
                window_start="2026-08-10T09:00:00Z",
                window_end="2026-08-10T11:00:00Z"), TECHNICIAN))

        # Even a different crew on a clean window cannot stack a second
        # SCHEDULED exchange on the same application.
        resp = api.create_meter_exchange(
            create_meter_exchange_payload(
                app["id"], crew_id="crew-b",
                window_start="2026-08-12T09:00:00Z",
                window_end="2026-08-12T11:00:00Z"), TECHNICIAN)
        validate_error(resp, ApiErrorId.ERR_EXCHANGE_ALREADY_ACTIVE, 422)


class TestExchangeWindowValidity:
    def test_window_end_equal_to_start_rejected(self, api):
        """PRD §3.7: "A `MeterTechnician` books an appointment by supplying the
        `application_id`, the `crew_id` of the assigned crew, and a
        `window_start` and `window_end`; an end that is not strictly after the
        start is rejected with `ERR_EXCHANGE_WINDOW_INVALID`."

        Design: Corner/validations/v_exchange_window_invalid_rejected
        """
        sc, ctx, app = _screen_passed("XW")
        resp = api.create_meter_exchange(
            create_meter_exchange_payload(
                app["id"], crew_id="crew-1",
                window_start="2026-08-10T09:00:00Z",
                window_end="2026-08-10T09:00:00Z"), TECHNICIAN)
        validate_error(resp, ApiErrorId.ERR_EXCHANGE_WINDOW_INVALID, 422)


class TestCrewBufferOverlap:
    def _two_screen_passed_apps(self, name, count=2):
        sc = setup_program_with_grid(name)
        ctxs = [add_customer_account(sc, str(i)) for i in range(1, count + 1)]
        apps = [drive_to_screen_passed(sc, ctx, size=10_000,
                                       production=15_000_000)
                for ctx in ctxs]
        return sc, ctxs, apps

    def test_window_inside_thirty_minute_buffer_rejected(self, api):
        """PRD §3.7: "crews are protected by a half-hour buffer: the half-open
        interval from thirty minutes before `window_start` to thirty minutes
        after `window_end` may not intersect the corresponding buffered window
        of any other `SCHEDULED` exchange for the same `crew_id`, failing which
        the booking is rejected with `ERR_EXCHANGE_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/rto_exchange_crew_buffer_overlap
        """
        sc, _ctxs, apps = self._two_screen_passed_apps("XOV")
        ex1 = get_success_data(api.create_meter_exchange(
            create_meter_exchange_payload(
                apps[0]["id"], crew_id="crew-9",
                window_start="2026-08-10T09:00:00Z",
                window_end="2026-08-10T11:00:00Z"), TECHNICIAN))
        assert_meter_exchange(ex1)
        assert ex1["exchange_status"] == "SCHEDULED"

        # Buffered occupation is [08:30, 11:30); an 11:30 start intersects it.
        resp = api.create_meter_exchange(
            create_meter_exchange_payload(
                apps[1]["id"], crew_id="crew-9",
                window_start="2026-08-10T11:30:00Z",
                window_end="2026-08-10T13:00:00Z"), TECHNICIAN)
        validate_error(resp, ApiErrorId.ERR_EXCHANGE_WINDOW_OVERLAP, 422)

        # A 12:00 start leaves the buffered intervals touching but disjoint.
        ex2 = get_success_data(api.create_meter_exchange(
            create_meter_exchange_payload(
                apps[1]["id"], crew_id="crew-9",
                window_start="2026-08-10T12:00:00Z",
                window_end="2026-08-10T13:30:00Z"), TECHNICIAN))
        assert ex2["exchange_status"] == "SCHEDULED"

    def test_buffer_is_per_crew_and_applies_before_the_window(self, api):
        """PRD §3.7: "the half-open interval from thirty minutes before
        `window_start` to thirty minutes after `window_end` may not intersect
        the corresponding buffered window of any other `SCHEDULED` exchange for
        the same `crew_id`, failing which the booking is rejected with
        `ERR_EXCHANGE_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/rto_exchange_crew_buffer_overlap
        """
        sc, _ctxs, apps = self._two_screen_passed_apps("XOV2", count=3)
        get_success_data(api.create_meter_exchange(
            create_meter_exchange_payload(
                apps[0]["id"], crew_id="crew-9",
                window_start="2026-08-10T09:00:00Z",
                window_end="2026-08-10T11:00:00Z"), TECHNICIAN))

        # The buffer is scoped per crew: an identical window on another crew
        # does not intersect anything.
        other_crew = get_success_data(api.create_meter_exchange(
            create_meter_exchange_payload(
                apps[1]["id"], crew_id="crew-2",
                window_start="2026-08-10T09:00:00Z",
                window_end="2026-08-10T11:00:00Z"), TECHNICIAN))
        assert other_crew["exchange_status"] == "SCHEDULED"

        # Ending at 08:30 puts the buffered window [06:30, 09:00), which
        # intersects the existing [08:30, 11:30) occupation.
        resp = api.create_meter_exchange(
            create_meter_exchange_payload(
                apps[2]["id"], crew_id="crew-9",
                window_start="2026-08-10T07:00:00Z",
                window_end="2026-08-10T08:30:00Z"), TECHNICIAN)
        validate_error(resp, ApiErrorId.ERR_EXCHANGE_WINDOW_OVERLAP, 422)

        # Ending at 08:00 buffers to [06:30, 08:30) — touching but disjoint.
        earlier = get_success_data(api.create_meter_exchange(
            create_meter_exchange_payload(
                apps[2]["id"], crew_id="crew-9",
                window_start="2026-08-10T07:00:00Z",
                window_end="2026-08-10T08:00:00Z"), TECHNICIAN))
        assert earlier["exchange_status"] == "SCHEDULED"
