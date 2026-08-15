"""Draw lifecycle: submit guards, invalid transitions, revision cycle, overlap."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_draw,
    add_work_line_item,
    create_draw,
    get_draw,
    make_borrower_headers,
    setup_funded_scenario,
    setup_loan_with_lines,
    start_review_draw,
    submit_draw,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["lender_admin_headers"]
PROCESSOR = TEST_USERS["draw_processor_headers"]


def _draft_with_line(sc, requested=100_000, period=("2026-03-01", "2026-03-31")):
    draw = create_draw(sc["loan"]["id"], sc["borrower"]["id"],
                       period_start=period[0], period_end=period[1])
    item = add_work_line_item(draw["id"], sc["lines"]["SITE"]["id"], requested,
                              sc["borrower"]["id"])
    return draw, item


def _under_review_draw(sc, requested=100_000, period=("2026-03-01", "2026-03-31")):
    draw, item = _draft_with_line(sc, requested=requested, period=period)
    submit_draw(draw["id"], sc["borrower"]["id"])
    start_review_draw(draw["id"])
    return draw


class TestSubmitGuards:
    def test_draw_submit_without_lines_rejected(self, api):
        """PRD §3.3: "Two guards apply, in order: the draw must contain at least
        one line item, or submission fails with `ERR_DRAW_HAS_NO_LINES`
        (HTTP 422)".

        Design: Corner/state_machines/draw_submit_without_lines_rejected
        """
        sc = setup_loan_with_lines()
        draw = create_draw(sc["loan"]["id"], sc["borrower"]["id"])

        resp = api.submit_draw(draw["id"],
                               make_borrower_headers(sc["borrower"]["id"]))
        validate_error(resp, ApiErrorId.ERR_DRAW_HAS_NO_LINES)
        assert get_draw(draw["id"])["status"] == "DRAFT", (
            "A draw that fails the line-item guard stays DRAFT"
        )


class TestInvalidTransitions:
    def test_draw_start_review_from_draft_rejected(self, api):
        """PRD §3.5: "Once a draw is `SUBMITTED`, a `DrawProcessor` takes it up,
        moving it from `SUBMITTED` to `UNDER_REVIEW`."
        PRD §2.6: "A transition attempted from any other state — including from an
        already-terminal state — is rejected with `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/draw_start_review_from_draft_rejected
        """
        sc = setup_loan_with_lines()
        draw = create_draw(sc["loan"]["id"], sc["borrower"]["id"])

        resp = api.start_review_draw(draw["id"], PROCESSOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_draw(draw["id"])["status"] == "DRAFT"

    def test_draw_withdraw_from_under_review_rejected(self, api):
        """PRD §3.3: "The borrower may instead abandon the draw: withdrawal moves a
        `DRAFT`, `SUBMITTED`, or `REVISION_REQUESTED` draw to the terminal
        `WITHDRAWN` state."
        PRD §2.6: "A transition attempted from any other state — including from an
        already-terminal state — is rejected with `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/draw_withdraw_from_under_review_rejected
        """
        sc = setup_loan_with_lines()
        draw = _under_review_draw(sc)

        resp = api.withdraw_draw(draw["id"],
                                 make_borrower_headers(sc["borrower"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_draw(draw["id"])["status"] == "UNDER_REVIEW"

    def test_draw_funded_terminal_lockdown(self, api):
        """PRD §3.5: "The draw's `funded_total_cents` becomes the sum of its items'
        `funded_cents`, and the draw settles into the terminal `FUNDED` state."
        PRD §2.6: "A transition attempted from any other state — including from an
        already-terminal state — is rejected with `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/draw_funded_terminal_lockdown
        """
        sc = setup_funded_scenario()
        draw = sc["draw"]
        assert draw["status"] == "FUNDED"

        resp = api.request_revision_draw(
            draw["id"], {"revision_notes": "too late"}, PROCESSOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = get_draw(draw["id"])
        assert after["status"] == "FUNDED", "FUNDED is terminal"
        assert after["revision_notes"] is None, (
            "The rejected transition records no revision_notes"
        )


class TestRevisionCycle:
    def test_revision_cycle_records_notes_and_allows_edits(self, api):
        """PRD §3.5: "Sending it back for revision moves it to `REVISION_REQUESTED`
        and records the supplied `revision_notes` on the draw".
        PRD §3.3: "While the draw is `DRAFT` — or later, while it sits in
        `REVISION_REQUESTED` — the borrower builds it up with line items."

        Design: Difficulty/non_linear_state_machine/draw_revision_cycle_resubmit
        """
        sc = setup_loan_with_lines()
        draw, _item = _draft_with_line(sc, requested=5_000_000)
        submit_draw(draw["id"], sc["borrower"]["id"])
        start_review_draw(draw["id"])

        revised = validate_success(api.request_revision_draw(
            draw["id"], {"revision_notes": "Add roofing line"}, PROCESSOR), 200)
        assert revised["status"] == "REVISION_REQUESTED"
        assert revised["revision_notes"] == "Add roofing line", (
            "The supplied revision_notes are recorded on the draw"
        )

        # The mutable window is open again: a line item can be added.
        item2 = validate_success(api.create_draw_line_item(
            {
                "draw_id": draw["id"],
                "budget_line_id": sc["lines"]["SITE"]["id"],
                "line_type": "WORK_COMPLETED",
                "requested_cents": 2_500_000,
            },
            make_borrower_headers(sc["borrower"]["id"]),
        ), 201)
        assert item2["requested_cents"] == 2_500_000

    def test_revision_cycle_resubmit_closes_cycle(self, api):
        """PRD §3.5: "the borrower then edits line items and documents and
        resubmits, closing the cycle `UNDER_REVIEW` → `REVISION_REQUESTED` →
        `SUBMITTED`, with the earlier `revision_notes` retained on the draw for
        audit."
        PRD §3.3: "Every line-item addition recomputes the draw's
        `requested_total_cents` as the sum of its items' `requested_cents`."

        Design: Difficulty/non_linear_state_machine/draw_revision_cycle_resubmit
        """
        sc = setup_loan_with_lines()
        draw, _item = _draft_with_line(sc, requested=5_000_000)
        submit_draw(draw["id"], sc["borrower"]["id"])
        start_review_draw(draw["id"])
        validate_success(api.request_revision_draw(
            draw["id"], {"revision_notes": "Add roofing line"}, PROCESSOR), 200)
        add_work_line_item(draw["id"], sc["lines"]["SITE"]["id"], 2_500_000,
                           sc["borrower"]["id"])

        resubmitted = validate_success(api.submit_draw(
            draw["id"], make_borrower_headers(sc["borrower"]["id"])), 200)
        assert resubmitted["status"] == "SUBMITTED", "Resubmission closes the cycle"
        assert resubmitted["requested_total_cents"] == 7_500_000, (
            "requested_total_cents is the sum of both line items"
        )
        assert resubmitted["revision_notes"] == "Add roofing line", (
            "revision_notes is retained on the draw for audit"
        )

        again = validate_success(api.start_review_draw(draw["id"], PROCESSOR), 200)
        assert again["status"] == "UNDER_REVIEW", "The cycle can repeat"


class TestPeriodOverlap:
    def _setup_three_draws(self):
        sc = setup_loan_with_lines()
        draw_a, _ = _draft_with_line(sc, requested=100_000,
                                     period=("2026-03-01", "2026-03-31"))
        submit_draw(draw_a["id"], sc["borrower"]["id"])
        draw_b, _ = _draft_with_line(sc, requested=100_000,
                                     period=("2026-03-31", "2026-04-30"))
        draw_c, _ = _draft_with_line(sc, requested=100_000,
                                     period=("2026-03-15", "2026-04-15"))
        return sc, draw_a, draw_b, draw_c

    def test_draw_period_adjacent_submit_allowed(self, api):
        """PRD §3.3: "Periods are half-open intervals: two periods overlap when the
        new period's `period_start_date` falls before the sibling's
        `period_end_date` and the sibling's `period_start_date` falls before the
        new period's `period_end_date`. Adjacency is allowed — a new period whose
        `period_start_date` equals a sibling's `period_end_date` touches but does
        not overlap it."

        Design: Difficulty/resource_temporal_overlap/draw_period_half_open_overlap
        """
        sc, _a, draw_b, _c = self._setup_three_draws()

        resp = api.submit_draw(draw_b["id"],
                               make_borrower_headers(sc["borrower"]["id"]))
        submitted = validate_success(resp, 200)
        assert submitted["status"] == "SUBMITTED", (
            "A period starting exactly at the sibling's end touches but does "
            "not overlap it"
        )

    def test_draw_period_interior_overlap_rejected(self, api):
        """PRD §3.3: "its billing period must not collide with a sibling draw of
        the same loan that sits in `SUBMITTED`, `UNDER_REVIEW`,
        `REVISION_REQUESTED`, `APPROVED`, or `FUNDED`."
        PRD §3.3: "A genuine collision is rejected with `ERR_DRAW_PERIOD_OVERLAP`
        (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/draw_period_half_open_overlap
        """
        sc, _a, draw_b, draw_c = self._setup_three_draws()
        submit_draw(draw_b["id"], sc["borrower"]["id"])

        resp = api.submit_draw(draw_c["id"],
                               make_borrower_headers(sc["borrower"]["id"]))
        validate_error(resp, ApiErrorId.ERR_DRAW_PERIOD_OVERLAP)
        assert get_draw(draw_c["id"])["status"] == "DRAFT", (
            "The colliding draw stays DRAFT"
        )
