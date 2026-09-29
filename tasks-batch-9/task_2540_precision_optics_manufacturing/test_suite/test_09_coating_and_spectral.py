"""Chamber occupancy, the two spectral variants and the strip-and-recoat cycle."""

from test_helpers import (
    ALL_ZERO_UUID,
    BAND_AVERAGE_REFLECTANCE_LIMIT_PCT,
    ERR_CHAMBER_CAPACITY_EXCEEDED,
    ERR_CHAMBER_NOT_FOUND,
    ERR_INVALID_STATE_TRANSITION,
    ERR_SPECTRAL_SAMPLE_INSUFFICIENT,
    MT_THIRD,
    PASSING_SPECTRAL_TRACE,
    SCRAP_REASON_COATING_STRIP_LIMIT,
    WORST_POINT_FAILING_TRACE,
    WORST_POINT_REFLECTANCE_LIMIT_PCT,
    advance_to_figure_accepted,
    assert_blank_ledger,
    assert_row_ids,
    assert_spectral_outputs,
    assert_spectral_outputs_cleared,
    build_coating_chamber_payload,
    build_coating_run_payload,
    build_spectral_samples,
    build_spectral_verification_payload,
    create_certified_lot,
    create_chamber,
    create_instrument,
    create_released_design,
    is_iso8601_timestamp,
    make_metrology_technician_headers,
    make_plant_admin_headers,
    make_procurement_officer_headers,
    make_process_technician_headers,
    omit,
    open_work_order,
    setup_figure_accepted_work_order,
    validate_error,
    validate_paginated,
    validate_success,
)

# The four in-band readings shared by both attempts of the upper-bound probe,
# plus the fifth point that moves from 701 nm to exactly 700 nm.
BOUNDARY_IN_BAND_POINTS = ((450, 0.4000), (500, 0.5000), (600, 0.6000), (680, 0.7000))

# The trace whose only defect is a 800 nm point outside the 450..700 nm band.
FOUR_IN_BAND_POINTS = ((450, 0.1000), (500, 0.1200), (600, 0.1400), (700, 0.1800))


def _read_run(api, coating_run_id):
    """Read one coating run with its spectral aggregates."""
    return validate_success(
        api.get_coating_run(coating_run_id, make_process_technician_headers()),
        expected_status=200,
    )


def _read_order(api, work_order_id):
    """Read one work order."""
    return validate_success(
        api.get_work_order(work_order_id, make_process_technician_headers()),
        expected_status=200,
    )


def _read_lot(api, glass_lot_id):
    """Read one melt lot and its blank ledger."""
    return validate_success(
        api.get_glass_lot(glass_lot_id, make_procurement_officer_headers()),
        expected_status=200,
    )


def _book(api, work_order_id, chamber_id, start_utc, end_utc, recipe="AR-VIS-01"):
    """Attempt one chamber booking and return the raw response."""
    return api.create_coating_run(
        build_coating_run_payload(
            work_order_id,
            chamber_id,
            window_start_utc=start_utc,
            window_end_utc=end_utc,
            coating_recipe_code=recipe,
        ),
        make_process_technician_headers(),
    )


def _verify(api, coating_run_id, samples, headers=None):
    """Submit one spectrophotometer trace against a deposited run."""
    return api.verify_coating_spectrum(
        coating_run_id,
        build_spectral_verification_payload(samples),
        headers if headers is not None else make_process_technician_headers(),
    )


def _deposited_run(api, slot_capacity=2, **overrides):
    """A work order in COATING whose coating run has reached DEPOSITED."""
    ctx = setup_figure_accepted_work_order(api, **overrides)
    ctx["chamber"] = create_chamber(
        api, chamber_code="CH-2540-1", slot_capacity=slot_capacity
    )
    ctx["coating_run"] = validate_success(
        _book(
            api,
            ctx["work_order"]["id"],
            ctx["chamber"]["id"],
            "2026-08-02T08:00:00Z",
            "2026-08-02T12:00:00Z",
        ),
        expected_status=201,
    )
    validate_success(
        api.deposit_coating_run(
            ctx["coating_run"]["id"], make_process_technician_headers()
        ),
        expected_status=200,
    )
    return ctx


def _verified_fail_run(api, **overrides):
    """A deposited run driven to VERIFIED_FAIL by the narrow-spike trace."""
    ctx = _deposited_run(api, **overrides)
    validate_success(
        _verify(api, ctx["coating_run"]["id"], list(WORST_POINT_FAILING_TRACE)),
        expected_status=200,
    )
    return ctx


def _two_figure_accepted_orders(api, slot_capacity=1):
    """Two orders at FIGURE_ACCEPTED, each on its own station, and one chamber."""
    design = create_released_design(api, design_code="OD-2540-A")
    lot = create_certified_lot(api, lot_code="GL-2540-1", total_blank_count=20)
    first = open_work_order(
        api, design["id"], lot["id"], lot["version"], wo_code="WO-2540-A"
    )
    lot_after = _read_lot(api, lot["id"])
    second = open_work_order(
        api, design["id"], lot["id"], lot_after["version"], wo_code="WO-2540-B"
    )
    instruments = [
        create_instrument(api, instrument_code="IF-2540-1"),
        create_instrument(api, instrument_code="IF-2540-2"),
    ]
    for order, instrument in zip((first, second), instruments):
        advance_to_figure_accepted(api, order["id"], instrument["id"])
    chamber = create_chamber(
        api, chamber_code="CH-2540-1", slot_capacity=slot_capacity
    )
    return {
        "design": design,
        "lot": lot,
        "orders": [first, second],
        "instruments": instruments,
        "chamber": chamber,
    }


class TestSpectralVariantsDivergeOnOneTrace:
    """One trace, two conventions: the band average passes and the spike does not."""

    def test_the_band_average_variant_sails_through_on_the_spike_trace(self, api):
        """The mean of the five in-band readings is 0.4400 per cent.

        The PRD states that "A trace of five in-band readings at 0.2000, 0.1800,
        0.2200, 0.2500 and 1.3500 per cent averages to 0.4400 — comfortably inside
        the band-average limit — yet its worst point of 1.3500 exceeds the point
        limit, and the pinned conjunction therefore yields `FAIL`."

        Design: Difficulty/dual_variant_calc/coating_spectral_band_average_and_worst_point_variants_diverge_on_coating_run
        """
        ctx = _deposited_run(api)

        verified = validate_success(
            _verify(api, ctx["coating_run"]["id"], list(WORST_POINT_FAILING_TRACE)),
            expected_status=200,
        )

        assert verified["in_band_sample_count"] == 5, (
            f"in_band_sample_count must be 5, got {verified['in_band_sample_count']}"
        )
        assert verified["band_average_reflectance_pct"] == 0.4400, (
            "band_average_reflectance_pct must be 0.4400, got "
            f"{verified['band_average_reflectance_pct']}"
        )
        assert (
            verified["band_average_reflectance_pct"]
            <= BAND_AVERAGE_REFLECTANCE_LIMIT_PCT
        ), (
            "0.4400 is inside the 0.5000 band-average limit, so that variant passes "
            "on its own"
        )

    def test_the_worst_point_variant_fails_and_the_conjunction_governs(self, api):
        """The largest single reading is 1.3500 per cent and it decides the verdict.

        The PRD states that "`worst_point_reflectance_pct` is the largest single
        `reflectance_pct` among the in-band samples, rounded half up to four decimal
        places, and it must not exceed 1.2000 per cent." and that
        "`spectral_verdict` is `PASS` only when **both** limits hold, and `FAIL` when
        either is breached."

        Design: Difficulty/dual_variant_calc/coating_spectral_band_average_and_worst_point_variants_diverge_on_coating_run
        """
        ctx = _deposited_run(api)

        verified = validate_success(
            _verify(api, ctx["coating_run"]["id"], list(WORST_POINT_FAILING_TRACE)),
            expected_status=200,
        )

        assert verified["worst_point_reflectance_pct"] == 1.3500, (
            "worst_point_reflectance_pct must be 1.3500, got "
            f"{verified['worst_point_reflectance_pct']}"
        )
        assert (
            verified["worst_point_reflectance_pct"]
            > WORST_POINT_REFLECTANCE_LIMIT_PCT
        ), "1.3500 is outside the 1.2000 point limit, so that variant fails"
        assert verified["spectral_verdict"] == "FAIL", (
            "the conjunction of a passing average and a failing point is FAIL, got "
            f"{verified['spectral_verdict']}"
        )

    def test_the_failing_conjunction_holds_the_order_in_coating(self, api):
        """A failed spectrum parks the run and leaves the order where it was.

        The PRD states that "On `FAIL` the run moves `DEPOSITED → VERIFIED_FAIL` and
        the work order stays in `COATING`."

        Design: Difficulty/dual_variant_calc/coating_spectral_band_average_and_worst_point_variants_diverge_on_coating_run
        """
        ctx = _deposited_run(api)

        validate_success(
            _verify(api, ctx["coating_run"]["id"], list(WORST_POINT_FAILING_TRACE)),
            expected_status=200,
        )

        run = _read_run(api, ctx["coating_run"]["id"])
        order = _read_order(api, ctx["work_order"]["id"])
        assert run["coating_status"] == "VERIFIED_FAIL", (
            f"coating_status must be VERIFIED_FAIL, got {run['coating_status']}"
        )
        assert run["strip_count"] == 0, (
            f"a failed verification does not strip anything, got {run['strip_count']}"
        )
        assert_spectral_outputs(run, 5, 0.4400, 1.3500, "FAIL")
        assert order["process_status"] == "COATING", (
            f"process_status must stay COATING, got {order['process_status']}"
        )


class TestStripAndRecoatCycle:
    """The coating loop is re-entrant once: VERIFIED_FAIL walks back to LOADED."""

    def test_the_strip_returns_the_run_to_loaded_with_every_output_cleared(self, api):
        """One strip rewinds the run and wipes all four spectral outputs.

        The PRD states that "When `strip_count` after the increment is still no
        greater than one, the run returns `VERIFIED_FAIL → LOADED` for another
        deposition attempt: `spectral_samples` is reset to an empty array,
        `in_band_sample_count` back to zero, both reflectance aggregates back to null
        and `spectral_verdict` back to `PENDING`."

        Design: Difficulty/non_linear_state_machine/coating_run_strip_and_recoat_cycle_returns_to_loaded
        """
        ctx = _verified_fail_run(api)

        stripped = validate_success(
            api.strip_coating_run(
                ctx["coating_run"]["id"], make_process_technician_headers()
            ),
            expected_status=200,
        )

        assert stripped["coating_status"] == "LOADED", (
            f"coating_status must be LOADED, got {stripped['coating_status']}"
        )
        assert stripped["strip_count"] == 1, (
            f"strip_count must be 1, got {stripped['strip_count']}"
        )
        assert_spectral_outputs_cleared(stripped)

    def test_the_second_deposition_re_enters_the_cycle(self, api):
        """The stripped run deposits again and the order never leaves COATING.

        The PRD states that "This is the strip-and-recoat cycle
        `LOADED → DEPOSITED → VERIFIED_FAIL → LOADED`, and the work order is driven
        `COATED → COATING` — or held in `COATING` if it was already there."

        Design: Difficulty/non_linear_state_machine/coating_run_strip_and_recoat_cycle_returns_to_loaded
        """
        ctx = _verified_fail_run(api)
        api.strip_coating_run(
            ctx["coating_run"]["id"], make_process_technician_headers()
        )

        after_strip = _read_order(api, ctx["work_order"]["id"])
        redeposited = validate_success(
            api.deposit_coating_run(
                ctx["coating_run"]["id"], make_process_technician_headers()
            ),
            expected_status=200,
        )

        assert after_strip["process_status"] == "COATING", (
            "an order already in COATING is held there by the strip, got "
            f"{after_strip['process_status']}"
        )
        assert redeposited["coating_status"] == "DEPOSITED", (
            f"coating_status must be DEPOSITED, got {redeposited['coating_status']}"
        )
        assert redeposited["strip_count"] == 1, (
            f"the second deposition does not strip again, got {redeposited['strip_count']}"
        )
        assert_spectral_outputs_cleared(redeposited)

    def test_the_clean_recoat_closes_the_cycle_at_verified_pass(self, api):
        """A passing trace on the second coat carries the order to COATED.

        The PRD states that "On `PASS` the run moves `DEPOSITED → VERIFIED_PASS` and
        the work order advances `COATING → COATED`."

        Design: Difficulty/non_linear_state_machine/coating_run_strip_and_recoat_cycle_returns_to_loaded
        """
        ctx = _verified_fail_run(api)
        api.strip_coating_run(
            ctx["coating_run"]["id"], make_process_technician_headers()
        )
        api.deposit_coating_run(
            ctx["coating_run"]["id"], make_process_technician_headers()
        )

        verified = validate_success(
            _verify(
                api,
                ctx["coating_run"]["id"],
                list(PASSING_SPECTRAL_TRACE),
                make_metrology_technician_headers(MT_THIRD),
            ),
            expected_status=200,
        )

        assert_spectral_outputs(verified, 5, 0.1400, 0.1800, "PASS")
        assert verified["coating_status"] == "VERIFIED_PASS", (
            f"coating_status must be VERIFIED_PASS, got {verified['coating_status']}"
        )
        assert verified["strip_count"] == 1, (
            f"strip_count must still be 1, got {verified['strip_count']}"
        )
        order = _read_order(api, ctx["work_order"]["id"])
        assert order["process_status"] == "COATED", (
            f"process_status must be COATED, got {order['process_status']}"
        )


class TestBandMembershipAtTheUpperBound:
    """One nanometre decides whether the fifth sample counts at all."""

    def test_a_point_one_nanometre_above_the_band_leaves_only_four_in_band_samples(
        self, api
    ):
        """A 701 nm reading on a 450..700 nm design is not counted.

        The PRD states that "A sample counts as in-band when its `wavelength_nm` lies
        within the design's specified range, inclusive at both ends — a sample exactly
        at `wavelength_max_nm` counts, a sample one nanometre above it does not." and
        that "`in_band_sample_count` is the number of such samples, and at least five
        are required; fewer is refused with `ERR_SPECTRAL_SAMPLE_INSUFFICIENT`
        (HTTP 422)."

        Design: Difficulty/boundary_precision_check/spectral_sample_exactly_at_band_upper_bound_counts_as_in_band
        """
        ctx = _deposited_run(api)

        refused = _verify(
            api,
            ctx["coating_run"]["id"],
            build_spectral_samples(*BOUNDARY_IN_BAND_POINTS, (701, 0.3000)),
        )

        validate_error(refused, ERR_SPECTRAL_SAMPLE_INSUFFICIENT)
        run = _read_run(api, ctx["coating_run"]["id"])
        assert run["coating_status"] == "DEPOSITED", (
            f"the refusal leaves the run DEPOSITED, got {run['coating_status']}"
        )
        assert_spectral_outputs_cleared(run)

    def test_moving_the_same_point_to_the_upper_bound_admits_it(self, api):
        """At exactly 700 nm the fifth sample counts and the average is 0.5000.

        The PRD states that "`band_average_reflectance_pct` is the mean of their
        `reflectance_pct` values — summed at full precision, divided by the in-band
        count, and rounded half up to four decimal places exactly once — and it must
        not exceed 0.5000 per cent."

        Design: Difficulty/boundary_precision_check/spectral_sample_exactly_at_band_upper_bound_counts_as_in_band
        """
        ctx = _deposited_run(api)
        _verify(
            api,
            ctx["coating_run"]["id"],
            build_spectral_samples(*BOUNDARY_IN_BAND_POINTS, (701, 0.3000)),
        )

        accepted = validate_success(
            _verify(
                api,
                ctx["coating_run"]["id"],
                build_spectral_samples(*BOUNDARY_IN_BAND_POINTS, (700, 0.3000)),
            ),
            expected_status=200,
        )

        assert_spectral_outputs(accepted, 5, 0.5000, 0.7000, "PASS")
        assert (
            accepted["band_average_reflectance_pct"]
            == BAND_AVERAGE_REFLECTANCE_LIMIT_PCT
        ), "an average exactly at the 0.5000 limit does not exceed it"
        assert accepted["coating_status"] == "VERIFIED_PASS", (
            f"coating_status must be VERIFIED_PASS, got {accepted['coating_status']}"
        )
        order = _read_order(api, ctx["work_order"]["id"])
        assert order["process_status"] == "COATED", (
            f"process_status must be COATED, got {order['process_status']}"
        )


class TestChamberHalfOpenIntervalsAtCapacity:
    """A single-slot chamber refuses an overlap and admits a touching booking."""

    def test_an_overlapping_booking_is_refused_when_the_only_slot_is_taken(self, api):
        """A request for 11:00-15:00 collides with the loaded 08:00-12:00 run.

        The PRD states that "the system counts the chamber's coating runs whose
        `coating_status` is `LOADED`, `DEPOSITED` or `VERIFIED_FAIL` and whose
        interval overlaps the requested one, and refuses the booking with
        `ERR_CHAMBER_CAPACITY_EXCEEDED` when that count has already reached the
        chamber's `slot_capacity`."

        Design: Difficulty/resource_temporal_overlap/chamber_half_open_interval_admits_touching_booking_and_rejects_overlap_at_capacity
        """
        ctx = _two_figure_accepted_orders(api, slot_capacity=1)
        first, second = ctx["orders"]
        validate_success(
            _book(
                api,
                first["id"],
                ctx["chamber"]["id"],
                "2026-08-02T08:00:00Z",
                "2026-08-02T12:00:00Z",
            ),
            expected_status=201,
        )

        refused = _book(
            api,
            second["id"],
            ctx["chamber"]["id"],
            "2026-08-02T11:00:00Z",
            "2026-08-02T15:00:00Z",
            recipe="AR-VIS-02",
        )

        validate_error(refused, ERR_CHAMBER_CAPACITY_EXCEEDED)
        held_back = _read_order(api, second["id"])
        assert held_back["process_status"] == "FIGURE_ACCEPTED", (
            "the refused booking leaves the order at FIGURE_ACCEPTED, got "
            f"{held_back['process_status']}"
        )

    def test_a_booking_that_starts_when_the_previous_one_ends_is_admitted(self, api):
        """A request for 12:00-16:00 touches without overlapping.

        The PRD states that "Consequently a booking that begins at the exact instant a
        previous booking ends does **not** overlap it and is always admissible; there
        is no purge buffer on a chamber."

        Design: Difficulty/resource_temporal_overlap/chamber_half_open_interval_admits_touching_booking_and_rejects_overlap_at_capacity
        """
        ctx = _two_figure_accepted_orders(api, slot_capacity=1)
        first, second = ctx["orders"]
        validate_success(
            _book(
                api,
                first["id"],
                ctx["chamber"]["id"],
                "2026-08-02T08:00:00Z",
                "2026-08-02T12:00:00Z",
            ),
            expected_status=201,
        )
        _book(
            api,
            second["id"],
            ctx["chamber"]["id"],
            "2026-08-02T11:00:00Z",
            "2026-08-02T15:00:00Z",
            recipe="AR-VIS-02",
        )

        admitted = validate_success(
            _book(
                api,
                second["id"],
                ctx["chamber"]["id"],
                "2026-08-02T12:00:00Z",
                "2026-08-02T16:00:00Z",
                recipe="AR-VIS-02",
            ),
            expected_status=201,
        )

        assert admitted["coating_status"] == "LOADED", (
            f"coating_status must be LOADED, got {admitted['coating_status']}"
        )
        assert admitted["strip_count"] == 0, (
            f"strip_count must start at zero, got {admitted['strip_count']}"
        )
        assert admitted["spectral_verdict"] == "PENDING", (
            f"spectral_verdict must be PENDING, got {admitted['spectral_verdict']}"
        )

    def test_both_bookings_stand_and_both_orders_are_in_coating(self, api):
        """The touching booking drives its own order and leaves the first alone.

        The PRD states that a successful booking "also drives the work order
        `FIGURE_ACCEPTED → COATING`."

        Design: Difficulty/resource_temporal_overlap/chamber_half_open_interval_admits_touching_booking_and_rejects_overlap_at_capacity
        """
        ctx = _two_figure_accepted_orders(api, slot_capacity=1)
        first, second = ctx["orders"]
        earlier = validate_success(
            _book(
                api,
                first["id"],
                ctx["chamber"]["id"],
                "2026-08-02T08:00:00Z",
                "2026-08-02T12:00:00Z",
            ),
            expected_status=201,
        )

        later = validate_success(
            _book(
                api,
                second["id"],
                ctx["chamber"]["id"],
                "2026-08-02T12:00:00Z",
                "2026-08-02T16:00:00Z",
                recipe="AR-VIS-02",
            ),
            expected_status=201,
        )

        assert _read_run(api, earlier["id"])["coating_status"] == "LOADED", (
            "the earlier run is untouched by the second booking"
        )
        assert later["coating_chamber_id"] == ctx["chamber"]["id"]
        assert _read_order(api, first["id"])["process_status"] == "COATING", (
            "the first order is in COATING"
        )
        assert _read_order(api, second["id"])["process_status"] == "COATING", (
            "the touching booking drives the second order into COATING"
        )


def test_chamber_occupancy_excludes_the_run_that_already_passed_verification(api):
    """The identical interval is refused, then admitted once the coat has passed.

    The PRD states that "Runs in `VERIFIED_PASS` or `SCRAPPED` have physically left
    the chamber and are excluded from the count."

    Design: Corner/calculations/chamber_occupancy_excludes_the_run_that_already_passed_verification
    """
    ctx = _two_figure_accepted_orders(api, slot_capacity=1)
    first, second = ctx["orders"]
    occupant = validate_success(
        _book(
            api,
            first["id"],
            ctx["chamber"]["id"],
            "2026-08-02T08:00:00Z",
            "2026-08-02T12:00:00Z",
        ),
        expected_status=201,
    )
    validate_success(
        api.deposit_coating_run(occupant["id"], make_process_technician_headers()),
        expected_status=200,
    )

    while_deposited = _book(
        api,
        second["id"],
        ctx["chamber"]["id"],
        "2026-08-02T08:00:00Z",
        "2026-08-02T12:00:00Z",
    )

    validate_error(while_deposited, ERR_CHAMBER_CAPACITY_EXCEEDED)
    verified = validate_success(
        _verify(api, occupant["id"], list(PASSING_SPECTRAL_TRACE)),
        expected_status=200,
    )
    assert_spectral_outputs(verified, 5, 0.1400, 0.1800, "PASS")
    assert verified["coating_status"] == "VERIFIED_PASS", (
        f"coating_status must be VERIFIED_PASS, got {verified['coating_status']}"
    )

    after_pass = validate_success(
        _book(
            api,
            second["id"],
            ctx["chamber"]["id"],
            "2026-08-02T08:00:00Z",
            "2026-08-02T12:00:00Z",
        ),
        expected_status=201,
    )

    assert after_pass["coating_status"] == "LOADED", (
        "the interval arithmetic is unchanged; only the counted set shrank, got "
        f"{after_pass['coating_status']}"
    )
    assert after_pass["coating_chamber_id"] == ctx["chamber"]["id"]
    assert _read_order(api, first["id"])["process_status"] == "COATED", (
        "the passing verification advanced the first order to COATED"
    )
    assert _read_order(api, second["id"])["process_status"] == "COATING", (
        "the admitted booking drove the second order into COATING"
    )


def test_strip_and_recoat_reconciles_the_three_spectral_outputs_twice(api):
    """Three successive spectral states, each fully reconciled with no stale value.

    The PRD states that "The array **replaces** whatever was previously stored on the
    run; it is not merged." and that "`spectral_verdict` is `PASS` only when **both**
    limits hold, and `FAIL` when either is breached."

    Design: Corner/calculations/strip_and_recoat_reconciles_the_three_spectral_outputs_twice
    """
    ctx = _verified_fail_run(api, slot_capacity=1)
    run_id = ctx["coating_run"]["id"]

    failed = _read_run(api, run_id)
    assert_spectral_outputs(failed, 5, 0.4400, 1.3500, "FAIL")
    assert failed["coating_status"] == "VERIFIED_FAIL", (
        f"coating_status must be VERIFIED_FAIL, got {failed['coating_status']}"
    )
    assert failed["strip_count"] == 0, (
        f"strip_count must still be 0, got {failed['strip_count']}"
    )
    assert _read_order(api, ctx["work_order"]["id"])["process_status"] == "COATING", (
        "a failed coat leaves the order in COATING"
    )

    validate_success(
        api.strip_coating_run(run_id, make_process_technician_headers()),
        expected_status=200,
    )

    stripped = _read_run(api, run_id)
    assert_spectral_outputs_cleared(stripped)
    assert stripped["coating_status"] == "LOADED", (
        f"coating_status must be LOADED, got {stripped['coating_status']}"
    )
    assert stripped["strip_count"] == 1, (
        f"strip_count must be 1, got {stripped['strip_count']}"
    )

    validate_success(
        api.deposit_coating_run(run_id, make_process_technician_headers()),
        expected_status=200,
    )
    validate_success(
        _verify(api, run_id, list(PASSING_SPECTRAL_TRACE)), expected_status=200
    )

    recoated = _read_run(api, run_id)
    assert_spectral_outputs(recoated, 5, 0.1400, 0.1800, "PASS")
    assert recoated["coating_status"] == "VERIFIED_PASS", (
        f"coating_status must be VERIFIED_PASS, got {recoated['coating_status']}"
    )
    assert recoated["strip_count"] == 1, (
        f"strip_count must still be 1, got {recoated['strip_count']}"
    )
    assert _read_order(api, ctx["work_order"]["id"])["process_status"] == "COATED", (
        "the order reaches COATED only after the passing verification"
    )


def test_second_strip_beyond_the_cycle_limit_scraps_the_run_and_the_order(api):
    """The second strip exhausts the loop and writes the substrate off.

    The PRD states that "When `strip_count` after the increment exceeds one, the shop
    has run out of attempts: the run moves `VERIFIED_FAIL → SCRAPPED`, a terminal
    state, and the work order is scrapped from `COATING` with `scrap_reason` set to the
    literal string `COATING_STRIP_LIMIT`, carrying the same four-hop chain declared in
    §3.5 — substrate written off from the still-open reservation, active components
    voided, affected assemblies recomputed and demoted."

    Design: Corner/state_machines/second_strip_beyond_the_cycle_limit_scraps_the_run_and_the_order
    """
    ctx = _verified_fail_run(api)
    run_id = ctx["coating_run"]["id"]
    validate_success(
        api.strip_coating_run(run_id, make_process_technician_headers()),
        expected_status=200,
    )
    validate_success(
        api.deposit_coating_run(run_id, make_process_technician_headers()),
        expected_status=200,
    )
    validate_success(
        _verify(api, run_id, list(WORST_POINT_FAILING_TRACE)), expected_status=200
    )

    scrapped = validate_success(
        api.strip_coating_run(run_id, make_process_technician_headers()),
        expected_status=200,
    )

    assert scrapped["strip_count"] == 2, (
        f"strip_count must be 2, got {scrapped['strip_count']}"
    )
    assert scrapped["coating_status"] == "SCRAPPED", (
        f"coating_status must be SCRAPPED, got {scrapped['coating_status']}"
    )
    assert_spectral_outputs(scrapped, 5, 0.4400, 1.3500, "FAIL")
    order = _read_order(api, ctx["work_order"]["id"])
    assert order["process_status"] == "SCRAPPED", (
        f"process_status must be SCRAPPED, got {order['process_status']}"
    )
    assert order["scrap_reason"] == SCRAP_REASON_COATING_STRIP_LIMIT, (
        f"scrap_reason must be COATING_STRIP_LIMIT, got {order['scrap_reason']}"
    )
    assert_blank_ledger(
        _read_lot(api, ctx["lot"]["id"]),
        reserved=0,
        consumed=0,
        scrapped=3,
        available=17,
        total=20,
    )

    third_strip = api.strip_coating_run(run_id, make_process_technician_headers())

    validate_error(third_strip, ERR_INVALID_STATE_TRANSITION)
    assert _read_run(api, run_id)["strip_count"] == 2, (
        "the refused third strip may not increment the counter"
    )


def test_coating_chamber_create_read_and_list_are_the_plain_crud_triple(api):
    """The one entity with no state machine exercises its three endpoints alone.

    The PRD states that "Chambers are plant assets, registered by a `PlantAdmin` with
    a `chamber_code` asset tag of 1 to 40 characters, a `coating_type` naming the
    family the chamber is tooled for — `AR_BROADBAND` by default, or
    `DIELECTRIC_MIRROR` or `BEAMSPLITTER` — and a `slot_capacity` of at least one,
    giving the number of load slots that may be occupied at the same instant." and
    that "Chambers are read individually or listed with an optional `coating_type`
    filter."

    Design: Corner/endpoints/coating_chamber_create_read_and_list_are_the_plain_crud_triple
    """
    admin = make_plant_admin_headers()

    first = validate_success(
        api.create_coating_chamber(
            omit(
                build_coating_chamber_payload(
                    chamber_code="CH-2540-1", slot_capacity=2
                ),
                "coating_type",
            ),
            admin,
        ),
        expected_status=201,
    )
    second = validate_success(
        api.create_coating_chamber(
            build_coating_chamber_payload(
                chamber_code="CH-2540-2",
                slot_capacity=1,
                coating_type="DIELECTRIC_MIRROR",
            ),
            admin,
        ),
        expected_status=201,
    )

    assert first["chamber_code"] == "CH-2540-1"
    assert first["slot_capacity"] == 2, (
        f"slot_capacity must be echoed as 2, got {first['slot_capacity']}"
    )
    assert first["coating_type"] == "AR_BROADBAND", (
        f"coating_type must default to AR_BROADBAND, got {first['coating_type']}"
    )
    assert second["coating_type"] == "DIELECTRIC_MIRROR"
    assert second["id"] != first["id"], "the two chambers must be distinct rows"

    read = validate_success(
        api.get_coating_chamber(first["id"], make_process_technician_headers()),
        expected_status=200,
    )
    assert read == first, (
        f"the single read must return the identical row, got {read} for {first}"
    )
    assert read["version"] == 1, f"version must start at 1, got {read['version']}"
    assert is_iso8601_timestamp(read["created_at"])

    everything, meta = validate_paginated(api.list_coating_chambers(admin))
    assert_row_ids(everything, [first["id"], second["id"]], "the chamber listing")
    assert meta["total_count"] == 2, f"total_count must be 2, got {meta['total_count']}"

    filtered, filtered_meta = validate_paginated(
        api.list_coating_chambers(admin, params={"coating_type": "DIELECTRIC_MIRROR"})
    )
    assert_row_ids(filtered, [second["id"]], "the coating_type filtered listing")
    assert filtered_meta["total_count"] == 1

    page, page_meta = validate_paginated(
        api.list_coating_chambers(admin, params={"limit": 1, "offset": 1})
    )
    assert_row_ids(page, [second["id"]], "the second page of one row")
    assert page_meta["total_count"] == 2, (
        f"total_count counts the match, not the page, got {page_meta['total_count']}"
    )
    assert page_meta["has_more"] is False

    missing = api.get_coating_chamber(ALL_ZERO_UUID, admin)

    validate_error(missing, ERR_CHAMBER_NOT_FOUND)


def test_four_in_band_samples_are_refused_before_any_reflectance_is_judged(api):
    """The sample-count gate is adjudicated before either reflectance limit.

    The PRD states that "Budget and sample-sufficiency gates: the design has at least
    one active tolerance allocation before the stack-up runs; a spectral verification
    supplies at least five in-band samples; the analysed stack does not exceed the
    design's tolerance budget at design release — `ERR_TOLERANCE_STACK_EMPTY`,
    `ERR_SPECTRAL_SAMPLE_INSUFFICIENT` or `ERR_TOLERANCE_BUDGET_EXCEEDED`, 422." and
    that "the first rule violated determines the entire response, and no later rule is
    evaluated".

    Design: Corner/errors/four_in_band_samples_are_refused_before_any_reflectance_is_judged
    """
    ctx = _deposited_run(api)
    run_id = ctx["coating_run"]["id"]

    refused = _verify(
        api, run_id, build_spectral_samples(*FOUR_IN_BAND_POINTS, (800, 0.2000))
    )

    validate_error(refused, ERR_SPECTRAL_SAMPLE_INSUFFICIENT)
    after_refusal = _read_run(api, run_id)
    assert after_refusal["coating_status"] == "DEPOSITED", (
        "the refusal leaves the run DEPOSITED, got "
        f"{after_refusal['coating_status']}"
    )
    assert_spectral_outputs_cleared(after_refusal)

    accepted = validate_success(
        _verify(
            api, run_id, build_spectral_samples(*FOUR_IN_BAND_POINTS, (680, 0.1600))
        ),
        expected_status=200,
    )

    assert_spectral_outputs(accepted, 5, 0.1400, 0.1800, "PASS")
    assert accepted["coating_status"] == "VERIFIED_PASS", (
        f"coating_status must be VERIFIED_PASS, got {accepted['coating_status']}"
    )
    assert accepted["worst_point_reflectance_pct"] == 0.1800, (
        "the 700 nm reading counts as in-band and is the worst point, got "
        f"{accepted['worst_point_reflectance_pct']}"
    )
    assert _read_order(api, ctx["work_order"]["id"])["process_status"] == "COATED", (
        "the passing verification advances the order to COATED"
    )
