"""Proof-of-death documentation and adjudication: document review one-shot
semantics, the conditional required-document set, approval gating, denial and
rescission cascades, segregation of duties, and the fixed state-vs-safety
validation order."""
from test_helpers import (
    EXAMINER_2,
    ApiErrorId,
    begin_review,
    create_designation,
    create_policy_with_statute,
    file_beneficiary_claim,
    file_claim,
    file_claim_with_verified_docs,
    get_beneficiary_claim,
    get_claim,
    list_beneficiary_claims_of,
    make_claims_approver_headers,
    review_document,
    set_clock,
    upload_document,
    validate_beneficiary_claim,
    validate_error,
    validate_success,
)


class TestDocumentReview:
    def test_document_double_review_rejected(self, api, claims_examiner_headers):
        """PRD §3.5: "Only `PENDING` documents can be reviewed — acting on an
        already-decided document is rejected with
        `ERR_DOCUMENT_ALREADY_REVIEWED`."
        PRD §3.5: "The reviewing examiner is recorded as `reviewed_by_id`."

        Design: Corner/state_machines/c_document_double_review_rejected
        """
        policy = create_policy_with_statute("IL", policy_number="P-SM-5")
        set_clock("2026-03-05T00:00:00Z")
        claim = file_claim(policy["id"], "2026-03-01")
        doc = upload_document(claim["id"])
        review_document(claim["id"], doc["id"], "VERIFIED")

        resp = api.review_document(
            claim["id"], doc["id"],
            {"review_result": "REJECTED", "rejection_reason": "ILLEGIBLE"},
            EXAMINER_2)
        validate_error(resp, ApiErrorId.ERR_DOCUMENT_ALREADY_REVIEWED)

        docs = api.list_documents(claim["id"], claims_examiner_headers).json()["data"]
        assert docs[0]["review_result"] == "VERIFIED"
        assert docs[0]["reviewed_by_id"] == "examiner-2"

    def test_document_rejection_keeps_proof_incomplete(
        self, api, claims_approver_headers
    ):
        """PRD §3.5: "A rejection can therefore clear a previously completed
        proof date, and `REJECTED` documents never count toward the set."
        PRD §3.6: "The approver must not be the examiner recorded in
        `assigned_examiner_id` (§2.9), and the required proof set of §3.5 must
        be fully `VERIFIED` before approval — an incomplete set is rejected with
        `ERR_REQUIRED_DOCS_INCOMPLETE`."

        Design: Corner/state_machines/c_document_rejection_keeps_proof_incomplete
        """
        policy = create_policy_with_statute("IL", policy_number="P-SM-6")
        set_clock("2026-03-05T00:00:00Z")
        claim = file_claim(policy["id"], "2026-03-01")
        doc = upload_document(claim["id"])
        review_document(claim["id"], doc["id"], "REJECTED",
                        rejection_reason="ILLEGIBLE")
        begin_review(claim["id"])

        fetched = get_claim(claim["id"])
        assert fetched["proof_complete_date"] is None, (
            "A REJECTED certificate never completes the proof set")

        resp = api.approve_claim(claim["id"], claims_approver_headers)
        validate_error(resp, ApiErrorId.ERR_REQUIRED_DOCS_INCOMPLETE)

    def test_contestable_claim_requires_aps_document(
        self, api, claims_approver_headers, claims_examiner_headers
    ):
        """PRD §3.5: "The required proof set depends on the claim's
        contestability posture: every claim needs at least one `VERIFIED`
        certified death certificate, and a claim whose `contestability_flag` is
        true additionally needs at least one `VERIFIED` attending physician
        statement."
        PRD §3.6: "the required proof set of §3.5 must be fully `VERIFIED`
        before approval — an incomplete set is rejected with
        `ERR_REQUIRED_DOCS_INCOMPLETE`."

        Design: Corner/state_machines/c_contestable_claim_requires_aps_document
        """
        policy = create_policy_with_statute("IL", policy_number="P-SM-4")
        claim, _docs = file_claim_with_verified_docs(policy["id"], "2026-02-28")
        assert claim["status"] == "CONTESTABILITY_REVIEW"
        assert get_claim(claim["id"])["contestability_flag"] is True

        resp = api.approve_claim(claim["id"], claims_approver_headers)
        validate_error(resp, ApiErrorId.ERR_REQUIRED_DOCS_INCOMPLETE)
        assert get_claim(claim["id"])["status"] == "CONTESTABILITY_REVIEW"


class TestApprovalGatedOnDocuments:
    def test_approve_blocked_with_pending_required_doc(
        self, api, claims_approver_headers
    ):
        """PRD §3.6: "The approver must not be the examiner recorded in
        `assigned_examiner_id` (§2.9), and the required proof set of §3.5 must
        be fully `VERIFIED` before approval — an incomplete set is rejected with
        `ERR_REQUIRED_DOCS_INCOMPLETE`."

        A still-PENDING certified death certificate blocks approval even though
        state and segregation preconditions are satisfied.

        Design: Difficulty/cross_entity_state_dependency/approve_blocked_until_required_documents_verified
        """
        policy = create_policy_with_statute("IL", policy_number="P-XD-1")
        set_clock("2026-03-05T00:00:00Z")
        claim = file_claim(policy["id"], "2026-03-01")
        upload_document(claim["id"])  # left PENDING
        begin_review(claim["id"])

        resp = api.approve_claim(claim["id"], claims_approver_headers)
        validate_error(resp, ApiErrorId.ERR_REQUIRED_DOCS_INCOMPLETE)
        assert get_claim(claim["id"])["status"] == "UNDER_REVIEW"

    def test_approve_unblocked_after_completing_review(
        self, api, claims_approver_headers
    ):
        """PRD §3.5: "After every document review the claim's
        `proof_complete_date` is recomputed: if every required document type now
        has at least one `VERIFIED` document, the field is set to the logical
        clock date of the review that completed the set; otherwise it is null."
        PRD §3.6: "Approval belongs to a `ClaimsApprover` and is permitted from
        either `UNDER_REVIEW` or `CONTESTABILITY_REVIEW`".

        Verifying the pending certificate completes the set and unblocks the
        approval.

        Design: Difficulty/cross_entity_state_dependency/approve_blocked_until_required_documents_verified
        """
        policy = create_policy_with_statute("IL", policy_number="P-XD-1")
        set_clock("2026-03-05T00:00:00Z")
        claim = file_claim(policy["id"], "2026-03-01")
        doc = upload_document(claim["id"])
        begin_review(claim["id"])

        review_document(claim["id"], doc["id"], "VERIFIED")
        assert get_claim(claim["id"])["proof_complete_date"] == "2026-03-05"

        approved = validate_success(api.approve_claim(claim["id"],
                                                      claims_approver_headers))
        assert approved["status"] == "APPROVED"
        assert approved["approved_at"] == "2026-03-05"


class TestDenialAndRescission:
    def test_rescind_from_contestability_review_succeeds(
        self, api, claims_approver_headers
    ):
        """PRD §3.6: "Rescission is the contestability outcome for material
        misrepresentation, available only from `CONTESTABILITY_REVIEW` — from
        any other state it is rejected with
        `ERR_CLAIM_NOT_IN_CONTESTABILITY_REVIEW` — again under segregation of
        duties."
        PRD §3.6: "It requires a `rescission_reason` and cascades identically,
        except that open beneficiary claims are rejected with `rejection_reason`
        set to `POLICY_RESCINDED`."

        Design: Corner/state_machines/c_rescind_from_contestability_review_succeeds
        """
        policy = create_policy_with_statute("IL", policy_number="P-SM-2")
        designation = create_designation(policy["id"], beneficiary_name="Alice Doe",
                                         share_percent=100)
        claim, _docs = file_claim_with_verified_docs(
            policy["id"], "2026-02-28",
            doc_types=("CERTIFIED_DEATH_CERTIFICATE",
                       "ATTENDING_PHYSICIAN_STATEMENT"))
        assert claim["status"] == "CONTESTABILITY_REVIEW"
        bc = file_beneficiary_claim(claim["id"], designation_id=designation["id"],
                                    claimant_name="Alice Doe")
        validate_beneficiary_claim(bc["id"])

        rescinded = validate_success(
            api.rescind_claim(claim["id"],
                              {"rescission_reason": "MATERIAL_MISREPRESENTATION"},
                              claims_approver_headers))
        assert rescinded["status"] == "RESCINDED"

        bc_after = get_beneficiary_claim(bc["id"])
        assert bc_after["status"] == "REJECTED"
        assert bc_after["rejection_reason"] == "POLICY_RESCINDED"

    def test_rescind_from_under_review_rejected(
        self, api, claims_approver_headers
    ):
        """PRD §3.6: "Rescission is the contestability outcome for material
        misrepresentation, available only from `CONTESTABILITY_REVIEW` — from
        any other state it is rejected with
        `ERR_CLAIM_NOT_IN_CONTESTABILITY_REVIEW` — again under segregation of
        duties."

        Design: Corner/state_machines/c_rescind_from_under_review_rejected
        """
        policy = create_policy_with_statute("IL", policy_number="P-SM-3")
        claim, _docs = file_claim_with_verified_docs(policy["id"], "2026-03-01")
        assert claim["status"] == "UNDER_REVIEW"

        resp = api.rescind_claim(claim["id"], {"rescission_reason": "X"},
                                 claims_approver_headers)
        validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_IN_CONTESTABILITY_REVIEW)
        assert get_claim(claim["id"])["status"] == "UNDER_REVIEW"

    def test_deny_cascades_open_beneficiary_claims(
        self, api, claims_approver_headers, claims_examiner_headers
    ):
        """PRD §3.6: "It requires a `denial_reason`, and it cascades: every
        beneficiary claim of this claim in `SUBMITTED`, `VALIDATED`, or
        `DISPUTED` is rejected with `rejection_reason` set to `CLAIM_DENIED`."
        PRD §3.4: "When a `ClaimsExaminer` begins review — allowed only from
        `NOTIFIED`, else `ERR_CLAIM_NOT_REVIEWABLE`".

        Design: Corner/state_machines/c_deny_cascades_open_beneficiary_claims
        """
        policy = create_policy_with_statute("IL", policy_number="P-SM-16")
        d1 = create_designation(policy["id"], beneficiary_name="Alice Doe",
                                share_percent=60)
        d2 = create_designation(policy["id"], beneficiary_name="Bob Doe",
                                share_percent=40)
        claim, _docs = file_claim_with_verified_docs(policy["id"], "2026-03-01")
        bc1 = file_beneficiary_claim(claim["id"], designation_id=d1["id"],
                                     claimant_name="Alice Doe")
        bc2 = file_beneficiary_claim(claim["id"], designation_id=d2["id"],
                                     claimant_name="Bob Doe")
        validate_beneficiary_claim(bc1["id"])

        denied = validate_success(
            api.deny_claim(claim["id"], {"denial_reason": "LAPSED_COVERAGE"},
                           claims_approver_headers))
        assert denied["status"] == "DENIED"

        listed = list_beneficiary_claims_of(claim["id"])
        by_id = {b["id"]: b for b in listed}
        for bc_id in (bc1["id"], bc2["id"]):
            assert by_id[bc_id]["status"] == "REJECTED"
            assert by_id[bc_id]["rejection_reason"] == "CLAIM_DENIED"

        # Terminal lockdown: no further transitions are possible on the claim.
        resp = api.begin_review(claim["id"], claims_examiner_headers)
        validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_REVIEWABLE)


class TestValidationPriorityStateBeatsSafety:
    def test_approve_denied_claim_state_error_beats_sod(
        self, api, claims_approver_headers
    ):
        """PRD §2.10: "When several checks could reject the same request, the
        server applies them in a fixed priority order so that the surfaced error
        is deterministic."
        PRD §2.10: "6. State preconditions of the target resource (the
        per-resource 409 errors such as `ERR_CLAIM_NOT_REVIEWABLE` or
        `ERR_BENEFICIARY_CLAIM_INVALID_STATE`)." precedes "7.
        Segregation-of-duties checks (`ERR_SEGREGATION_OF_DUTIES_VIOLATION`)."

        The approver-role caller reuses the assigned examiner's user id, so the
        call violates both the from-state rule and segregation of duties; the
        state error must surface.

        Design: Difficulty/priority_pair_validation_conflict/approve_state_error_beats_segregation_of_duties
        """
        policy = create_policy_with_statute("IL", policy_number="P-PRI-1")
        claim, _docs = file_claim_with_verified_docs(policy["id"], "2026-03-01")
        validate_success(api.deny_claim(claim["id"],
                                        {"denial_reason": "LAPSED_COVERAGE"},
                                        claims_approver_headers))
        assert get_claim(claim["id"])["status"] == "DENIED"

        resp = api.approve_claim(claim["id"],
                                 make_claims_approver_headers("examiner-1"))
        validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_UNDER_REVIEW)
        assert resp.status_code == 409
        assert get_claim(claim["id"])["status"] == "DENIED"

    def test_approve_notified_claim_state_error_beats_sod(
        self, api
    ):
        """PRD §2.10: "When several checks could reject the same request, the
        server applies them in a fixed priority order so that the surfaced error
        is deterministic."
        PRD §2.10: "6. State preconditions of the target resource (the
        per-resource 409 errors such as `ERR_CLAIM_NOT_REVIEWABLE` or
        `ERR_BENEFICIARY_CLAIM_INVALID_STATE`)." precedes "7.
        Segregation-of-duties checks (`ERR_SEGREGATION_OF_DUTIES_VIOLATION`)."
        PRD §3.6: "from any other state the attempt is rejected with
        `ERR_CLAIM_NOT_UNDER_REVIEW`".

        Same pairing from a different invalid from-state (NOTIFIED): the state
        error again surfaces over the segregation-of-duties violation.

        Design: Difficulty/priority_pair_validation_conflict/approve_state_error_beats_segregation_of_duties
        """
        policy = create_policy_with_statute("IL", policy_number="P-PRI-1")
        set_clock("2026-03-05T00:00:00Z")
        claim = file_claim(policy["id"], "2026-03-01")  # stays NOTIFIED

        resp = api.approve_claim(claim["id"],
                                 make_claims_approver_headers("examiner-1"))
        validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_UNDER_REVIEW)
        assert get_claim(claim["id"])["status"] == "NOTIFIED"


class TestSegregationOfDuties:
    def test_sod_assigned_examiner_cannot_approve(self, api):
        """PRD §2.9: "The operator who approves, denies, or rescinds a claim
        must not be the examiner who filed it: on each of those three actions
        the caller's `X-User-ID` is compared against the claim's
        `assigned_examiner_id`, and equality is rejected with
        `ERR_SEGREGATION_OF_DUTIES_VIOLATION` (HTTP 403)."

        The role is correct (ClaimsApprover) and the claim is otherwise fully
        approvable; only the identity match rejects the call.

        Design: Corner/rbac/c_sod_assigned_examiner_cannot_approve
        """
        policy = create_policy_with_statute("IL", policy_number="P-RBAC-3")
        claim, _docs = file_claim_with_verified_docs(policy["id"], "2026-03-01")
        assert claim["status"] == "UNDER_REVIEW"

        resp = api.approve_claim(claim["id"],
                                 make_claims_approver_headers("examiner-1"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION)
        assert resp.status_code == 403
        assert get_claim(claim["id"])["status"] == "UNDER_REVIEW"

    def test_document_self_review_forbidden(self, api, claims_examiner_headers):
        """PRD §2.9: "the examiner who reviews a proof-of-death document must
        not be the operator who uploaded it, so the reviewer's `X-User-ID` is
        compared against the document's `uploaded_by_id`, with equality
        likewise rejected as `ERR_SEGREGATION_OF_DUTIES_VIOLATION`."

        Design: Corner/rbac/c_document_self_review_forbidden
        """
        policy = create_policy_with_statute("IL", policy_number="P-RBAC-4")
        set_clock("2026-03-05T00:00:00Z")
        claim = file_claim(policy["id"], "2026-03-01")
        doc = upload_document(claim["id"])  # uploaded by examiner-1

        resp = api.review_document(claim["id"], doc["id"],
                                   {"review_result": "VERIFIED"},
                                   claims_examiner_headers)  # same examiner-1
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION)

        docs = api.list_documents(claim["id"], claims_examiner_headers).json()["data"]
        assert docs[0]["review_result"] == "PENDING"
