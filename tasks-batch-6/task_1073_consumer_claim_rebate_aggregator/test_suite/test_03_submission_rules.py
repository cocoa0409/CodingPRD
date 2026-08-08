"""Claim submission: the ordered business-rule gate, boundaries, and overlaps."""
from test_helpers import (
    validate_error, get_success_data, ApiErrorId, TEST_USERS, make_consumer_headers,
)
from test_helpers import fixtures as fx

PM = TEST_USERS["program_manager_headers"]
REVIEWER = TEST_USERS["claim_reviewer_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


def _submit(api, claim, consumer):
    return api.submit_claim(claim["id"], make_consumer_headers(consumer["id"]))


class TestSubmitRequiresProgramOpen:
    """Difficulty cross_entity_state_dependency — submit gated on program.status."""

    def test_submit_against_draft_program_rejected(self, api):
        """PRD §3.3: "The program must be `OPEN`; submitting against a program in
        any other status is rejected with `ERR_PROGRAM_NOT_OPEN`."

        Design: Difficulty/cross_entity_state_dependency/claim_submit_requires_program_open
        """
        fx.set_clock(api)
        program = fx.create_program(api)  # left in DRAFT, never opened
        consumer = fx.register_verified_consumer(api)
        claim = fx.create_claim(api, consumer, program["id"])
        fx.add_document(api, claim, consumer)
        resp = _submit(api, claim, consumer)
        validate_error(resp, ApiErrorId.ERR_PROGRAM_NOT_OPEN.value)
        assert get_success_data(api.get_claim(claim["id"], ADMIN))["status"] == "DRAFT"

    def test_submit_against_closed_program_rejected(self, api):
        """PRD §3.3: "The program must be `OPEN`; submitting against a program in
        any other status is rejected with `ERR_PROGRAM_NOT_OPEN`."

        Design: Difficulty/cross_entity_state_dependency/claim_submit_requires_program_open
        """
        fx.set_clock(api)
        program = fx.create_open_program(api)
        consumer = fx.register_verified_consumer(api)
        claim = fx.create_claim(api, consumer, program["id"])
        fx.add_document(api, claim, consumer)
        get_success_data(api.close_program(program["id"], PM))  # OPEN -> CLOSED
        resp = _submit(api, claim, consumer)
        validate_error(resp, ApiErrorId.ERR_PROGRAM_NOT_OPEN.value)


class TestSubmitWindowBeatsDocuments:
    """Difficulty priority_pair_validation_conflict — window (step 2) precedes
    document sufficiency (step 4) in the submit gate."""

    def test_window_closed_and_zero_docs_reports_window_closed(self, api):
        """PRD §3.3: "The current instant must fall within the claim window ... a
        submission outside that half-open window is rejected with
        `ERR_CLAIM_WINDOW_CLOSED`."

        Design: Difficulty/priority_pair_validation_conflict/submit_window_closed_beats_insufficient_documents
        """
        fx.set_clock(api, "2026-06-15T00:00:00Z")
        program = fx.create_open_program(
            api, claim_window_open_at="2026-06-01T00:00:00Z",
            claim_window_close_at="2026-06-10T00:00:00Z")  # window already closed
        consumer = fx.register_verified_consumer(api)
        claim = fx.create_claim(api, consumer, program["id"])  # zero documents
        resp = _submit(api, claim, consumer)
        validate_error(resp, ApiErrorId.ERR_CLAIM_WINDOW_CLOSED.value)
        assert get_success_data(api.get_claim(claim["id"], ADMIN))["status"] == "DRAFT"

    def test_insufficient_documents_reported_when_window_open(self, api):
        """PRD §3.3: "If the program `requires_proof`, the claim's `document_count`
        must be at least the program's `min_documents`; too few attached documents
        yields `ERR_INSUFFICIENT_DOCUMENTS`."

        Design: Difficulty/priority_pair_validation_conflict/submit_window_closed_beats_insufficient_documents
        """
        fx.set_clock(api, "2026-06-15T00:00:00Z")
        program = fx.create_open_program(api)  # window open through 2026-09-01
        consumer = fx.register_verified_consumer(api)
        claim = fx.create_claim(api, consumer, program["id"])  # zero documents
        resp = _submit(api, claim, consumer)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_DOCUMENTS.value)


class TestSubmitDocumentBoundary:
    """Difficulty boundary_precision_check — document_count at the min_documents edge."""

    def test_zero_documents_empty_set_rejected(self, api):
        """PRD §3.3: "If the program `requires_proof`, the claim's `document_count`
        must be at least the program's `min_documents`; too few attached documents
        yields `ERR_INSUFFICIENT_DOCUMENTS`."

        Design: Difficulty/boundary_precision_check/submit_zero_documents_empty_set_rejected
        """
        fx.set_clock(api)
        program = fx.create_open_program(api, requires_proof=True, min_documents=1)
        consumer = fx.register_verified_consumer(api)
        claim = fx.create_claim(api, consumer, program["id"])  # zero documents
        resp = _submit(api, claim, consumer)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_DOCUMENTS.value)
        data = get_success_data(api.get_claim(claim["id"], ADMIN))
        assert data["status"] == "DRAFT"
        assert data["document_count"] == 0

    def test_exactly_min_documents_allows_submit(self, api):
        """PRD §3.3: "If the program `requires_proof`, the claim's `document_count`
        must be at least the program's `min_documents`; too few attached documents
        yields `ERR_INSUFFICIENT_DOCUMENTS`."

        Design: Difficulty/boundary_precision_check/submit_zero_documents_empty_set_rejected
        """
        fx.set_clock(api)
        program = fx.create_open_program(api, requires_proof=True, min_documents=1)
        consumer = fx.register_verified_consumer(api)
        claim = fx.create_claim(api, consumer, program["id"])
        fx.add_document(api, claim, consumer)  # exactly one document
        data = get_success_data(_submit(api, claim, consumer))
        assert data["status"] == "SUBMITTED"


class TestBenefitPeriodOverlap:
    """Difficulty resource_temporal_overlap — half-open benefit-period overlap."""

    def test_overlapping_benefit_period_rejected(self, api):
        """PRD §3.3: "two periods overlap when the new period's start precedes the
        existing period's end **and** the existing period's start precedes the new
        period's end. ... a collision yields `ERR_BENEFIT_PERIOD_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/claim_benefit_period_half_open_overlap
        """
        fx.set_clock(api)
        program = fx.create_open_program(api)
        consumer = fx.register_verified_consumer(api)
        c1 = fx.create_claim(api, consumer, program["id"],
                            benefit_period_start="2026-01-01T00:00:00Z",
                            benefit_period_end="2026-02-01T00:00:00Z")
        fx.add_document(api, c1, consumer)
        get_success_data(_submit(api, c1, consumer))
        c2 = fx.create_claim(api, consumer, program["id"],
                            benefit_period_start="2026-01-15T00:00:00Z",
                            benefit_period_end="2026-02-15T00:00:00Z")
        fx.add_document(api, c2, consumer)
        resp = _submit(api, c2, consumer)
        validate_error(resp, ApiErrorId.ERR_BENEFIT_PERIOD_OVERLAP.value)
        assert get_success_data(api.get_claim(c2["id"], ADMIN))["status"] == "DRAFT"

    def test_overlap_ignores_rejected_claim(self, api):
        """PRD §3.3: "Only claims whose status is neither `REJECTED` nor `EXPIRED`
        count as live for this test".

        Design: Difficulty/resource_temporal_overlap/claim_benefit_period_half_open_overlap
        """
        fx.set_clock(api)
        program = fx.create_open_program(api)
        consumer = fx.register_verified_consumer(api)
        c1 = fx.create_claim(api, consumer, program["id"],
                            benefit_period_start="2026-01-01T00:00:00Z",
                            benefit_period_end="2026-02-01T00:00:00Z")
        d1 = fx.add_document(api, c1, consumer)
        get_success_data(_submit(api, c1, consumer))
        fx.verify_document(api, d1["id"])
        fx.start_review(api, c1["id"])
        get_success_data(api.reject_claim(c1["id"], REVIEWER))  # c1 -> REJECTED (not live)
        c2 = fx.create_claim(api, consumer, program["id"],
                            benefit_period_start="2026-01-15T00:00:00Z",
                            benefit_period_end="2026-02-15T00:00:00Z")
        fx.add_document(api, c2, consumer)
        data = get_success_data(_submit(api, c2, consumer))
        assert data["status"] == "SUBMITTED"


def test_submit_below_min_purchase_returns_not_eligible(api):
    """PRD §3.3: "The claimed spend must clear the eligibility floor:
    `claimed_amount_cents` must be at least the program's
    `eligibility_min_purchase_cents`, else `ERR_NOT_ELIGIBLE`."

    Design: Corner/validations/submit_below_min_purchase_returns_not_eligible
    """
    fx.set_clock(api)
    program = fx.create_open_program(api, eligibility_min_purchase_cents=5000)
    consumer = fx.register_verified_consumer(api)
    claim = fx.create_claim(api, consumer, program["id"], claimed_amount_cents=3000)
    fx.add_document(api, claim, consumer)
    resp = _submit(api, claim, consumer)
    validate_error(resp, ApiErrorId.ERR_NOT_ELIGIBLE.value)
    assert get_success_data(api.get_claim(claim["id"], ADMIN))["status"] == "DRAFT"


def test_benefit_period_adjacent_allowed(api):
    """PRD §3.3: "Periods that merely touch — where one's end equals the other's
    start — do not overlap and are permitted."

    Design: Corner/validations/benefit_period_adjacent_allowed
    """
    fx.set_clock(api)
    program = fx.create_open_program(api)
    consumer = fx.register_verified_consumer(api)
    c1 = fx.create_claim(api, consumer, program["id"],
                        benefit_period_start="2026-01-01T00:00:00Z",
                        benefit_period_end="2026-02-01T00:00:00Z")
    fx.add_document(api, c1, consumer)
    get_success_data(_submit(api, c1, consumer))
    c2 = fx.create_claim(api, consumer, program["id"],
                        benefit_period_start="2026-02-01T00:00:00Z",
                        benefit_period_end="2026-03-01T00:00:00Z")
    fx.add_document(api, c2, consumer)
    data = get_success_data(_submit(api, c2, consumer))
    assert data["status"] == "SUBMITTED"
