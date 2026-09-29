"""Installation invoice waterfall — scope pricing, tier selection, crossover
waiver, half-up discount rounding and the passing final-inspection branch
(PRD §3.7 and §3.8)."""

from test_helpers import (
    FINAL_INSPECTOR_USER_ID,
    api_client,
    assert_set_job,
    final_inspection_payload,
    make_inspector_headers,
    read_order,
    read_set_job,
    setup_job_ready_for_final_inspection,
    validate_success,
)


def _sign_final_inspection(job_id, punch_item_count=0):
    """Sign the final installation inspection as the final inspector.

    PRD §3.8 requires the acting user to differ from the inspector who signed
    the site-readiness verdict, so the dedicated final-inspector identity is
    used for every signature in this module.
    """
    response = api_client.final_inspection(
        job_id,
        final_inspection_payload(punch_item_count=punch_item_count),
        make_inspector_headers(FINAL_INSPECTOR_USER_ID),
    )
    return validate_success(response, 200)


class TestInstallationInvoiceFullWaterfall:
    """The six-step waterfall on a job carrying every priced line."""

    def test_installer_owned_skirting_and_steps_are_priced_from_the_split(self):
        """PRD §3.7: "Pricing follows directly: `skirting_fee_cents` is zero when
        `skirting_owner` is `DEALER`, and otherwise the skirting run length
        multiplied by eighteen dollars fifty per linear foot (1,850 cents per
        foot), rounded half up to whole cents; `steps_fee_cents` is zero when
        `steps_owner` is `DEALER`, and otherwise the step count multiplied by
        four hundred and twenty dollars per unit (42,000 cents), which needs no
        rounding."

        Fifty-two linear feet of installer-owned skirting prices at 96,200
        cents and a single installer-owned step unit at 42,000 cents.

        Design: Corner/calculations/installation_invoice_full_waterfall_correct_result
        """
        scenario = setup_job_ready_for_final_inspection(
            section_count=1,
            labor_base_cents=480000,
            scope_overrides={
                "skirting_owner": "INSTALLER",
                "steps_owner": "INSTALLER",
                "skirting_linear_ft": 52,
                "steps_count": 1,
            },
            crossover_count=3,
        )
        job = scenario["set_job"]
        assert_set_job(job)
        assert job["skirting_fee_cents"] == 96200, (
            f"52 linear feet at 1,850 cents per foot must price at 96200, "
            f"got {job['skirting_fee_cents']}"
        )
        assert job["steps_fee_cents"] == 42000, (
            f"one step unit at 42,000 cents must price at 42000, "
            f"got {job['steps_fee_cents']}"
        )
        assert job["skirting_owner"] == "INSTALLER", (
            f"expected skirting_owner INSTALLER, got {job['skirting_owner']}"
        )
        assert job["steps_owner"] == "INSTALLER", (
            f"expected steps_owner INSTALLER, got {job['steps_owner']}"
        )

    def test_three_crossovers_price_at_mobilisation_plus_per_crossover(self):
        """PRD §3.7: "The submission supplies `crossover_count`, the number of
        crossovers made between sections, and pricing is a flat six hundred
        dollars (60,000 cents) for mobilising the crossover work plus one
        hundred and eighty dollars (18,000 cents) for each crossover made,
        stored as `crossover_fee_cents`." The same section adds: "The step also
        sets `crossover_recorded` to true, and that boolean rather than the
        count is what the final-inspection gate reads — a genuine single-wide
        with zero crossovers must be distinguishable from a job whose crossover
        step was simply never performed."

        Design: Corner/calculations/installation_invoice_full_waterfall_correct_result
        """
        scenario = setup_job_ready_for_final_inspection(
            section_count=1,
            labor_base_cents=480000,
            crossover_count=3,
        )
        job = scenario["set_job"]
        assert job["crossover_fee_cents"] == 114000, (
            f"60,000 cents of mobilisation plus three crossovers at 18,000 "
            f"cents each must price at 114000, got {job['crossover_fee_cents']}"
        )
        assert job["crossover_recorded"] is True, (
            f"expected crossover_recorded True, got {job['crossover_recorded']}"
        )
        assert job["scope_status"] == "SCOPE_DELIVERED", (
            f"expected scope_status SCOPE_DELIVERED, got {job['scope_status']}"
        )
        assert job["progress_status"] == "SET_COMPLETE", (
            f"recording the crossover leaves progress_status at SET_COMPLETE, "
            f"got {job['progress_status']}"
        )

    def test_full_waterfall_invoices_574268_and_closes_the_order(self):
        """PRD §3.8: "First, the pre-discount total is the job's
        `labor_base_cents` plus the scope subtotal — that is,
        `skirting_fee_cents` plus `steps_fee_cents` — plus the full, un-waived
        `crossover_fee_cents`." "Fifth, the volume discount in cents is the
        discount percentage applied to the **pre-discount total from the first
        step** — never to the billable base — rounded half up to whole cents."
        "Sixth, `invoice_total_cents` is the billable base less the volume
        discount." And on the passing branch: "When `punch_item_count` is 0, the
        job's `progress_status` moves `SET_COMPLETE → CLOSED`, `final_result` is
        set to `PASS`, the acting `X-User-ID` is stored in
        `final_inspector_user_id`, the invoice is assembled into
        `invoice_total_cents` and mirrored onto the order's own
        `invoice_total_cents`, the order's `warranty_start_date` is set to the
        logical clock's current UTC date, and the order's posture is re-derived
        and lands on `CLOSED`."

        Labour of 480,000 cents, a scope subtotal of 138,200 cents and three
        crossovers at 114,000 cents give a pre-discount total of 732,200 cents,
        which selects the six percent tier, waives the crossover line down to a
        billable base of 618,200 cents, and discounts 43,932 cents for an
        invoice of 574,268 cents.

        Design: Corner/calculations/installation_invoice_full_waterfall_correct_result
        """
        scenario = setup_job_ready_for_final_inspection(
            section_count=1,
            labor_base_cents=480000,
            scope_overrides={
                "skirting_owner": "INSTALLER",
                "steps_owner": "INSTALLER",
                "skirting_linear_ft": 52,
                "steps_count": 1,
            },
            crossover_count=3,
        )
        job_id = scenario["set_job"]["id"]
        order_id = scenario["order"]["id"]

        inspected = _sign_final_inspection(job_id, punch_item_count=0)

        assert inspected["invoice_total_cents"] == 574268, (
            f"expected invoice_total_cents 574268, "
            f"got {inspected['invoice_total_cents']}"
        )
        assert inspected["final_result"] == "PASS", (
            f"expected final_result PASS, got {inspected['final_result']}"
        )
        assert inspected["progress_status"] == "CLOSED", (
            f"expected progress_status CLOSED, got {inspected['progress_status']}"
        )
        assert inspected["final_inspector_user_id"] == FINAL_INSPECTOR_USER_ID, (
            f"expected final_inspector_user_id {FINAL_INSPECTOR_USER_ID}, "
            f"got {inspected['final_inspector_user_id']}"
        )

        order = read_order(order_id)
        assert order["invoice_total_cents"] == 574268, (
            f"the order must mirror invoice_total_cents 574268, "
            f"got {order['invoice_total_cents']}"
        )
        assert order["warranty_start_date"] == "2026-08-01", (
            f"expected warranty_start_date 2026-08-01 from the logical clock, "
            f"got {order['warranty_start_date']}"
        )
        assert order["posture"] == "CLOSED", (
            f"expected order posture CLOSED, got {order['posture']}"
        )

    def test_single_section_job_closes_the_line_as_not_applicable(self):
        """PRD §3.7: "A single-section order therefore records no joints, closes
        with a `closure_score` of 0.00 and a `closure_status` of
        `NOT_APPLICABLE`, and passes the later gate vacuously."

        Design: Corner/calculations/installation_invoice_full_waterfall_correct_result
        """
        scenario = setup_job_ready_for_final_inspection(
            section_count=1,
            labor_base_cents=480000,
            crossover_count=3,
        )
        job = read_set_job(scenario["set_job"]["id"])
        assert job["closure_status"] == "NOT_APPLICABLE", (
            f"expected closure_status NOT_APPLICABLE on a single-section order, "
            f"got {job['closure_status']}"
        )


class TestInvoiceTierBoundaryAt300000:
    """The three percent tier is selected on an inclusive lower bound."""

    def test_pre_discount_total_of_exactly_300000_waives_the_crossover(self):
        """PRD §3.8: "Second, the discount tier is selected from that
        pre-discount total on inclusive lower bounds: ten percent when the
        pre-discount total is at least nine thousand dollars (900,000 cents),
        otherwise six percent when it is at least six thousand dollars (600,000
        cents), otherwise three percent when it is at least three thousand
        dollars (300,000 cents), otherwise no discount at all." "Third, the
        crossover line is waived: the billed crossover amount is zero whenever
        any discount applies, and equal to `crossover_fee_cents` when the
        discount is zero." "The tier chosen in the second step is never
        re-evaluated after the waiver or after the discount is subtracted, even
        though the waiver lowers the amount actually billed below the figure
        that qualified for the tier; that asymmetry is intentional and is what
        makes the crossover waiver worth something to the customer."

        Labour of 240,000 cents, a dealer-owned scope worth nothing and a bare
        crossover mobilisation of 60,000 cents put the pre-discount total on
        exactly 300,000 cents: the three percent tier applies, the crossover
        line is waived to leave a billable base of 240,000 cents, and the 9,000
        cent discount computed on 300,000 leaves an invoice of 231,000 cents.

        Design: Corner/calculations/invoice_tier_boundary_at_300000_flips_waiver_and_discount
        """
        scenario = setup_job_ready_for_final_inspection(
            section_count=1,
            labor_base_cents=240000,
            scope_overrides={
                "skirting_owner": "DEALER",
                "steps_owner": "DEALER",
                "skirting_linear_ft": 52,
                "steps_count": 1,
            },
            crossover_count=0,
        )
        job = scenario["set_job"]
        assert job["skirting_fee_cents"] == 0, (
            f"a dealer-owned skirting line prices at 0, "
            f"got {job['skirting_fee_cents']}"
        )
        assert job["steps_fee_cents"] == 0, (
            f"a dealer-owned steps line prices at 0, got {job['steps_fee_cents']}"
        )
        assert job["crossover_fee_cents"] == 60000, (
            f"zero crossovers still price the 60,000 cent mobilisation, "
            f"got {job['crossover_fee_cents']}"
        )

        inspected = _sign_final_inspection(job["id"], punch_item_count=0)
        assert inspected["invoice_total_cents"] == 231000, (
            f"expected invoice_total_cents 231000 at the inclusive 300,000 cent "
            f"tier boundary, got {inspected['invoice_total_cents']}"
        )

    def test_pre_discount_total_of_299999_bills_the_crossover_undiscounted(self):
        """PRD §3.8: "Second, the discount tier is selected from that
        pre-discount total on inclusive lower bounds: ten percent when the
        pre-discount total is at least nine thousand dollars (900,000 cents),
        otherwise six percent when it is at least six thousand dollars (600,000
        cents), otherwise three percent when it is at least three thousand
        dollars (300,000 cents), otherwise no discount at all." "Third, the
        crossover line is waived: the billed crossover amount is zero whenever
        any discount applies, and equal to `crossover_fee_cents` when the
        discount is zero."

        One cent below the boundary no tier applies, so the crossover line is
        billed in full and the invoice is the whole 299,999 cent pre-discount
        total.

        Design: Corner/calculations/invoice_tier_boundary_at_300000_flips_waiver_and_discount
        """
        scenario = setup_job_ready_for_final_inspection(
            section_count=1,
            labor_base_cents=239999,
            scope_overrides={
                "skirting_owner": "DEALER",
                "steps_owner": "DEALER",
                "skirting_linear_ft": 52,
                "steps_count": 1,
            },
            crossover_count=0,
        )
        job = scenario["set_job"]
        inspected = _sign_final_inspection(job["id"], punch_item_count=0)
        assert inspected["invoice_total_cents"] == 299999, (
            f"expected invoice_total_cents 299999 one cent below the tier "
            f"boundary, got {inspected['invoice_total_cents']}"
        )


class TestInvoiceDiscountRoundsHalfUp:
    """The volume discount rounds half up at an exact half cent."""

    def test_discount_of_36100_point_5_rounds_up_to_36101(self):
        """PRD §3.8: "Fifth, the volume discount in cents is the discount
        percentage applied to the **pre-discount total from the first step** —
        never to the billable base — rounded half up to whole cents." "Sixth,
        `invoice_total_cents` is the billable base less the volume discount."

        Labour of 495,425 cents plus 46,250 cents of installer-owned skirting
        plus a 60,000 cent crossover mobilisation give a pre-discount total of
        601,675 cents, whose six percent discount is exactly 36,100.5 cents.
        Rounding half up yields 36,101 cents, so the waived billable base of
        541,675 cents invoices at 505,574 cents rather than 505,575.

        Design: Corner/calculations/invoice_discount_round_half_up_at_exact_half_cent
        """
        scenario = setup_job_ready_for_final_inspection(
            section_count=1,
            labor_base_cents=495425,
            scope_overrides={
                "skirting_owner": "INSTALLER",
                "steps_owner": "DEALER",
                "skirting_linear_ft": 25,
                "steps_count": 1,
            },
            crossover_count=0,
        )
        job = scenario["set_job"]
        assert job["skirting_fee_cents"] == 46250, (
            f"25 linear feet at 1,850 cents per foot must price at 46250, "
            f"got {job['skirting_fee_cents']}"
        )
        assert job["steps_fee_cents"] == 0, (
            f"a dealer-owned steps line prices at 0, got {job['steps_fee_cents']}"
        )
        assert job["crossover_fee_cents"] == 60000, (
            f"expected crossover_fee_cents 60000, got {job['crossover_fee_cents']}"
        )

        inspected = _sign_final_inspection(job["id"], punch_item_count=0)
        assert inspected["invoice_total_cents"] == 505574, (
            f"a half-cent discount must round up to 36101, leaving "
            f"invoice_total_cents 505574, got {inspected['invoice_total_cents']}"
        )
