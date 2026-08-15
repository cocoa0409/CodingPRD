"""Invoice submission guards and the auto-review rule engine (PRD §2.8, §2.9, §3.5)."""
from test_helpers import (
    ApiErrorId,
    assert_invoice,
    assert_matter_spend_invariants,
    block_billed_line,
    clean_line,
    create_engaged_matter,
    create_firm,
    create_matter,
    create_invoice_payload,
    engage_matter,
    firm_headers,
    get_invoice,
    get_matter,
    list_line_items,
    ops_headers,
    register_timekeeper,
    setup_billing_ready,
    setup_department_with_firm,
    submit_invoice,
    validate_error,
    validate_success,
)


class TestInvoiceBranchingFork:
    """From UNDER_REVIEW the invoice lands on APPROVED, PARTIALLY_APPROVED, or
    REJECTED depending on the aggregate line-item outcome."""

    def test_all_clean_lines_invoice_approved(self, api):
        """PRD §3.5: "The invoice's aggregate status derives from its lines and is re-evaluated after every line-item review action and every appeal resolution: while any line remains `PENDING` the invoice stays `UNDER_REVIEW`; when every line sits in `APPROVED`, `ADJUSTED_APPROVED`, or `REINSTATED`, the invoice becomes `APPROVED`; when every line sits in `REJECTED` or `UPHELD`, it becomes `REJECTED`; anything in between yields `PARTIALLY_APPROVED`."
        PRD §3.5: "Landing on `APPROVED` or `PARTIALLY_APPROVED` books spend — the matter's `billed_to_date_cents` increases by the invoice's `approved_total_cents`"

        Design: Difficulty/non_linear_state_machine/invoice_branching_fork_from_under_review
        """
        ctx = setup_billing_ready()
        dept_id, firm_id = ctx["dept"]["id"], ctx["firm"]["id"]
        invoice = submit_invoice(
            dept_id, ctx["matter"]["id"], firm_id, ctx["matter_version"],
            [clean_line(ctx["timekeeper"]["id"], "L110", 1.00, 100_000)],
            invoice_number="INV-A",
        )
        inv = get_invoice(dept_id, ctx["matter"]["id"], invoice["id"])
        assert_invoice(inv)
        assert inv["status"] == "APPROVED", f"all-clean invoice must land APPROVED, got {inv['status']}"
        assert inv["approved_total_cents"] == 100_000
        matter = get_matter(dept_id, ctx["matter"]["id"])
        assert matter["billed_to_date_cents"] == 100_000, (
            f"APPROVED books approved_total onto the matter, got {matter['billed_to_date_cents']}"
        )
        assert_matter_spend_invariants(matter)

    def test_mixed_lines_invoice_partially_approved(self, api):
        """PRD §3.5: "The invoice's aggregate status derives from its lines and is re-evaluated after every line-item review action and every appeal resolution: while any line remains `PENDING` the invoice stays `UNDER_REVIEW`; when every line sits in `APPROVED`, `ADJUSTED_APPROVED`, or `REINSTATED`, the invoice becomes `APPROVED`; when every line sits in `REJECTED` or `UPHELD`, it becomes `REJECTED`; anything in between yields `PARTIALLY_APPROVED`."
        PRD §3.5: "The invoice's `approved_total_cents` is recomputed on the same triggers: a line contributes its `adjusted_amount_cents` when `ADJUSTED_APPROVED`, its `amount_cents` when `APPROVED` or `REINSTATED`, and zero in any other status."

        Design: Difficulty/non_linear_state_machine/invoice_branching_fork_from_under_review
        """
        ctx = setup_billing_ready()
        dept_id, firm_id = ctx["dept"]["id"], ctx["firm"]["id"]
        tk_id = ctx["timekeeper"]["id"]
        invoice = submit_invoice(
            dept_id, ctx["matter"]["id"], firm_id, ctx["matter_version"],
            [clean_line(tk_id, "L110", 1.00, 100_000), block_billed_line(tk_id, "L120", 1.00, 100_000)],
            invoice_number="INV-B",
        )
        inv = get_invoice(dept_id, ctx["matter"]["id"], invoice["id"])
        assert inv["status"] == "PARTIALLY_APPROVED", (
            f"mixed outcome must land PARTIALLY_APPROVED, got {inv['status']}"
        )
        assert inv["approved_total_cents"] == 100_000, (
            f"only the clean line contributes, got {inv['approved_total_cents']}"
        )
        matter = get_matter(dept_id, ctx["matter"]["id"])
        assert matter["billed_to_date_cents"] == 100_000

    def test_all_rejected_lines_invoice_rejected(self, api):
        """PRD §3.5: "The invoice's aggregate status derives from its lines and is re-evaluated after every line-item review action and every appeal resolution: while any line remains `PENDING` the invoice stays `UNDER_REVIEW`; when every line sits in `APPROVED`, `ADJUSTED_APPROVED`, or `REINSTATED`, the invoice becomes `APPROVED`; when every line sits in `REJECTED` or `UPHELD`, it becomes `REJECTED`; anything in between yields `PARTIALLY_APPROVED`."
        PRD §3.5: "A fully `REJECTED` invoice books nothing."

        Design: Difficulty/non_linear_state_machine/invoice_branching_fork_from_under_review
        """
        ctx = setup_billing_ready()
        dept_id, firm_id = ctx["dept"]["id"], ctx["firm"]["id"]
        invoice = submit_invoice(
            dept_id, ctx["matter"]["id"], firm_id, ctx["matter_version"],
            [block_billed_line(ctx["timekeeper"]["id"], "L110", 1.00, 100_000)],
            invoice_number="INV-C",
        )
        inv = get_invoice(dept_id, ctx["matter"]["id"], invoice["id"])
        assert inv["status"] == "REJECTED", f"all-rejected invoice must land REJECTED, got {inv['status']}"
        assert inv["approved_total_cents"] == 0
        matter = get_matter(dept_id, ctx["matter"]["id"])
        assert matter["billed_to_date_cents"] == 0, (
            f"a fully REJECTED invoice books nothing, got {matter['billed_to_date_cents']}"
        )


def test_block_billing_single_code_passes(api):
    """PRD §3.5: "First, the block-billing detector: if a line's `narrative` contains two or more distinct task-code markers — an uppercase letter "L" immediately followed by three digits, matched case-sensitively — over and above the single structured `utbms_task_code` on the line, the line is rejected with reason `BLOCK_BILLING`. Otherwise, if the asserted `rate_cents` exceeds the timekeeper's `approved_rate_cents` for the billing period's year, the line is rejected with `RATE_EXCEEDS_APPROVED`."

    Design: Corner/calculations/block_billing_single_code_passes
    """
    ctx = setup_billing_ready()
    dept_id, firm_id = ctx["dept"]["id"], ctx["firm"]["id"]
    invoice = submit_invoice(
        dept_id, ctx["matter"]["id"], firm_id, ctx["matter_version"],
        [clean_line(ctx["timekeeper"]["id"], "L110", 2.00, 100_000, narrative="drafted L110 memo")],
        invoice_number="INV-BB1",
    )
    lines = list_line_items(dept_id, ctx["matter"]["id"], invoice["id"])
    assert len(lines) == 1
    assert lines[0]["review_status"] == "APPROVED", (
        f"a single narrative task-code marker must not trigger block-billing, got {lines[0]['review_status']}"
    )


def test_per_line_rounding_half_up_pinned(api):
    """PRD §2.7: "A line item's `amount_cents` is pinned at the moment of computation as the line's `hours` multiplied by its `rate_cents`, rounded half-up to a whole cent. This per-line rounding happens before any aggregation; invoice-level totals are plain integer sums over already-rounded line amounts and undergo no further rounding."

    Design: Corner/calculations/per_line_rounding_half_up_pinned
    """
    ctx = setup_billing_ready()
    dept_id, firm_id = ctx["dept"]["id"], ctx["firm"]["id"]
    invoice = submit_invoice(
        dept_id, ctx["matter"]["id"], firm_id, ctx["matter_version"],
        [clean_line(ctx["timekeeper"]["id"], "L110", 1.005, 100_000)],
        invoice_number="INV-RND",
    )
    lines = list_line_items(dept_id, ctx["matter"]["id"], invoice["id"])
    # 1.005 hours * 100000 cents = 100500.0 exactly at the half-up step.
    assert lines[0]["amount_cents"] == 100_500, (
        f"amount_cents must be round_half_up(1.005 * 100000) = 100500, got {lines[0]['amount_cents']}"
    )


def test_duplicate_invoice_number_rejected(api):
    """PRD §3.5: "Submission guards stack up in pipeline order: the matter must be `ENGAGED` (`ERR_INVALID_STATE`); the firm must be `ACTIVE` (`ERR_FIRM_NOT_ACTIVE`); the acting user's firm must equal the matter's engaged firm (`ERR_FIRM_MISMATCH`); the `invoice_number` must be unique across that firm's invoices (`ERR_DUPLICATE_INVOICE_NUMBER`); the period end must be later than the period start (`ERR_INVALID_TEMPORAL`); every line's timekeeper must belong to the engaged firm (`ERR_REFERENTIAL_INTEGRITY`); and a stale expected version is rejected with `ERR_STALE_VERSION`."

    Design: Corner/validations/duplicate_invoice_number_rejected
    """
    ctx = setup_billing_ready()
    dept_id, firm_id = ctx["dept"]["id"], ctx["firm"]["id"]
    tk_id = ctx["timekeeper"]["id"]
    m2 = create_engaged_matter(dept_id, firm_id, title="M2", budget_cents=100_000_000)
    submit_invoice(
        dept_id, ctx["matter"]["id"], firm_id, ctx["matter_version"],
        [clean_line(tk_id, "L110", 1.00, 100_000)],
        invoice_number="INV-DUP",
    )
    # The number is unique across the firm's invoices, not per matter: reusing it
    # on a different matter of the same firm is still a duplicate.
    resp = api.create_invoice(
        dept_id, m2["id"],
        create_invoice_payload(
            invoice_number="INV-DUP",
            expected_matter_version=m2["version"],
            line_items=[clean_line(tk_id, "L110", 1.00, 100_000)],
        ),
        firm_headers(firm_id),
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_INVOICE_NUMBER)


def test_invoice_with_inverted_billing_period_rejected(api):
    """PRD §3.5: "the period end must be later than the period start (`ERR_INVALID_TEMPORAL`)"
    PRD §2.9: "8. Temporal rules: a billing period must end after it starts, a guideline's `effective_date` must not lie in the past, and an accrual period must not lie in the future — otherwise `ERR_INVALID_TEMPORAL`."

    Design: Corner/validations/invoice_with_inverted_billing_period_rejected
    """
    ctx = setup_billing_ready()
    dept_id, firm_id = ctx["dept"]["id"], ctx["firm"]["id"]
    resp = api.create_invoice(
        dept_id, ctx["matter"]["id"],
        create_invoice_payload(
            invoice_number="INV-TMP",
            billing_period_start="2026-09-01T00:00:00Z",
            billing_period_end="2026-08-01T00:00:00Z",
            expected_matter_version=ctx["matter_version"],
            line_items=[clean_line(ctx["timekeeper"]["id"], "L110", 1.00, 100_000)],
        ),
        firm_headers(firm_id),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_TEMPORAL)


class TestReferentialBeatsTemporal:
    """Referential integrity (priority 6) surfaces before temporal rules (priority 8)."""

    def _two_firm_setup(self, api):
        dept, firm1 = setup_department_with_firm()
        firm2 = create_firm(dept["id"], "F2")
        tk2 = register_timekeeper(dept["id"], firm2["id"], "OtherFirmTK", "PARTNER")
        matter = create_engaged_matter(dept["id"], firm1["id"], title="M Ref", budget_cents=100_000_000)
        return dept, firm1, tk2, matter

    def test_referential_and_temporal_violation_returns_referential(self, api):
        """PRD §2.9: "When several checks could reject the same request, the server applies them in a fixed priority order so that the surfaced error is deterministic:"
        PRD §2.9: "6. Referential integrity: foreign references resolve within scope — the billed timekeeper belongs to the engaged firm, the engaged firm is `ACTIVE`, an accrual's period is not already matched — otherwise `ERR_REFERENTIAL_INTEGRITY`."
        PRD §2.9: "8. Temporal rules: a billing period must end after it starts, a guideline's `effective_date` must not lie in the past, and an accrual period must not lie in the future — otherwise `ERR_INVALID_TEMPORAL`."

        Design: Difficulty/priority_pair_validation_conflict/referential_beats_temporal_on_invoice_create
        """
        dept, firm1, tk2, matter = self._two_firm_setup(api)
        # Wrong-firm timekeeper (referential) AND inverted billing period (temporal):
        # the pipeline surfaces the referential failure first.
        resp = api.create_invoice(
            dept["id"], matter["id"],
            create_invoice_payload(
                invoice_number="INV-REF",
                billing_period_start="2026-09-01T00:00:00Z",
                billing_period_end="2026-08-01T00:00:00Z",
                expected_matter_version=matter["version"],
                line_items=[clean_line(tk2["id"], "L110", 1.00, 100_000)],
            ),
            firm_headers(firm1["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_REFERENTIAL_INTEGRITY)

    def test_referential_violation_alone_returns_referential(self, api):
        """PRD §3.5: "every line's timekeeper must belong to the engaged firm (`ERR_REFERENTIAL_INTEGRITY`)"

        Design: Difficulty/priority_pair_validation_conflict/referential_beats_temporal_on_invoice_create
        """
        dept, firm1, tk2, matter = self._two_firm_setup(api)
        resp = api.create_invoice(
            dept["id"], matter["id"],
            create_invoice_payload(
                invoice_number="INV-REF-2",
                expected_matter_version=matter["version"],
                line_items=[clean_line(tk2["id"], "L110", 1.00, 100_000)],
            ),
            firm_headers(firm1["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_REFERENTIAL_INTEGRITY)


def test_error_stale_version_on_invoice_create(api):
    """PRD §2.8: "Submitting an invoice against a matter requires the request to carry `expected_matter_version`, set to the matter's `version` as last observed by the client. Invoice creation itself advances the matter's `version` (its spend caches are maintained as a side effect), so a second submission carrying the previously observed version is deterministically stale. If the supplied value does not match the matter's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/errors/error_stale_version_on_invoice_create
    """
    ctx = setup_billing_ready()
    dept_id, firm_id = ctx["dept"]["id"], ctx["firm"]["id"]
    tk_id = ctx["timekeeper"]["id"]
    stale_v = ctx["matter_version"]
    submit_invoice(
        dept_id, ctx["matter"]["id"], firm_id, stale_v,
        [clean_line(tk_id, "L110", 1.00, 100_000)],
        invoice_number="INV-OCC-1",
    )
    resp = api.create_invoice(
        dept_id, ctx["matter"]["id"],
        create_invoice_payload(
            invoice_number="INV-OCC-2",
            expected_matter_version=stale_v,
            line_items=[clean_line(tk_id, "L110", 1.00, 100_000)],
        ),
        firm_headers(firm_id),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


def test_occ_correct_version_succeeds_and_bumps(api):
    """PRD §2.8: "Invoice creation itself advances the matter's `version` (its spend caches are maintained as a side effect), so a second submission carrying the previously observed version is deterministically stale."
    PRD §2.4: "`version` (integer): starts at 1 on creation and increments by one on every mutation, including mutations caused by cascades and derived-field recomputation."

    Design: Corner/cross_cutting_layers/occ_correct_version_succeeds_and_bumps
    """
    ctx = setup_billing_ready()
    dept_id, firm_id = ctx["dept"]["id"], ctx["firm"]["id"]
    v_before = ctx["matter_version"]
    submit_invoice(
        dept_id, ctx["matter"]["id"], firm_id, v_before,
        [clean_line(ctx["timekeeper"]["id"], "L110", 1.00, 100_000)],
        invoice_number="INV-OCC-OK",
    )
    v_after = get_matter(dept_id, ctx["matter"]["id"])["version"]
    assert v_after == v_before + 1, (
        f"invoice creation must advance the matter version by exactly 1: {v_before} -> {v_after}"
    )


def test_legal_ops_reviewer_cannot_submit_invoice(api, legal_ops_headers):
    """PRD §3.5: "Billing enters the system when a `PanelFirmUser` submits an invoice against an `ENGAGED` matter."
    PRD §2.1: "Write operations are restricted per endpoint, and a caller whose role is not permitted on an endpoint is rejected with `ERR_FORBIDDEN`."

    Design: Corner/rbac/legal_ops_reviewer_cannot_submit_invoice
    """
    ctx = setup_billing_ready()
    dept_id = ctx["dept"]["id"]
    resp = api.create_invoice(
        dept_id, ctx["matter"]["id"],
        create_invoice_payload(
            invoice_number="INV-RBAC",
            expected_matter_version=ctx["matter_version"],
            line_items=[clean_line(ctx["timekeeper"]["id"], "L110", 1.00, 100_000)],
        ),
        legal_ops_headers,
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
