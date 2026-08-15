"""Packaging lines, film supply, and line runs (PRD §2.10, §3.5)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_film_conservation,
    cook_batch,
    create_approved_recipe,
    create_batch,
    create_copack_customer,
    create_film_lot,
    create_order,
    create_packaging_line,
    get_film_lot,
    kit_batch,
    pin_clock,
    schedule_run,
    setup_kitted_batch,
    validate_error,
    validate_paginated,
    validate_success,
)

PM = TEST_USERS["plant_manager_headers"]
PLANNER = TEST_USERS["production_planner_headers"]
OPERATOR = TEST_USERS["line_operator_headers"]
QA_TECH = TEST_USERS["qa_technician_headers"]


class TestFilmLotComputedFields:
    def test_film_lot_computed_meter_fields(self, api):
        """PRD §3.5: "the lot's `meters_received` is the product of rolls and
        length per roll and is a conserved quantity — at every moment, the meters
        reserved plus the meters consumed plus the meters available equal the
        meters received." / "A film lot begins `AVAILABLE`"

        Design: Corner/entities/film_lot_computed_meter_fields
        """
        resp = api.create_film_lot(
            {"film_type": "POUCH_FILM", "rolls_received": 3, "meters_per_roll": 500},
            PM,
        )
        data = validate_success(resp, expected_status=201)
        assert data["meters_received"] == 1500, "3 rolls x 500 m = 1500"
        assert data["meters_reserved"] == 0
        assert data["meters_consumed"] == 0
        assert data["meters_available"] == 1500
        assert data["status"] == "AVAILABLE"
        assert_film_conservation(data)


class TestFilmReservationRounding:
    def _two_small_runs(self):
        """Two 50-unit RETAIL runs on one film lot (10000 m received)."""
        env = setup_kitted_batch()
        line = create_packaging_line()
        film = create_film_lot()
        run1 = schedule_run(
            line["id"], env["batch"]["id"], film["id"],
            planned_start="2026-08-03T08:00:00Z", units_planned=50,
        )
        run2 = schedule_run(
            line["id"], env["batch"]["id"], film["id"],
            planned_start="2026-08-03T08:16:00Z", units_planned=50,
        )
        return film, run1, run2

    def test_film_reservation_rounded_per_run(self, api):
        """PRD §3.5: "the run's `reserved_film_m` is `units_planned` multiplied by
        the per-unit film allowance of the order's pack format — 0.42 meters per
        unit for `RETAIL`, 0.35 meters per unit for `FOODSERVICE` — and then
        multiplied by 1.06 to cover the six percent waste allowance, with the
        result rounded half up to a whole meter for this run."

        Design: Difficulty/combinatorial_formula/film_reservation_per_run_rounding
        """
        _, run1, run2 = self._two_small_runs()
        # round_half_up(50 * 0.42 * 1.06) = round_half_up(22.26) = 22 per run.
        assert run1["reserved_film_m"] == 22, (
            f"per-run reservation rounds to whole meters: 22, got {run1['reserved_film_m']}"
        )
        assert run2["reserved_film_m"] == 22

    def test_film_reservation_sums_per_run_values(self, api):
        """PRD §3.5: "Only then do per-run reservations sum into the lot's
        `meters_reserved`; summing raw unrounded values and rounding once would
        produce different totals and is not the contract."
        PRD §3.5: "its `meters_available` is what remains of the received quantity
        after both."

        Design: Difficulty/combinatorial_formula/film_reservation_per_run_rounding
        """
        film, _, _ = self._two_small_runs()
        lot = get_film_lot(film["id"])
        # The pinned rounding order gives 22 + 22 = 44; sum-then-round of the raw
        # values would give round_half_up(44.52) = 45 — the orders differ.
        assert lot["meters_reserved"] == 44, (
            f"lot reservation sums per-run rounded values: 44, got {lot['meters_reserved']}"
        )
        assert lot["meters_available"] == 9956
        assert_film_conservation(lot)


class TestFilmReserveCancelInvariant:
    def test_film_reserve_on_schedule(self, api):
        """PRD §3.5: "the lot's `meters_received` is the product of rolls and
        length per roll and is a conserved quantity — at every moment, the meters
        reserved plus the meters consumed plus the meters available equal the
        meters received."
        PRD §3.5: "on success the lot's `meters_reserved` grows by exactly the
        run's `reserved_film_m`, and the run begins in `SCHEDULED` status."

        Design: Difficulty/compensating_invariant/film_reserve_cancel_invariant
        """
        env = setup_kitted_batch()
        line = create_packaging_line()
        film = create_film_lot()
        run = schedule_run(line["id"], env["batch"]["id"], film["id"], units_planned=6000)
        # round_half_up(6000 * 0.42 * 1.06) = round_half_up(2671.2) = 2671.
        assert run["reserved_film_m"] == 2671
        lot = get_film_lot(film["id"])
        assert lot["meters_reserved"] == 2671
        assert lot["meters_available"] == 7329
        assert_film_conservation(lot)

    def test_film_cancel_restores_conservation(self, api):
        """PRD §3.5: "Cancelling a scheduled run is a `ProductionPlanner` act that
        moves the run from `SCHEDULED` to `CANCELLED` and releases its film
        reservation, dropping the lot's `meters_reserved` by the run's
        `reserved_film_m`."
        PRD §3.5: "at every moment, the meters reserved plus the meters consumed
        plus the meters available equal the meters received."

        Design: Difficulty/compensating_invariant/film_reserve_cancel_invariant
        """
        env = setup_kitted_batch()
        line = create_packaging_line()
        film = create_film_lot()
        run = schedule_run(line["id"], env["batch"]["id"], film["id"], units_planned=6000)
        cancelled = validate_success(api.cancel_line_run(run["id"], PLANNER), expected_status=200)
        assert cancelled["status"] == "CANCELLED"
        lot = get_film_lot(film["id"])
        assert lot["meters_reserved"] == 0, "cancel releases the whole reservation"
        assert lot["meters_consumed"] == 0
        assert lot["meters_available"] == 10000, (
            f"compensating cancel restores availability exactly, got {lot['meters_available']}"
        )
        assert_film_conservation(lot)


class TestRunBookingGates:
    def test_film_insufficient_meters_rejected(self, api):
        """PRD §3.5: "Booking requires the lot's `meters_available` to be at least
        the new reservation — equality is allowed — otherwise the booking is
        rejected with `ERR_FILM_INSUFFICIENT`"

        Design: Corner/validations/film_insufficient_meters_rejected
        """
        env = setup_kitted_batch()
        line = create_packaging_line()
        film = create_film_lot(rolls_received=1, meters_per_roll=100)
        # The 6000-unit run needs 2671 m; only 100 m are available.
        resp = api.create_line_run(
            line["id"],
            {
                "batch_id": env["batch"]["id"], "film_lot_id": film["id"],
                "planned_start": "2026-08-03T08:00:00Z", "units_planned": 6000,
            },
            PLANNER,
        )
        validate_error(resp, ApiErrorId.ERR_FILM_INSUFFICIENT, expected_status=409)

    def test_film_type_mismatch_rejected(self, api):
        """PRD §3.5: "the film lot's `film_type` must equal the line's
        `supported_film_type`, otherwise `ERR_FILM_TYPE_MISMATCH`"

        Design: Corner/validations/film_type_mismatch_rejected
        """
        env = setup_kitted_batch()
        line = create_packaging_line()  # TRAY line, supported_film_type TRAY_FILM
        film = create_film_lot(film_type="POUCH_FILM")
        resp = api.create_line_run(
            line["id"],
            {
                "batch_id": env["batch"]["id"], "film_lot_id": film["id"],
                "planned_start": "2026-08-03T08:00:00Z", "units_planned": 6000,
            },
            PLANNER,
        )
        validate_error(resp, ApiErrorId.ERR_FILM_TYPE_MISMATCH, expected_status=409)

    def test_line_format_mismatch_rejected(self, api):
        """PRD §3.5: "Format discipline is enforced at booking: a `RETAIL` order
        requires a `TRAY` line and a `FOODSERVICE` order requires a `POUCH` line,
        and a mismatch is rejected with `ERR_LINE_FORMAT_MISMATCH`"

        Design: Corner/validations/line_format_mismatch_rejected
        """
        recipe = create_approved_recipe(name="R-LFM")
        order = create_order(recipe["id"], pack_format="FOODSERVICE", units_planned=6000)
        batch = create_batch(order["id"], units_planned=6000)
        kit_batch(batch["id"])
        line = create_packaging_line()  # TRAY line
        film = create_film_lot()  # TRAY_FILM matches the line
        resp = api.create_line_run(
            line["id"],
            {
                "batch_id": batch["id"], "film_lot_id": film["id"],
                "planned_start": "2026-08-03T08:00:00Z", "units_planned": 6000,
            },
            PLANNER,
        )
        validate_error(resp, ApiErrorId.ERR_LINE_FORMAT_MISMATCH, expected_status=409)


class TestQuarantinedFilmPriority:
    def _quarantined_setup(self, api):
        env = setup_kitted_batch()
        line = create_packaging_line()
        film_quarantined = create_film_lot()
        film_ok = create_film_lot()
        validate_success(api.quarantine_film_lot(film_quarantined["id"], QA_TECH))
        # Existing run occupying 08:00-09:00 on the line (6000 units at 100/min).
        run1 = schedule_run(
            line["id"], env["batch"]["id"], film_ok["id"],
            planned_start="2026-08-03T08:00:00Z", units_planned=6000,
        )
        return env, line, film_quarantined, run1

    def test_quarantined_film_beats_window_conflict(self, api):
        """PRD §2.4: "When several checks could reject the same request, the
        earliest failing stage in the order below determines the error that is
        returned; later stages are never consulted for that request."
        PRD §2.4: "9. **Critical-control safety.** The latest check of each
        required type is `PASS` before lot release, and the film lot is not
        `QUARANTINED` at run creation or run start; otherwise
        `ERR_CCP_NOT_CURRENT` or `ERR_FILM_LOT_QUARANTINED` (HTTP 409)." — listed
        before "10. **Temporal windows.** Freezer-cell windows including the
        sanitation buffer, packaging-line windows including changeover buffers,
        and expiry gates all hold; otherwise `ERR_CELL_WINDOW_CONFLICT`,
        `ERR_LINE_WINDOW_CONFLICT`, or `ERR_LOT_EXPIRED` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/run_create_quarantined_film_beats_window_conflict
        """
        env, line, film_quarantined, _ = self._quarantined_setup(api)
        # 08:30 collides with the existing 08:00-09:00 run AND the film lot is
        # quarantined: the safety stage (9) fires before temporal windows (10).
        resp = api.create_line_run(
            line["id"],
            {
                "batch_id": env["batch"]["id"], "film_lot_id": film_quarantined["id"],
                "planned_start": "2026-08-03T08:30:00Z", "units_planned": 6000,
            },
            PLANNER,
        )
        validate_error(resp, ApiErrorId.ERR_FILM_LOT_QUARANTINED, expected_status=409)

    def test_quarantined_film_rejected_with_clean_window(self, api):
        """PRD §3.5: "the film lot must be `AVAILABLE`, otherwise
        `ERR_FILM_LOT_QUARANTINED`"

        Design: Difficulty/priority_pair_validation_conflict/run_create_quarantined_film_beats_window_conflict
        """
        env, line, film_quarantined, _ = self._quarantined_setup(api)
        # A non-overlapping window isolates the safety gate from any temporal
        # conflict; the quarantine alone must reject the booking.
        resp = api.create_line_run(
            line["id"],
            {
                "batch_id": env["batch"]["id"], "film_lot_id": film_quarantined["id"],
                "planned_start": "2026-08-03T12:00:00Z", "units_planned": 6000,
            },
            PLANNER,
        )
        validate_error(resp, ApiErrorId.ERR_FILM_LOT_QUARANTINED, expected_status=409)


class TestRunLifecycle:
    def test_run_start_before_frozen_rejected(self, api):
        """PRD §3.5: "A `LineOperator` starts a scheduled run, moving it from
        `SCHEDULED` to `IN_PROGRESS`, under two gates: the batch must be `FROZEN`
        — starting the pack before freezing has verified is rejected with
        `ERR_BATCH_STATE`"

        Design: Corner/state_machines/run_start_before_frozen_rejected
        """
        env = setup_kitted_batch()
        cook_batch(env["batch"]["id"], cooked_mass_kg=1550)  # COOKED, not yet FROZEN
        line = create_packaging_line()
        film = create_film_lot()
        run = schedule_run(line["id"], env["batch"]["id"], film["id"], units_planned=6000)
        resp = api.start_line_run(run["id"], OPERATOR)
        validate_error(resp, ApiErrorId.ERR_BATCH_STATE, expected_status=409)
        after = validate_success(api.get_line_run(run["id"], PLANNER))
        assert after["status"] == "SCHEDULED", "rejected start must leave the run SCHEDULED"

    def test_start_cancelled_run_rejected(self, api):
        """PRD §3.5: "Attempting any run transition from a state where it is
        undefined, such as starting a `CANCELLED` run, is rejected with
        `ERR_RUN_STATE`."

        Design: Corner/validations/start_cancelled_run_rejected
        """
        env = setup_kitted_batch()
        line = create_packaging_line()
        film = create_film_lot()
        run = schedule_run(line["id"], env["batch"]["id"], film["id"], units_planned=6000)
        validate_success(api.cancel_line_run(run["id"], PLANNER), expected_status=200)
        resp = api.start_line_run(run["id"], OPERATOR)
        validate_error(resp, ApiErrorId.ERR_RUN_STATE, expected_status=409)
        after = validate_success(api.get_line_run(run["id"], PLANNER))
        assert after["status"] == "CANCELLED", "CANCELLED is terminal for a run"


class TestLineChangeover:
    def _two_customer_batches(self):
        pin_clock()
        recipe = create_approved_recipe(name="R-Win2")
        cust_a = create_copack_customer(name="Cust A", base_changeover_minutes=45)
        cust_b = create_copack_customer(name="Cust B", base_changeover_minutes=45)
        line = create_packaging_line()
        film = create_film_lot()
        order_a = create_order(
            recipe["id"], units_planned=600, copack_customer_id=cust_a["id"]
        )
        batch_a = create_batch(order_a["id"], units_planned=600)
        kit_batch(batch_a["id"])
        order_b = create_order(
            recipe["id"], units_planned=600, copack_customer_id=cust_b["id"]
        )
        batch_b = create_batch(order_b["id"], units_planned=600)
        kit_batch(batch_b["id"])
        # Run for customer A: 08:00, ceil(600/100) = 6 minutes -> ends 08:06.
        run1 = schedule_run(
            line["id"], batch_a["id"], film["id"],
            planned_start="2026-08-03T08:00:00Z", units_planned=600,
        )
        return line, film, batch_b, run1

    def test_changeover_gap_one_minute_short_rejected(self, api):
        """PRD §2.10: "when a run follows a run belonging to a different co-pack
        customer, the two must be separated by the incoming customer's
        `base_changeover_minutes` (which defaults to 45 minutes)"
        PRD §3.5: "The run's `duration_minutes` is `units_planned` divided by the
        line's `rate_units_per_minute`, rounded up to a whole minute, and its
        `planned_end` is `planned_start` plus that duration."
        PRD §2.4: "10. **Temporal windows.** Freezer-cell windows including the
        sanitation buffer, packaging-line windows including changeover buffers,
        and expiry gates all hold; otherwise `ERR_CELL_WINDOW_CONFLICT`,
        `ERR_LINE_WINDOW_CONFLICT`, or `ERR_LOT_EXPIRED` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/line_run_conditional_changeover
        """
        line, film, batch_b, run1 = self._two_customer_batches()
        assert run1["planned_end"] == "2026-08-03T08:06:00Z", (
            f"600 units at 100/min = 6 minutes, got {run1['planned_end']}"
        )
        # 08:50 leaves a 44-minute gap after 08:06 — one minute short of 45.
        resp = api.create_line_run(
            line["id"],
            {
                "batch_id": batch_b["id"], "film_lot_id": film["id"],
                "planned_start": "2026-08-03T08:50:00Z", "units_planned": 600,
            },
            PLANNER,
        )
        validate_error(resp, ApiErrorId.ERR_LINE_WINDOW_CONFLICT, expected_status=409)

    def test_changeover_gap_exact_boundary_accepted(self, api):
        """PRD §2.10: "when a run follows a run belonging to a different co-pack
        customer, the two must be separated by the incoming customer's
        `base_changeover_minutes` (which defaults to 45 minutes)"
        PRD §2.10: "Two bookings on the same resource whose half-open windows
        merely touch — one ending exactly when the other begins — do not by
        themselves conflict."

        Design: Difficulty/resource_temporal_overlap/line_run_conditional_changeover
        """
        line, film, batch_b, _ = self._two_customer_batches()
        # 08:51 leaves exactly the required 45-minute gap after 08:06.
        run2 = schedule_run(
            line["id"], batch_b["id"], film["id"],
            planned_start="2026-08-03T08:51:00Z", units_planned=600,
        )
        assert run2["status"] == "SCHEDULED"
        assert run2["planned_end"] == "2026-08-03T08:57:00Z", (
            f"08:51 + 6 minutes = 08:57, got {run2['planned_end']}"
        )


class TestRunListFilters:
    def test_film_lot_fk_reverse_reachable(self, api):
        """PRD §3.5: "The run list is filterable by `line_id`, `batch_id`,
        `film_lot_id`, and `status`."

        Design: Corner/endpoints/film_lot_fk_reverse_reachable
        """
        pin_clock()
        env = setup_kitted_batch()
        line1 = create_packaging_line(line_code="L-1")
        line2 = create_packaging_line(line_code="L-2")
        film = create_film_lot()
        film2 = create_film_lot()
        schedule_run(
            line1["id"], env["batch"]["id"], film["id"],
            planned_start="2026-08-03T08:00:00Z", units_planned=600,
        )
        schedule_run(
            line2["id"], env["batch"]["id"], film["id"],
            planned_start="2026-08-03T08:00:00Z", units_planned=600,
        )
        schedule_run(
            line1["id"], env["batch"]["id"], film2["id"],
            planned_start="2026-08-03T08:21:00Z", units_planned=600,
        )
        data, meta = validate_paginated(
            api.list_line_runs(PLANNER, params={"film_lot_id": film["id"]})
        )
        assert meta["total_count"] == 2, (
            f"exactly the two runs booked against the film lot, got {meta['total_count']}"
        )
        assert all(r["film_lot_id"] == film["id"] for r in data)
        data, meta = validate_paginated(
            api.list_line_runs(PLANNER, params={"batch_id": env["batch"]["id"]})
        )
        assert meta["total_count"] == 3, (
            f"all three runs of the batch, got {meta['total_count']}"
        )
