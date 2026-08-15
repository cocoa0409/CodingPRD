"""Draw intake: creation defaults, field validation, fiscal caps, listing."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_budget_line,
    add_work_line_item,
    assert_draw_request,
    create_borrower,
    create_draw,
    create_draw_payload,
    create_loan,
    get_loan,
    make_borrower_headers,
    setup_loan_with_lines,
    submit_draw,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["lender_admin_headers"]


class TestDrawCreationDefaults:
    def test_draw_initial_state_draft(self, api):
        """PRD §3.3: "The server stamps the draw with a `draw_number`, a per-loan
        monotone sequence that starts at 1, assigns each new draw the highest
        existing number on that loan plus one, and is never reused even if a draw
        is later withdrawn or rejected. A new draw sits in `DRAFT`; its
        `requested_total_cents`, `approved_total_cents`, `retainage_total_cents`,
        and `funded_total_cents` all start at 0, `revision_notes` and
        `rejection_reason` start null, `effective_retainage_pct` starts null, and
        `milestone_applied` starts false."

        Design: Corner/state_machines/draw_initial_state_draft
        """
        sc = setup_loan_with_lines()
        resp = api.create_draw(
            create_draw_payload(sc["loan"]["id"], period_start_date="2026-03-01",
                                period_end_date="2026-03-31"),
            make_borrower_headers(sc["borrower"]["id"]),
        )
        draw = validate_success(resp, 201)
        assert_draw_request(draw)
        assert draw["status"] == "DRAFT", "A new draw sits in DRAFT"
        assert draw["draw_number"] == 1, "First draw of the loan is numbered 1"
        assert draw["requested_total_cents"] == 0
        assert draw["approved_total_cents"] == 0
        assert draw["retainage_total_cents"] == 0
        assert draw["funded_total_cents"] == 0
        assert draw["revision_notes"] is None
        assert draw["effective_retainage_pct"] is None
        assert draw["milestone_applied"] is False


class TestLineItemValidation:
    def _draft_draw(self, api):
        sc = setup_loan_with_lines()
        draw = create_draw(sc["loan"]["id"], sc["borrower"]["id"])
        return sc, draw

    def test_draw_line_item_missing_required_field(self, api):
        """PRD §2.8: "A missing required field, an invalid enum value, or a
        non-positive amount anywhere in a request body is a structural failure
        reported as `ERR_INVALID_REQUEST` (HTTP 400)."
        PRD §3.3: "A line item names its `draw_id`, the `budget_line_id` it
        charges against, a `line_type` of `WORK_COMPLETED` or `STORED_MATERIALS`,
        and a positive `requested_cents`."

        Design: Corner/entities/draw_line_item_missing_required_field
        """
        sc, draw = self._draft_draw(api)
        payload = {
            "draw_id": draw["id"],
            "budget_line_id": sc["lines"]["SITE"]["id"],
            "line_type": "WORK_COMPLETED",
        }
        resp = api.create_draw_line_item(
            payload, make_borrower_headers(sc["borrower"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_stored_materials_evidence_required(self, api):
        """PRD §3.3: "`stored_material_invoice_cents` (the invoice value of the
        stored materials), `insurance_certificate_ref` (the insurance evidence
        reference), and `stored_location` (where the materials sit) are all
        required whenever `line_type` is `STORED_MATERIALS`, and their absence
        yields `ERR_STORED_MATERIALS_EVIDENCE_MISSING` (HTTP 422)."

        Design: Corner/entities/stored_materials_evidence_required
        """
        sc = setup_loan_with_lines(
            line_specs=(("MATS", "Materials", 1_000_000, False),))
        draw = create_draw(sc["loan"]["id"], sc["borrower"]["id"])
        payload = {
            "draw_id": draw["id"],
            "budget_line_id": sc["lines"]["MATS"]["id"],
            "line_type": "STORED_MATERIALS",
            "requested_cents": 200_000,
            "stored_material_invoice_cents": 200_000,
            "stored_location": "Bonded warehouse, Lot 9",
            # insurance_certificate_ref intentionally omitted
        }
        resp = api.create_draw_line_item(
            payload, make_borrower_headers(sc["borrower"]["id"]))
        validate_error(resp, ApiErrorId.ERR_STORED_MATERIALS_EVIDENCE_MISSING)

    def test_stored_fields_forbidden_on_work_line(self, api):
        """PRD §3.3: "Those same three fields are forbidden on a `WORK_COMPLETED`
        line — their presence there is `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/stored_fields_forbidden_on_work_line
        """
        sc, draw = self._draft_draw(api)
        payload = {
            "draw_id": draw["id"],
            "budget_line_id": sc["lines"]["SITE"]["id"],
            "line_type": "WORK_COMPLETED",
            "requested_cents": 100_000,
            "insurance_certificate_ref": "CERT-1",
        }
        resp = api.create_draw_line_item(
            payload, make_borrower_headers(sc["borrower"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestBudgetAndPeriodValidation:
    def test_draw_period_invalid_rejected(self, api):
        """PRD §3.3: "Creating one names the `loan_id` and the billing period as
        `period_start_date` and `period_end_date` — both ISO dates, start inclusive
        and end exclusive — and the end must fall strictly after the start, or the
        create is rejected with `ERR_DRAW_PERIOD_INVALID` (HTTP 422)."

        Design: Corner/validations/draw_period_invalid_rejected
        """
        sc = setup_loan_with_lines()
        resp = api.create_draw(
            create_draw_payload(sc["loan"]["id"], period_start_date="2026-03-31",
                                period_end_date="2026-03-31"),
            make_borrower_headers(sc["borrower"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DRAW_PERIOD_INVALID)

    def test_duplicate_cost_code_rejected(self, api):
        """PRD §3.2: "Within one loan a `cost_code` may be used only once; a
        duplicate is rejected with `ERR_DUPLICATE_COST_CODE` (HTTP 409)."

        Design: Corner/validations/duplicate_cost_code_rejected
        """
        borrower = create_borrower()
        loan1 = create_loan(borrower["id"], commitment_amount_cents=100_000_000)
        loan2 = create_loan(borrower["id"], commitment_amount_cents=100_000_000)
        add_budget_line(loan1["id"], cost_code="SITE",
                        original_amount_cents=1_000_000)

        dup = api.create_budget_line(
            {
                "loan_id": loan1["id"],
                "cost_code": "SITE",
                "description": "Duplicate",
                "original_amount_cents": 500_000,
            },
            ADMIN,
        )
        validate_error(dup, ApiErrorId.ERR_DUPLICATE_COST_CODE)

        other_loan = api.create_budget_line(
            {
                "loan_id": loan2["id"],
                "cost_code": "SITE",
                "description": "Fine on another loan",
                "original_amount_cents": 500_000,
            },
            ADMIN,
        )
        validate_success(other_loan, 201)

    def test_commitment_exceeded_rejected(self, api):
        """PRD §3.2: "The commitment is a hard ceiling: the sum of
        `original_amount_cents` across all of a loan's budget lines may never
        exceed the loan's `commitment_amount_cents`. A line whose addition would
        break that ceiling is rejected with `ERR_COMMITMENT_EXCEEDED` (HTTP 422)."

        Design: Corner/validations/commitment_exceeded_rejected
        """
        borrower = create_borrower()
        loan = create_loan(borrower["id"], commitment_amount_cents=100_000_000)
        add_budget_line(loan["id"], cost_code="SITE",
                        original_amount_cents=90_000_000)

        resp = api.create_budget_line(
            {
                "loan_id": loan["id"],
                "cost_code": "FRAM",
                "description": "Framing",
                "original_amount_cents": 20_000_000,
            },
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_COMMITMENT_EXCEEDED)

        loan_after = get_loan(loan["id"])
        assert loan_after["total_original_budget_cents"] == 90_000_000, (
            "The rejected line must not enter the loan's original-budget total"
        )


class TestOwnership:
    def test_borrower_ownership_mismatch_forbidden(self, api):
        """PRD §2.1: "When `X-User-Role` is `Borrower`, `X-User-ID` is the `id` of
        the acting Borrower record; ownership checks on any resource that traces
        back to a loan compare the loan's `borrower_id` against `X-User-ID`, and a
        mismatch on a borrower-only write is rejected with
        `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."

        Design: Corner/validations/borrower_ownership_mismatch_forbidden
        """
        borrower_a = create_borrower()
        borrower_b = create_borrower(legal_name="Beta Homes Inc",
                                     contact_email="b@beta.example",
                                     entity_type="CORPORATION")
        loan = create_loan(borrower_a["id"], commitment_amount_cents=100_000_000)

        resp = api.create_draw(
            create_draw_payload(loan["id"], period_start_date="2026-03-01",
                                period_end_date="2026-03-31"),
            make_borrower_headers(borrower_b["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

        _rows, meta = validate_paginated(
            api.list_draws(ADMIN, params={"loan_id": loan["id"]}))
        assert meta["total_count"] == 0, "No draw may be persisted by the foreign borrower"


class TestCrossLoanReferences:
    def test_budget_line_loan_mismatch_rejected(self, api):
        """PRD §3.3: "The referenced budget line must belong to the same loan as
        the draw; a cross-loan reference is rejected with
        `ERR_BUDGET_LINE_LOAN_MISMATCH` (HTTP 422)."

        Design: Corner/errors/budget_line_loan_mismatch_rejected
        """
        borrower = create_borrower()
        loan1 = create_loan(borrower["id"], commitment_amount_cents=100_000_000)
        loan2 = create_loan(borrower["id"], commitment_amount_cents=100_000_000)
        line_x = add_budget_line(loan2["id"], cost_code="SITE",
                                 original_amount_cents=1_000_000)
        draw = create_draw(loan1["id"], borrower["id"])

        resp = api.create_draw_line_item(
            {
                "draw_id": draw["id"],
                "budget_line_id": line_x["id"],
                "line_type": "WORK_COMPLETED",
                "requested_cents": 100_000,
            },
            make_borrower_headers(borrower["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_BUDGET_LINE_LOAN_MISMATCH)

        _items, meta = validate_paginated(
            api.list_draw_line_items(ADMIN, params={"draw_id": draw["id"]}))
        assert meta["total_count"] == 0, "The mismatched line item must not persist"


class TestDrawListing:
    def test_draws_list_pagination(self, api):
        """PRD §2.3: "List endpoints accept two query parameters: `limit` and
        `offset`. `limit` defaults to 10, with a minimum of 1 and a maximum of 100;
        `offset` defaults to 0. Results are always sorted by `created_at` in
        ascending order. The `meta` object of every list response carries four
        pagination fields: `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/draws_list_pagination
        """
        sc = setup_loan_with_lines()
        d1 = create_draw(sc["loan"]["id"], sc["borrower"]["id"],
                         period_start="2026-03-01", period_end="2026-03-31")
        d2 = create_draw(sc["loan"]["id"], sc["borrower"]["id"],
                         period_start="2026-04-01", period_end="2026-04-30")

        page1, meta1 = validate_paginated(api.list_draws(
            ADMIN, params={"loan_id": sc["loan"]["id"], "limit": 1, "offset": 0}))
        assert len(page1) == 1
        assert meta1["total_count"] == 2
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(api.list_draws(
            ADMIN, params={"loan_id": sc["loan"]["id"], "limit": 1, "offset": 1}))
        assert len(page2) == 1
        assert meta2["has_more"] is False
        assert {page1[0]["id"], page2[0]["id"]} == {d1["id"], d2["id"]}, (
            "The two pages return the two distinct draws"
        )

    def test_draws_list_filter_by_status(self, api):
        """PRD §3.3: "draws themselves with optional `loan_id` and `status`
        filters."

        Design: Corner/endpoints/draws_list_filter_by_status
        """
        sc = setup_loan_with_lines()
        d1 = create_draw(sc["loan"]["id"], sc["borrower"]["id"],
                         period_start="2026-03-01", period_end="2026-03-31")
        add_work_line_item(d1["id"], sc["lines"]["SITE"]["id"], 100_000,
                           sc["borrower"]["id"])
        submit_draw(d1["id"], sc["borrower"]["id"])
        d2 = create_draw(sc["loan"]["id"], sc["borrower"]["id"],
                         period_start="2026-04-01", period_end="2026-04-30")

        drafts, meta_d = validate_paginated(api.list_draws(
            ADMIN, params={"loan_id": sc["loan"]["id"], "status": "DRAFT"}))
        assert meta_d["total_count"] == 1
        assert drafts[0]["id"] == d2["id"], "status=DRAFT returns only the draft"

        submitted, meta_s = validate_paginated(api.list_draws(
            ADMIN, params={"loan_id": sc["loan"]["id"], "status": "SUBMITTED"}))
        assert meta_s["total_count"] == 1
        assert submitted[0]["id"] == d1["id"], (
            "status=SUBMITTED returns only the submitted draw"
        )
