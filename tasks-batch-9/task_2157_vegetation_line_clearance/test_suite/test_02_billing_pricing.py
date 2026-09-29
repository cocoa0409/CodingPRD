"""Unit-price versus time-and-materials pricing, and the settlement waterfall."""
import pytest

from test_helpers import (
    TEST_USERS, assert_billing_line, assert_production_entry, complete_prepared_span,
    assert_settlement_waterfall, current_version, draft_billing_line, file_production,
    read_line, read_plan, read_span, setup_completed_span, setup_in_progress_span,
    validate_paginated, validate_success,
)

ANALYST = TEST_USERS["analyst_headers"]


class TestUnitPriceVersusTimeAndMaterials:
    """One field outcome, two contracts, two different gross figures."""

    @staticmethod
    def _two_spans_same_field_outcome():
        world = setup_completed_span(
            span_miles=2.5, planned_unit_count=200, units_trimmed=180,
            labor_hours=8, equipment_hours=6, disposal_tons=1,
            extra_spans=[{"span_miles": 2.5, "billing_method": "TIME_AND_MATERIALS",
                          "planned_unit_count": 200}])
        tm = complete_prepared_span(
            world["extra_spans"][0]["id"], world["crew"]["id"],
            units_trimmed=180, labor_hours=8, equipment_hours=6, disposal_tons=1)
        world["tm_span"] = tm["span"]
        return world

    def test_unit_price_line_prices_from_units_and_the_density_tier(self, api):
        """PRD §3.9: "The gross is `billable_units` multiplied by the unit rate for the
        circuit's `voltage_class` — 4,200 cents per unit at `DISTRIBUTION_4KV`, 4,800 at
        `DISTRIBUTION_12KV`, 6,100 at `DISTRIBUTION_35KV`, 7,500 at `SUBTRANSMISSION_69KV` and
        9,000 at `TRANSMISSION_115KV` — multiplied by the `density_multiplier`, with the
        product rounded half-up to a whole cent and stored as `gross_cents`."
        PRD §3.9: "Labor hours, equipment hours and disposal tonnage are ignored entirely by
        this variant."

        Design: Difficulty/dual_variant_calc/unit_price_vs_tm_gross_diverge_on_identical_field_outcome
        """
        world = self._two_spans_same_field_outcome()

        version = current_version(world["span"]["id"])
        resp = api.create_billing_line(
            world["span"]["id"],
            {"billing_method": "UNIT_PRICE", "expected_work_order_version": version}, ANALYST)
        line = validate_success(resp, 201)

        assert_billing_line(line)
        assert line["billable_units"] == 180
        assert line["density_multiplier"] == pytest.approx(1.00, abs=0.001)
        assert line["gross_cents"] == 864000
        assert line["final_payable_cents"] == 820800
        assert_settlement_waterfall(line)

    def test_time_and_materials_line_on_identical_work_yields_a_different_gross(self, api):
        """PRD §3.9: "Under `TIME_AND_MATERIALS` the arithmetic is the mirror image: refusals
        and the density tier are ignored entirely, so the line records `billable_units` of 0
        and a `density_multiplier` of 1.00, and the gross is assembled from the production
        sheets instead."
        PRD §3.9: "The consequence worth stating plainly is that an identical field outcome
        yields a different `gross_cents` under the two variants — they are not two views of one
        number."

        Design: Difficulty/dual_variant_calc/unit_price_vs_tm_gross_diverge_on_identical_field_outcome
        """
        world = self._two_spans_same_field_outcome()

        unit_line = draft_billing_line(world["span"]["id"], "UNIT_PRICE")
        tm_line = draft_billing_line(world["tm_span"]["id"], "TIME_AND_MATERIALS")

        assert tm_line["gross_cents"] == 128064, \
            "8 h labor at 8533 + 6 equipment hours at 9500 + 1 ton at 2800"
        assert tm_line["billable_units"] == 0
        assert tm_line["retainage_cents"] == 0
        assert tm_line["final_payable_cents"] == 128064
        assert unit_line["gross_cents"] != tm_line["gross_cents"]
        assert read_plan(world["plan"]["id"])["committed_cents"] == 948864


class TestTimeAndMaterialsRoundingOrder:
    """Each production entry is rounded to a whole cent before the entries are added."""

    @staticmethod
    def _span_with_three_entries():
        world = setup_in_progress_span(
            span_miles=1.0, billing_method="TIME_AND_MATERIALS", planned_unit_count=100,
            start_at="2026-08-03T06:00:00Z", end_at="2026-08-06T20:00:00Z")
        crew_id = world["crew"]["id"]
        booking_id = world["booking"]["id"]
        world["entries"] = [
            file_production(booking_id, crew_id, work_date="2026-08-03", units_trimmed=40,
                            labor_hours=12, equipment_hours=8, disposal_tons=2),
            file_production(booking_id, crew_id, work_date="2026-08-04", units_trimmed=35,
                            labor_hours=9.5, equipment_hours=6.25, disposal_tons=1.5),
            file_production(booking_id, crew_id, work_date="2026-08-05", units_trimmed=10,
                            labor_hours=3.5, equipment_hours=0, disposal_tons=0),
        ]
        from test_helpers import complete_span
        world["span"] = complete_span(world["span"]["id"])
        return world

    def test_each_production_entry_is_rounded_to_a_whole_cent_on_its_own(self, api):
        """PRD §3.4: "Those four amounts are added together and the sum is rounded half-up to a
        whole cent, and that whole-cent figure is the stored `entry_cents`."
        PRD §3.4: "Labor splits at a 10-hour daily break: the straight-time portion is the
        lesser of the entry's `labor_hours` and 10, and the overtime portion is whatever
        `labor_hours` exceed 10, or zero if none do."

        Design: Difficulty/combinatorial_formula/tm_gross_rounds_per_production_entry_then_sums
        """
        world = self._span_with_three_entries()
        first, second, third = world["entries"]

        for entry in world["entries"]:
            assert_production_entry(entry)
        assert first["entry_cents"] == 192529
        assert second["entry_cents"] == 144639, "144638.5 rounds half-up to 144639"
        assert third["entry_cents"] == 29866, "29865.5 rounds half-up to 29866"

    def test_time_and_materials_gross_sums_the_already_rounded_entries(self, api):
        """PRD §3.9: "`gross_cents` is the sum of those rounded `entry_cents` values. This
        rounding order is pinned: round each entry to a whole cent first, then add. Adding the
        unrounded entry values and rounding the total once is wrong and can differ from the
        correct answer by one or more cents."

        Design: Difficulty/combinatorial_formula/tm_gross_rounds_per_production_entry_then_sums
        """
        world = self._span_with_three_entries()

        line = draft_billing_line(world["span"]["id"], "TIME_AND_MATERIALS")

        assert line["gross_cents"] == 367034
        assert line["gross_cents"] != 367033, \
            "summing unrounded entry values and rounding once is the wrong order"
        assert line["retainage_cents"] == 0
        assert line["final_payable_cents"] == 367034
        assert_settlement_waterfall(line)


class TestSettlementWaterfall:
    """Retainage is keyed on gross; the mobilization credit is keyed on net."""

    @staticmethod
    def _two_dense_spans():
        world = setup_completed_span(
            span_miles=2.5, planned_unit_count=240, units_trimmed=236,
            extra_spans=[{"span_miles": 2.5, "billing_method": "UNIT_PRICE",
                          "planned_unit_count": 240}])
        second = complete_prepared_span(
            world["extra_spans"][0]["id"], world["crew"]["id"], units_trimmed=240)
        world["span_q"] = second["span"]
        return world

    def test_line_just_below_the_net_break_earns_no_mobilization_credit(self, api):
        """PRD §3.9: "Step two withholds retainage, and the retainage percentage is keyed on
        the **gross** tier: a gross below 500,000 cents withholds nothing, a gross of at least
        500,000 cents but below 2,000,000 cents withholds 5 percent, and a gross of 2,000,000
        cents or more withholds 10 percent."
        PRD §3.9: "Step five awards a mobilization credit keyed on the **net** tier:
        `mobilization_credit_cents` is 25,000 when `net_payable_cents` is at least 1,000,000,
        and 0 otherwise."

        Design: Difficulty/combinatorial_formula/settlement_retainage_keyed_on_gross_credit_keyed_on_net
        """
        world = self._two_dense_spans()

        line = draft_billing_line(world["span"]["id"], "UNIT_PRICE")

        assert line["gross_cents"] == 1042176, "236 units at 4800 with the 0.92 dense tier"
        assert line["retainage_cents"] == 52109, "5 percent of the gross, rounded half-up"
        assert line["net_payable_cents"] == 990067
        assert line["mobilization_credit_cents"] == 0, "net sits below the 1,000,000 break"
        assert line["final_payable_cents"] == 990067
        assert_settlement_waterfall(line)

    def test_credit_never_re_enters_the_retainage_tier_decision(self, api):
        """PRD §3.9: "The credit awarded in step five never re-enters the tier decision of step
        two even though it changes what is actually paid — a re-entrant reading would flip the
        retainage tier for lines sitting near a boundary, and that reading is wrong."
        PRD §3.9: "Step six gives `final_payable_cents` as `net_payable_cents` minus
        `mobilization_credit_cents`, again exact integer arithmetic."

        Design: Difficulty/combinatorial_formula/settlement_retainage_keyed_on_gross_credit_keyed_on_net
        """
        world = self._two_dense_spans()

        line_p = draft_billing_line(world["span"]["id"], "UNIT_PRICE")
        line_q = draft_billing_line(world["span_q"]["id"], "UNIT_PRICE")

        assert line_q["gross_cents"] == 1059840
        assert line_q["retainage_cents"] == 52992, "still the 5 percent gross tier"
        assert line_q["net_payable_cents"] == 1006848
        assert line_q["mobilization_credit_cents"] == 25000
        assert line_q["final_payable_cents"] == 981848
        assert line_p["mobilization_credit_cents"] == 0
        assert read_plan(world["plan"]["id"])["committed_cents"] == 1971915


class TestDensityTierBoundary:

    @staticmethod
    def _spans_at_and_below_forty_units_per_mile():
        world = setup_completed_span(
            span_miles=2.5, planned_unit_count=200, units_trimmed=100,
            extra_spans=[{"span_miles": 2.5, "billing_method": "UNIT_PRICE",
                          "planned_unit_count": 200}])
        second = complete_prepared_span(
            world["extra_spans"][0]["id"], world["crew"]["id"], units_trimmed=99)
        world["span_y"] = second["span"]
        return world

    def test_exactly_forty_units_per_mile_bills_at_the_middle_tier(self, api):
        """PRD §3.9: "Density is then measured as `billable_units` divided by the span's
        `span_miles`, and the `density_multiplier` is read off that figure in three bands — a
        sparse span of fewer than 40 units per mile bills at 1.15, because scattered work costs
        more per tree; a span at 40 or more but under 80 units per mile bills at 1.00; and a
        dense span at 80 or more units per mile bills at 0.92."

        Design: Difficulty/boundary_precision_check/density_multiplier_at_exactly_forty_units_per_mile
        """
        world = self._spans_at_and_below_forty_units_per_mile()

        line = draft_billing_line(world["span"]["id"], "UNIT_PRICE")

        assert line["density_multiplier"] == pytest.approx(1.00, abs=0.001), \
            "100 units over 2.5 miles is exactly 40 units per mile"
        assert line["gross_cents"] == 480000
        assert line["retainage_cents"] == 0, "the gross sits below the 500,000 break"
        assert line["final_payable_cents"] == 480000

    def test_one_unit_below_the_break_bills_at_the_sparse_tier(self, api):
        """PRD §3.9: "Density is then measured as `billable_units` divided by the span's
        `span_miles`, and the `density_multiplier` is read off that figure in three bands — a
        sparse span of fewer than 40 units per mile bills at 1.15, because scattered work costs
        more per tree; a span at 40 or more but under 80 units per mile bills at 1.00; and a
        dense span at 80 or more units per mile bills at 0.92."

        Design: Difficulty/boundary_precision_check/density_multiplier_at_exactly_forty_units_per_mile
        """
        world = self._spans_at_and_below_forty_units_per_mile()

        line = draft_billing_line(world["span_y"]["id"], "UNIT_PRICE")

        assert line["density_multiplier"] == pytest.approx(1.15, abs=0.001), \
            "99 units over 2.5 miles is 39.6 units per mile"
        assert line["gross_cents"] == 546480
        assert line["retainage_cents"] == 27324
        assert line["final_payable_cents"] == 519156
        assert_settlement_waterfall(line)


class TestProductionEntryPricing:

    def test_overtime_starts_strictly_above_ten_labor_hours(self, api):
        """PRD §3.4: "Straight-time hours bill at the crew's `hourly_rate_cents`; overtime
        hours bill at that same rate multiplied by 1.5."
        PRD §3.4: "Labor splits at a 10-hour daily break: the straight-time portion is the
        lesser of the entry's `labor_hours` and 10, and the overtime portion is whatever
        `labor_hours` exceed 10, or zero if none do."

        Design: Corner/calculations/corner_overtime_split_at_exactly_ten_labor_hours
        """
        world = setup_in_progress_span(
            span_miles=1.0, billing_method="TIME_AND_MATERIALS", planned_unit_count=100,
            start_at="2026-08-03T06:00:00Z", end_at="2026-08-05T20:00:00Z")
        crew_id, booking_id = world["crew"]["id"], world["booking"]["id"]

        at_break = file_production(booking_id, crew_id, work_date="2026-08-03",
                                   units_trimmed=5, labor_hours=10,
                                   equipment_hours=0, disposal_tons=0)
        past_break = file_production(booking_id, crew_id, work_date="2026-08-04",
                                     units_trimmed=5, labor_hours=10.5,
                                     equipment_hours=0, disposal_tons=0)

        assert at_break["entry_cents"] == 85330, "10 straight-time hours at 8533"
        assert past_break["entry_cents"] == 91730, \
            "10 straight hours plus half an hour at 1.5x rounds half-up"
        assert read_span(world["span"]["id"])["actual_units_completed"] == 10


class TestBillingLineSupersession:

    def test_new_draft_voids_the_prior_draft_and_records_the_link(self, api):
        """PRD §3.9: "When a prior `DRAFT` line does exist, it moves `DRAFT → VOID` and its
        `superseded_by_billing_line_id` is set to the new line's identifier."
        PRD §3.9: "It is the exact integer sum of `final_payable_cents` across every billing
        line belonging to any span of the plan whose `status` is `DRAFT`, `SUBMITTED`,
        `APPROVED` or `PAID`, regardless of what `execution_status` those spans are in."

        Design: Corner/endpoints/corner_billing_line_supersede_voids_prior_draft_and_links_it
        """
        world = setup_completed_span()
        first = draft_billing_line(world["span"]["id"], "UNIT_PRICE")

        version = current_version(world["span"]["id"])
        resp = api.create_billing_line(
            world["span"]["id"],
            {"billing_method": "UNIT_PRICE", "expected_work_order_version": version}, ANALYST)
        second = validate_success(resp, 201)

        voided = read_line(first["id"])
        assert voided["status"] == "VOID"
        assert voided["superseded_by_billing_line_id"] == second["id"]
        assert second["status"] == "DRAFT"
        assert second["final_payable_cents"] == 820800
        assert read_plan(world["plan"]["id"])["committed_cents"] == 820800, \
            "the voided line leaves the committed set as the new one enters it"
        _, meta = validate_paginated(api.list_billing_lines(
            ANALYST, params={"work_order_id": world["span"]["id"]}))
        assert meta["total_count"] == 2
