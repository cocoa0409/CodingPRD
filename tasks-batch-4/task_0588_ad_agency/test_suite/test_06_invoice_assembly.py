"""Invoice assembly: the two billing modes, the markup, the commission and the pinned total."""

from test_helpers import (
    ApiErrorId,
    assert_invoice,
    assemble_invoice,
    create_invoice_payload,
    log_and_approve_time,
    log_time,
    place_insertion_order,
    record_and_approve_vendor_cost,
    record_vendor_cost,
    register_placement,
    reserve_insertion_order,
    setup_base,
    setup_media_plan,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestProvisionalVersusFinal:
    """Difficulty: dual_variant_calc / invoice_provisional_vs_final_money_divergence."""

    @staticmethod
    def _setup():
        base = setup_base(retainer_funding=5_000_000)
        approved = log_and_approve_time(base, "dana", "2026-06-02T09:00:00Z",
                                        "2026-06-02T17:00:00Z")          # 480 min, APPROVED
        submitted = log_time(base, "dana", "2026-06-02T17:00:00Z",
                             "2026-06-02T19:00:00Z")                     # 120 min, SUBMITTED
        cost = record_vendor_cost(base, vendor_name="Freelance Editor", vendor_type="FREELANCER",
                                  estimated_amount_cents=100_000, incurred_on="2026-06-03")
        base.update({"approved_entry": approved, "submitted_entry": submitted, "cost": cost})
        return base

    def test_provisional_bills_unapproved_work_at_forecast_values(self, api):
        """PRD §3.8: "Under `PROVISIONAL`, the agency bills forecast values from work that has
        not yet been signed off. Time entries of the campaign whose `work_date` falls inside the
        window and whose status is `SUBMITTED` or `APPROVED` are included, each contributing its
        `estimated_amount_cents` — the straight-line figure with no overtime uplift. Vendor costs
        of the campaign whose `incurred_on` falls inside the window and whose status is
        `SUBMITTED` or `APPROVED` are included, each contributing its `estimated_amount_cents` as
        its base. Insertion orders belonging to any media plan of the campaign, whose
        `flight_start` falls inside the window, are included when their status is `RESERVED`,
        `PLACED` or `DELIVERED`."
        PRD §3.8: "`line_count` is the number of included time entries plus the number of
        included vendor costs plus one more if `media_gross_cents` is greater than zero."

        Design: Difficulty/dual_variant_calc/invoice_provisional_vs_final_money_divergence
        """
        base = self._setup()

        invoice = validate_success(
            api.create_invoice(
                create_invoice_payload(base["client_id"], base["campaign_id"], base["retainer_id"],
                                       billing_mode="PROVISIONAL"),
                base["am_headers"],
            ),
            201,
        )
        assert_invoice(invoice)
        assert invoice["line_count"] == 3, "two time entries + one vendor cost, no media"
        assert invoice["labor_cents"] == 200_000, "160000 approved + 40000 still submitted"
        assert invoice["vendor_base_cents"] == 100_000
        assert invoice["vendor_marked_up_cents"] == 117_500
        assert invoice["subtotal_cents"] == 317_500
        assert invoice["admin_fee_cents"] == 9_525
        assert invoice["total_cents"] == 327_025

    def test_final_bills_only_approved_work_at_actual_values(self, api):
        """PRD §3.8: "Under `FINAL`, the agency bills only approved work at actual values. Time
        entries in the window are included only when their status is `APPROVED`, and each
        contributes its `billable_amount_cents` — the figure *with* the overtime uplift. Vendor
        costs in the window are included only when their status is `APPROVED`, and each
        contributes its `actual_amount_cents` as its base. Insertion orders in the window are
        included only when their status is `PLACED` or `DELIVERED`."
        PRD §3.5: "An approved entry later moves `APPROVED → BILLED` when a final invoice that
        includes it is issued, and reverts `BILLED → APPROVED` if that invoice is subsequently
        voided — the compensating move that releases the line to be billed again."

        Design: Difficulty/dual_variant_calc/invoice_provisional_vs_final_money_divergence
        """
        base = self._setup()

        invoice = validate_success(
            api.create_invoice(
                create_invoice_payload(base["client_id"], base["campaign_id"], base["retainer_id"],
                                       billing_mode="FINAL"),
                base["am_headers"],
            ),
            201,
        )
        assert_invoice(invoice)
        assert invoice["line_count"] == 1, "only the APPROVED entry survives the FINAL filter"
        assert invoice["labor_cents"] == 160_000
        assert invoice["vendor_base_cents"] == 0, "the SUBMITTED vendor cost is excluded"
        assert invoice["vendor_marked_up_cents"] == 0
        assert invoice["subtotal_cents"] == 160_000
        assert invoice["admin_fee_cents"] == 4_800
        assert invoice["total_cents"] == 164_800

        submitted = validate_success(
            api.get_time_entry(base["submitted_entry"]["id"], base["admin_headers"])
        )
        assert submitted["status"] == "SUBMITTED"

        costs, _meta = validate_paginated(
            api.list_campaign_vendor_costs(base["campaign_id"], base["am_headers"])
        )
        assert next(c for c in costs if c["id"] == base["cost"]["id"])["status"] == "SUBMITTED"


class TestVendorMarkupRoundingOrder:
    """Difficulty: combinatorial_formula / vendor_markup_rounded_per_line_then_summed."""

    @staticmethod
    def _setup():
        base = setup_base(retainer_funding=5_000_000)
        record_and_approve_vendor_cost(
            base, 1_000_002, vendor_name="Reel Post House", vendor_type="PRODUCTION",
            estimated_amount_cents=900_000, incurred_on="2026-06-03",
        )
        record_and_approve_vendor_cost(
            base, 1_000_002, vendor_name="Grade Suite", vendor_type="PRODUCTION",
            estimated_amount_cents=900_000, incurred_on="2026-06-03",
        )
        return base

    def test_each_supplier_line_is_marked_up_and_rounded_on_its_own(self, api):
        """PRD §3.6: "**each line individually** is multiplied by one plus the markup rate and
        rounded half up to a whole cent, and only then are the marked-up lines summed into the
        invoice's `vendor_marked_up_cents`. The un-marked-up bases of the same lines are summed,
        without any rounding step, into `vendor_base_cents`. Summing the bases first and applying
        the markup once to the aggregate is a different — and wrong — answer: two lines of
        1,000,002 cents at a 17.5 percent markup come to 2,350,004 cents when rounded per line
        and 2,350,005 cents when rounded after summing."

        Design: Difficulty/combinatorial_formula/vendor_markup_rounded_per_line_then_summed
        """
        base = self._setup()

        invoice = assemble_invoice(base, billing_mode="FINAL")

        assert invoice["line_count"] == 2
        assert invoice["vendor_base_cents"] == 2_000_004
        assert invoice["vendor_marked_up_cents"] == 2_350_004
        assert invoice["vendor_marked_up_cents"] != 2_350_005, (
            "2350005 is the sum-then-round answer the PRD explicitly rejects"
        )

    def test_the_per_line_markup_feeds_the_subtotal_and_the_total(self, api):
        """PRD §3.8: "1. `subtotal_cents` is `labor_cents` plus `vendor_marked_up_cents` plus
        `media_commission_cents`."
        PRD §3.8: "4. `admin_fee_cents` is 3 percent of the *discounted* subtotal — that is, 0.03
        multiplied by the difference of `subtotal_cents` and `discount_cents` — rounded half up
        to a whole cent. It is computed **after** the discount, never before."
        PRD §3.8: "5. `total_cents` is `subtotal_cents` less `discount_cents` plus
        `admin_fee_cents`."

        Design: Difficulty/combinatorial_formula/vendor_markup_rounded_per_line_then_summed
        """
        base = self._setup()

        invoice = assemble_invoice(base, billing_mode="FINAL")

        assert_invoice(invoice)
        assert invoice["labor_cents"] == 0
        assert invoice["media_commission_cents"] == 0
        assert invoice["subtotal_cents"] == 2_350_004
        assert invoice["admin_fee_cents"] == 70_500
        assert invoice["total_cents"] == 2_420_504


class TestDiscountTierKeysOnSubtotal:
    """Difficulty: combinatorial_formula / invoice_discount_tier_keyed_on_subtotal_not_on_total."""

    @staticmethod
    def _setup():
        base = setup_base(retainer_funding=5_000_000)
        placement = register_placement(publisher_name="StreamCo", channel="VIDEO", min_dark_days=0)
        plan = setup_media_plan(base, approve=True, approved_budget_cents=10_000_000,
                                allowed_channels=["VIDEO"])
        order = reserve_insertion_order(
            base, plan["id"], placement["id"], flight_start="2026-06-05",
            flight_end="2026-06-20", gross_cents=5_000_000,
        )
        place_insertion_order(base, order["id"])
        record_and_approve_vendor_cost(
            base, 7_829_787, vendor_name="Reel Post House", vendor_type="PRODUCTION",
            estimated_amount_cents=7_000_000, incurred_on="2026-06-03",
        )
        return base

    def test_the_subtotal_is_assembled_from_marked_up_vendor_and_tiered_commission(self, api):
        """PRD §3.8: "The commission rate is 15 percent while the gross is below 5,000,000 cents;
        12 percent from 5,000,000 cents up to but not including 20,000,000 cents; and 10 percent
        from 20,000,000 cents upward. The tier boundaries are inclusive at the low end, so a
        gross of exactly 5,000,000 cents takes 12 percent (not 15) and a gross of exactly
        20,000,000 cents takes 10 percent (not 12)."
        PRD §3.8: "1. `subtotal_cents` is `labor_cents` plus `vendor_marked_up_cents` plus
        `media_commission_cents`."

        Design: Difficulty/combinatorial_formula/invoice_discount_tier_keyed_on_subtotal_not_on_total
        """
        base = self._setup()

        invoice = assemble_invoice(base, billing_mode="FINAL")

        assert invoice["labor_cents"] == 0
        assert invoice["vendor_base_cents"] == 7_829_787
        assert invoice["vendor_marked_up_cents"] == 9_200_000
        assert invoice["media_gross_cents"] == 5_000_000
        assert invoice["media_commission_cents"] == 600_000, "exactly 5,000,000 takes 12 percent"
        assert invoice["subtotal_cents"] == 9_800_000

    def test_a_subtotal_below_the_tier_takes_no_discount_even_when_the_total_crosses_it(self, api):
        """PRD §3.8: "2. `discount_pct` is the volume-discount rate selected from
        `subtotal_cents` **and from nothing else**: 0.00 while the subtotal is below 10,000,000
        cents; 0.05 from 10,000,000 cents up to but not including 25,000,000 cents; and 0.08 from
        25,000,000 cents upward."
        PRD §3.8: "The trap in that sequence is worth stating plainly: the discount tier keys on
        the subtotal, not on the total. A subtotal of 9,800,000 cents therefore takes a 0.00
        discount and an admin fee of 294,000 cents, for a total of 10,094,000 cents."

        Design: Difficulty/combinatorial_formula/invoice_discount_tier_keyed_on_subtotal_not_on_total
        """
        base = self._setup()

        invoice = assemble_invoice(base, billing_mode="FINAL")

        assert_invoice(invoice)
        assert invoice["subtotal_cents"] == 9_800_000
        assert invoice["discount_pct"] == 0
        assert invoice["discount_cents"] == 0
        assert invoice["admin_fee_cents"] == 294_000
        assert invoice["total_cents"] == 10_094_000, (
            "the total crosses 10,000,000 but the tier keyed on the subtotal, which did not"
        )


class TestEmptyInvoiceBoundary:
    """Difficulty: boundary_precision_check / final_invoice_zero_eligible_lines_empty_set_boundary."""

    @staticmethod
    def _setup():
        base = setup_base(retainer_funding=5_000_000)
        log_time(base, "dana", "2026-06-02T09:00:00Z", "2026-06-02T10:00:00Z")  # SUBMITTED
        record_vendor_cost(base, vendor_name="Freelance Editor", vendor_type="FREELANCER",
                           estimated_amount_cents=100_000, incurred_on="2026-06-03")  # SUBMITTED
        return base

    def test_provisional_still_assembles_two_lines_from_unapproved_rows(self, api):
        """PRD §3.8: "Under `PROVISIONAL`, the agency bills forecast values from work that has
        not yet been signed off. Time entries of the campaign whose `work_date` falls inside the
        window and whose status is `SUBMITTED` or `APPROVED` are included, each contributing its
        `estimated_amount_cents` — the straight-line figure with no overtime uplift. Vendor costs
        of the campaign whose `incurred_on` falls inside the window and whose status is
        `SUBMITTED` or `APPROVED` are included, each contributing its `estimated_amount_cents` as
        its base."

        Design: Difficulty/boundary_precision_check/final_invoice_zero_eligible_lines_empty_set_boundary
        """
        base = self._setup()

        invoice = validate_success(
            api.create_invoice(
                create_invoice_payload(base["client_id"], base["campaign_id"], base["retainer_id"],
                                       billing_mode="PROVISIONAL"),
                base["am_headers"],
            ),
            201,
        )
        assert invoice["line_count"] == 2
        assert invoice["labor_cents"] == 20_000
        assert invoice["vendor_marked_up_cents"] == 117_500

    def test_final_assembles_zero_lines_and_is_not_created_at_all(self, api):
        """PRD §3.8: "`line_count` is the number of included time entries plus the number of
        included vendor costs plus one more if `media_gross_cents` is greater than zero. An
        invoice that assembles zero lines is not created at all: it is rejected with
        `ERR_INVOICE_NO_LINES`."
        PRD §3.8: "Under `FINAL`, the agency bills only approved work at actual values. Time
        entries in the window are included only when their status is `APPROVED`, and each
        contributes its `billable_amount_cents` — the figure *with* the overtime uplift. Vendor
        costs in the window are included only when their status is `APPROVED`, and each
        contributes its `actual_amount_cents` as its base."

        Design: Difficulty/boundary_precision_check/final_invoice_zero_eligible_lines_empty_set_boundary
        """
        base = self._setup()
        validate_success(
            api.create_invoice(
                create_invoice_payload(base["client_id"], base["campaign_id"], base["retainer_id"],
                                       billing_mode="PROVISIONAL"),
                base["am_headers"],
            ),
            201,
        )

        resp = api.create_invoice(
            create_invoice_payload(base["client_id"], base["campaign_id"], base["retainer_id"],
                                   billing_mode="FINAL"),
            base["am_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVOICE_NO_LINES.value)
        assert resp.status_code == 422

        _rows, meta = validate_paginated(api.list_invoices(
            base["admin_headers"], params={"campaign_id": base["campaign_id"]}))
        assert meta["total_count"] == 1, "the rejected FINAL invoice was never persisted"


def test_media_commission_is_clamped_to_the_ceiling_after_the_tier_multiply(api):
    """PRD §3.8: "The raw commission is the gross multiplied by the selected rate, rounded half
    up to a whole cent, and it is then clamped into a band: no less than 50,000 cents and no more
    than 2,500,000 cents. One exception overrides the band — when `media_gross_cents` is zero,
    `media_commission_cents` is zero, and the 50,000-cent floor does **not** apply."
    PRD §3.8: "The commission rate is 15 percent while the gross is below 5,000,000 cents; 12
    percent from 5,000,000 cents up to but not including 20,000,000 cents; and 10 percent from
    20,000,000 cents upward."

    Design: Corner/calculations/media_commission_min_floor_and_max_ceiling_clamps
    """
    base = setup_base(retainer_funding=5_000_000)
    placement = register_placement(publisher_name="StreamCo", channel="VIDEO", min_dark_days=0)
    plan = setup_media_plan(base, approve=True, approved_budget_cents=40_000_000,
                            allowed_channels=["VIDEO"])
    order = reserve_insertion_order(
        base, plan["id"], placement["id"], flight_start="2026-06-05",
        flight_end="2026-06-20", gross_cents=30_000_000,
    )
    place_insertion_order(base, order["id"])

    invoice = assemble_invoice(base, billing_mode="FINAL")

    assert_invoice(invoice)
    assert invoice["line_count"] == 1, "the media block contributes exactly one line"
    assert invoice["media_gross_cents"] == 30_000_000
    assert invoice["media_commission_cents"] == 2_500_000, (
        "10 percent of 30,000,000 is 3,000,000, clamped down to the 2,500,000 ceiling"
    )
    assert invoice["subtotal_cents"] == 2_500_000
    assert invoice["discount_pct"] == 0
    assert invoice["admin_fee_cents"] == 75_000
    assert invoice["total_cents"] == 2_575_000


def test_the_billing_window_excludes_a_cost_incurred_on_the_period_end(api):
    """PRD §3.8: "An invoice is assembled by an `AccountManager` for exactly one campaign over a
    half-open period. The payload names the `client_id`, the `campaign_id` being billed, the
    `retainer_id` whose prepaid balance will be drawn down, a `billing_mode` of `PROVISIONAL` or
    `FINAL`, and the window `period_start` (inclusive) to `period_end` (exclusive, and strictly
    after the start)."
    PRD §3.8: "Vendor costs in the window are included only when their status is `APPROVED`, and
    each contributes its `actual_amount_cents` as its base."

    Design: Corner/calculations/invoice_period_window_is_half_open_on_period_end
    """
    base = setup_base(retainer_funding=5_000_000)
    record_and_approve_vendor_cost(
        base, 100_000, vendor_name="In Window", vendor_type="PRINT",
        estimated_amount_cents=90_000, incurred_on="2026-06-30",
    )
    record_and_approve_vendor_cost(
        base, 200_000, vendor_name="Out Of Window", vendor_type="PRINT",
        estimated_amount_cents=190_000, incurred_on="2026-07-01",
    )

    invoice = assemble_invoice(base, billing_mode="FINAL",
                               period_start="2026-06-01", period_end="2026-07-01")

    assert invoice["line_count"] == 1, "only the 2026-06-30 cost falls inside [start, end)"
    assert invoice["vendor_base_cents"] == 100_000
    assert invoice["vendor_marked_up_cents"] == 117_500
    assert invoice["subtotal_cents"] == 117_500
    assert invoice["total_cents"] == 121_025
