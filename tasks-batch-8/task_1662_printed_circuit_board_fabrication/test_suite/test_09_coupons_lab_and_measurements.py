"""Impedance coupons, microsection lab bookings, measurement disposition
variants, the retest budget, and the quality-disposition dimension
(PRD §3.7).
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId,
    assert_coupon_measurement,
    setup_in_production, create_coupon, create_booking, record_measurement,
    book_and_measure, pass_coupon, drive_coupon_to_final_fail, set_clock,
    prepare_order,
    TEST_USERS,
    WINDOW_AT_DEFAULT_CLOCK, WINDOW_AT_0100, WINDOW_AT_0200, WINDOW_AT_0300,
    CLOCK_0100, CLOCK_0200, CLOCK_0300,
)

QI = TEST_USERS["quality_inspector_headers"]
PLANNER = TEST_USERS["production_planner_headers"]
FAB_ADMIN = TEST_USERS["fab_admin_headers"]

SE_LINE = {"layer_name": "L1", "target_ohms": 50.0, "tolerance_plus_ohms": 5.0,
           "tolerance_minus_ohms": 5.0, "line_type": "SINGLE_ENDED",
           "coupon_required": True}

DIFF_LINE_100 = {"layer_name": "L2", "target_ohms": 100.0,
                 "tolerance_plus_ohms": 10.0, "tolerance_minus_ohms": 10.0,
                 "line_type": "DIFFERENTIAL", "coupon_required": True}

SE_LINE_100 = {"layer_name": "L1", "target_ohms": 100.0,
               "tolerance_plus_ohms": 10.0, "tolerance_minus_ohms": 10.0,
               "line_type": "SINGLE_ENDED", "coupon_required": True}


def _in_production_with_lines(spec_lines, company, email, lot_code):
    return setup_in_production(
        company_name=company, contact_email=email,
        lot_code=lot_code, spec_lines=spec_lines,
    )


class TestDispositionVariants:
    def test_single_passes_where_statistical_fails_on_spread(self, api):
        """PRD §3.7: "Under the SINGLE variant (for `SINGLE_ENDED` lines), the
        coupon passes when the primary reading falls inside the band. Under the
        STATISTICAL variant (for `DIFFERENTIAL` lines), both legs of the same
        measurement event must fall inside the band and, in addition, the
        absolute difference between the two legs must not exceed 6.0 ohms — so
        two in-band legs can still fail when they diverge by more than the
        spread limit." Each measurement "updates the coupon's
        `latest_measured_ohms` to the primary reading and its
        `disposition_basis` to the variant used."

        Design: Difficulty/dual_variant_calc/single_vs_statistical_coupon_disposition
        """
        ctx = _in_production_with_lines(
            (SE_LINE_100, DIFF_LINE_100), "Beta Circuits", "ops@beta.example", "LOT-B1",
        )
        line1, line2 = ctx["spec_lines"]
        c1 = create_coupon(ctx["order"]["id"], line1["id"], panel_ref="P01")
        c2 = create_coupon(ctx["order"]["id"], line2["id"], panel_ref="P02")

        # SINGLE variant: 99.0 inside [90, 110] passes on the primary reading.
        _, m1 = book_and_measure(c1["id"], 99.0, *WINDOW_AT_DEFAULT_CLOCK)
        assert m1["result"] == "PASS"
        c1 = get_success_data(api.get_coupon(c1["id"], QI))
        assert c1["status"] == "PASSED"
        assert c1["disposition_basis"] == "SINGLE"

        # STATISTICAL variant: legs 91.0 / 99.0 both inside [90, 110], but the
        # 8.0-ohm spread exceeds 6.0, so the same measurement FAILS.
        set_clock(CLOCK_0100)
        _, m2 = book_and_measure(c2["id"], 91.0, *WINDOW_AT_0100, measured_ohms_b=99.0)
        assert m2["result"] == "FAIL", (
            "both legs in-band yet spread 8.0 > 6.0 fails only the STATISTICAL variant"
        )
        c2 = get_success_data(api.get_coupon(c2["id"], QI))
        assert c2["status"] == "FAILED"
        assert c2["disposition_basis"] == "STATISTICAL"

    def test_statistical_passes_within_spread_and_band_edges_inclusive(self, api):
        """PRD §3.7: "The acceptance band runs from `target_ohms` minus
        `tolerance_minus_ohms` to `target_ohms` plus `tolerance_plus_ohms`,
        inclusive at both ends." and "the absolute difference between the two
        legs must not exceed 6.0 ohms".

        Design: Difficulty/dual_variant_calc/single_vs_statistical_coupon_disposition
        """
        ctx = _in_production_with_lines(
            (SE_LINE_100, DIFF_LINE_100), "Beta Two", "ops@beta2.example", "LOT-B2",
        )
        line1, line2 = ctx["spec_lines"]
        c1 = create_coupon(ctx["order"]["id"], line1["id"], panel_ref="P01")
        c2 = create_coupon(ctx["order"]["id"], line2["id"], panel_ref="P02")

        # SINGLE: the lower band edge (90.0) is inclusive and passes.
        _, m1 = book_and_measure(c1["id"], 90.0, *WINDOW_AT_DEFAULT_CLOCK)
        assert m1["result"] == "PASS", "band edges are inclusive at both ends"

        # STATISTICAL: both legs in band with spread 1.0 <= 6.0 passes.
        set_clock(CLOCK_0100)
        _, m2 = book_and_measure(c2["id"], 98.0, *WINDOW_AT_0100, measured_ohms_b=99.0)
        assert m2["result"] == "PASS"
        c2 = get_success_data(api.get_coupon(c2["id"], QI))
        assert c2["status"] == "PASSED"
        assert c2["disposition_basis"] == "STATISTICAL"

    def test_statistical_measurement_requires_leg_b(self, api):
        """PRD §3.7: "for a `DIFFERENTIAL` spec line a second leg
        `measured_ohms_b` is required, and its absence is rejected with
        `ERR_VALIDATION`, while for a `SINGLE_ENDED` line it is ignored."

        Design: Corner/calculations/statistical_measurement_requires_leg_b
        """
        ctx = _in_production_with_lines(
            (DIFF_LINE_100,), "LegB Co", "legb@co.example", "LOT-LB1",
        )
        c2 = create_coupon(ctx["order"]["id"], ctx["spec_lines"][0]["id"],
                           panel_ref="P02")
        booking = create_booking(c2["id"], *WINDOW_AT_DEFAULT_CLOCK)

        resp = api.create_measurement(
            c2["id"],
            {"measured_ohms": 99.0, "lab_slot_booking_id": booking["id"]},
            QI,
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION)


class TestCouponRetestCycle:
    def test_coupon_retest_cycle_fail_then_pass(self, api):
        """PRD §3.7: "While the coupon's `retest_count` is below the maximum of
        two retests, a `QualityInspector` may retest: the coupon returns from
        `FAILED` to `AWAITING_MEASURE`, its `retest_count` increments by one".
        Measurements are append-only and listed in creation order (PRD §2.3).

        Design: Difficulty/non_linear_state_machine/coupon_retest_cycle
        """
        ctx = _in_production_with_lines((SE_LINE,), "Tau Circuits",
                                        "ops@tau.example", "LOT-U1")
        cpn = create_coupon(ctx["order"]["id"], ctx["spec_lines"][0]["id"])

        _, m1 = book_and_measure(cpn["id"], 60.0, *WINDOW_AT_DEFAULT_CLOCK)
        assert m1["result"] == "FAIL"

        coupon = get_success_data(api.retest_coupon(cpn["id"], QI))
        assert coupon["status"] == "AWAITING_MEASURE"
        assert coupon["retest_count"] == 1

        set_clock(CLOCK_0100)
        _, m2 = book_and_measure(cpn["id"], 52.0, *WINDOW_AT_0100)
        assert m2["result"] == "PASS"

        coupon = get_success_data(api.get_coupon(cpn["id"], QI))
        assert coupon["status"] == "PASSED", (
            "the FAILED -> AWAITING_MEASURE -> PASSED loop must close"
        )
        assert coupon["retest_count"] == 1
        assert coupon["latest_measured_ohms"] == 52.0

        data, meta = validate_paginated(api.list_coupon_measurements(cpn["id"], QI))
        assert meta["total_count"] == 2
        assert [m["result"] for m in data] == ["FAIL", "PASS"], (
            "measurements are append-only and listed in chronological order"
        )

    def test_coupon_two_retests_then_pass(self, api):
        """PRD §3.7: "a `QualityInspector` may retest: the coupon returns from
        `FAILED` to `AWAITING_MEASURE`, its `retest_count` increments by one" —
        the loop iterates twice within the two-retest budget before the pass.

        Design: Difficulty/non_linear_state_machine/coupon_retest_cycle
        """
        ctx = _in_production_with_lines((SE_LINE,), "Tau Two",
                                        "ops@tau2.example", "LOT-U2")
        cpn = create_coupon(ctx["order"]["id"], ctx["spec_lines"][0]["id"])

        book_and_measure(cpn["id"], 60.0, *WINDOW_AT_DEFAULT_CLOCK)
        get_success_data(api.retest_coupon(cpn["id"], QI))
        set_clock(CLOCK_0100)
        book_and_measure(cpn["id"], 61.0, *WINDOW_AT_0100)
        get_success_data(api.retest_coupon(cpn["id"], QI))
        set_clock(CLOCK_0200)
        _, m3 = book_and_measure(cpn["id"], 52.0, *WINDOW_AT_0200)
        assert m3["result"] == "PASS"

        coupon = get_success_data(api.get_coupon(cpn["id"], QI))
        assert coupon["status"] == "PASSED"
        assert coupon["retest_count"] == 2

        data, meta = validate_paginated(api.list_coupon_measurements(cpn["id"], QI))
        assert [m["result"] for m in data] == ["FAIL", "FAIL", "PASS"]


class TestCouponFinalFailCascade:
    def test_final_fail_cascades_to_order(self, api):
        """PRD §3.7: "A failure evaluated while `retest_count` already equals
        two is final: the order's `quality_disposition` falls from `PENDING` to
        `FAILED`, the system auto-creates a `DefectRecord` with `defect_code`
        `IMPEDANCE`, `severity` `SCRAP`, `source` `MANUAL`, `detected_at` set to
        the logical clock, the `panel_array_id` of the order's `RELEASED` array,
        and `boards_affected` equal to that array's `boards_per_panel` — and the
        same panel count is added to the order's `boards_scrapped`."

        Design: Difficulty/transitive_cascade/coupon_final_fail_cascade
        """
        ctx = _in_production_with_lines((SE_LINE,), "Upsilon Circuits",
                                        "ops@upsilon.example", "LOT-V1")
        cpn = create_coupon(ctx["order"]["id"], ctx["spec_lines"][0]["id"])
        drive_coupon_to_final_fail(cpn["id"])

        coupon = get_success_data(api.get_coupon(cpn["id"], QI))
        assert coupon["status"] == "FAILED"
        assert coupon["retest_count"] == 2

        order = get_success_data(api.get_fab_order(ctx["order"]["id"], PLANNER))
        assert order["quality_disposition"] == "FAILED", (
            "link 1 of the cascade: the final failure flips disposition to FAILED"
        )
        assert order["boards_scrapped"] == 4, (
            "boards_per_panel (2x2 = 4) is added to boards_scrapped"
        )

        data, meta = validate_paginated(
            api.list_order_defects(ctx["order"]["id"], QI)
        )
        assert meta["total_count"] == 1, "exactly one auto-created defect record"
        record = data[0]
        assert record["defect_code"] == "IMPEDANCE"
        assert record["severity"] == "SCRAP"
        assert record["source"] == "MANUAL"
        assert record["boards_affected"] == 4
        assert record["panel_array_id"] == ctx["array"]["id"]

    def test_final_fail_on_non_required_line_blocks_complete_fab(self, api):
        """PRD §3.7: "every spec line of the locked stackup whose
        `coupon_required` is true must have a coupon in `PASSED` status, else
        `ERR_COUPON_NOT_PASSED`; and the order's `quality_disposition` must be
        `PENDING` or `PASSED` — a `FAILED` or `CONDITIONAL` disposition blocks
        completion with `ERR_DISPOSITION_FAILED`."

        Design: Difficulty/transitive_cascade/coupon_final_fail_cascade
        """
        required_line = dict(SE_LINE)
        optional_line = {"layer_name": "L2", "target_ohms": 50.0,
                         "tolerance_plus_ohms": 5.0, "tolerance_minus_ohms": 5.0,
                         "line_type": "SINGLE_ENDED", "coupon_required": False}
        ctx = _in_production_with_lines(
            (required_line, optional_line), "Upsilon Two", "ops@upsilon2.example",
            "LOT-V2",
        )
        line1, line2 = ctx["spec_lines"]

        # The required line's coupon passes; the non-required line's coupon
        # fails finally, so the coupon gate is satisfied but disposition FAILED.
        c1 = create_coupon(ctx["order"]["id"], line1["id"], panel_ref="P01")
        pass_coupon(c1["id"], reading=52.0)
        c2 = create_coupon(ctx["order"]["id"], line2["id"], panel_ref="P02")
        set_clock(CLOCK_0100)
        book_and_measure(c2["id"], 60.0, *WINDOW_AT_0100)
        get_success_data(api.retest_coupon(c2["id"], QI))
        set_clock(CLOCK_0200)
        book_and_measure(c2["id"], 61.0, *WINDOW_AT_0200)
        get_success_data(api.retest_coupon(c2["id"], QI))
        set_clock(CLOCK_0300)
        book_and_measure(c2["id"], 62.0, *WINDOW_AT_0300)

        order = get_success_data(api.get_fab_order(ctx["order"]["id"], PLANNER))
        assert order["quality_disposition"] == "FAILED"

        resp = api.complete_fab(ctx["order"]["id"], PLANNER)
        validate_error(resp, ApiErrorId.ERR_DISPOSITION_FAILED)
        order = get_success_data(api.get_fab_order(ctx["order"]["id"], PLANNER))
        assert order["fab_status"] == "IN_PRODUCTION"


class TestCompleteFabCouponGate:
    def test_complete_fab_rejected_while_coupon_failed(self, api):
        """PRD §3.7: "every spec line of the locked stackup whose
        `coupon_required` is true must have a coupon in `PASSED` status, else
        `ERR_COUPON_NOT_PASSED`".

        Design: Difficulty/cross_entity_state_dependency/complete_fab_requires_coupons_passed
        """
        ctx = _in_production_with_lines((SE_LINE,), "Xi Circuits",
                                        "ops@xi.example", "LOT-X1")
        cpn = create_coupon(ctx["order"]["id"], ctx["spec_lines"][0]["id"])
        _, m1 = book_and_measure(cpn["id"], 60.0, *WINDOW_AT_DEFAULT_CLOCK)
        assert m1["result"] == "FAIL"

        resp = api.complete_fab(ctx["order"]["id"], PLANNER)
        validate_error(resp, ApiErrorId.ERR_COUPON_NOT_PASSED)
        order = get_success_data(api.get_fab_order(ctx["order"]["id"], PLANNER))
        assert order["fab_status"] == "IN_PRODUCTION", (
            "a rejected complete-fab leaves the order IN_PRODUCTION"
        )

    def test_complete_fab_rejected_without_any_coupon(self, api):
        """PRD §3.7: "every spec line of the locked stackup whose
        `coupon_required` is true must have a coupon in `PASSED` status, else
        `ERR_COUPON_NOT_PASSED`" — a required line with no coupon at all fails
        the same gate.

        Design: Difficulty/cross_entity_state_dependency/complete_fab_requires_coupons_passed
        """
        ctx = _in_production_with_lines((SE_LINE,), "Xi Two",
                                        "ops@xi2.example", "LOT-X2")
        resp = api.complete_fab(ctx["order"]["id"], PLANNER)
        validate_error(resp, ApiErrorId.ERR_COUPON_NOT_PASSED)


class TestParallelStatusDimensions:
    def test_quality_dimension_evolves_independently_of_fab_status(self, api):
        """PRD §3.7: "A `FabAdmin` may concede a `FAILED` order, moving the
        disposition to `CONDITIONAL`, but only with a non-empty
        `concession_note` in the payload. A `QualityInspector` may then
        requalify a `CONDITIONAL` order back to `PASSED`, likewise only with a
        non-empty `requalification_note`." PRD §1-style parallel dimensions are
        narrated at §1: "an independent quality disposition that evolves as
        coupons are measured and failures are conceded or requalified".

        Design: Difficulty/non_linear_state_machine/order_parallel_status_dimensions
        """
        ctx = _in_production_with_lines((SE_LINE,), "Zeta Circuits",
                                        "ops@zeta.example", "LOT-Z1")
        cpn = create_coupon(ctx["order"]["id"], ctx["spec_lines"][0]["id"])
        drive_coupon_to_final_fail(cpn["id"])

        order = get_success_data(api.get_fab_order(ctx["order"]["id"], PLANNER))
        assert order["quality_disposition"] == "FAILED"
        assert order["boards_scrapped"] == 4

        order = get_success_data(
            api.concede_order(
                order["id"],
                {"concession_note": "customer accepted 62-ohm deviation"},
                FAB_ADMIN,
            )
        )
        assert order["quality_disposition"] == "CONDITIONAL"
        assert order["fab_status"] == "IN_PRODUCTION", (
            "quality-dimension transitions never touch fab_status"
        )

        order = get_success_data(
            api.requalify_order(
                order["id"],
                {"requalification_note": "re-inspection passed on secondary coupon"},
                QI,
            )
        )
        assert order["quality_disposition"] == "PASSED", (
            "FAILED -> CONDITIONAL -> PASSED closes the remediation path"
        )
        assert order["fab_status"] == "IN_PRODUCTION"

    def test_concede_requires_non_empty_note(self, api):
        """PRD §3.7: "A `FabAdmin` may concede a `FAILED` order, moving the
        disposition to `CONDITIONAL`, but only with a non-empty
        `concession_note` in the payload." PRD §2.9: field-level shape problems
        are "reported as `ERR_VALIDATION` (HTTP 400)".

        Design: Difficulty/non_linear_state_machine/order_parallel_status_dimensions
        """
        ctx = _in_production_with_lines((SE_LINE,), "Zeta Two",
                                        "ops@zeta2.example", "LOT-Z2")
        cpn = create_coupon(ctx["order"]["id"], ctx["spec_lines"][0]["id"])
        drive_coupon_to_final_fail(cpn["id"])

        resp = api.concede_order(ctx["order"]["id"], {}, FAB_ADMIN)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)
        order = get_success_data(api.get_fab_order(ctx["order"]["id"], PLANNER))
        assert order["quality_disposition"] == "FAILED", (
            "a concession without a note leaves the disposition FAILED"
        )


class TestLabBookingRules:
    def test_lab_slot_buffer_gap(self, api):
        """PRD §3.7: "Per station, `BOOKED` windows are half-open intervals and
        must keep a clearance of at least 15 minutes to every other `BOOKED`
        window on that station: a gap of exactly 15 minutes passes, while
        anything shorter is rejected with `ERR_LAB_SLOT_CONFLICT`".

        Design: Difficulty/resource_temporal_overlap/lab_slot_buffer_gap
        """
        ctx = _in_production_with_lines((SE_LINE,), "Pi Circuits",
                                        "ops@pi.example", "LOT-P1")
        cpn = create_coupon(ctx["order"]["id"], ctx["spec_lines"][0]["id"])

        b1 = create_booking(cpn["id"], "2026-08-01T10:00:00Z", "2026-08-01T11:00:00Z")
        assert b1["status"] == "BOOKED"

        # A gap of exactly 15 minutes satisfies the buffer.
        b2 = create_booking(cpn["id"], "2026-08-01T11:15:00Z", "2026-08-01T12:00:00Z")
        assert b2["status"] == "BOOKED"

        # A 14-minute gap violates the clearance.
        resp = api.create_lab_booking(
            {
                "coupon_id": cpn["id"], "station": "MICROSECTION_A",
                "starts_at": "2026-08-01T11:14:00Z", "ends_at": "2026-08-01T12:00:00Z",
            },
            QI,
        )
        validate_error(resp, ApiErrorId.ERR_LAB_SLOT_CONFLICT)

    def test_booking_duration_limit(self, api):
        """PRD §3.7: "The window must be well-formed: `ends_at` must fall
        strictly after `starts_at` and the duration must be no longer than 120
        minutes, else `ERR_BOOKING_WINDOW_INVALID`."

        Design: Difficulty/resource_temporal_overlap/lab_slot_buffer_gap
        """
        ctx = _in_production_with_lines((SE_LINE,), "Pi Two",
                                        "ops@pi2.example", "LOT-P2")
        cpn = create_coupon(ctx["order"]["id"], ctx["spec_lines"][0]["id"])

        # Exactly 120 minutes is admitted ("no longer than 120 minutes").
        b1 = create_booking(cpn["id"], "2026-08-01T10:00:00Z", "2026-08-01T12:00:00Z")
        assert b1["status"] == "BOOKED"

        # 121 minutes is rejected (13:00 -> 15:01; the 60-minute gap to the
        # prior booking clears the 15-minute station buffer).
        resp = api.create_lab_booking(
            {
                "coupon_id": cpn["id"], "station": "MICROSECTION_A",
                "starts_at": "2026-08-01T13:00:00Z", "ends_at": "2026-08-01T15:01:00Z",
            },
            QI,
        )
        validate_error(resp, ApiErrorId.ERR_BOOKING_WINDOW_INVALID)

    def test_booking_window_invalid_rejected(self, api):
        """PRD §3.7: "`ends_at` must fall strictly after `starts_at` and the
        duration must be no longer than 120 minutes, else
        `ERR_BOOKING_WINDOW_INVALID`."

        Design: Corner/validations/booking_window_invalid_rejected
        """
        ctx = _in_production_with_lines((SE_LINE,), "Book Co",
                                        "book@co.example", "LOT-BK1")
        cpn = create_coupon(ctx["order"]["id"], ctx["spec_lines"][0]["id"])
        resp = api.create_lab_booking(
            {
                "coupon_id": cpn["id"], "station": "MICROSECTION_A",
                "starts_at": "2026-08-01T11:00:00Z", "ends_at": "2026-08-01T11:00:00Z",
            },
            QI,
        )
        validate_error(resp, ApiErrorId.ERR_BOOKING_WINDOW_INVALID)

    def test_measurement_without_active_booking_rejected(self, api):
        """PRD §3.7: "The measurement is admitted only when the coupon's owning
        order is `IN_PRODUCTION` or `AWAITING_ETEST` (`ERR_INVALID_STATE`
        otherwise) and a `BOOKED` booking for that coupon covers the logical
        clock — the clock must fall at or after `starts_at` and strictly before
        `ends_at`, else `ERR_NO_ACTIVE_LAB_BOOKING`".

        Design: Corner/validations/measurement_without_active_booking_rejected
        """
        other_line = {"layer_name": "L2", "target_ohms": 100.0,
                      "tolerance_plus_ohms": 10.0, "tolerance_minus_ohms": 10.0,
                      "line_type": "SINGLE_ENDED", "coupon_required": False}
        ctx = _in_production_with_lines(
            (SE_LINE, other_line), "NoBook Co", "nobook@co.example", "LOT-NB1",
        )
        c1 = create_coupon(ctx["order"]["id"], ctx["spec_lines"][0]["id"],
                           panel_ref="P01")
        c2 = create_coupon(ctx["order"]["id"], ctx["spec_lines"][1]["id"],
                           panel_ref="P02")
        # The only booking belongs to coupon c2; presenting it for c1 fails.
        booking = create_booking(c2["id"], *WINDOW_AT_DEFAULT_CLOCK)

        resp = api.create_measurement(
            c1["id"],
            {"measured_ohms": 50.0, "lab_slot_booking_id": booking["id"]},
            QI,
        )
        validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_LAB_BOOKING)


class TestCouponConstraints:
    def test_coupon_exists_rejected(self, api):
        """PRD §3.7: "At most one non-`CANCELLED` coupon may exist per spec
        line — a second live coupon is rejected with `ERR_COUPON_EXISTS`".

        Design: Corner/validations/coupon_exists_rejected
        """
        ctx = _in_production_with_lines((SE_LINE,), "Cpn Co",
                                        "cpn@co.example", "LOT-CP1")
        create_coupon(ctx["order"]["id"], ctx["spec_lines"][0]["id"],
                      panel_ref="P01")
        resp = api.create_coupon(
            ctx["order"]["id"],
            {"spec_line_id": ctx["spec_lines"][0]["id"], "panel_ref": "P02"},
            QI,
        )
        validate_error(resp, ApiErrorId.ERR_COUPON_EXISTS)

    def test_retest_limit_reached_rejected(self, api):
        """PRD §3.7: "A retest attempted when the count has already reached two
        is rejected with `ERR_RETEST_LIMIT_REACHED`".

        Design: Corner/validations/retest_limit_reached_rejected
        """
        ctx = _in_production_with_lines((SE_LINE,), "Ret Co",
                                        "ret@co.example", "LOT-RT1")
        cpn = create_coupon(ctx["order"]["id"], ctx["spec_lines"][0]["id"])
        drive_coupon_to_final_fail(cpn["id"])

        resp = api.retest_coupon(cpn["id"], QI)
        validate_error(resp, ApiErrorId.ERR_RETEST_LIMIT_REACHED)
