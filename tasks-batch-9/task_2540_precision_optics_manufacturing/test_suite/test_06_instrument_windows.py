"""Exclusive station occupation: the purge buffer, window shape and cancellation."""

import pytest

from test_helpers import (
    CANCEL_REASON_BY_OPERATOR,
    ERR_INSTRUMENT_WINDOW_CONFLICT,
    ERR_INVALID_WINDOW,
    ERR_RUN_STAGE_OUT_OF_ORDER,
    MIN_WINDOW_MINUTES,
    assert_blank_ledger,
    assert_booked_minutes,
    assert_row_ids,
    build_cancel_run_payload,
    build_process_run_payload,
    create_certified_lot,
    create_instrument,
    create_released_design,
    error_id_of,
    expected_capability_ratio,
    make_plant_admin_headers,
    make_process_technician_headers,
    make_procurement_officer_headers,
    open_work_order,
    validate_error,
    validate_paginated,
    validate_success,
)


def _read_instrument(api, instrument_id):
    """Read one metrology station as the plant administrator."""
    return validate_success(
        api.get_metrology_instrument(instrument_id, make_plant_admin_headers()),
        expected_status=200,
    )


def _read_order(api, work_order_id):
    """Read one work order as the process technician who owns it."""
    return validate_success(
        api.get_work_order(work_order_id, make_process_technician_headers()),
        expected_status=200,
    )


def _read_run(api, run_id):
    """Read one process run as the process technician who booked it."""
    return validate_success(
        api.get_process_run(run_id, make_process_technician_headers()),
        expected_status=200,
    )


def _schedule(api, work_order_id, instrument_id, start_utc, end_utc, run_stage="POLISHING"):
    """Attempt one metrology booking, returning the raw response."""
    return api.create_process_run(
        build_process_run_payload(
            work_order_id,
            instrument_id,
            run_stage=run_stage,
            metrology_window_start_utc=start_utc,
            metrology_window_end_utc=end_utc,
        ),
        make_process_technician_headers(),
    )


def _lot_version(api, lot_id):
    """Re-read the lot's optimistic-concurrency version between reservations."""
    lot = validate_success(
        api.get_glass_lot(lot_id, make_procurement_officer_headers()),
        expected_status=200,
    )
    return lot["version"]


def _three_orders_on_one_station(api, order_count=3):
    """A released design, a certified 20-blank lot, N orders and one station."""
    design = create_released_design(api, design_code="OD-2540-PB")
    lot = create_certified_lot(api, lot_code="GL-2540-PB", total_blank_count=20)
    orders = []
    for _ in range(order_count):
        orders.append(
            open_work_order(
                api, design["id"], lot["id"], _lot_version(api, lot["id"]), element_count=2
            )
        )
    instrument = create_instrument(api, instrument_code="IF-2540-1")
    return {"design": design, "lot": lot, "orders": orders, "instrument": instrument}


class TestPurgeBufferAtFifteenAndFourteenMinutes:
    """The symmetric purge buffer is decided on the minute, in both directions."""

    def test_a_gap_of_exactly_fifteen_minutes_is_admissible(self, api):
        """A window opening 10:15 behind a run that ends 10:00 is booked.

        The PRD states that "Occupation of a station is exclusive and carries a
        symmetric fifteen-minute purge buffer for thermal settling, applied with
        closed endpoints." and that "A gap of exactly fifteen minutes between two
        windows is therefore admissible; a gap of fourteen minutes is not."

        Design: Difficulty/resource_temporal_overlap/instrument_purge_buffer_admits_exact_fifteen_minute_gap_and_rejects_fourteen
        """
        ctx = _three_orders_on_one_station(api)
        instrument_id = ctx["instrument"]["id"]

        first = validate_success(
            _schedule(
                api,
                ctx["orders"][0]["id"],
                instrument_id,
                "2026-08-01T08:00:00Z",
                "2026-08-01T10:00:00Z",
            ),
            expected_status=201,
        )
        assert first["window_minutes"] == 120, (
            f"the leading window is 120 minutes, got {first['window_minutes']}"
        )
        assert_booked_minutes(_read_instrument(api, instrument_id), 120)

        touching = validate_success(
            _schedule(
                api,
                ctx["orders"][1]["id"],
                instrument_id,
                "2026-08-01T10:15:00Z",
                "2026-08-01T11:15:00Z",
            ),
            expected_status=201,
        )

        assert touching["window_minutes"] == 60, (
            f"window_minutes must be 60, got {touching['window_minutes']}"
        )
        assert touching["run_status"] == "SCHEDULED", (
            f"run_status must be SCHEDULED, got {touching['run_status']}"
        )
        assert_booked_minutes(_read_instrument(api, instrument_id), 180)

    def test_a_gap_of_fourteen_minutes_is_refused_as_a_window_conflict(self, api):
        """A window opening 11:29 behind a run that ends 11:15 is inside the buffer.

        The PRD states that "A requested window conflicts with another run's window
        on the same station when the requested start falls strictly before that run's
        end extended by fifteen minutes, **and** that run's start falls strictly
        before the requested end extended by fifteen minutes." A conflict "is
        reported as `ERR_INSTRUMENT_WINDOW_CONFLICT`".

        Design: Difficulty/resource_temporal_overlap/instrument_purge_buffer_admits_exact_fifteen_minute_gap_and_rejects_fourteen
        """
        ctx = _three_orders_on_one_station(api)
        instrument_id = ctx["instrument"]["id"]
        _schedule(
            api,
            ctx["orders"][0]["id"],
            instrument_id,
            "2026-08-01T08:00:00Z",
            "2026-08-01T10:00:00Z",
        )
        _schedule(
            api,
            ctx["orders"][1]["id"],
            instrument_id,
            "2026-08-01T10:15:00Z",
            "2026-08-01T11:15:00Z",
        )

        refused = _schedule(
            api,
            ctx["orders"][2]["id"],
            instrument_id,
            "2026-08-01T11:29:00Z",
            "2026-08-01T12:29:00Z",
        )

        validate_error(refused, ERR_INSTRUMENT_WINDOW_CONFLICT)
        assert error_id_of(refused) != ERR_INVALID_WINDOW, (
            "a sixty-minute window is well formed, so the shape gate must not fire"
        )

    def test_the_refused_booking_charges_no_minutes_and_leaves_its_order_alone(self, api):
        """The station's meter and the third order are untouched by the refusal.

        The PRD states that "`booked_minutes_total` is incremented by the run's
        `window_minutes` at scheduling and decremented by the same amount whenever
        the run is later cancelled, whether cancelled directly or by one of the
        cascades in §3.2 and §3.3."

        Design: Difficulty/resource_temporal_overlap/instrument_purge_buffer_admits_exact_fifteen_minute_gap_and_rejects_fourteen
        """
        ctx = _three_orders_on_one_station(api)
        instrument_id = ctx["instrument"]["id"]
        first = validate_success(
            _schedule(
                api,
                ctx["orders"][0]["id"],
                instrument_id,
                "2026-08-01T08:00:00Z",
                "2026-08-01T10:00:00Z",
            ),
            expected_status=201,
        )
        second = validate_success(
            _schedule(
                api,
                ctx["orders"][1]["id"],
                instrument_id,
                "2026-08-01T10:15:00Z",
                "2026-08-01T11:15:00Z",
            ),
            expected_status=201,
        )

        _schedule(
            api,
            ctx["orders"][2]["id"],
            instrument_id,
            "2026-08-01T11:29:00Z",
            "2026-08-01T12:29:00Z",
        )

        assert_booked_minutes(_read_instrument(api, instrument_id), 180)
        third = _read_order(api, ctx["orders"][2]["id"])
        assert third["process_status"] == "BLANKS_RESERVED", (
            "a refused booking may not advance the order, got "
            f"{third['process_status']}"
        )
        rows, meta = validate_paginated(
            api.list_process_runs(
                make_process_technician_headers(),
                params={"metrology_instrument_id": instrument_id},
            )
        )
        assert_row_ids(rows, [first["id"], second["id"]], "the station's run listing")
        assert meta["total_count"] == 2, (
            f"only the two admitted runs exist, got {meta['total_count']}"
        )


class TestStageGateOutranksWindowConflict:
    """One request breaks the stage gate and the purge buffer; priority 14 wins."""

    @staticmethod
    def _two_orders_and_one_booked_window(api):
        """Two orders on one station, the second holding 08:00-10:00."""
        ctx = _three_orders_on_one_station(api, order_count=2)
        ctx["first_run"] = validate_success(
            _schedule(
                api,
                ctx["orders"][1]["id"],
                ctx["instrument"]["id"],
                "2026-08-01T08:00:00Z",
                "2026-08-01T10:00:00Z",
            ),
            expected_status=201,
        )
        return ctx

    def test_an_out_of_order_stage_is_reported_before_the_buffer_collision(self, api):
        """FIGURING from BLANKS_RESERVED reports the stage gate, not the calendar.

        The PRD states that "Scheduling a process run evaluates the stage gate, then
        the open-run gate, then calibration currency, then capability, then window
        shape, then window conflict — so a run requested at an out-of-order stage on
        an overdue instrument reports `ERR_RUN_STAGE_OUT_OF_ORDER`, and a malformed
        window on an overdue instrument reports
        `ERR_INSTRUMENT_CALIBRATION_OVERDUE`, because calibration currency is
        adjudicated before window shape."

        Design: Difficulty/priority_pair_validation_conflict/run_stage_order_outranks_instrument_window_conflict_on_process_run_create
        """
        ctx = self._two_orders_and_one_booked_window(api)

        refused = _schedule(
            api,
            ctx["orders"][0]["id"],
            ctx["instrument"]["id"],
            "2026-08-01T10:05:00Z",
            "2026-08-01T11:05:00Z",
            run_stage="FIGURING",
        )

        validate_error(refused, ERR_RUN_STAGE_OUT_OF_ORDER)
        assert error_id_of(refused) != ERR_INSTRUMENT_WINDOW_CONFLICT, (
            "priority 14 outranks priority 19, so the conflict code must not surface"
        )

    def test_the_identical_window_at_an_admissible_stage_surfaces_the_conflict(self, api):
        """With the stage gate satisfied, the five-minute gap is the live defect.

        The PRD states that "A `GRINDING` run may be scheduled only from
        `BLANKS_RESERVED` or `GRINDING`; a `POLISHING` run only from
        `BLANKS_RESERVED`, `GRINDING` or `POLISHING` — pre-polished blanks are
        allowed to skip grinding entirely; and a `FIGURING` run only from `POLISHING`
        or `FIGURING`." and that "Anything else is `ERR_RUN_STAGE_OUT_OF_ORDER`."

        Design: Difficulty/priority_pair_validation_conflict/run_stage_order_outranks_instrument_window_conflict_on_process_run_create
        """
        ctx = self._two_orders_and_one_booked_window(api)
        window = ("2026-08-01T10:05:00Z", "2026-08-01T11:05:00Z")

        stage_refused = _schedule(
            api,
            ctx["orders"][0]["id"],
            ctx["instrument"]["id"],
            window[0],
            window[1],
            run_stage="FIGURING",
        )
        conflict_refused = _schedule(
            api,
            ctx["orders"][0]["id"],
            ctx["instrument"]["id"],
            window[0],
            window[1],
            run_stage="POLISHING",
        )

        validate_error(stage_refused, ERR_RUN_STAGE_OUT_OF_ORDER)
        validate_error(conflict_refused, ERR_INSTRUMENT_WINDOW_CONFLICT)

    def test_neither_rejection_charges_the_station_or_moves_any_row(self, api):
        """The meter stays at 120 and both rows keep the state they had.

        The PRD states that "The invariant is that a station's
        `booked_minutes_total` always equals the sum of `window_minutes` over its
        runs whose `run_status` is `SCHEDULED`, `IN_PROCESS`, `AWAITING_METROLOGY`,
        `ACCEPTED` or `REWORK_REQUIRED` — accepted and reworked runs still count as
        capacity consumed even though they no longer block the calendar."

        Design: Difficulty/priority_pair_validation_conflict/run_stage_order_outranks_instrument_window_conflict_on_process_run_create
        """
        ctx = self._two_orders_and_one_booked_window(api)
        for stage in ("FIGURING", "POLISHING"):
            _schedule(
                api,
                ctx["orders"][0]["id"],
                ctx["instrument"]["id"],
                "2026-08-01T10:05:00Z",
                "2026-08-01T11:05:00Z",
                run_stage=stage,
            )

        assert_booked_minutes(_read_instrument(api, ctx["instrument"]["id"]), 120)
        first_order = _read_order(api, ctx["orders"][0]["id"])
        assert first_order["process_status"] == "BLANKS_RESERVED", (
            "two refusals may not advance the order, got "
            f"{first_order['process_status']}"
        )
        booked_run = _read_run(api, ctx["first_run"]["id"])
        assert booked_run["run_status"] == "SCHEDULED", (
            f"the incumbent run stays SCHEDULED, got {booked_run['run_status']}"
        )
        rows, meta = validate_paginated(
            api.list_process_runs(
                make_process_technician_headers(),
                params={"metrology_instrument_id": ctx["instrument"]["id"]},
            )
        )
        assert_row_ids(rows, [ctx["first_run"]["id"]], "the station's run listing")
        assert meta["total_count"] == 1, (
            f"no refused request may leave a row behind, got {meta['total_count']}"
        )


class TestRunCancelRestoresTheStationLedger:
    """A cancelled run gives back its minutes and its place in the queue."""

    @staticmethod
    def _one_booked_run(api):
        """One order in BLANKS_RESERVED with a scheduled 08:00-10:00 polishing run."""
        ctx = _three_orders_on_one_station(api, order_count=1)
        ctx["run"] = validate_success(
            _schedule(
                api,
                ctx["orders"][0]["id"],
                ctx["instrument"]["id"],
                "2026-08-01T08:00:00Z",
                "2026-08-01T10:00:00Z",
            ),
            expected_status=201,
        )
        return ctx

    def test_cancelling_the_run_returns_exactly_its_window_minutes(self, api):
        """The station meter falls 120 to 0 and nothing else moves.

        The PRD states that "Cancellation sets `run_status` to `CANCELLED` and
        decrements the station's `booked_minutes_total` by the run's
        `window_minutes`."

        Design: Difficulty/compensating_invariant/process_run_cancel_restores_instrument_booked_minutes_and_frees_the_window
        """
        ctx = self._one_booked_run(api)
        assert_booked_minutes(_read_instrument(api, ctx["instrument"]["id"]), 120)

        cancelled = validate_success(
            api.cancel_process_run(
                ctx["run"]["id"],
                build_cancel_run_payload(cancel_reason=CANCEL_REASON_BY_OPERATOR),
                make_process_technician_headers(),
            ),
            expected_status=200,
        )

        assert cancelled["run_status"] == "CANCELLED", (
            f"run_status must be CANCELLED, got {cancelled['run_status']}"
        )
        assert cancelled["cancel_reason"] == CANCEL_REASON_BY_OPERATOR, (
            f"cancel_reason must be CANCELLED_BY_OPERATOR, got {cancelled['cancel_reason']}"
        )
        assert cancelled["window_minutes"] == 120, (
            "the cancelled run keeps the window it held, got "
            f"{cancelled['window_minutes']}"
        )
        assert_booked_minutes(_read_instrument(api, ctx["instrument"]["id"]), 0)

    def test_the_cancellation_rewinds_neither_the_order_nor_the_blank_ledger(self, api):
        """Only the station's capacity is a compensated quantity here.

        The PRD states that cancellation "deliberately does **not** rewind the work
        order: `process_status` is left wherever the run put it, because the glass has
        already been touched."

        Design: Difficulty/compensating_invariant/process_run_cancel_restores_instrument_booked_minutes_and_frees_the_window
        """
        ctx = self._one_booked_run(api)

        api.cancel_process_run(
            ctx["run"]["id"],
            build_cancel_run_payload(cancel_reason=CANCEL_REASON_BY_OPERATOR),
            make_process_technician_headers(),
        )

        order = _read_order(api, ctx["orders"][0]["id"])
        assert order["process_status"] == "BLANKS_RESERVED", (
            "a run cancelled before it started leaves the order where it was, got "
            f"{order['process_status']}"
        )
        lot = validate_success(
            api.get_glass_lot(ctx["lot"]["id"], make_procurement_officer_headers()),
            expected_status=200,
        )
        assert_blank_ledger(
            lot, reserved=3, consumed=0, scrapped=0, available=17, total=20
        )

    def test_the_freed_window_admits_a_byte_identical_re_booking_with_no_residue(
        self, api
    ):
        """The cancelled run has left the conflict scan, so the window is free again.

        The PRD states that "The conflict scan considers only runs on the same station
        whose `run_status` is `SCHEDULED`, `IN_PROCESS` or `AWAITING_METROLOGY`; runs
        that are `CANCELLED`, `ACCEPTED` or `REWORK_REQUIRED` have left the station and
        are ignored."

        Design: Difficulty/compensating_invariant/process_run_cancel_restores_instrument_booked_minutes_and_frees_the_window
        """
        ctx = self._one_booked_run(api)
        api.cancel_process_run(
            ctx["run"]["id"],
            build_cancel_run_payload(cancel_reason=CANCEL_REASON_BY_OPERATOR),
            make_process_technician_headers(),
        )

        replacement = validate_success(
            _schedule(
                api,
                ctx["orders"][0]["id"],
                ctx["instrument"]["id"],
                "2026-08-01T08:00:00Z",
                "2026-08-01T10:00:00Z",
            ),
            expected_status=201,
        )

        assert replacement["run_status"] == "SCHEDULED", (
            f"run_status must be SCHEDULED, got {replacement['run_status']}"
        )
        assert replacement["window_minutes"] == 120, (
            f"window_minutes must be 120, got {replacement['window_minutes']}"
        )
        assert replacement["capability_ratio_at_scheduling"] == pytest.approx(
            expected_capability_ratio(0.0010, 0.0800), abs=1e-4
        ), (
            "the re-booking freezes its own capability ratio, got "
            f"{replacement['capability_ratio_at_scheduling']}"
        )
        assert_booked_minutes(_read_instrument(api, ctx["instrument"]["id"]), 120)


def test_process_run_window_shape_is_enforced_at_both_bounds(api):
    """Twenty-nine minutes, four hundred and eighty-one minutes and an inversion.

    The PRD states that "The window must end strictly after it starts and its
    duration must lie between 30 and 480 whole minutes inclusive — half an hour at
    the shortest, eight hours at the longest — otherwise `ERR_INVALID_WINDOW` (HTTP
    422) is returned."

    Design: Corner/validations/process_run_window_shape_is_enforced_at_both_bounds
    """
    ctx = _three_orders_on_one_station(api, order_count=1)
    order_id = ctx["orders"][0]["id"]
    instrument_id = ctx["instrument"]["id"]

    too_short = _schedule(
        api, order_id, instrument_id, "2026-08-01T08:00:00Z", "2026-08-01T08:29:00Z"
    )
    too_long = _schedule(
        api, order_id, instrument_id, "2026-08-01T08:00:00Z", "2026-08-01T16:01:00Z"
    )
    inverted = _schedule(
        api, order_id, instrument_id, "2026-08-01T09:00:00Z", "2026-08-01T08:00:00Z"
    )

    validate_error(too_short, ERR_INVALID_WINDOW, expected_status=422)
    validate_error(too_long, ERR_INVALID_WINDOW, expected_status=422)
    validate_error(inverted, ERR_INVALID_WINDOW, expected_status=422)
    assert_booked_minutes(_read_instrument(api, instrument_id), 0)

    accepted = validate_success(
        _schedule(
            api, order_id, instrument_id, "2026-08-01T08:00:00Z", "2026-08-01T08:30:00Z"
        ),
        expected_status=201,
    )

    assert accepted["window_minutes"] == MIN_WINDOW_MINUTES, (
        f"the shortest admissible window is 30 minutes, got {accepted['window_minutes']}"
    )
    assert accepted["run_status"] == "SCHEDULED", (
        f"run_status must be SCHEDULED, got {accepted['run_status']}"
    )
    assert_booked_minutes(_read_instrument(api, instrument_id), MIN_WINDOW_MINUTES)
    order = _read_order(api, order_id)
    assert order["process_status"] == "BLANKS_RESERVED", (
        "scheduling alone does not advance the stage, got "
        f"{order['process_status']}"
    )
