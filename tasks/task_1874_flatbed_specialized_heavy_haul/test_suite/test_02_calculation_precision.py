"""Combinatorial formulas and boundary precision: tiered permit fees, per-line
escort rounding, fuel-surcharge tier keying, escort width thresholds, and the
standby free-allowance boundary."""
from test_helpers import (
    DRIVER,
    assert_invoice,
    assert_invoice_arithmetic,
    book_escort,
    create_customer,
    create_load_for_customer,
    create_permit_for_load,
    file_and_approve_securement,
    file_permit,
    grant_permit,
    issue_invoice,
    plan_load,
    report_and_resolve_fine,
    schedule_both_cranes,
    set_clock,
    setup_standard_load_cleared,
    survey_load,
    validate_success,
)


class TestPermitFeeTieredMultiInput:
    def _setup_tx_superload(self, api):
        customer = create_customer("Gulf Petrochem", 100_000_000)
        load = create_load_for_customer(
            customer["id"],
            cargo_description="Reactor vessel", gross_weight_lbs=148000,
            width_in=200, height_in=100, length_in=400,
            origin="Houston TX", destination="Midland TX",
        )
        # width 200 > 192 -> superload; EXTENDABLE capacity 150000 >= 148000;
        # required axles = max(2, ceil(148000/20000)) = 8.
        plan_load(
            load["id"], trailer_type="EXTENDABLE_DOUBLE_DROP",
            trailer_axle_count=8, driver_name="C. Nguyen",
            driver_oversize_endorsed=True,
        )
        surveyed = survey_load(
            load["id"], route_miles=100, states_crossed=["TX"],
            min_bridge_clearance_in=200, max_bridge_weight_lbs=160000,
        )
        permit = create_permit_for_load(
            load["id"], "TX", "SUPERLOAD",
            expected_load_version=surveyed["version"],
        )
        return load, permit

    def test_superload_fee_combines_base_marginal_weight_and_flat_width(self, api):
        """PRD §3.5: "For `SUPERLOAD` they are 50,000 / 40,000 / 45,000 /
        55,000 / 48,000 cents in the same order."
        PRD §3.5: "the first 20,000 excess pounds at 1 cent per pound, the next
        30,000 pounds at 2 cents per pound, and every pound beyond 50,000
        excess at 4 cents per pound, each tier priced only on the pounds inside
        it."

        Design: Difficulty/combinatorial_formula/permit_fee_tiered_multi_input
        """
        _, permit = self._setup_tx_superload(api)
        filed = file_permit(permit["id"])
        assert filed["weight_basis_lbs"] == 148000  # declared basis
        # 55000 TX SUPERLOAD base
        # + marginal weight: 20000x1 + 30000x2 + 18000x4 = 152000
        # + flat width bracket (200 > 192): 10000
        assert filed["fee_cents"] == 217000

    def test_weight_surcharge_is_marginal_not_flat(self, api):
        """PRD §3.5: "A **marginal weight surcharge**, which applies to
        `OVERWEIGHT` and `SUPERLOAD` permits only and is zero for `OVERSIZE`.
        The surcharge prices the pounds by which the weight basis exceeds
        80,000 lbs (zero if it does not): the first 20,000 excess pounds at 1
        cent per pound, the next 30,000 pounds at 2 cents per pound, and every
        pound beyond 50,000 excess at 4 cents per pound, each tier priced only
        on the pounds inside it."

        Design: Difficulty/combinatorial_formula/permit_fee_tiered_multi_input
        """
        _, permit = self._setup_tx_superload(api)
        filed = file_permit(permit["id"])
        # Only the bracketed 152000 weight surcharge is accepted: a flat 4-cent
        # rate over 68000 excess lbs would give 272000 (total 337000) and a
        # flat 1-cent rate would give 68000 (total 133000).
        weight_surcharge = filed["fee_cents"] - 55000 - 10000
        assert weight_surcharge == 152000
        assert filed["fee_cents"] not in (337000, 133000)


class TestInvoicePerLineRoundingBeatsSumRounding:
    def _setup_two_one_minute_bookings(self, api):
        customer = create_customer("Precision Fab", 100_000_000)
        load = create_load_for_customer(
            customer["id"],
            cargo_description="Wide beam", gross_weight_lbs=40000,
            width_in=170, height_in=50, length_in=400,
            origin="Sparks NV", destination="Elko NV",
        )
        # width 170 in [168, ...) -> FRONT + REAR escorts required.
        plan_load(
            load["id"], trailer_type="FLATBED", trailer_axle_count=2,
            driver_name="D. Park", driver_oversize_endorsed=True,
        )
        surveyed = survey_load(
            load["id"], route_miles=10, states_crossed=["NV"],
            min_bridge_clearance_in=120, max_bridge_weight_lbs=80000,
        )
        permit = create_permit_for_load(
            load["id"], "NV", "OVERSIZE",
            expected_load_version=surveyed["version"],
        )
        file_permit(permit["id"])
        grant_permit(permit["id"])
        book_escort(
            load["id"], provider_name="PF", position="FRONT",
            start="2026-08-12T10:00:00Z", end="2026-08-12T10:01:00Z",
            rate_per_hour_cents=10001,
        )
        book_escort(
            load["id"], provider_name="PR", position="REAR",
            start="2026-08-12T10:00:00Z", end="2026-08-12T10:01:00Z",
            rate_per_hour_cents=10001,
        )
        schedule_both_cranes(load["id"])
        file_and_approve_securement(
            load["id"], method="CHAINS", tiedown_count=2,
            wll_per_tiedown_lbs=10000,
        )
        set_clock("2026-08-12T10:00:00Z")
        validate_success(api.depart_load(load["id"], DRIVER), 200)
        validate_success(api.arrive_load(load["id"], DRIVER), 200)
        return load

    def test_escort_lines_rounded_per_booking_before_summing(self, api):
        """PRD §3.9: "`escorts_cents` — for each `COMPLETED` escort booking,
        `scheduled_minutes` multiplied by `rate_per_hour_cents` and divided by
        60, rounded half-up to whole cents **per booking**, with the rounded
        line values then summed; summing first and rounding once is forbidden."

        Design: Difficulty/combinatorial_formula/invoice_per_line_rounding_beats_sum_rounding
        """
        load = self._setup_two_one_minute_bookings(api)
        inv = issue_invoice(load["id"])
        assert_invoice(inv)
        # 167 + 167 = 334 per-line; sum-then-round would give
        # round(2 x 10001 / 60) = 333 and is rejected by the pinned rule.
        assert inv["escorts_cents"] == 334

    def test_invoice_totals_after_per_line_rounding(self, api):
        """PRD §2.9: "Where a calculation aggregates several lines, each line
        is individually rounded before the sum; summing raw unrounded lines and
        rounding once at the end is forbidden."
        PRD §3.9: "`subtotal_cents` — the sum of the five lines above."

        Design: Difficulty/combinatorial_formula/invoice_per_line_rounding_beats_sum_rounding
        """
        load = self._setup_two_one_minute_bookings(api)
        inv = issue_invoice(load["id"])
        assert_invoice_arithmetic(inv)
        # linehaul 3500 (10 mi x 350) + permits 12000 (NV 7000 + width 5000)
        # + escorts 334.
        assert inv["linehaul_cents"] == 3500
        assert inv["permits_cents"] == 12000
        assert inv["subtotal_cents"] == 15834
        # round_half_up(15834 x 0.08) = round_half_up(1266.72) = 1267
        assert inv["fuel_surcharge_cents"] == 1267
        assert inv["total_cents"] == 17101


class TestFuelSurchargeTierKeysOnSubtotalNotTotal:
    def _setup_subtotal_4800000(self, api):
        customer = create_customer("Cascade Timber", 20_000_000)
        load = create_load_for_customer(
            customer["id"],
            cargo_description="Glulam bundles", gross_weight_lbs=40000,
            width_in=100, height_in=50, length_in=400,
            origin="Eugene OR", destination="Bend OR",
        )
        plan_load(
            load["id"], trailer_type="RGN_LOWBOY", trailer_axle_count=2,
            driver_name="E. Silva", driver_oversize_endorsed=False,
        )
        survey_load(
            load["id"], route_miles=8000, states_crossed=["OR"],
            min_bridge_clearance_in=100, max_bridge_weight_lbs=80000,
        )
        schedule_both_cranes(load["id"])
        file_and_approve_securement(
            load["id"], method="STRAPS", tiedown_count=2,
            wll_per_tiedown_lbs=10000,
        )
        # DAMAGE fine 400000 resolved customer-liable -> enters fines_cents.
        report_and_resolve_fine(
            load["id"], kind="DAMAGE", amount_cents=400000,
            resolution="CUSTOMER_LIABLE",
            description="Fork tine puncture",
        )
        set_clock("2026-08-12T10:00:00Z")
        validate_success(api.depart_load(load["id"], DRIVER), 200)
        validate_success(api.arrive_load(load["id"], DRIVER), 200)
        return load

    def test_eight_percent_tier_applies_below_threshold(self, api):
        """PRD §3.9: "`fuel_surcharge_cents` — keyed on the **pre-surcharge**
        subtotal: a subtotal of at least 5,000,000 cents attracts a 12%
        surcharge, anything below attracts 8%, and the chosen percentage is
        multiplied by the subtotal and rounded half-up to whole cents. The tier
        never keys on the total, so a subtotal just under the threshold still
        bills the low rate even though the surcharge itself would push the
        total over it."

        Design: Difficulty/combinatorial_formula/fuel_surcharge_tier_keys_on_subtotal_not_total
        """
        load = self._setup_subtotal_4800000(api)
        inv = issue_invoice(load["id"])
        assert_invoice_arithmetic(inv)
        assert inv["fines_cents"] == 400000
        assert inv["subtotal_cents"] == 4800000  # 4400000 linehaul + 400000
        # 8% tier (4800000 < 5000000); NOT 576000 = 12%.
        assert inv["fuel_surcharge_cents"] == 384000

    def test_total_crossing_threshold_does_not_change_tier(self, api):
        """PRD §3.9: "The tier never keys on the total, so a subtotal just
        under the threshold still bills the low rate even though the surcharge
        itself would push the total over it."

        Design: Difficulty/combinatorial_formula/fuel_surcharge_tier_keys_on_subtotal_not_total
        """
        load = self._setup_subtotal_4800000(api)
        inv = issue_invoice(load["id"])
        # The total itself exceeds 5000000, proving the tier read the subtotal.
        assert inv["total_cents"] == 5184000
        assert inv["total_cents"] > 5000000
        assert inv["fuel_surcharge_cents"] == 384000


class TestEscortThresholdAtExactly144Width:
    def _plan_beam(self, api, customer_id, width_in):
        load = create_load_for_customer(
            customer_id,
            cargo_description=f"Beam {width_in}", gross_weight_lbs=40000,
            width_in=width_in, height_in=50, length_in=400,
            origin="Tracy CA", destination="Modesto CA",
        )
        return plan_load(
            load["id"], trailer_type="FLATBED", trailer_axle_count=2,
            driver_name="L. Zhu", driver_oversize_endorsed=True,
        )

    def test_width_144_requires_rear_escort(self, api):
        """PRD §3.2: "The boundary comparisons are inclusive: a width of
        exactly 144 inches requires the rear escort, 143 inches requires none,
        and exactly 192 inches of overall height adds the pole car."

        Design: Difficulty/boundary_precision_check/escort_threshold_at_exactly_144_width
        """
        customer = create_customer("Borderline Beams", 100_000_000)
        planned = self._plan_beam(api, customer["id"], 144)
        assert planned["required_escort_positions"] == ["REAR"]

    def test_width_143_requires_no_escort(self, api):
        """PRD §3.2: "Required escort positions are derived as
        `required_escort_positions`: width of at least 168 inches demands both
        a `FRONT` and a `REAR` escort; width of at least 144 inches but under
        168 demands a `REAR` escort only; narrower loads need none — and
        independently, an `overall_height_in` of at least 192 inches appends a
        `POLE_FRONT` pole car."

        Design: Difficulty/boundary_precision_check/escort_threshold_at_exactly_144_width
        """
        customer = create_customer("Borderline Beams", 100_000_000)
        planned = self._plan_beam(api, customer["id"], 143)
        # 143 falls one inch below the inclusive >= 144 threshold.
        assert planned["required_escort_positions"] == []
        # Heights are identical (50 + deck 60 = 110 < 192): width is isolated
        # as the only differing input.
        assert planned["overall_height_in"] == 110


class TestStandbyFreeMinutesExactly120:
    def test_exactly_120_minutes_bills_nothing(self, api):
        """PRD §3.7: "Two anchors pin the tiers: exactly 120 minutes of
        customer delay bills nothing, and exactly 480 minutes bills 360 minutes
        entirely at the standard rate."

        Design: Difficulty/boundary_precision_check/standby_free_minutes_exactly_120
        """
        _, load = setup_standard_load_cleared(company_name="Pinpoint Paper")
        set_clock("2026-08-12T10:00:00Z")
        validate_success(api.depart_load(load["id"], DRIVER), 200)
        event = validate_success(
            api.create_delay_event(
                load["id"],
                {
                    "kind": "CUSTOMER_DELAY",
                    "started_at": "2026-08-12T11:00:00Z",
                    "ended_at": "2026-08-12T13:00:00Z",  # exactly 120 min
                },
                DRIVER,
            ),
            201,
        )
        assert event["duration_minutes"] == 120
        assert event["billable_minutes"] == 0
        assert event["standby_amount_cents"] == 0

    def test_121_minutes_bills_one_minute(self, api):
        """PRD §3.7: "Its `billable_minutes` is the duration minus a 120-minute
        free allowance, floored at zero, for `CUSTOMER_DELAY` events, and zero
        for carrier delays and weather. The `standby_amount_cents` tiers the
        billable minutes per event: the first 360 billable minutes at 17,500
        cents per hour, any remainder at a 1.5-times premium of 26,250 cents
        per hour, with the sum of the two tier charges divided by 60 and
        rounded half-up to whole cents."

        Design: Difficulty/boundary_precision_check/standby_free_minutes_exactly_120
        """
        _, load = setup_standard_load_cleared(company_name="Pinpoint Paper")
        set_clock("2026-08-12T10:00:00Z")
        validate_success(api.depart_load(load["id"], DRIVER), 200)
        event = validate_success(
            api.create_delay_event(
                load["id"],
                {
                    "kind": "CUSTOMER_DELAY",
                    "started_at": "2026-08-12T14:00:00Z",
                    "ended_at": "2026-08-12T16:01:00Z",  # 121 min
                },
                DRIVER,
            ),
            201,
        )
        assert event["billable_minutes"] == 1
        # round_half_up(1 x 17500 / 60) = round_half_up(291.666...) = 292
        assert event["standby_amount_cents"] == 292
