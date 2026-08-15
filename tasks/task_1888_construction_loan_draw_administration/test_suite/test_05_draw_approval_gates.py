"""Draw approval gates: waiver coverage, staleness, inspection presence, invoices."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    accept_inspection,
    add_draw_documents,
    add_draw,
    add_work_line_item,
    complete_inspection,
    get_draw,
    make_borrower_headers,
    order_inspection,
    progress_draw,
    review_decision_payload,
    setup_loan_with_lines,
    start_review_draw,
    submit_draw,
    validate_error,
    validate_success,
    verify_document,
    attach_document,
)

PROCESSOR = TEST_USERS["draw_processor_headers"]
OFFICER = TEST_USERS["credit_officer_headers"]


def _under_review_with_docs(*, requested=100_000, line_amount=1_000_000,
                            invoice=100_000, waiver=100_000,
                            verify_invoice=True, verify_waiver=True,
                            inspection_pct=None,
                            inspection_scheduled="2026-03-20",
                            inspection_completed="2026-03-21"):
    """Draw in UNDER_REVIEW with configurable verified docs and an optional
    completed/accepted draw inspection. Returns (scenario, draw, docs, inspection).
    """
    sc = setup_loan_with_lines(
        line_specs=(("SITE", "Site work", line_amount, False),))
    draw = add_draw(sc)
    add_work_line_item(draw["id"], sc["lines"]["SITE"]["id"], requested,
                       sc["borrower"]["id"])
    docs = []
    if invoice is not None:
        docs.append(attach_document(draw["id"], "INVOICE", invoice,
                                    sc["borrower"]["id"]))
    if waiver is not None:
        docs.append(attach_document(draw["id"], "LIEN_WAIVER_CONDITIONAL", waiver,
                                    sc["borrower"]["id"]))
    if verify_invoice and invoice is not None:
        verify_document(docs[0]["id"])
    if verify_waiver and waiver is not None:
        verify_document(docs[-1]["id"])
    submit_draw(draw["id"], sc["borrower"]["id"])
    start_review_draw(draw["id"])
    inspection = None
    if inspection_pct is not None:
        inspection = order_inspection(sc["loan"]["id"], inspection_scheduled,
                                      draw_id=draw["id"])
        complete_inspection(inspection["id"], inspection_pct, inspection_completed)
    return sc, draw, docs, inspection


class TestWaiverCoverage:
    def test_waiver_coverage_excludes_unverified(self, api):
        """PRD §3.5: "First, lien-waiver coverage, failing which the draw is
        rejected with `ERR_LIEN_WAIVER_UNVERIFIED` (HTTP 409)".
        PRD §3.5: "Documents still `SUBMITTED` or already `REJECTED` count for
        nothing."
        PRD §3.3: "Only `VERIFIED` documents count toward the approval gates of
        §3.5."

        Design: Corner/calculations/waiver_coverage_excludes_unverified
        """
        sc, draw, docs, _insp = _under_review_with_docs(
            requested=100_000, invoice=100_000, waiver=100_000,
            verify_waiver=False, inspection_pct=40.00)
        accept_inspection(_insp["id"])
        waiver_doc = docs[-1]
        assert waiver_doc["status"] == "SUBMITTED"

        first = api.approve_draw(draw["id"], OFFICER)
        validate_error(first, ApiErrorId.ERR_LIEN_WAIVER_UNVERIFIED)

        verify_document(waiver_doc["id"])
        second = api.approve_draw(draw["id"], OFFICER)
        approved = validate_success(second, 200)
        assert approved["status"] == "APPROVED", (
            "Verifying the waiver flips the same approve call to success"
        )


class TestInspectionGates:
    def test_inspection_stale_blocks_approve(self, api):
        """PRD §3.5: "Second, inspection staleness: when an `ACCEPTED` inspection
        linked to this draw exists, its `completed_date` must lie within the closed
        interval from the draw's `period_start_date` through its
        `period_end_date`, or approval is rejected with `ERR_INSPECTION_STALE`
        (HTTP 409)."

        Design: Corner/validations/inspection_stale_blocks_approve
        """
        sc, draw, _docs, insp = _under_review_with_docs(
            inspection_pct=40.00, inspection_scheduled="2026-02-19",
            inspection_completed="2026-02-20")
        accept_inspection(insp["id"])

        resp = api.approve_draw(draw["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_INSPECTION_STALE)
        assert get_draw(draw["id"])["status"] == "UNDER_REVIEW"

    def test_approve_without_accepted_inspection_rejected(self, api):
        """PRD §3.5: "Third, at least one `ACCEPTED` inspection whose `draw_id` is
        this draw must exist at all, or approval is rejected with
        `ERR_INSPECTION_REQUIRED` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/approve_requires_accepted_inspection
        """
        _sc, draw, _docs, insp = _under_review_with_docs(inspection_pct=40.00)
        # Inspection is COMPLETED but never ACCEPTED.
        current = validate_success(api.get_inspection(insp["id"], PROCESSOR))
        assert current["status"] == "COMPLETED"

        resp = api.approve_draw(draw["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_INSPECTION_REQUIRED)
        assert get_draw(draw["id"])["status"] == "UNDER_REVIEW", (
            "The draw remains UNDER_REVIEW while no ACCEPTED inspection exists"
        )

    def test_approve_unblocked_by_accepting_inspection(self, api):
        """PRD §3.5: "Third, at least one `ACCEPTED` inspection whose `draw_id` is
        this draw must exist at all, or approval is rejected with
        `ERR_INSPECTION_REQUIRED` (HTTP 409)."
        PRD §3.5: "Approval stamps the draw `APPROVED` and records its
        `approved_total_cents` as the sum of the per-line `approved_cents`".

        Design: Difficulty/cross_entity_state_dependency/approve_requires_accepted_inspection
        """
        _sc, draw, _docs, insp = _under_review_with_docs(inspection_pct=40.00)
        validate_error(api.approve_draw(draw["id"], OFFICER),
                       ApiErrorId.ERR_INSPECTION_REQUIRED)

        accept_inspection(insp["id"])
        approved = validate_success(api.approve_draw(draw["id"], OFFICER), 200)
        assert approved["status"] == "APPROVED", (
            "Accepting the inspection unblocks the same approve call"
        )
        assert approved["approved_total_cents"] == 100_000


class TestGateOrdering:
    def test_approve_safety_beats_temporal_error(self, api):
        """PRD §2.8: "When several checks could reject the same request, they run
        in a fixed priority order and the earliest failing check determines the
        error returned."
        PRD §3.5: "Its gates run in a fixed order. First, lien-waiver coverage,
        failing which the draw is rejected with `ERR_LIEN_WAIVER_UNVERIFIED`
        (HTTP 409)".

        Design: Difficulty/priority_pair_validation_conflict/approve_safety_beats_temporal
        """
        # Waiver coverage missing AND the accepted inspection is stale: the
        # safety gate (first) must surface, not the temporal gate (second).
        _sc, draw, _docs, insp = _under_review_with_docs(
            waiver=None, inspection_pct=40.00,
            inspection_scheduled="2026-02-19", inspection_completed="2026-02-20")
        accept_inspection(insp["id"])

        resp = api.approve_draw(draw["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_LIEN_WAIVER_UNVERIFIED)

    def test_approve_safety_beats_temporal_state_unchanged(self, api):
        """PRD §3.5: "First, lien-waiver coverage, failing which the draw is
        rejected with `ERR_LIEN_WAIVER_UNVERIFIED` (HTTP 409)".
        PRD §3.5: "Second, inspection staleness: when an `ACCEPTED` inspection
        linked to this draw exists, its `completed_date` must lie within the
        closed interval from the draw's `period_start_date` through its
        `period_end_date`, or approval is rejected with `ERR_INSPECTION_STALE`
        (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/approve_safety_beats_temporal
        """
        _sc, draw, _docs, insp = _under_review_with_docs(
            waiver=None, inspection_pct=40.00,
            inspection_scheduled="2026-02-19", inspection_completed="2026-02-20")
        accept_inspection(insp["id"])

        validate_error(api.approve_draw(draw["id"], OFFICER),
                       ApiErrorId.ERR_LIEN_WAIVER_UNVERIFIED)
        assert get_draw(draw["id"])["status"] == "UNDER_REVIEW", (
            "A rejected approval leaves the draw in UNDER_REVIEW"
        )


class TestInvoiceCoverageAndApprovability:
    def test_invoice_coverage_insufficient_rejected(self, api):
        """PRD §3.5: "Fourth, invoice coverage, failing which the draw is rejected
        with `ERR_INVOICE_COVERAGE_INSUFFICIENT` (HTTP 422): the sum of this draw's
        `VERIFIED` documents of type `INVOICE` must be at least the sum of
        `requested_cents` across the draw's `WORK_COMPLETED` line items".

        Design: Corner/errors/invoice_coverage_insufficient_rejected
        """
        _sc, draw, _docs, insp = _under_review_with_docs(
            requested=100_000, invoice=50_000, waiver=100_000,
            inspection_pct=40.00)
        accept_inspection(insp["id"])

        resp = api.approve_draw(draw["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_INVOICE_COVERAGE_INSUFFICIENT)
        assert get_draw(draw["id"])["status"] == "UNDER_REVIEW"

    def test_nothing_approvable_rejected(self, api):
        """PRD §3.5: "Finally, the computed `approved_total_cents` must be greater
        than zero, or approval is rejected with `ERR_NOTHING_APPROVABLE`
        (HTTP 422)."
        PRD §3.5: "Its inspection cap is the budget line's `revised_amount_cents`
        multiplied by the inspection's `percent_complete_reported` and divided by
        100, rounded down to a whole cent".

        Design: Corner/errors/nothing_approvable_rejected
        """
        _sc, draw, _docs, insp = _under_review_with_docs(inspection_pct=0.00)
        accept_inspection(insp["id"])

        resp = api.approve_draw(draw["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_NOTHING_APPROVABLE)
        assert get_draw(draw["id"])["status"] == "UNDER_REVIEW"


class TestApprovalRole:
    def test_draw_approve_forbidden_for_borrower(self, api):
        """PRD §2.1: "A request whose role is not authorized for the target
        endpoint is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
        PRD §3.5: "Approval belongs to the `CreditOfficer`".

        Design: Corner/validations/draw_approve_forbidden_for_borrower
        """
        sc = setup_loan_with_lines()
        draw = add_draw(sc)
        add_work_line_item(draw["id"], sc["lines"]["SITE"]["id"], 100_000,
                           sc["borrower"]["id"])
        submit_draw(draw["id"], sc["borrower"]["id"])
        start_review_draw(draw["id"])

        resp = api.approve_draw(
            draw["id"], make_borrower_headers(sc["borrower"]["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
        assert get_draw(draw["id"])["status"] == "UNDER_REVIEW"
