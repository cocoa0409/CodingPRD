"""Document evidence cycle: rejection cascades, deadlines, resume gates,
upload validations, and bank-statement period overlap."""
from test_helpers import (
    COUNSELOR,
    ApiErrorId,
    add_member,
    assert_instant_eq,
    build_under_review_application,
    create_active_policy,
    create_application,
    create_patient,
    get_application,
    list_application_notices,
    reject_document,
    request_documents,
    set_clock,
    setup_verified_application,
    upload_and_verify,
    upload_document,
    validate_error,
    validate_success,
    verify_document,
)


def _rejection_scenario():
    """Application UNDER_REVIEW with one SUBMITTED TAX_RETURN; clock parked at
    2026-03-01T00:00:00Z for the rejection."""
    set_clock("2026-02-01T00:00:00Z")
    create_active_policy()
    ctx = build_under_review_application(
        patient_name="Reject Rhonda", mrn="MRN-REJ-1", ssn_last4="3434",
        date_of_birth="1988-09-09", reported_income=2000000,
        members=(("SELF", 37),),
    )
    doc = upload_document(
        ctx["application"]["id"],
        doc_type="TAX_RETURN", period_start="2025-01-01", period_end="2025-12-31",
        amount_cents=2000000, household_member_id=ctx["members"][0]["id"],
    )
    set_clock("2026-03-01T00:00:00Z")
    return ctx, doc


class TestRejectionCascade:
    def test_reject_moves_application_to_pending_documents(self, api):
        """PRD §3.5: "Rejection is also the first link of a cascade: if the
        owning application is `UNDER_REVIEW`, the rejection forces it back to
        `PENDING_DOCUMENTS` — the rejected document's `doc_type` is unioned
        into `requested_doc_types` (deduplicated), `doc_response_deadline` is
        reset to now plus the pinned policy's `doc_response_days` on each
        rejection, and a fresh `DOC_REQUEST` notice is created."

        Design: Difficulty/transitive_cascade/document_reject_cascades_application_pending_and_notice
        """
        ctx, doc = _rejection_scenario()
        rejected = validate_success(
            api.reject_document(doc["id"], {"rejection_reason": "illegible scan"}, COUNSELOR)
        )
        assert rejected["status"] == "REJECTED"
        assert rejected["rejection_reason"] == "illegible scan"
        app = get_application(ctx["application"]["id"])
        assert app["status"] == "PENDING_DOCUMENTS", (
            "rejection of a document on an UNDER_REVIEW application forces it "
            "back to document collection"
        )
        assert "TAX_RETURN" in app["requested_doc_types"]
        # doc_response_days 30 from 2026-03-01 -> 2026-03-31
        assert_instant_eq(app["doc_response_deadline"], "2026-03-31T00:00:00Z")

    def test_reject_creates_doc_request_notice(self, api):
        """PRD §3.5: "Rejection is also the first link of a cascade: if the
        owning application is `UNDER_REVIEW`, the rejection forces it back to
        `PENDING_DOCUMENTS` — the rejected document's `doc_type` is unioned
        into `requested_doc_types` (deduplicated), `doc_response_deadline` is
        reset to now plus the pinned policy's `doc_response_days` on each
        rejection, and a fresh `DOC_REQUEST` notice is created."

        Design: Difficulty/transitive_cascade/document_reject_cascades_application_pending_and_notice
        """
        ctx, doc = _rejection_scenario()
        reject_document(doc["id"], rejection_reason="illegible scan")
        notices = list_application_notices(ctx["application"]["id"])
        doc_requests = [n for n in notices if n["notice_type"] == "DOC_REQUEST"]
        assert len(doc_requests) >= 1, (
            "entering PENDING_DOCUMENTS via rejection creates a DOC_REQUEST notice"
        )
        assert doc_requests[0]["application_id"] == ctx["application"]["id"]


class TestDeadlinesAndResume:
    def test_expire_at_deadline_rejected_then_succeeds(self, api):
        """PRD §3.5: "Expiry requires `PENDING_DOCUMENTS` status
        (`ERR_APPLICATION_NOT_PENDING_DOCUMENTS`) and requires the logical
        clock to be strictly later than `doc_response_deadline`
        (`ERR_DOC_DEADLINE_NOT_REACHED`, HTTP 422) — at the deadline instant
        itself expiry is not yet permitted."

        Design: Corner/state_machines/expire_before_deadline_rejected
        """
        set_clock("2026-02-01T00:00:00Z")
        create_active_policy()
        ctx = build_under_review_application(
            patient_name="Expire Earl", mrn="MRN-EXP-1", ssn_last4="0014",
            date_of_birth="1991-01-01", reported_income=1000000,
            members=(("SELF", 35),),
        )
        app_id = ctx["application"]["id"]
        set_clock("2026-03-01T00:00:00Z")
        request_documents(app_id, ["TAX_RETURN"])
        # deadline == 2026-03-31T00:00:00Z (30 days); strict > gate
        set_clock("2026-03-31T00:00:00Z")
        resp = api.expire_application(app_id, COUNSELOR)
        validate_error(resp, ApiErrorId.ERR_DOC_DEADLINE_NOT_REACHED)
        set_clock("2026-03-31T00:00:01Z")
        expired = validate_success(api.expire_application(app_id, COUNSELOR))
        assert expired["status"] == "EXPIRED"

    def test_resume_review_with_unverified_docs_rejected(self, api):
        """PRD §3.5: "Resuming review moves `PENDING_DOCUMENTS → UNDER_REVIEW`
        and requires two things: the application must actually be in
        `PENDING_DOCUMENTS` (`ERR_APPLICATION_NOT_PENDING_DOCUMENTS`), and for
        every doc type listed in `requested_doc_types` at least one document
        of this application with that type must be `VERIFIED`
        (`ERR_DOCS_OUTSTANDING`, HTTP 422)."

        Design: Corner/state_machines/resume_review_with_outstanding_docs_rejected
        """
        set_clock("2026-02-01T00:00:00Z")
        create_active_policy()
        ctx = build_under_review_application(
            patient_name="Resume Rhea", mrn="MRN-RES-1", ssn_last4="0015",
            date_of_birth="1992-01-01", reported_income=1000000,
            members=(("SELF", 34),),
        )
        app_id = ctx["application"]["id"]
        request_documents(app_id, ["TAX_RETURN"])
        upload_document(
            app_id, doc_type="TAX_RETURN", period_start="2025-01-01",
            period_end="2025-12-31", amount_cents=1000000,
            household_member_id=ctx["members"][0]["id"],
        )  # left SUBMITTED — never verified
        resp = api.resume_review(app_id, COUNSELOR)
        validate_error(resp, ApiErrorId.ERR_DOCS_OUTSTANDING)


class TestUploadValidation:
    def test_document_period_end_before_start_rejected(self, api):
        """PRD §3.5: "Each upload names a `doc_type` (`PAY_STUB`,
        `TAX_RETURN`, `BENEFIT_LETTER`, `BANK_STATEMENT`, or `IDENTITY`), a
        `period_start` and `period_end` forming a closed interval
        (`period_end` earlier than `period_start` is `ERR_INVALID_PERIOD`,
        HTTP 422), an `amount_cents`, and an optional `household_member_id`
        identifying which member the document evidences — required semantics
        vary by type, and an `IDENTITY` document for the applicant may omit
        it."

        Design: Corner/validations/document_invalid_period_rejected
        """
        ctx = setup_verified_application(
            patient_name="Bad Period", mrn="MRN-BPER-1", ssn_last4="0037",
            reported_income=1000000, tax_return_amount=1000000,
        )
        resp = api.upload_document(
            ctx["application"]["id"],
            {
                "doc_type": "BENEFIT_LETTER",
                "period_start": "2025-12-31",
                "period_end": "2025-01-01",
                "amount_cents": 100000,
                "household_member_id": ctx["members"][0]["id"],
            },
            COUNSELOR,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_PERIOD)

    def test_document_member_of_other_application_rejected(self, api):
        """PRD §3.5: "If a `household_member_id` is supplied it must belong to
        the same application, else `ERR_MEMBER_APPLICATION_MISMATCH`
        (HTTP 422)."

        Design: Corner/validations/document_member_of_other_application_rejected
        """
        set_clock("2026-02-01T00:00:00Z")
        create_active_policy()
        ctx_a = build_under_review_application(
            patient_name="Mem A", mrn="MRN-MEMA-1", ssn_last4="0038",
            reported_income=1000000,
        )
        patient_b = create_patient(
            full_name="Mem B", date_of_birth="1990-01-01",
            ssn_last4="0039", mrn="MRN-MEMB-1",
        )
        app_b = create_application(
            patient_b["id"], screening_source="STANDARD",
            reported_annual_income_cents=1000000, reported_liquid_assets_cents=0,
        )
        member_b = add_member(
            app_b["id"], full_name="Mem B", relationship="SELF", age=40
        )
        resp = api.upload_document(
            ctx_a["application"]["id"],
            {
                "doc_type": "TAX_RETURN",
                "period_start": "2025-01-01",
                "period_end": "2025-12-31",
                "amount_cents": 1000000,
                "household_member_id": member_b["id"],
            },
            COUNSELOR,
        )
        validate_error(resp, ApiErrorId.ERR_MEMBER_APPLICATION_MISMATCH)


class TestBankStatementOverlap:
    def _overlap_setup(self):
        """D1 VERIFIED 2026-01-01..2026-01-31; D2 touching at 01-31; D3
        adjacent starting 02-01."""
        set_clock("2026-02-01T00:00:00Z")
        create_active_policy()
        ctx = build_under_review_application(
            patient_name="Overlap Olive", mrn="MRN-OVL-1", ssn_last4="1616",
            date_of_birth="1984-06-06", reported_income=2000000,
            members=(("SELF", 41),),
        )
        app_id = ctx["application"]["id"]
        member_id = ctx["members"][0]["id"]
        d1 = upload_and_verify(
            app_id, member_id, doc_type="BANK_STATEMENT", amount_cents=100000,
            period_start="2026-01-01", period_end="2026-01-31",
        )
        return ctx, app_id, member_id, d1

    def test_touching_period_counts_as_overlap(self, api):
        """PRD §3.5: "Verification carries one additional guard: for a
        `BANK_STATEMENT` document with `household_member_id` set, no other
        already-`VERIFIED` bank statement for the same member may have a
        closed-period overlap — a conflict exists when the new statement's
        `period_start` is on or before the existing statement's `period_end`
        and the existing statement's `period_start` is on or before the new
        statement's `period_end`, with touching dates counting as overlap —
        and a conflict is rejected with `ERR_DOC_PERIOD_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/bank_statement_closed_interval_overlap_rejected
        """
        ctx, app_id, member_id, _d1 = self._overlap_setup()
        d2 = upload_document(
            app_id, doc_type="BANK_STATEMENT", period_start="2026-01-31",
            period_end="2026-02-28", amount_cents=110000,
            household_member_id=member_id,
        )
        resp = api.verify_document(d2["id"], COUNSELOR)
        validate_error(resp, ApiErrorId.ERR_DOC_PERIOD_OVERLAP)
        doc = validate_success(api.get_document(d2["id"], COUNSELOR))
        assert doc["status"] == "SUBMITTED", "rejected verify leaves the document SUBMITTED"

    def test_adjacent_after_end_verifies_and_counts(self, api):
        """PRD §3.5: "Verification carries one additional guard: for a
        `BANK_STATEMENT` document with `household_member_id` set, no other
        already-`VERIFIED` bank statement for the same member may have a
        closed-period overlap — a conflict exists when the new statement's
        `period_start` is on or before the existing statement's `period_end`
        and the existing statement's `period_start` is on or before the new
        statement's `period_end`, with touching dates counting as overlap —
        and a conflict is rejected with `ERR_DOC_PERIOD_OVERLAP` (HTTP 409)."
        PRD §3.6: "The `verified_liquid_assets_cents` is the plain sum of
        `amount_cents` over the application's `VERIFIED` bank statements."

        Design: Difficulty/resource_temporal_overlap/bank_statement_closed_interval_overlap_rejected
        """
        ctx, app_id, member_id, _d1 = self._overlap_setup()
        d3 = upload_document(
            app_id, doc_type="BANK_STATEMENT", period_start="2026-02-01",
            period_end="2026-02-28", amount_cents=120000,
            household_member_id=member_id,
        )
        verified = verify_document(d3["id"])
        assert verified["status"] == "VERIFIED", (
            "2026-02-01 is strictly after the VERIFIED period end 2026-01-31: no overlap"
        )
        app = get_application(app_id)
        assert app["verified_liquid_assets_cents"] == 220000, (
            "100000 (D1) + 120000 (D3); the rejected D2 contributes nothing"
        )
