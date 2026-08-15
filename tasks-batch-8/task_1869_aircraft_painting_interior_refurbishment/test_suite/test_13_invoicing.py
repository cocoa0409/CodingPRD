"""Invoices: milestones, stall fee, per-line rounding, issue/void (PRD §3.12)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_program,
    api_client,
    assert_invoice,
    book_slot,
    book_booth_window,
    create_and_approve_scheme,
    create_and_certify_lot,
    create_assessment,
    create_bay,
    create_booth,
    create_discovery,
    create_engagement,
    create_invoice,
    decide_assessment,
    estimate_discovery,
    get_program,
    issue_invoice,
    make_customer_rep_headers,
    pass_standard_inspections,
    prepare_weight_record,
    set_logical_clock,
    setup_booked_program,
    setup_in_work_program,
    setup_inducted_program,
    sign_off_weight_record,
    validate_error,
    validate_success,
)
from test_helpers.factories import complete_discovery_payload

_FIN = TEST_USERS["finance_clerk_headers"]
_TECH = TEST_USERS["shop_technician_headers"]


def _ready_with_two_completed_items():
    """READY_FOR_DELIVERY with two discovery items COMPLETED at an actual cost
    of 333,333 cents each and the booth completed at its scheduled 8 hours
    (fee 200,000); no delay events, so the penalty is zero."""
    ctx = setup_inducted_program()
    for desc in ("Wing-root corrosion blend-out", "Fairing fastener replacement"):
        item = create_discovery(ctx["program"]["id"], description=desc)
        estimate_discovery(item["id"], est_cost_cents=300000, est_hours=40)
        validate_success(
            api_client.approve_discovery_item(
                item["id"],
                {"expected_program_version": get_program(ctx["program"]["id"])["version"]},
                make_customer_rep_headers(ctx["customer"]["id"]),
            )
        )
        validate_success(
            api_client.complete_discovery_item(
                item["id"], complete_discovery_payload(actual_cost_cents=333333), _TECH
            )
        )
    ctx["assessment"] = create_assessment(ctx["program"]["id"])
    advance_program(ctx["program"]["id"], "SURFACE_REVIEW")
    decide_assessment(ctx["assessment"]["id"], decision="STRIP", corrosion_severity="NONE")
    ctx["scheme"] = create_and_approve_scheme(
        ctx["program"]["id"], ctx["customer"]["id"]
    )
    ctx["booth"] = create_booth()
    ctx["booking"] = book_booth_window(ctx["booth"]["id"], ctx["program"]["id"])
    advance_program(ctx["program"]["id"], "IN_WORK")
    validate_success(
        api_client.complete_booth_booking(ctx["booking"]["id"], {"actual_hours": 8}, _TECH)
    )
    advance_program(ctx["program"]["id"], "IN_INSPECTION")
    pass_standard_inspections(ctx)
    ctx["lot"] = create_and_certify_lot(ctx["program"]["id"])
    ctx["wbr"] = prepare_weight_record(ctx["program"]["id"], ctx["scheme"]["id"])
    sign_off_weight_record(ctx["wbr"]["id"])
    advance_program(ctx["program"]["id"], "READY_FOR_DELIVERY")
    return ctx


class TestFinalInvoiceRoundingOrder:
    def test_per_item_handling_lines_rounded_individually(self, api):
        """PRD §3.12: "Every line is individually rounded half-up to integer
        cents first, and only then summed into `total_cents` — sum-then-round
        is forbidden, and the per-line handling surcharge below is where that
        ordering bites." and "plus a per-item handling line of ten percent of
        that item's amount, each handling line individually rounded half-up".

        Design: Difficulty/combinatorial_formula/invoice_per_line_rounding_then_sum
        """
        ctx = _ready_with_two_completed_items()
        invoice = create_invoice(ctx["program"]["id"], "FINAL")
        handling = [l["amount_cents"] for l in invoice["lines"]
                    if l["amount_cents"] == 33333]
        assert len(handling) == 2, (
            "each 333333-cent item yields round(33333.3) = 33333 individually"
        )

    def test_final_total_is_sum_of_individually_rounded_lines(self, api):
        """PRD §3.12: "Every line is individually rounded half-up to integer
        cents first, and only then summed into `total_cents` — sum-then-round
        is forbidden". Aggregate-then-round on the two handling amounts would
        produce round(666666 x 0.10) = 66667 and a total of 7,106,170 instead
        of 7,106,169.

        Design: Difficulty/combinatorial_formula/invoice_per_line_rounding_then_sum
        """
        ctx = _ready_with_two_completed_items()
        invoice = create_invoice(ctx["program"]["id"], "FINAL")
        assert_invoice(invoice)
        # remainder 6172837 + items 333333 x2 + handling 33333 x2 + booth 200000 - 0.
        assert invoice["total_cents"] == 7106169


class TestIssueVoidConservation:
    def test_issued_invoice_contributes_to_billed_total(self, api):
        """PRD §3.12: "The customer pays an `ISSUED` invoice — ownership-checked
        — moving it to `PAID` and recomputing the program's
        `billed_total_cents`, which sums `total_cents` over invoices in
        `ISSUED` or `PAID` status and nothing else". DEPOSIT milestone:
        "A `DEPOSIT` invoice carries a single milestone line: ten percent of
        `base_price_cents`, rounded."

        Design: Difficulty/compensating_invariant/invoice_issue_void_billed_total_conservation
        """
        ctx = setup_booked_program()
        invoice = create_invoice(ctx["program"]["id"], "DEPOSIT")
        # round(12345673 x 0.10) = round(1234567.3) = 1234567.
        assert invoice["total_cents"] == 1234567
        issue_invoice(invoice["id"])

        program = get_program(ctx["program"]["id"])
        assert program["billed_total_cents"] == 1234567

    def test_void_after_issue_restores_billed_total(self, api):
        """PRD §2.7: "Second, issue-then-void on an invoice nets to zero:
        voiding an ISSUED invoice drops it out of `billed_total_cents`
        precisely, leaving the total unchanged from before issuance."

        Design: Difficulty/compensating_invariant/invoice_issue_void_billed_total_conservation
        """
        ctx = setup_booked_program()
        invoice = create_invoice(ctx["program"]["id"], "DEPOSIT")
        issue_invoice(invoice["id"])
        assert get_program(ctx["program"]["id"])["billed_total_cents"] == 1234567

        voided = validate_success(api.void_invoice(invoice["id"], _FIN))
        assert voided["status"] == "VOIDED"
        program = get_program(ctx["program"]["id"])
        assert program["billed_total_cents"] == 0, (
            "issue + void conserve billed_total_cents"
        )


class TestInvoiceGates:
    def test_duplicate_kind_issue_rejected(self, api):
        """PRD §3.12: "Issuance is gated by phase and uniqueness, both rejected
        with the named errors: ... a second non-`VOIDED` invoice of the same
        kind surfaces as `ERR_INVOICE_ALREADY_ISSUED`." and "An invoice begins
        `DRAFT`".

        Design: Corner/state_machines/invoice_duplicate_kind_issue_rejected
        """
        ctx = setup_booked_program()
        first = create_invoice(ctx["program"]["id"], "DEPOSIT")
        assert first["status"] == "DRAFT", "invoice initial state is DRAFT"
        issue_invoice(first["id"])

        second = create_invoice(ctx["program"]["id"], "DEPOSIT")
        resp = api.issue_invoice(second["id"], _FIN)
        validate_error(resp, ApiErrorId.ERR_INVOICE_ALREADY_ISSUED)

    def test_final_invoice_issue_phase_gated(self, api):
        """PRD §3.12: "a `FINAL` invoice requires exactly `READY_FOR_DELIVERY`
        — violations surface as `ERR_INVOICE_KIND_PHASE`" and "Drafting is
        permitted in any non-terminal program phase — the kind-appropriate
        phase is enforced at issuance, not at drafting".

        Design: Corner/validations/final_invoice_issue_phase_gated
        """
        ctx = setup_in_work_program()  # drafting a FINAL invoice is legal here
        invoice = create_invoice(ctx["program"]["id"], "FINAL")
        resp = api.issue_invoice(invoice["id"], _FIN)
        validate_error(resp, ApiErrorId.ERR_INVOICE_KIND_PHASE)


class TestProgressStallFee:
    def test_progress_invoice_includes_calendar_day_ceiling_stall_fee(self, api):
        """PRD §3.12: "A `PROGRESS` invoice carries a milestone line of forty
        percent of `base_price_cents`, rounded, plus a hangar stall fee line.
        The stall fee takes the program's longest-duration non-`CANCELLED`
        hangar slot (`BOOKED`, `ACTIVE`, or `RELEASED`; ties broken by earliest
        `created_at`, and the line is zero if none exists), computes the
        calendar-day ceiling of its occupied window — the window length divided
        by twenty-four hours, rounded up — and multiplies those days by the
        bay's `daily_rate_cents`."

        Design: Corner/calculations/hangar_stall_fee_ceil_days_on_progress_invoice
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        ctx = create_engagement()
        ctx["bay"] = create_bay()
        # 2026-08-01 -> 2026-08-22 is exactly 21 days: ceil(21.0) = 21.
        book_slot(ctx["bay"]["id"], ctx["program"]["id"],
                  start_at="2026-08-01T00:00:00Z", end_at="2026-08-22T00:00:00Z")

        invoice = create_invoice(ctx["program"]["id"], "PROGRESS")
        assert_invoice(invoice)
        # round(12345673 x 0.40) = 4938269 milestone + 21 x 85000 stall.
        assert invoice["total_cents"] == 4938269 + 21 * 85000 == 6723269
