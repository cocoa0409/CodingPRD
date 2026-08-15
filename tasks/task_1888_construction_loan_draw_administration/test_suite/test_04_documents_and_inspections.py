"""Document review, inspection lifecycle, scheduling gaps, role denial."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_work_line_item,
    attach_document,
    complete_inspection,
    create_borrower,
    create_draw,
    create_loan,
    get_draw,
    get_loan,
    make_borrower_headers,
    order_inspection,
    review_decision_payload,
    setup_loan_with_lines,
    start_review_draw,
    submit_draw,
    validate_error,
    validate_success,
    verify_document,
    add_budget_line,
)

ADMIN = TEST_USERS["lender_admin_headers"]
PROCESSOR = TEST_USERS["draw_processor_headers"]
INSPECTOR = TEST_USERS["inspector_headers"]


def _draft_draw_with_invoice(amount=100_000):
    """Loan + line + DRAFT draw + one SUBMITTED invoice document."""
    sc = setup_loan_with_lines()
    draw = create_draw(sc["loan"]["id"], sc["borrower"]["id"])
    doc = attach_document(draw["id"], "INVOICE", amount, sc["borrower"]["id"])
    return sc, draw, doc


class TestDocumentReview:
    def test_document_double_review_rejected(self, api):
        """PRD §3.3: "A `DrawProcessor` then reviews each one, passing a `decision`
        of `VERIFIED` or `REJECTED`".
        PRD §2.6: "A transition attempted from any other state — including from an
        already-terminal state — is rejected with `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/document_double_review_rejected
        """
        _sc, _draw, doc = _draft_draw_with_invoice()
        verify_document(doc["id"])

        resp = api.review_draw_document(
            doc["id"], review_decision_payload("REJECTED", reason="changed mind"),
            PROCESSOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = validate_success(api.get_draw_document(doc["id"], PROCESSOR))
        assert after["status"] == "VERIFIED", (
            "The first review is not silently replayed"
        )

    def test_review_decision_invalid_enum(self, api):
        """PRD §3.3: "A `DrawProcessor` then reviews each one, passing a `decision`
        of `VERIFIED` or `REJECTED`".
        PRD §2.8: "A missing required field, an invalid enum value, or a
        non-positive amount anywhere in a request body is a structural failure
        reported as `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/endpoints/review_decision_invalid_enum
        """
        _sc, _draw, doc = _draft_draw_with_invoice()

        resp = api.review_draw_document(doc["id"], {"decision": "MAYBE"}, PROCESSOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        after = validate_success(api.get_draw_document(doc["id"], PROCESSOR))
        assert after["status"] == "SUBMITTED"

    def test_inspector_cannot_review_document(self, api):
        """PRD §2.1: "A request whose role is not authorized for the target
        endpoint is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
        PRD §2.1: "`Inspector` — third-party inspector; reports inspection results
        only."

        Design: Corner/roles/inspector_cannot_review_document
        """
        _sc, _draw, doc = _draft_draw_with_invoice()

        resp = api.review_draw_document(
            doc["id"], review_decision_payload("VERIFIED"), INSPECTOR)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
        after = validate_success(api.get_draw_document(doc["id"], PROCESSOR))
        assert after["status"] == "SUBMITTED"


class TestInspectionLifecycle:
    def test_inspection_complete_twice_rejected(self, api):
        """PRD §3.4: "Completing an `ORDERED` inspection records the
        `percent_complete_reported` — a value from 0.00 to 100.00 inclusive ...
        The inspection moves to `COMPLETED`."
        PRD §2.6: "A transition attempted from any other state — including from an
        already-terminal state — is rejected with `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/inspection_complete_twice_rejected
        """
        sc = setup_loan_with_lines()
        insp = order_inspection(sc["loan"]["id"], "2026-06-15")
        complete_inspection(insp["id"], 75.00, "2026-06-16")

        resp = api.complete_inspection(
            insp["id"],
            {"percent_complete_reported": 80.00, "completed_date": "2026-06-17"},
            INSPECTOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = validate_success(api.get_inspection(insp["id"], PROCESSOR))
        assert after["status"] == "COMPLETED"
        assert after["percent_complete_reported"] == 75.00, (
            "The rejected second completion leaves the first report intact"
        )


class TestInspectionSchedulingGap:
    def test_inspection_gap_two_days_conflicts(self, api):
        """PRD §3.4: "Scheduling keeps a minimum three-day gap on a loan: if the
        new inspection's `scheduled_date` falls within two days, in either
        direction, of the `scheduled_date` of an existing `ORDERED` inspection on
        the same loan, the order is rejected with
        `ERR_INSPECTION_SCHEDULE_CONFLICT` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/inspection_minimum_gap_buffer
        """
        sc = setup_loan_with_lines()
        order_inspection(sc["loan"]["id"], "2026-03-10")

        resp = api.create_inspection(
            {"loan_id": sc["loan"]["id"], "scheduled_date": "2026-03-12"},
            PROCESSOR)
        validate_error(resp, ApiErrorId.ERR_INSPECTION_SCHEDULE_CONFLICT)

    def test_inspection_gap_three_days_allowed(self, api):
        """PRD §3.4: "Scheduling keeps a minimum three-day gap on a loan: if the
        new inspection's `scheduled_date` falls within two days, in either
        direction, of the `scheduled_date` of an existing `ORDERED` inspection on
        the same loan, the order is rejected with
        `ERR_INSPECTION_SCHEDULE_CONFLICT` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/inspection_minimum_gap_buffer
        """
        sc = setup_loan_with_lines()
        order_inspection(sc["loan"]["id"], "2026-03-10")

        resp = api.create_inspection(
            {"loan_id": sc["loan"]["id"], "scheduled_date": "2026-03-13"},
            PROCESSOR)
        created = validate_success(resp, 201)
        assert created["status"] == "ORDERED", (
            "A gap of exactly three days satisfies the minimum gap"
        )


class TestInspectionCrossReferences:
    def test_inspection_draw_loan_mismatch_rejected(self, api):
        """PRD §3.4: "When `draw_id` is supplied, that draw must belong to the
        named loan, or the order is rejected with `ERR_DRAW_LOAN_MISMATCH`
        (HTTP 422)."

        Design: Corner/errors/inspection_draw_loan_mismatch_rejected
        """
        borrower = create_borrower()
        loan1 = create_loan(borrower["id"], commitment_amount_cents=100_000_000)
        loan2 = create_loan(borrower["id"], commitment_amount_cents=100_000_000)
        line_x = add_budget_line(loan2["id"], cost_code="SITE",
                                 original_amount_cents=1_000_000)
        draw2 = create_draw(loan2["id"], borrower["id"])
        add_work_line_item(draw2["id"], line_x["id"], 100_000, borrower["id"])
        submit_draw(draw2["id"], borrower["id"])
        start_review_draw(draw2["id"])

        resp = api.create_inspection(
            {"loan_id": loan1["id"], "draw_id": draw2["id"],
             "scheduled_date": "2026-03-20"},
            PROCESSOR)
        validate_error(resp, ApiErrorId.ERR_DRAW_LOAN_MISMATCH)
