"""Invoicing: allowable reimbursement variants, caps, prompt-pay, ytd cascade."""
from test_helpers import (
    ORDER_TYPE_TO_ITEM_CODE,
    ApiErrorId,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import create_expense_line_payload
from test_helpers.fixtures import (
    add_expense_line,
    approve_work_order,
    assign_work_order,
    complete_work_order,
    create_work_order,
    get_invoice_for_work_order,
    set_clock,
    setup_completed_order_with_invoice,
    setup_portfolio,
    start_work_order,
    submit_work_order,
    upload_minimum_photos,
)
from test_helpers.test_users import TEST_USERS, make_servicer_headers

ADMIN = TEST_USERS["vendor_admin_headers"]


def _completed_invoice_with_lines(api, ctx, order_type, line_prices, date, due_date,
                                  hash_prefix, drive_to="DRAFT"):
    """One completed order + auto-created invoice with one line per price.

    drive_to: "DRAFT" (lines added only), "SUBMITTED", or "APPROVED".
    Returns the invoice id."""
    wo = create_work_order(ctx["property_id"], ctx["servicer_id"],
                           order_type=order_type, due_date=due_date)
    assign_work_order(wo["id"], ctx["crew_id"], scheduled_date=date)
    start_work_order(wo["id"], ctx["crew_id"])
    upload_minimum_photos(wo["id"], order_type, ctx["crew_id"], date=date,
                          hash_prefix=hash_prefix)
    submit_work_order(wo["id"], ctx["crew_id"], sum(line_prices))
    approve_work_order(wo["id"])
    complete_work_order(wo["id"])
    inv = get_invoice_for_work_order(wo["id"])
    item_code = ORDER_TYPE_TO_ITEM_CODE[order_type]
    for price in line_prices:
        add_expense_line(inv["id"], item_code=item_code, unit_price_cents=price)
    if drive_to in ("SUBMITTED", "APPROVED"):
        validate_success(api.submit_invoice(inv["id"], ADMIN))
    if drive_to == "APPROVED":
        validate_success(api.approve_invoice(inv["id"], make_servicer_headers(ctx["servicer_id"])))
    return inv["id"]


class TestProvisionalVsFinalAllowable:
    def _setup_three_invoices(self, api):
        """FHA/GRASS_CUT (per-occurrence 3000, 2 occurrences/yr, aggregate 10000/yr);
        i1 APPROVED at 3000, i2 SUBMITTED at 3000, i3 DRAFT at 3000."""
        ctx = setup_portfolio(item_code="GRASS_CUT", allowable_overrides={
            "max_per_occurrence_cents": 3000, "max_occurrences_per_calendar_year": 2,
            "aggregate_cap_cents_per_property_year": 10000, "requires_bid_over_cents": 999999},
            clock="2026-03-01T00:00:00Z")
        i1 = _completed_invoice_with_lines(api, ctx, "GRASS_CUT", [3000],
                                           "2026-03-02", "2026-03-10", "pf1", "APPROVED")
        i2 = _completed_invoice_with_lines(api, ctx, "GRASS_CUT", [3000],
                                           "2026-03-03", "2026-03-12", "pf2", "SUBMITTED")
        i3 = _completed_invoice_with_lines(api, ctx, "GRASS_CUT", [3000],
                                           "2026-03-04", "2026-03-14", "pf3", "DRAFT")
        return ctx, i1, i2, i3

    def test_provisional_counts_pending_submission(self, api):
        """PRD: "The two variants differ only in the inclusion set: the provisional
        variant counts invoices in `SUBMITTED`, `APPROVED`, `PARTIALLY_APPROVED`,
        and `PAID` — a conservative posture that holds not-yet-approved submissions
        against the caps" and "The line's eligible units are the smaller of its
        `quantity` and the remaining occurrence allowance — the snapshot's
        `max_occurrences_per_calendar_year` minus the consumed units, floored at
        zero."

        Design: Difficulty/dual_variant_calc/invoice_allowable_provisional_vs_final
        """
        _ctx, _i1, _i2, i3 = self._setup_three_invoices(api)
        submitted = validate_success(api.submit_invoice(i3, ADMIN))
        assert submitted["provisional_allowed_cents"] == 0, (
            "PROVISIONAL counts the SUBMITTED sibling: 2 occurrences already used, "
            f"got {submitted['provisional_allowed_cents']}")

    def test_final_counts_only_settled_invoices(self, api):
        """PRD: "the final variant counts only settled invoices in `APPROVED`,
        `PARTIALLY_APPROVED`, and `PAID`, so the final figure can diverge from the
        provisional one when another of the property's invoices is still awaiting
        review."

        Design: Difficulty/dual_variant_calc/invoice_allowable_provisional_vs_final
        """
        ctx, _i1, _i2, i3 = self._setup_three_invoices(api)
        validate_success(api.submit_invoice(i3, ADMIN))
        approved = validate_success(api.approve_invoice(i3, make_servicer_headers(ctx["servicer_id"])))
        assert approved["approved_amount_cents"] == 3000, (
            "FINAL counts only the settled sibling (1 occurrence used), "
            f"got {approved['approved_amount_cents']}")
        assert approved["status"] == "APPROVED"


class TestAggregateCapBoundary:
    def _setup_cap_boundary(self, api):
        """FHA/GRASS_CUT (per-occurrence 3000, 10 occurrences/yr, aggregate
        10000/yr); i1 lines 3000+3000+1000 APPROVED (7000 consumed); i2 one
        3000-cent line SUBMITTED."""
        ctx = setup_portfolio(item_code="GRASS_CUT", allowable_overrides={
            "max_per_occurrence_cents": 3000, "max_occurrences_per_calendar_year": 10,
            "aggregate_cap_cents_per_property_year": 10000, "requires_bid_over_cents": 999999})
        _completed_invoice_with_lines(api, ctx, "GRASS_CUT", [3000, 3000, 1000],
                                      "2026-08-02", "2026-08-06", "cap1", "APPROVED")
        i2 = _completed_invoice_with_lines(api, ctx, "GRASS_CUT", [3000],
                                           "2026-08-03", "2026-08-09", "cap2", "SUBMITTED")
        return ctx, i2

    def test_aggregate_cap_exact_boundary_approved_in_full(self, api):
        """PRD: "The remaining item budget is the snapshot's
        `aggregate_cap_cents_per_property_year` minus the consumed cents, floored at
        zero. The line's `allowed_cents` is the smaller of two figures: its eligible
        units times the lesser of its `unit_price_cents` and the snapshot's
        `max_per_occurrence_cents`, and the remaining item budget." and "the invoice
        lands `APPROVED` when the approved amount equals the `claimed_total_cents`".

        Design: Difficulty/boundary_precision_check/allowable_aggregate_cap_exact_boundary
        """
        ctx, i2 = self._setup_cap_boundary(api)
        approved = validate_success(api.approve_invoice(i2, make_servicer_headers(ctx["servicer_id"])))
        assert approved["approved_amount_cents"] == 3000, (
            f"exact remaining budget (10000 - 7000) approves in full, got {approved['approved_amount_cents']}")
        assert approved["status"] == "APPROVED"

    def test_aggregate_cap_exact_boundary_line_fully_allowed(self, api):
        """PRD: "a fully allowed line carries no denial reason."

        Design: Difficulty/boundary_precision_check/allowable_aggregate_cap_exact_boundary
        """
        ctx, i2 = self._setup_cap_boundary(api)
        validate_success(api.approve_invoice(i2, make_servicer_headers(ctx["servicer_id"])))
        lines, _meta = validate_paginated(api.list_invoice_lines(i2, ADMIN))
        assert lines[0]["allowed_cents"] == 3000
        assert lines[0]["denial_reason"] is None, "exact-boundary line is fully allowed"


class TestPromptPayRounding:
    def _setup_two_line_invoice(self, api):
        """DEBRIS_REMOVAL completed order; invoice lines 3333 and 3335; SUBMITTED."""
        ctx = setup_portfolio(item_code="DEBRIS_REMOVAL", allowable_overrides={
            "max_per_occurrence_cents": 100000, "max_occurrences_per_calendar_year": 20,
            "aggregate_cap_cents_per_property_year": 1000000, "requires_bid_over_cents": 999999})
        inv = _completed_invoice_with_lines(api, ctx, "DEBRIS_REMOVAL", [3333, 3335],
                                            "2026-08-02", "2026-08-10", "pp", "SUBMITTED")
        return ctx, inv

    def test_prompt_pay_discount_per_line_rounding(self, api):
        """PRD: "Each line's `line_discount_cents` is two percent of its
        `allowed_cents`, rounded half up to whole cents; the invoice's
        `prompt_pay_discount_cents` is the sum of those per-line discounts" and
        "Computing two percent on the invoice total instead yields a different cent
        value and is non-conformant."

        Design: Difficulty/combinatorial_formula/prompt_pay_discount_per_line_rounding
        """
        ctx, inv = self._setup_two_line_invoice(api)
        approved = validate_success(api.approve_invoice(inv, make_servicer_headers(ctx["servicer_id"])))
        assert approved["approved_amount_cents"] == 6668
        assert approved["prompt_pay_discount_cents"] == 134, (
            f"per-line round_half_up(66.66)=67 and round_half_up(66.70)=67 sum to 134, "
            f"got {approved['prompt_pay_discount_cents']}")
        lines, _meta = validate_paginated(api.list_invoice_lines(inv, ADMIN))
        for line in lines:
            assert line["line_discount_cents"] == 67, (
                f"each line rounds half up to 67, got {line['line_discount_cents']}")

    def test_prompt_pay_payable_amount(self, api):
        """PRD: "its `payable_amount_cents` is the approved amount minus the
        discount."

        Design: Difficulty/combinatorial_formula/prompt_pay_discount_per_line_rounding
        """
        ctx, inv = self._setup_two_line_invoice(api)
        approved = validate_success(api.approve_invoice(inv, make_servicer_headers(ctx["servicer_id"])))
        assert approved["payable_amount_cents"] == 6534, (
            f"6668 - 134 = 6534, got {approved['payable_amount_cents']}")
        assert approved["status"] == "APPROVED"


class TestYtdConservedQuantity:
    def _setup_board_up_invoice(self, api, line_price=50000):
        ctx = setup_completed_order_with_invoice(
            order_type="BOARD_UP", unit_price_cents=line_price,
            submitted_cost_cents=line_price,
            allowable_overrides={
                "max_per_occurrence_cents": 100000, "max_occurrences_per_calendar_year": 5,
                "aggregate_cap_cents_per_property_year": 500000,
                "requires_bid_over_cents": 99999999})
        validate_success(api.submit_invoice(ctx["invoice_id"], ADMIN))
        return ctx

    def test_ytd_invariant_approve_adds_exactly(self, api):
        """PRD: "The year-to-date counter obeys a conserved-quantity invariant:
        approval adds exactly `approved_amount_cents`".

        Design: Difficulty/compensating_invariant/invoice_approve_void_ytd_invariant
        """
        ctx = self._setup_board_up_invoice(api)
        pre = validate_success(api.get_property(ctx["property_id"], ADMIN))
        assert pre["ytd_investor_approved_cents"] == 0
        approved = validate_success(api.approve_invoice(
            ctx["invoice_id"], make_servicer_headers(ctx["servicer_id"])))
        assert approved["approved_amount_cents"] == 50000
        mid = validate_success(api.get_property(ctx["property_id"], ADMIN))
        assert mid["ytd_investor_approved_cents"] == 50000, (
            f"approve adds exactly 50000, got {mid['ytd_investor_approved_cents']}")

    def test_ytd_invariant_void_reverses(self, api):
        """PRD: "voiding or appealing removes exactly the same amount, and an
        approve-then-void pair leaves `ytd_investor_approved_cents` unchanged."

        Design: Difficulty/compensating_invariant/invoice_approve_void_ytd_invariant
        """
        ctx = self._setup_board_up_invoice(api)
        validate_success(api.approve_invoice(ctx["invoice_id"],
                                             make_servicer_headers(ctx["servicer_id"])))
        validate_success(api.void_invoice(ctx["invoice_id"], {"reason": "duplicate submission"},
                                          make_servicer_headers(ctx["servicer_id"])))
        post = validate_success(api.get_property(ctx["property_id"], ADMIN))
        assert post["ytd_investor_approved_cents"] == 0, (
            f"approve+void conserves the counter at 0, got {post['ytd_investor_approved_cents']}")


class TestYtdReviewFlagCascade:
    def _setup_flag_scenario(self, api):
        """i1 150000 APPROVED, i2 60000 APPROVED (ytd 210000 crosses 200000),
        i3 DRAFT with a 1000-cent line. Returns (ctx, i1, i2, i3, prop_mid)."""
        ctx = setup_portfolio(item_code="BOARD_UP", allowable_overrides={
            "max_per_occurrence_cents": 210000, "max_occurrences_per_calendar_year": 5,
            "aggregate_cap_cents_per_property_year": 2000000,
            "requires_bid_over_cents": 99999999},
            property_overrides={"heating_system": "NONE", "fixture_count": 4})
        i1 = _completed_invoice_with_lines(api, ctx, "BOARD_UP", [150000],
                                           "2026-08-02", "2026-08-10", "fl1", "APPROVED")
        prop_mid = validate_success(api.get_property(ctx["property_id"], ADMIN))
        i2 = _completed_invoice_with_lines(api, ctx, "BOARD_UP", [60000],
                                           "2026-08-03", "2026-08-12", "fl2", "APPROVED")
        i3 = _completed_invoice_with_lines(api, ctx, "BOARD_UP", [1000],
                                           "2026-08-04", "2026-08-14", "fl3", "DRAFT")
        return ctx, i1, i2, i3, prop_mid

    def test_ytd_threshold_sets_review_flag(self, api):
        """PRD: "`approved_amount_cents` is added to `ytd_investor_approved_cents`,
        and when the resulting total reaches or exceeds 200,000 cents the property's
        `financial_review_required` is set true".

        Design: Difficulty/transitive_cascade/invoice_approval_ytd_review_flag_depth2
        """
        ctx, _i1, _i2, _i3, prop_mid = self._setup_flag_scenario(api)
        assert prop_mid["ytd_investor_approved_cents"] == 150000
        assert prop_mid["financial_review_required"] is False, "below threshold after first approve"
        prop_end = validate_success(api.get_property(ctx["property_id"], ADMIN))
        assert prop_end["ytd_investor_approved_cents"] == 210000
        assert prop_end["financial_review_required"] is True, (
            "the second approve's ytd mutation crossed 200000 and set the flag")

    def test_review_flag_blocks_submit_until_cleared(self, api):
        """PRD: "blocking further invoice submission until a `VendorAdmin` clears
        the flag through the property's clear-financial-review capability" and
        "requires the property's `financial_review_required` flag to be false
        (`ERR_FINANCIAL_REVIEW_REQUIRED`)".

        Design: Difficulty/transitive_cascade/invoice_approval_ytd_review_flag_depth2
        """
        ctx, _i1, _i2, i3, _mid = self._setup_flag_scenario(api)
        blocked = api.submit_invoice(i3, ADMIN)
        validate_error(blocked, ApiErrorId.ERR_FINANCIAL_REVIEW_REQUIRED)
        validate_success(api.clear_financial_review(ctx["property_id"], ADMIN))
        submitted = validate_success(api.submit_invoice(i3, ADMIN))
        assert submitted["status"] == "SUBMITTED", "submission succeeds once the flag is cleared"


class TestAllowableSnapshotPinning:
    def test_version_pinning_allowable_snapshot(self, api):
        """PRD: "Thereafter the schedule row may be updated — such an update
        increments the row's `version` — but existing work orders keep their pinned
        snapshot, and all downstream invoice math for those orders reads the
        snapshot, never the live row." and "A curtailed line records the first
        applicable `denial_reason`: `PER_OCCURRENCE_CAP` when the per-occurrence
        unit-price cap bound" and "the invoice lands `APPROVED` when the approved
        amount equals the `claimed_total_cents` and `PARTIALLY_APPROVED`
        otherwise."

        Design: Corner/cross_cutting_layers/version_pinning_allowable_snapshot
        """
        ctx = setup_portfolio(item_code="LOCK_CHANGE", allowable_overrides={
            "max_per_occurrence_cents": 100, "max_occurrences_per_calendar_year": 4,
            "aggregate_cap_cents_per_property_year": 80000, "requires_bid_over_cents": 999999})
        al_v1 = ctx["allowable"]["version"]
        wo = create_work_order(ctx["property_id"], ctx["servicer_id"],
                               order_type="SECURING", due_date="2026-08-08")
        assert wo["investor_allowable_version"] == al_v1, "snapshot pinned at creation"
        assert wo["allowable_cap_cents"] == 100
        patched = validate_success(api.update_investor_allowable(
            ctx["allowable_id"], {"max_per_occurrence_cents": 200}, ADMIN))
        assert patched["version"] == al_v1 + 1, "PATCH bumped the schedule version"
        assign_work_order(wo["id"], ctx["crew_id"], scheduled_date="2026-08-02")
        start_work_order(wo["id"], ctx["crew_id"])
        upload_minimum_photos(wo["id"], "SECURING", ctx["crew_id"], hash_prefix="pin")
        submit_work_order(wo["id"], ctx["crew_id"], 150)
        approve_work_order(wo["id"])
        complete_work_order(wo["id"])
        inv = get_invoice_for_work_order(wo["id"])
        add_expense_line(inv["id"], item_code="LOCK_CHANGE", unit_price_cents=150)
        validate_success(api.submit_invoice(inv["id"], ADMIN))
        approved = validate_success(api.approve_invoice(inv["id"], make_servicer_headers(ctx["servicer_id"])))
        assert approved["approved_amount_cents"] == 100, (
            f"pinned v1 cap 100 applies, not the live 200, got {approved['approved_amount_cents']}")
        assert approved["status"] == "PARTIALLY_APPROVED"
        lines, _meta = validate_paginated(api.list_invoice_lines(inv["id"], ADMIN))
        assert lines[0]["allowed_cents"] == 100
        assert lines[0]["denial_reason"] == "PER_OCCURRENCE_CAP"


class TestApproveResponseConsistency:
    def test_immediate_consistency_approve_response(self, api):
        """PRD: "operations that create or modify a resource will return the created
        or updated resource object in the data field" and "Approval reruns the
        calculation in its final variant, storing the result as
        `approved_amount_cents` and refreshing each line's `allowed_cents`" and "the
        invoice's `prompt_pay_discount_cents` is the sum of those per-line
        discounts, and its `payable_amount_cents` is the approved amount minus the
        discount."

        Design: Corner/consistency_model/immediate_consistency_approve_response
        """
        ctx = setup_completed_order_with_invoice(order_type="GRASS_CUT",
                                                 unit_price_cents=1000,
                                                 submitted_cost_cents=1000)
        validate_success(api.submit_invoice(ctx["invoice_id"], ADMIN))
        approved = validate_success(api.approve_invoice(
            ctx["invoice_id"], make_servicer_headers(ctx["servicer_id"])))
        assert approved["approved_amount_cents"] == 1000
        assert approved["prompt_pay_discount_cents"] == 20
        assert approved["payable_amount_cents"] == 980
        assert approved["status"] == "APPROVED"


class TestInvoiceDraftAndAppealGates:
    def test_expense_line_locked_after_invoice_submit(self, api):
        """PRD: "A `VendorAdmin` builds the claim by adding expense lines to a
        `DRAFT` invoice" — a SUBMITTED invoice is out of state, and "failures
        surface as `ERR_INVALID_STATE`".

        Design: Corner/entities/expense_line_locked_after_invoice_submit
        """
        ctx = setup_completed_order_with_invoice(order_type="GRASS_CUT",
                                                 unit_price_cents=1000,
                                                 submitted_cost_cents=1000)
        validate_success(api.submit_invoice(ctx["invoice_id"], ADMIN))
        resp = api.add_expense_line(ctx["invoice_id"],
                                    create_expense_line_payload(unit_price_cents=500), ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_invoice_submit_without_lines_rejected(self, api):
        """PRD: "Submitting the invoice — `DRAFT → SUBMITTED`, by a `VendorAdmin` —
        requires at least one expense line (`ERR_INVOICE_NO_LINES`)".

        Design: Corner/errors/invoice_submit_without_lines_rejected
        """
        ctx = setup_completed_order_with_invoice(order_type="GRASS_CUT", add_line=False)
        resp = api.submit_invoice(ctx["invoice_id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVOICE_NO_LINES)

    def test_invoice_second_appeal_rejected(self, api):
        """PRD: "Either disappointment may be appealed once by a `VendorAdmin`: from
        `DENIED` or `PARTIALLY_APPROVED` back to `SUBMITTED`, provided the invoice's
        `appeal_round` is still below 1 — a second appeal is rejected with
        `ERR_APPEAL_EXHAUSTED`. Appealing sets `appeal_round` to 1".

        Design: Corner/errors/invoice_second_appeal_rejected
        """
        ctx = setup_completed_order_with_invoice(order_type="GRASS_CUT",
                                                 unit_price_cents=1000,
                                                 submitted_cost_cents=1000)
        inv_id = ctx["invoice_id"]
        validate_success(api.submit_invoice(inv_id, ADMIN))
        svc = make_servicer_headers(ctx["servicer_id"])
        validate_success(api.deny_invoice(inv_id, {"reason": "cost not justified"}, svc))
        appealed = validate_success(api.appeal_invoice(inv_id, ADMIN))
        assert appealed["appeal_round"] == 1
        assert appealed["status"] == "SUBMITTED", "first appeal reopens once"
        validate_success(api.deny_invoice(inv_id, {"reason": "still not justified"}, svc))
        resp = api.appeal_invoice(inv_id, ADMIN)
        validate_error(resp, ApiErrorId.ERR_APPEAL_EXHAUSTED)

    def test_invoice_lines_subresource_returns_array(self, api):
        """PRD: "Lines may be listed under their invoice" and "The line's
        `claimed_cents` is its quantity times its unit price, and the invoice's
        `claimed_total_cents` is the sum of its lines' claimed amounts, recomputed
        as lines are added."

        Design: Corner/endpoints/invoice_lines_subresource_returns_array
        """
        ctx = setup_completed_order_with_invoice(order_type="GRASS_CUT", add_line=False)
        empty, _meta = validate_paginated(api.list_invoice_lines(ctx["invoice_id"], ADMIN))
        assert empty == [], "the auto-created DRAFT invoice initially has no lines"
        add_expense_line(ctx["invoice_id"], item_code="GRASS_CUT", quantity=2,
                         unit_price_cents=400)
        lines, _meta2 = validate_paginated(api.list_invoice_lines(ctx["invoice_id"], ADMIN))
        assert lines[0]["quantity"] == 2
        assert lines[0]["claimed_cents"] == 800, "quantity 2 x 400 cents = 800"
