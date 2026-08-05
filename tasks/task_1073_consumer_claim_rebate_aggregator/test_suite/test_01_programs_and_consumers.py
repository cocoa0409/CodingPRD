"""Catalog creation, consumer registration, and the program-window buffer rule."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, NON_EXISTENT_UUID,
    create_program_payload, create_consumer_payload, unique_email,
    make_consumer_headers,
)
from test_helpers import fixtures as fx

PM = TEST_USERS["program_manager_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]
ANON = TEST_USERS["anonymous_headers"]


def test_program_creation_returns_draft(api):
    """PRD §3.1: "A newly created program begins in `DRAFT` with `status` set
    accordingly; its `fund_remaining_cents` is not yet meaningful until the
    program opens."

    Design: Corner/entities/program_creation_returns_draft
    """
    payload = create_program_payload(
        fund_total_cents=50000, advertised_amount_cents=10000,
        per_claim_cap_cents=20000)
    resp = api.create_program(payload, PM)
    data = validate_success(resp, 201)
    assert data["status"] == "DRAFT"
    assert data["fund_total_cents"] == 50000


def test_program_defaults_applied_on_omission(api):
    """PRD §3.1: "eligibility_min_purchase_cents, the minimum claimed spend a
    claim must assert to be eligible (defaulting to 0 when omitted); requires_proof,
    whether supporting documents are mandatory (defaulting to true); and min_documents,
    the minimum count of uploaded documents required to submit a claim (defaulting to 1)."

    Design: Corner/entities/program_defaults_applied_on_omission
    """
    payload = create_program_payload(
        category="WARRANTY", fund_total_cents=50000,
        advertised_amount_cents=10000, per_claim_cap_cents=20000)
    for k in ("eligibility_min_purchase_cents", "requires_proof", "min_documents"):
        payload.pop(k, None)
    data = validate_success(api.create_program(payload, PM), 201)
    assert data["min_documents"] == 1
    assert data["requires_proof"] is True
    assert data["eligibility_min_purchase_cents"] == 0


def test_consumer_get_nonexistent_returns_not_found(api):
    """PRD §2.11: "existence — every id referenced in the path or body exists,
    validated left to right along the path, else `ERR_NOT_FOUND`".

    Design: Corner/entities/consumer_get_nonexistent_returns_not_found
    """
    resp = api.get_consumer(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_claim_create_missing_required_field_rejected(api):
    """PRD §2.11: "request well-formedness — the body is well-formed, required
    fields are present, enums are valid, amounts that must be positive are positive
    ... else `ERR_INVALID_REQUEST`".

    Design: Corner/entities/claim_create_missing_required_field_rejected
    """
    program = fx.create_open_program(
        api, eligibility_min_purchase_cents=0, requires_proof=False, min_documents=0)
    consumer = fx.register_consumer(api)
    headers = make_consumer_headers(consumer["id"])
    payload = {
        "consumer_id": consumer["id"],
        "program_id": program["id"],
        "benefit_period_start": "2026-01-01T00:00:00Z",
        "benefit_period_end": "2026-02-01T00:00:00Z",
        # claimed_amount_cents deliberately omitted
    }
    resp = api.create_claim(payload, headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_consumer_duplicate_email_rejected(api):
    """PRD §3.2: "If the supplied `email` is already registered, the request is
    rejected with `ERR_DUPLICATE_EMAIL`."

    Design: Corner/entities/consumer_duplicate_email_rejected
    """
    email = unique_email("dup")
    validate_success(api.create_consumer(
        create_consumer_payload(email=email, full_name="First"), ANON), 201)
    resp = api.create_consumer(
        create_consumer_payload(email=email, full_name="Second"), ANON)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_EMAIL.value)


def test_claim_document_count_computed(api):
    """PRD §3.3: "its arrival refreshes the parent claim's `document_count`,
    which tallies attached documents in any status."

    Design: Corner/entities/claim_document_count_computed
    """
    program = fx.create_open_program(
        api, eligibility_min_purchase_cents=0, requires_proof=True, min_documents=1)
    consumer = fx.register_consumer(api)
    claim = fx.create_claim(api, consumer, program["id"], claimed_amount_cents=12000)
    fx.add_document(api, claim, consumer, doc_type="RECEIPT", file_ref="a")
    fx.add_document(api, claim, consumer, doc_type="PROOF_OF_PURCHASE", file_ref="b")
    data = get_success_data(api.get_claim(claim["id"], make_consumer_headers(consumer["id"])))
    assert data["document_count"] == 2


def test_program_window_buffer_gap_satisfied_allows_create(api):
    """PRD §3.1: "the new program conflicts with an existing sibling case-program
    unless the new window opens no earlier than the sibling's close instant plus
    thirty days, or the new window closes no later than the sibling's open instant
    minus thirty days."

    Design: Corner/endpoints/program_window_buffer_gap_satisfied_allows_create
    """
    case = "CASE_OK_SHARED"
    fx.create_program(
        api, name="OK1", settlement_case_id=case, category="CLASS_ACTION",
        eligibility_min_purchase_cents=0, requires_proof=False, min_documents=0,
        claim_window_open_at="2026-06-01T00:00:00Z",
        claim_window_close_at="2026-07-01T00:00:00Z")
    # Opens 2026-08-15, i.e. 45 days after the sibling's 2026-07-01 close > 30-day buffer.
    payload = create_program_payload(
        name="OK2", settlement_case_id=case, category="CLASS_ACTION",
        eligibility_min_purchase_cents=0, requires_proof=False, min_documents=0,
        claim_window_open_at="2026-08-15T00:00:00Z",
        claim_window_close_at="2026-09-15T00:00:00Z")
    data = validate_success(api.create_program(payload, PM), 201)
    assert data["status"] == "DRAFT"
    assert data["settlement_case_id"] == case


class TestProgramWindowConflict:
    """Difficulty resource_temporal_overlap — the closed-interval + 30-day
    buffer guard on same-settlement_case_id programs."""

    def test_window_within_buffer_conflicts(self, api):
        """PRD §3.1: "any gap shorter than the full thirty-day buffer conflicts
        as well. A conflicting window is rejected with `ERR_PROGRAM_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/program_window_closed_interval_buffer_conflict
        """
        case = "CASE_BUF"
        fx.create_program(
            api, name="BUF1", settlement_case_id=case, category="CLASS_ACTION",
            eligibility_min_purchase_cents=0, requires_proof=False, min_documents=0,
            claim_window_open_at="2026-06-01T00:00:00Z",
            claim_window_close_at="2026-07-01T00:00:00Z")
        # Opens only 14 days after the sibling closes — inside the 30-day buffer.
        payload = create_program_payload(
            name="BUF2", settlement_case_id=case, category="CLASS_ACTION",
            eligibility_min_purchase_cents=0, requires_proof=False, min_documents=0,
            claim_window_open_at="2026-07-15T00:00:00Z",
            claim_window_close_at="2026-08-15T00:00:00Z")
        resp = api.create_program(payload, PM)
        validate_error(resp, ApiErrorId.ERR_PROGRAM_WINDOW_CONFLICT.value)

    def test_window_at_full_buffer_boundary_allowed(self, api):
        """PRD §3.1: "the new program conflicts with an existing sibling
        case-program unless the new window opens no earlier than the sibling's
        close instant plus thirty days".

        Design: Difficulty/resource_temporal_overlap/program_window_closed_interval_buffer_conflict
        """
        case = "CASE_BUF_OK"
        fx.create_program(
            api, name="BUFA", settlement_case_id=case, category="CLASS_ACTION",
            eligibility_min_purchase_cents=0, requires_proof=False, min_documents=0,
            claim_window_open_at="2026-06-01T00:00:00Z",
            claim_window_close_at="2026-07-01T00:00:00Z")
        # Opens exactly 30 days after 2026-07-01 close -> at the buffer edge, allowed.
        payload = create_program_payload(
            name="BUFB", settlement_case_id=case, category="CLASS_ACTION",
            eligibility_min_purchase_cents=0, requires_proof=False, min_documents=0,
            claim_window_open_at="2026-07-31T00:00:00Z",
            claim_window_close_at="2026-08-31T00:00:00Z")
        data = validate_success(api.create_program(payload, PM), 201)
        assert data["status"] == "DRAFT"
