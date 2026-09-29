"""The station drift curve, the capability ratio and the gates it feeds."""

from test_helpers import (
    CAPABILITY_RATIO_LIMIT,
    CLOCK_EPOCH_UTC,
    ERR_METROLOGY_CAPABILITY_INSUFFICIENT,
    ERR_RUN_ALREADY_OPEN,
    ERR_WORK_ORDER_NOT_IN_PROCESS,
    assert_booked_minutes,
    assert_instrument_drift,
    assert_row_ids,
    assert_uncertainty_value,
    build_cancel_run_payload,
    build_coating_run_payload,
    build_process_run_payload,
    create_certified_lot,
    create_chamber,
    create_instrument,
    create_released_design,
    error_id_of,
    expected_capability_ratio,
    make_plant_admin_headers,
    make_process_technician_headers,
    open_work_order,
    round_half_up,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

TIGHT_ALLOCATION = (
    {
        "contributor_type": "SURFACE_IRREGULARITY",
        "sensitivity_waves_per_unit": 0.5,
        "manufacturing_tolerance_units": 0.0100,
    },
)

VERY_TIGHT_ALLOCATION = (
    {
        "contributor_type": "SURFACE_IRREGULARITY",
        "sensitivity_waves_per_unit": 0.1,
        "manufacturing_tolerance_units": 0.0250,
    },
)


def _read_instrument(api, instrument_id):
    """Read one metrology station as the plant administrator."""
    return validate_success(
        api.get_metrology_instrument(instrument_id, make_plant_admin_headers()),
        expected_status=200,
    )


def _schedule(api, work_order_id, instrument_id, start_utc, end_utc):
    """Attempt one metrology booking, returning the raw response."""
    return api.create_process_run(
        build_process_run_payload(
            work_order_id,
            instrument_id,
            metrology_window_start_utc=start_utc,
            metrology_window_end_utc=end_utc,
        ),
        make_process_technician_headers(),
    )


class TestCapabilityIndexNestedMinClipsDrift:
    """The drift cap bites before the budget scaling, not after it."""

    @staticmethod
    def _context(api):
        """An order against a 0.0400-wave budget and a station 92 days out."""
        design = create_released_design(
            api,
            TIGHT_ALLOCATION,
            design_code="OD-2540-C",
            tolerance_budget_waves=0.0400,
        )
        lot = create_certified_lot(api, lot_code="GL-2540-1")
        work_order = open_work_order(api, design["id"], lot["id"], lot["version"])
        instrument = create_instrument(
            api,
            instrument_code="IF-2540-1",
            base_uncertainty_waves=0.0010,
            calibration_interval_days=120,
            last_calibrated_utc=CLOCK_EPOCH_UTC,
        )
        set_clock(api, "2026-11-01T00:00:00Z")
        return {"design": design, "work_order": work_order, "instrument": instrument}

    def test_the_drift_term_is_clipped_to_double_the_base_uncertainty(self, api):
        """Ninety-two days of drift stop at twice the base figure.

        The PRD states that `effective_uncertainty_waves` "is
        `base_uncertainty_waves` inflated by two per cent for each whole day since
        calibration, but never allowed past twice the base figure — formally, the
        smaller of the drifted value and double the base value, rounded half up to
        six decimal places."

        Design: Difficulty/combinatorial_formula/capability_index_nested_min_clips_drift_before_budget_scaling
        """
        ctx = self._context(api)

        station = _read_instrument(api, ctx["instrument"]["id"])

        assert_instrument_drift(
            station,
            days_since_calibration=92,
            effective_uncertainty_waves=0.002000,
            instrument_status="CALIBRATED",
        )

    def test_the_clipped_uncertainty_is_what_the_budget_scaling_divides(self, api):
        """The booking is accepted on the clipped ratio of exactly 0.2000.

        The PRD states that "the linear drift term is clipped by the cap before it
        is scaled against the budget, so a badly overdue station's ratio stops
        rising even as the days accumulate."

        Design: Difficulty/combinatorial_formula/capability_index_nested_min_clips_drift_before_budget_scaling
        """
        ctx = self._context(api)

        response = _schedule(
            api,
            ctx["work_order"]["id"],
            ctx["instrument"]["id"],
            "2026-11-01T08:00:00Z",
            "2026-11-01T10:00:00Z",
        )

        run = validate_success(response, expected_status=201)
        assert run["capability_ratio_at_scheduling"] == expected_capability_ratio(
            0.002000, 0.0400
        ), (
            "the ratio must be four times the clipped uncertainty over the budget, "
            f"got {run['capability_ratio_at_scheduling']}"
        )
        assert run["capability_ratio_at_scheduling"] == 0.2000, (
            f"got {run['capability_ratio_at_scheduling']}"
        )
        assert run["window_minutes"] == 120, f"got {run['window_minutes']}"
        assert run["run_status"] == "SCHEDULED", f"got {run['run_status']}"
        assert_booked_minutes(_read_instrument(api, ctx["instrument"]["id"]), 120)

    def test_scaling_the_unclipped_drift_would_have_refused_the_run(self, api):
        """The unclipped 0.2840 ratio never surfaces as a refusal.

        The PRD states that "The gate is inclusive: a ratio of exactly 0.2500 is
        accepted, and only a ratio strictly greater than 0.2500 is refused, with
        `ERR_METROLOGY_CAPABILITY_INSUFFICIENT`."

        Design: Difficulty/combinatorial_formula/capability_index_nested_min_clips_drift_before_budget_scaling
        """
        ctx = self._context(api)
        unclipped_ratio = round_half_up(4 * 0.0010 * (1 + 0.02 * 92) / 0.0400, 4)
        assert unclipped_ratio > CAPABILITY_RATIO_LIMIT, (
            "the unclipped ratio is over the limit, so this test is only meaningful "
            f"if the clip is what saves the booking, got {unclipped_ratio}"
        )

        response = _schedule(
            api,
            ctx["work_order"]["id"],
            ctx["instrument"]["id"],
            "2026-11-01T08:00:00Z",
            "2026-11-01T10:00:00Z",
        )

        assert error_id_of(response) is None, (
            "the booking must not be refused, got "
            f"{error_id_of(response)} with HTTP {response.status_code}"
        )
        run = validate_success(response, expected_status=201)
        assert run["capability_ratio_at_scheduling"] != unclipped_ratio, (
            "the frozen ratio must not be the unclipped figure "
            f"{unclipped_ratio}, got {run['capability_ratio_at_scheduling']}"
        )


class TestCapabilityRatioExactlyAtQuarterLimit:
    """A quarter of the budget exactly is admissible; a hair more is not."""

    @staticmethod
    def _context(api):
        """An order against a 0.0800-wave budget and a 0.0050-wave station."""
        design = create_released_design(api, design_code="OD-2540-A")
        lot = create_certified_lot(api, lot_code="GL-2540-1")
        work_order = open_work_order(api, design["id"], lot["id"], lot["version"])
        instrument = create_instrument(
            api,
            instrument_code="IF-2540-1",
            base_uncertainty_waves=0.0050,
            calibration_interval_days=90,
            last_calibrated_utc=CLOCK_EPOCH_UTC,
        )
        return {"design": design, "work_order": work_order, "instrument": instrument}

    def test_a_ratio_of_exactly_one_quarter_is_admitted(self, api):
        """On calibration day the ratio lands on the limit and books the window.

        The PRD states that "The capability ratio is four times the station's
        `effective_uncertainty_waves` divided by the design's
        `tolerance_budget_waves`, rounded half up to four decimal places" and that
        "a ratio of exactly 0.2500 is accepted".

        Design: Difficulty/boundary_precision_check/capability_ratio_exactly_at_quarter_limit_is_admissible
        """
        ctx = self._context(api)
        station = _read_instrument(api, ctx["instrument"]["id"])
        assert_uncertainty_value(
            station["effective_uncertainty_waves"],
            0.005000,
            "effective_uncertainty_waves",
        )

        run = validate_success(
            _schedule(
                api,
                ctx["work_order"]["id"],
                ctx["instrument"]["id"],
                "2026-08-01T08:00:00Z",
                "2026-08-01T10:00:00Z",
            ),
            expected_status=201,
        )

        assert run["capability_ratio_at_scheduling"] == CAPABILITY_RATIO_LIMIT, (
            "the ratio must sit exactly on the limit, got "
            f"{run['capability_ratio_at_scheduling']}"
        )
        assert run["window_minutes"] == 120, f"got {run['window_minutes']}"
        assert_booked_minutes(_read_instrument(api, ctx["instrument"]["id"]), 120)

    def test_one_day_of_drift_pushes_the_identical_booking_over_the_limit(self, api):
        """A single day lifts the ratio one ten-thousandth past the gate.

        The PRD states that "only a ratio strictly greater than 0.2500 is refused,
        with `ERR_METROLOGY_CAPABILITY_INSUFFICIENT`".

        Design: Difficulty/boundary_precision_check/capability_ratio_exactly_at_quarter_limit_is_admissible
        """
        ctx = self._context(api)
        first = validate_success(
            _schedule(
                api,
                ctx["work_order"]["id"],
                ctx["instrument"]["id"],
                "2026-08-01T08:00:00Z",
                "2026-08-01T10:00:00Z",
            ),
            expected_status=201,
        )
        validate_success(
            api.cancel_process_run(
                first["id"],
                build_cancel_run_payload(),
                make_process_technician_headers(),
            ),
            expected_status=200,
        )
        set_clock(api, "2026-08-02T00:00:00Z")

        drifted = _read_instrument(api, ctx["instrument"]["id"])
        assert_instrument_drift(
            drifted,
            days_since_calibration=1,
            effective_uncertainty_waves=0.005100,
            instrument_status="CALIBRATED",
        )
        assert expected_capability_ratio(0.005100, 0.0800) == 0.2550, (
            "one day of drift takes the ratio to 0.2550"
        )

        refused = _schedule(
            api,
            ctx["work_order"]["id"],
            ctx["instrument"]["id"],
            "2026-08-02T08:00:00Z",
            "2026-08-02T10:00:00Z",
        )

        validate_error(
            refused, ERR_METROLOGY_CAPABILITY_INSUFFICIENT, expected_status=409
        )

    def test_the_cancelled_window_returns_its_minutes_and_the_refusal_books_none(
        self, api
    ):
        """The meter tracks the admitted booking and ignores the refused one.

        The PRD states that "`booked_minutes_total` is incremented by the run's
        `window_minutes` at scheduling and decremented by the same amount whenever
        the run is later cancelled".

        Design: Difficulty/boundary_precision_check/capability_ratio_exactly_at_quarter_limit_is_admissible
        """
        ctx = self._context(api)
        first = validate_success(
            _schedule(
                api,
                ctx["work_order"]["id"],
                ctx["instrument"]["id"],
                "2026-08-01T08:00:00Z",
                "2026-08-01T10:00:00Z",
            ),
            expected_status=201,
        )

        cancelled = validate_success(
            api.cancel_process_run(
                first["id"],
                build_cancel_run_payload(),
                make_process_technician_headers(),
            ),
            expected_status=200,
        )
        assert cancelled["run_status"] == "CANCELLED", f"got {cancelled['run_status']}"
        assert_booked_minutes(_read_instrument(api, ctx["instrument"]["id"]), 0)

        set_clock(api, "2026-08-02T00:00:00Z")
        refused = _schedule(
            api,
            ctx["work_order"]["id"],
            ctx["instrument"]["id"],
            "2026-08-02T08:00:00Z",
            "2026-08-02T10:00:00Z",
        )
        assert refused.status_code == 409, f"got {refused.status_code}"

        assert_booked_minutes(_read_instrument(api, ctx["instrument"]["id"]), 0)


def test_instrument_capability_run_concurrency_and_stage_readiness_each_refuse_a_run(
    api,
):
    """Three readiness refusals, and a finer station that proves the first one.

    The PRD states that "an order may have at most one run in flight: if any other
    run of the same work order is in `SCHEDULED`, `IN_PROCESS` or
    `AWAITING_METROLOGY`, the request is refused with `ERR_RUN_ALREADY_OPEN`", and
    that loading a coating run demands a work order whose `process_status` is
    "exactly `FIGURE_ACCEPTED`; from any other fabrication state the booking is
    refused with `ERR_WORK_ORDER_NOT_IN_PROCESS`."

    Design: Corner/errors/instrument_capability_run_concurrency_and_stage_readiness_each_refuse_a_run
    """
    design = create_released_design(
        api,
        VERY_TIGHT_ALLOCATION,
        design_code="OD-2540-T",
        tolerance_budget_waves=0.0100,
    )
    lot = create_certified_lot(api, lot_code="GL-2540-1")
    work_order = open_work_order(api, design["id"], lot["id"], lot["version"])
    coarse = create_instrument(
        api, instrument_code="IF-2540-COARSE", base_uncertainty_waves=0.0010
    )
    fine = create_instrument(
        api, instrument_code="IF-2540-FINE", base_uncertainty_waves=0.0006
    )
    chamber = create_chamber(api, chamber_code="CH-2540-1")

    too_coarse = _schedule(
        api,
        work_order["id"],
        coarse["id"],
        "2026-08-01T08:00:00Z",
        "2026-08-01T10:00:00Z",
    )
    validate_error(
        too_coarse, ERR_METROLOGY_CAPABILITY_INSUFFICIENT, expected_status=409
    )

    admitted = validate_success(
        _schedule(
            api,
            work_order["id"],
            fine["id"],
            "2026-08-01T08:00:00Z",
            "2026-08-01T10:00:00Z",
        ),
        expected_status=201,
    )
    assert admitted["capability_ratio_at_scheduling"] == 0.2400, (
        "the finer station's ratio is inside the limit, got "
        f"{admitted['capability_ratio_at_scheduling']}"
    )
    assert admitted["run_status"] == "SCHEDULED", f"got {admitted['run_status']}"

    second_run = _schedule(
        api,
        work_order["id"],
        fine["id"],
        "2026-08-01T13:00:00Z",
        "2026-08-01T15:00:00Z",
    )
    validate_error(second_run, ERR_RUN_ALREADY_OPEN, expected_status=409)

    early_coating = api.create_coating_run(
        build_coating_run_payload(work_order["id"], chamber["id"]),
        make_process_technician_headers(),
    )
    validate_error(early_coating, ERR_WORK_ORDER_NOT_IN_PROCESS, expected_status=409)

    rows, meta = validate_paginated(
        api.list_process_runs(
            make_process_technician_headers(),
            params={"work_order_id": work_order["id"]},
        )
    )
    assert_row_ids(rows, [admitted["id"]], "the run listing for the work order")
    assert meta["total_count"] == 1, f"got {meta['total_count']}"
    assert_booked_minutes(_read_instrument(api, fine["id"]), 120)
    assert_booked_minutes(_read_instrument(api, coarse["id"]), 0)
