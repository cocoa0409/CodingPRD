"""The pricing engine: provisional (estimate) vs final (invoice) variants,
the tiered premium stack, single-rounding-site parts tax, the discount-tier
snapshot order, the P1 callout, and the free-mile boundary."""
from test_helpers import (
    TEST_USERS,
    adjust_fleet_spend,
    advance_clock,
    approve_estimate,
    create_estimate,
    create_fleet,
    create_invoice_for_call,
    create_standard_rate_card,
    create_technician,
    create_vehicle,
    diagnose_call,
    drive_call_on_site,
    get_success_data,
    issue_invoice,
    make_fleet_manager_headers,
    open_triaged_call,
    run_on_site_repair,
    start_repair,
    stock_van,
    submit_estimate,
    post_part_usage,
    complete_repair,
)

OPS = TEST_USERS["ops_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


def _after_hours_p1_gold_job():
    """After-hours (18:30 received) BLOCKING -> P1 job for a GOLD-tier fleet
    (month spend adjusted to exactly 200000), MASTER technician, 2.0h actual,
    30 actual one-way miles, 80 travel minutes, 1x STARTER-9 @ 82000.
    The estimate is drafted after diagnosis while the MASTER dispatch is
    still active (ON_SITE), so the master labor column applies."""
    create_standard_rate_card()
    fleet = create_fleet(per_call_authorization_limit_cents=100000,
                         monthly_spend_cap_cents=500000)
    adjust_fleet_spend(fleet["id"], 200000, reason="prior-month true-up")
    veh = create_vehicle(fleet_account_id=fleet["id"], odometer_miles=120000)
    tech, tech_headers = create_technician(labor_rate_class="MASTER",
                                           full_name="Rita Master")
    stock = stock_van(tech["id"], part_number="STARTER-9",
                      description="Starter motor", qty_on_hand=10,
                      unit_cost_cents=41000, unit_retail_cents=82000)
    call = open_triaged_call(veh["id"], severity="BLOCKING",
                             received_at="2026-08-03T18:30:00Z",
                             distance_miles_from_depot=30,
                             breakdown_location_text="I-70 mm 241",
                             symptom_description="cranks, no start")
    call, dispatch = drive_call_on_site(
        call, tech["id"], tech_headers, "2026-08-03T18:30:00Z",
        "2026-08-03T23:30:00Z", planned_travel_miles=30,
        depart_at="2026-08-03T19:10:00Z", arrive_at="2026-08-03T20:30:00Z",
        actual_travel_miles=30)
    call = diagnose_call(call["id"], tech_headers,
                         diagnosis_summary="Failed starter motor")
    estimate = create_estimate(call["id"], labor_hours_est=2.0,
                               travel_miles_est=30, parts_estimate_cents=80000,
                               headers=tech_headers)
    submit_estimate(estimate["id"], headers=tech_headers)
    estimate = approve_estimate(estimate["id"],
                                make_fleet_manager_headers(fleet["id"]))
    start_repair(call["id"], tech_headers)
    post_part_usage(call["id"], tech_headers, stock["id"], 1)
    call = complete_repair(call["id"], tech_headers, 2.0, 120500,
                           at="2026-08-03T22:00:00Z")
    return {"fleet": fleet, "veh": veh, "tech": tech,
            "tech_headers": tech_headers, "stock": stock, "call": call,
            "dispatch": dispatch, "estimate": estimate}


class TestProvisionalVsFinalDivergence:
    def test_estimate_provisional_variant_total(self, api):
        """PRD: "Travel in the provisional variant is always charged on a
        one-way basis with the card's free-mile allowance deducted ... even
        when the call is after-hours; estimates never carry a travel-time
        component at all."

        Design: Difficulty/dual_variant_calc/estimate_provisional_vs_final_invoice_divergence
        """
        ctx = _after_hours_p1_gold_job()
        # Provisional: 2.0h x 17500 (MASTER) x 1.5 = 52500 labor;
        # max(0, 30-25) x 425 = 2125 travel (one-way even after hours);
        # 25000 P1 callout; gross 79625; GOLD 5% discount 3981;
        # + 80000 parts estimate + round(80000 x 0.0725) = 5800 tax.
        assert ctx["estimate"]["total_cents"] == 161444

    def test_final_invoice_variant_total(self, api):
        """PRD: "on an after-hours call bills portal-to-portal at twice the
        one-way actual miles with no free allowance deducted" — the final
        variant on identical call data prices a different, higher total.

        Design: Difficulty/dual_variant_calc/estimate_provisional_vs_final_invoice_divergence
        """
        ctx = _after_hours_p1_gold_job()
        invoice = create_invoice_for_call(ctx["call"]["id"])
        # Final: labor 52500; travel 2 x 30 x 425 = 25500; time 80 x 200 =
        # 16000; callout 25000; gross 119000; GOLD 5% discount 5950;
        # parts 82000; tax round(82000 x 0.0725) = 5945.
        assert invoice["labor_amount_cents"] == 52500
        assert invoice["travel_amount_cents"] == 25500
        assert invoice["discount_cents"] == 5950
        assert invoice["tax_cents"] == 5945
        assert invoice["total_cents"] == 200995
        assert invoice["total_cents"] - ctx["estimate"]["total_cents"] == 39551


class TestFinalInvoiceTieredStack:
    def test_mode_a_final_invoice_component_stack(self, api):
        """PRD: "`labor_amount_cents` ... multiplied by the after-hours
        multiplier when the call is after-hours, rounded half-up"; "A
        `P1_EMERGENCY` call adds the `emergency_callout_fee_cents` as
        `callout_fee_cents`, zero otherwise"; "the billable miles times
        `travel_per_mile_cents` form `travel_amount_cents`".

        Design: Difficulty/combinatorial_formula/mode_a_final_invoice_tiered_premium_stack
        """
        ctx = _after_hours_p1_gold_job()
        invoice = create_invoice_for_call(ctx["call"]["id"])
        assert invoice["labor_amount_cents"] == 52500, (
            "round_half_up(2.0 x 17500 x 1.5)")
        assert invoice["travel_miles_billable"] == 60, (
            "portal-to-portal 2 x 30, no free miles after hours")
        assert invoice["travel_amount_cents"] == 25500
        assert invoice["travel_time_amount_cents"] == 16000, "80 min x 200"
        assert invoice["callout_fee_cents"] == 25000, "P1_EMERGENCY callout"

    def test_mode_a_final_invoice_discount_tax_and_total(self, api):
        """PRD: "The invoice's `total_cents` is labor plus travel amount plus
        travel time plus callout, minus discount, plus parts subtotal, plus
        tow, plus tax, minus warranty offset, floored at zero".

        Design: Difficulty/combinatorial_formula/mode_a_final_invoice_tiered_premium_stack
        """
        ctx = _after_hours_p1_gold_job()
        invoice = create_invoice_for_call(ctx["call"]["id"])
        assert invoice["discount_tier"] == "GOLD"
        assert invoice["discount_cents"] == 5950, "5% of gross 119000"
        assert invoice["parts_subtotal_cents"] == 82000
        assert invoice["tax_cents"] == 5945
        # 119000 - 5950 + 82000 + 0 tow + 5945 - 0 offset.
        assert invoice["total_cents"] == 200995


class TestPartsTaxSingleRoundingSite:
    def _three_line_parts_invoice(self):
        """Business-hours DEFERRED retail call; 3x BRAKE-7 @ 33333; 1.0h
        STANDARD labor; 30 travel minutes; 10 actual miles (0 billable)."""
        create_standard_rate_card()
        veh = create_vehicle()
        tech, tech_headers = create_technician(certifications=("BRAKES",),
                                               full_name="Bob Brakes")
        stock = stock_van(tech["id"], part_number="BRAKE-7",
                          description="Brake chamber", part_class="BRAKE",
                          qty_on_hand=10, unit_cost_cents=15000,
                          unit_retail_cents=33333)
        ctx = run_on_site_repair(
            veh["id"], tech["id"], tech_headers, severity="DEFERRED",
            symptom_category="BRAKE_FAULT",
            received_at="2026-08-04T14:00:00Z",
            window=("2026-08-04T14:00:00Z", "2026-08-04T17:00:00Z"),
            depart_at="2026-08-04T14:10:00Z",
            arrive_at="2026-08-04T14:40:00Z",
            actual_travel_miles=10, planned_travel_miles=10,
            labor_hours_actual=1.0, completion_odometer_miles=90050,
            parts=[{"item_id": stock["id"], "qty": 3}],
            diagnosis_summary="brake chamber failed")
        return ctx

    def test_mode_b_parts_tax_single_rounding_site(self, api):
        """PRD: "`tax_cents` is the parts subtotal times the card's
        `parts_tax_rate_bp` divided by ten thousand, rounded half-up exactly
        once" — three lines at 33333 give subtotal 99999 and tax
        round_half_up(7249.9275) = 7250.

        Design: Difficulty/combinatorial_formula/mode_b_parts_tax_single_rounding_site
        """
        ctx = self._three_line_parts_invoice()
        invoice = create_invoice_for_call(ctx["call"]["id"])
        assert invoice["parts_subtotal_cents"] == 99999, "3 x 33333 exact"
        assert invoice["tax_cents"] == 7250, (
            "single rounding site on the subtotal")

    def test_mode_b_per_line_rounding_would_drift(self, api):
        """PRD: "the parts tax on a document is computed exactly once against
        the parts subtotal — per-line tax rounding followed by summation is
        forbidden, because it can drift from the single-rounding result by
        cents."

        Design: Difficulty/combinatorial_formula/mode_b_parts_tax_single_rounding_site
        """
        ctx = self._three_line_parts_invoice()
        invoice = create_invoice_for_call(ctx["call"]["id"])
        assert invoice["tax_cents"] != 7251, (
            "the forbidden per-line order would give 3 x 2417 = 7251")
        # labor 14500 + travel 0 + time 6000 + parts 99999 + tax 7250.
        assert invoice["total_cents"] == 127749


class TestDiscountTierSnapshotOrder:
    def _gold_edge_invoice(self):
        """Fleet month spend adjusted to exactly 499999 (GOLD); small job."""
        create_standard_rate_card()
        fleet = create_fleet(per_call_authorization_limit_cents=100000,
                             monthly_spend_cap_cents=900000)
        adjusted = adjust_fleet_spend(fleet["id"], 499999,
                                      reason="prior invoices true-up")
        assert adjusted["month_to_date_spend_cents"] == 499999
        veh = create_vehicle(fleet_account_id=fleet["id"],
                             odometer_miles=120000)
        tech, tech_headers = create_technician()
        stock = stock_van(tech["id"], part_number="FILTER-1",
                          description="Fuel filter", part_class="FILTERS",
                          qty_on_hand=10, unit_cost_cents=4000,
                          unit_retail_cents=10000)
        ctx = run_on_site_repair(
            veh["id"], tech["id"], tech_headers, severity="DEFERRED",
            symptom_category="OTHER",
            received_at="2026-08-05T14:00:00Z",
            window=("2026-08-05T14:00:00Z", "2026-08-05T17:00:00Z"),
            depart_at=None, arrive_at=None,
            actual_travel_miles=20, planned_travel_miles=20,
            labor_hours_actual=1.0, completion_odometer_miles=120100,
            parts=[{"item_id": stock["id"], "qty": 1}],
            diagnosis_summary="filter due",
            symptom_description="fuel filter service",
            breakdown_location_text="yard lot 4")
        return fleet, ctx

    def test_mode_c_tier_snapshotted_before_this_invoice(self, api):
        """PRD: "The discount uses the fleet's tier snapshotted from
        `month_to_date_spend_cents` before this invoice is counted — the
        invoice's own total feeds the month total only afterward, at issue".

        Design: Difficulty/combinatorial_formula/mode_c_discount_tier_mtd_snapshot_order
        """
        fleet, ctx = self._gold_edge_invoice()
        invoice = create_invoice_for_call(ctx["call"]["id"])
        assert invoice["discount_tier"] == "GOLD", (
            "499999 is GOLD even though this invoice pushes spend past "
            "500000")
        assert invoice["discount_cents"] == 725, "5% of gross 14500"
        assert invoice["tax_cents"] == 725, "round_half_up(10000 x 0.0725)"
        # 14500 - 725 + 10000 + 725.
        assert invoice["total_cents"] == 24500

    def test_mode_c_month_total_updates_only_at_issue(self, api):
        """PRD: "the invoice's `total_cents` is added to the fleet's
        `month_to_date_spend_cents`" at issue — after issue the derived tier
        crosses into PLATINUM for the next document.

        Design: Difficulty/combinatorial_formula/mode_c_discount_tier_mtd_snapshot_order
        """
        fleet, ctx = self._gold_edge_invoice()
        invoice = create_invoice_for_call(ctx["call"]["id"])
        assert invoice["total_cents"] == 24500
        issue_invoice(invoice["id"])
        fleet_after = get_success_data(
            api.get_fleet_account(fleet["id"], OPS))
        assert fleet_after["month_to_date_spend_cents"] == 524499, (
            "499999 + 24500")
        assert fleet_after["effective_discount_tier"] == "PLATINUM"


class TestCalloutFee:
    def test_priority_mapping_drives_callout_fee(self, api):
        """PRD: "A `P1_EMERGENCY` call adds the `emergency_callout_fee_cents`
        as `callout_fee_cents`, zero otherwise." — identical business-hours
        jobs differ only by the severity-driven priority.

        Design: Corner/calculations/priority_mapping_drives_callout_fee
        """
        create_standard_rate_card()
        veh_a = create_vehicle()
        veh_b = create_vehicle()
        tech, tech_headers = create_technician()

        ctx_a = run_on_site_repair(
            veh_a["id"], tech["id"], tech_headers, severity="BLOCKING",
            received_at="2026-08-04T09:00:00Z",
            window=("2026-08-04T09:00:00Z", "2026-08-04T11:00:00Z"),
            depart_at=None, arrive_at="2026-08-04T09:30:00Z",
            actual_travel_miles=10, planned_travel_miles=10,
            labor_hours_actual=1.0, completion_odometer_miles=90020,
            diagnosis_summary="fuse")
        assert ctx_a["call"]["priority"] == "P1_EMERGENCY"
        inv_a = create_invoice_for_call(ctx_a["call"]["id"])
        assert inv_a["callout_fee_cents"] == 25000
        # 14500 labor + 0 travel + 6000 time + 25000 callout.
        assert inv_a["total_cents"] == 45500

        advance_clock("2026-08-04T11:00:00Z")
        ctx_b = run_on_site_repair(
            veh_b["id"], tech["id"], tech_headers, severity="DEFERRED",
            received_at=None,
            window=("2026-08-04T11:00:00Z", "2026-08-04T13:00:00Z"),
            depart_at=None, arrive_at="2026-08-04T11:30:00Z",
            actual_travel_miles=10, planned_travel_miles=10,
            labor_hours_actual=1.0, completion_odometer_miles=90040,
            diagnosis_summary="fuse")
        assert ctx_b["call"]["priority"] == "P3_STANDARD"
        inv_b = create_invoice_for_call(ctx_b["call"]["id"])
        assert inv_b["callout_fee_cents"] == 0
        assert inv_b["total_cents"] == 20500


class TestFreeMileBoundary:
    def _mileage_job(self, veh_id, tech, tech_headers, actual_miles,
                     completion_odometer, received_at, window, arrive_at):
        ctx = run_on_site_repair(
            veh_id, tech["id"], tech_headers, severity="DEFERRED",
            received_at=received_at, window=window, depart_at=None,
            arrive_at=arrive_at, actual_travel_miles=actual_miles,
            planned_travel_miles=actual_miles, labor_hours_actual=0.5,
            completion_odometer_miles=completion_odometer,
            diagnosis_summary="fuse")
        return create_invoice_for_call(ctx["call"]["id"])

    def test_free_mile_boundary_25_vs_26_billable_miles(self, api):
        """PRD: "on a business-hours call bills the excess over the card's
        free-mile allowance (actual miles minus `travel_free_miles`, floored
        at zero)" — exactly 25 actual miles bills nothing; 26 bills one mile.

        Design: Difficulty/boundary_precision_check/free_mile_boundary_25_vs_26
        """
        create_standard_rate_card()
        veh_a = create_vehicle()
        veh_b = create_vehicle()
        tech, tech_headers = create_technician()
        inv_a = self._mileage_job(
            veh_a["id"], tech, tech_headers, 25, 90030,
            received_at="2026-08-04T09:00:00Z",
            window=("2026-08-04T09:00:00Z", "2026-08-04T11:00:00Z"),
            arrive_at="2026-08-04T09:30:00Z")
        assert inv_a["travel_miles_billable"] == 0, "max(0, 25 - 25)"
        assert inv_a["travel_amount_cents"] == 0

        advance_clock("2026-08-04T11:00:00Z")
        inv_b = self._mileage_job(
            veh_b["id"], tech, tech_headers, 26, 90040,
            received_at=None,
            window=("2026-08-04T11:00:00Z", "2026-08-04T13:00:00Z"),
            arrive_at="2026-08-04T11:30:00Z")
        assert inv_b["travel_miles_billable"] == 1
        assert inv_b["travel_amount_cents"] == 425

    def test_free_mile_boundary_25_vs_26_totals(self, api):
        """PRD: "the billable miles times `travel_per_mile_cents` form
        `travel_amount_cents`" — the one-mile difference moves the invoice
        total by exactly 425 (labor 7250 + time 6000 on both).

        Design: Difficulty/boundary_precision_check/free_mile_boundary_25_vs_26
        """
        create_standard_rate_card()
        veh_a = create_vehicle()
        veh_b = create_vehicle()
        tech, tech_headers = create_technician()
        inv_a = self._mileage_job(
            veh_a["id"], tech, tech_headers, 25, 90030,
            received_at="2026-08-04T09:00:00Z",
            window=("2026-08-04T09:00:00Z", "2026-08-04T11:00:00Z"),
            arrive_at="2026-08-04T09:30:00Z")
        advance_clock("2026-08-04T11:00:00Z")
        inv_b = self._mileage_job(
            veh_b["id"], tech, tech_headers, 26, 90040,
            received_at=None,
            window=("2026-08-04T11:00:00Z", "2026-08-04T13:00:00Z"),
            arrive_at="2026-08-04T11:30:00Z")
        assert inv_a["total_cents"] == 13250, "7250 labor + 6000 time"
        assert inv_b["total_cents"] == 13675, "+ 425 for the one billable mile"


class TestTravelVariantSelection:
    def _travel_variant_job(self, veh_id, tech, tech_headers, received_at,
                            window, arrive_at, completion_odometer):
        """1.0h STANDARD, 60 travel minutes, 40 actual miles, no parts,
        DEFERRED (P3, no callout)."""
        ctx = run_on_site_repair(
            veh_id, tech["id"], tech_headers, severity="DEFERRED",
            received_at=received_at, window=window, depart_at=None,
            arrive_at=arrive_at, actual_travel_miles=40,
            planned_travel_miles=40, labor_hours_actual=1.0,
            completion_odometer_miles=completion_odometer,
            diagnosis_summary="loose cable",
            symptom_description="won't crank")
        return ctx

    def test_travel_standard_vs_after_hours_portal_basis(self, api):
        """PRD: "on a business-hours call bills the excess over the card's
        free-mile allowance (actual miles minus `travel_free_miles`, floored
        at zero), while on an after-hours call bills portal-to-portal at twice
        the one-way actual miles with no free allowance deducted".

        Design: Difficulty/dual_variant_calc/travel_standard_vs_after_hours_portal_basis
        """
        create_standard_rate_card()
        veh_a = create_vehicle()
        veh_b = create_vehicle()
        tech, tech_headers = create_technician()
        ctx_a = self._travel_variant_job(
            veh_a["id"], tech, tech_headers, "2026-08-04T14:00:00Z",
            ("2026-08-04T14:00:00Z", "2026-08-04T16:00:00Z"),
            "2026-08-04T15:00:00Z", 90100)
        assert ctx_a["call"]["after_hours"] is False
        inv_a = create_invoice_for_call(ctx_a["call"]["id"])
        assert inv_a["travel_amount_cents"] == 6375, (
            "(40 - 25) x 425, standard variant")

        ctx_b = self._travel_variant_job(
            veh_b["id"], tech, tech_headers, "2026-08-04T20:00:00Z",
            ("2026-08-04T20:00:00Z", "2026-08-04T23:00:00Z"),
            "2026-08-04T21:00:00Z", 90110)
        assert ctx_b["call"]["after_hours"] is True
        inv_b = create_invoice_for_call(ctx_b["call"]["id"])
        assert inv_b["travel_amount_cents"] == 34000, (
            "2 x 40 portal-to-portal x 425, no free miles, after-hours")

    def test_travel_variant_selection_moves_the_total(self, api):
        """PRD: "The final variant resolves the rate card the same way, takes
        the call's completed dispatch (the latest by `completed_at`), and
        prices labor from actuals" — with identical mileage the after-hours
        portal-to-portal basis and the 1.5x labor multiplier raise the total.

        Design: Difficulty/dual_variant_calc/travel_standard_vs_after_hours_portal_basis
        """
        create_standard_rate_card()
        veh_a = create_vehicle()
        veh_b = create_vehicle()
        tech, tech_headers = create_technician()
        ctx_a = self._travel_variant_job(
            veh_a["id"], tech, tech_headers, "2026-08-04T14:00:00Z",
            ("2026-08-04T14:00:00Z", "2026-08-04T16:00:00Z"),
            "2026-08-04T15:00:00Z", 90100)
        inv_a = create_invoice_for_call(ctx_a["call"]["id"])
        ctx_b = self._travel_variant_job(
            veh_b["id"], tech, tech_headers, "2026-08-04T20:00:00Z",
            ("2026-08-04T20:00:00Z", "2026-08-04T23:00:00Z"),
            "2026-08-04T21:00:00Z", 90110)
        inv_b = create_invoice_for_call(ctx_b["call"]["id"])
        # Business: 14500 labor + 6375 travel + 12000 time.
        assert inv_a["total_cents"] == 32875
        # After hours: 21750 labor (1.5x) + 34000 travel + 12000 time.
        assert inv_b["total_cents"] == 67750
