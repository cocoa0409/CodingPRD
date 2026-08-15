"""Translation pipeline: queueing, assignment gates, review loop, supersession."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_translation_job,
    assign_translator,
    create_active_contract,
    create_department,
    create_document,
    create_interpreter,
    create_job_in_quality_review,
    create_translation_job,
    get_contract,
    get_translation_job,
    make_officer_headers,
    make_reviewer_headers,
    review_job,
    setup_translation_workspace,
    submit_translation,
    validate_error,
    validate_success,
)

COORDINATOR = TEST_USERS["coordinator_headers"]


class TestRevisionLoop:
    def _workspace_with_assigned_job(self):
        ws = setup_translation_workspace(word_rate=20, ceiling_cents=1_000_000)
        job = create_translation_job(ws["document"]["id"], ws["contract"]["id"],
                                     target_language_code="es", word_count=2000)
        assign_translator(job["id"], ws["translator"]["id"])
        return ws, job

    def test_revision_loop_cycles_between_translation_and_review(self, api):
        """PRD §3.4: "A `decision` of `REQUEST_REVISION` instead loops the job
        `QUALITY_REVIEW` → `IN_TRANSLATION`, incrementing `revision_count` — zero
        when the job is first queued — by one while leaving the translator
        assignment unchanged."

        Design: Difficulty/non_linear_state_machine/translation_job_revision_loop
        """
        ws, job = self._workspace_with_assigned_job()
        translator_id = ws["translator"]["id"]
        reviewer_id = ws["reviewer"]["id"]

        in_review = submit_translation(job["id"], translator_id, 2100)
        assert in_review["status"] == "QUALITY_REVIEW"
        first_loop = review_job(job["id"], reviewer_id, "REQUEST_REVISION")
        assert first_loop["status"] == "IN_TRANSLATION"
        assert first_loop["revision_count"] == 1

        second_submit = submit_translation(job["id"], translator_id, 2100)
        assert second_submit["status"] == "QUALITY_REVIEW"
        second_loop = review_job(job["id"], reviewer_id, "REQUEST_REVISION")
        assert second_loop["status"] == "IN_TRANSLATION"
        assert second_loop["revision_count"] == 2, (
            "two full revision cycles must leave revision_count == 2"
        )

    def test_revision_loop_keeps_translator_and_provisional_commitment(self, api):
        """PRD §3.4: "A `decision` of `REQUEST_REVISION` instead loops the job
        `QUALITY_REVIEW` → `IN_TRANSLATION`, incrementing `revision_count` — zero
        when the job is first queued — by one while leaving the translator
        assignment unchanged."
        PRD §3.3: "`committed_cents` is the sum of `provisional_cost_cents` over
        the contract's translation jobs in `QUEUED`, `IN_TRANSLATION`, or
        `QUALITY_REVIEW`, plus the `estimated_cost_cents` of `ASSIGNED`
        interpretation requests whose interpreter bills to this contract."

        Design: Difficulty/non_linear_state_machine/translation_job_revision_loop
        """
        ws, job = self._workspace_with_assigned_job()
        translator_id = ws["translator"]["id"]
        reviewer_id = ws["reviewer"]["id"]
        for _ in range(2):
            submit_translation(job["id"], translator_id, 2100)
            review_job(job["id"], reviewer_id, "REQUEST_REVISION")

        current = get_translation_job(job["id"])
        assert current["translator_id"] == translator_id, (
            "the revision loop must leave the translator assignment unchanged"
        )
        contract = get_contract(ws["contract"]["id"])
        assert contract["committed_cents"] == 40000, (
            "the 2000-word x 20c provisional stays committed while the job loops"
        )
        assert contract["spent_cents"] == 0


class TestRevisionCapAndRushPricing:
    def _approve_after_five_revisions(self):
        ws = setup_translation_workspace(word_rate=20, ceiling_cents=1_000_000)
        job = create_translation_job(ws["document"]["id"], ws["contract"]["id"],
                                     target_language_code="es", word_count=10000,
                                     rush=True)
        assign_translator(job["id"], ws["translator"]["id"])
        translator_id = ws["translator"]["id"]
        reviewer_id = ws["reviewer"]["id"]
        for _ in range(5):
            submit_translation(job["id"], translator_id, 10000)
            review_job(job["id"], reviewer_id, "REQUEST_REVISION")
        submit_translation(job["id"], translator_id, 10000)
        approved = review_job(job["id"], reviewer_id, "APPROVE")
        return ws, job, approved

    def test_five_revision_cycles_are_counted(self, api):
        """PRD §3.4: "A `decision` of `REQUEST_REVISION` instead loops the job
        `QUALITY_REVIEW` → `IN_TRANSLATION`, incrementing `revision_count` — zero
        when the job is first queued — by one while leaving the translator
        assignment unchanged."
        PRD §3.4: "A `decision` of `APPROVE` moves the job to `APPROVED`, stamps
        `reviewer_id` from the caller, and prices the job for settlement from
        four inputs — `submitted_word_count`, `revision_count`, `rush`, and the
        contract's per-word rate."

        Design: Difficulty/combinatorial_formula/translation_final_cost_revision_cap_and_rush
        """
        ws, job, approved = self._approve_after_five_revisions()
        assert approved["revision_count"] == 5
        assert approved["status"] == "APPROVED"
        assert approved["reviewer_id"] == ws["reviewer"]["id"]

    def test_revision_cap_and_rush_multiplier_applied(self, api):
        """PRD §3.4: "The base is the submitted word count multiplied by the
        rate. A revision surcharge percentage is then taken as the lesser of ten
        percent per completed revision cycle and a hard cap of thirty percent;
        the surcharge amount — base times that percentage, rounded half up to
        whole cents — is added to the base. When `rush` is true the surcharged
        amount is multiplied by 1.25 and rounded half up again; otherwise the
        surcharged amount stands."
        PRD §3.4: "Settlement then moves money: the contract's `committed_cents`
        drops by the provisional amount while its `spent_cents` rises by the
        final, and the document-owning department's `spent_cents` absorbs the
        final as well."

        Design: Difficulty/combinatorial_formula/translation_final_cost_revision_cap_and_rush
        """
        ws, job, approved = self._approve_after_five_revisions()
        # base = 10000 x 20 = 200000; surcharge = min(5 x 10%, 30%) = 30%
        # -> +60000; rush x1.25 -> 260000 x 1.25 = 325000.
        assert approved["final_cost_cents"] == 325000, (
            "the revision surcharge must cap at 30% before the rush multiplier"
        )
        contract = get_contract(ws["contract"]["id"])
        assert contract["spent_cents"] == 325000
        assert contract["committed_cents"] == 0, (
            "approval settles the provisional commitment into spend"
        )


class TestJobInitialState:
    def test_job_created_in_queued_initial_state(self, api, coordinator_headers):
        """PRD §3.4: "The provisional price — `word_count` multiplied by the
        contract's `translation_per_word_cents` — is computed and stored as
        `provisional_cost_cents` and committed against the ceiling at creation,
        subject to the §3.3 ceiling gate (`ERR_CONTRACT_CEILING_EXCEEDED`). The
        job lands in `QUEUED`."
        PRD §3.4: "incrementing `revision_count` — zero when the job is first
        queued — by one while leaving the translator assignment unchanged."
        PRD §3.4: "The result, null until this moment, is stored as
        `final_cost_cents`."

        Design: Corner/state_machines/job_created_in_queued_initial_state
        """
        dept = create_department(name="Dept Init", annual_budget_cents=100000)
        contract = create_active_contract(vendor_name="VendorInit",
                                          ceiling_cents=500000)
        document = create_document(dept["id"], title="Init Doc",
                                   document_type="GUIDE")
        job = create_translation_job(document["id"], contract["id"],
                                     target_language_code="es", word_count=1000)
        assert_translation_job(job)
        assert job["status"] == "QUEUED"
        assert job["revision_count"] == 0
        assert job["provisional_cost_cents"] == 20000
        assert job["final_cost_cents"] is None
        contract_after = get_contract(contract["id"])
        assert contract_after["committed_cents"] == 20000, (
            "the provisional commitment must be visible immediately"
        )


class TestJobCancellation:
    def test_cancel_approved_job_returns_invalid_transition(self, api):
        """PRD §3.4: "Cancellation — invoked explicitly by the Coordinator or
        driven by system cascades such as document retirement and contract
        exhaustion — is permitted from `QUEUED`, `IN_TRANSLATION`, or
        `QUALITY_REVIEW`; from any other state it fails with
        `ERR_INVALID_TRANSITION`."

        Design: Corner/state_machines/cancel_approved_job_returns_invalid_transition
        """
        ws = setup_translation_workspace(word_rate=20, ceiling_cents=500000)
        job = create_job_in_quality_review(ws, word_count=100,
                                           submitted_word_count=100)
        review_job(job["id"], ws["reviewer"]["id"], "APPROVE")
        contract_before = get_contract(ws["contract"]["id"])
        assert contract_before["spent_cents"] == 2000

        resp = api.cancel_translation_job(job["id"], COORDINATOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_TRANSITION.value)
        assert get_translation_job(job["id"])["status"] == "APPROVED"
        assert get_contract(ws["contract"]["id"])["spent_cents"] == 2000, (
            "no compensation may fire for a terminal job"
        )


class TestDocumentRetirement:
    def test_retire_document_cascades_cancel_queued_job(self, api, coordinator_headers):
        """PRD §3.4: "Retiring a document is a Coordinator action valid only from
        `ACTIVE` (else `ERR_INVALID_TRANSITION`) that lands the document in
        `RETIRED` and cascades exactly such a cancellation through every one of
        its jobs still in `QUEUED`, `IN_TRANSLATION`, or `QUALITY_REVIEW`,
        releasing each provisional commitment in turn."

        Design: Corner/state_machines/retire_document_cascades_cancel_queued_job
        """
        dept = create_department(name="Dept Retire", annual_budget_cents=100000)
        contract = create_active_contract(vendor_name="VendorRetire",
                                          ceiling_cents=500000)
        document = create_document(dept["id"], title="Retire Doc",
                                   document_type="POLICY")
        job = create_translation_job(document["id"], contract["id"],
                                     target_language_code="es", word_count=1000)
        retired = validate_success(api.retire_document(document["id"],
                                                       coordinator_headers))
        assert retired["status"] == "RETIRED"
        assert get_translation_job(job["id"])["status"] == "CANCELLED", (
            "retirement cascades cancellation to non-terminal jobs"
        )
        assert get_contract(contract["id"])["committed_cents"] == 0, (
            "each cascaded cancellation releases its provisional commitment"
        )


class TestSupersession:
    def test_approve_supersedes_prior_approved_job(self, api, coordinator_headers):
        """PRD §3.4: "Finally, any previously `APPROVED` job for the same
        document and target language becomes `SUPERSEDED` with its
        `superseded_by_job_id` pointing at the newly approved job, and the
        document's `translated_language_codes` is recomputed."
        PRD §3.4: "the sorted, de-duplicated set of target languages from the
        document's `APPROVED` translation jobs, excluding any job that has since
        been `SUPERSEDED`."

        Design: Corner/state_machines/approve_supersedes_prior_approved_job
        """
        ws = setup_translation_workspace(word_rate=20, ceiling_cents=500000)
        doc_id = ws["document"]["id"]
        job1 = create_job_in_quality_review(ws, word_count=1000,
                                            submitted_word_count=1000)
        review_job(job1["id"], ws["reviewer"]["id"], "APPROVE")
        job2 = create_job_in_quality_review(ws, word_count=500,
                                            submitted_word_count=500)
        approved2 = review_job(job2["id"], ws["reviewer"]["id"], "APPROVE")

        assert approved2["status"] == "APPROVED"
        assert approved2["final_cost_cents"] == 10000
        job1_after = get_translation_job(job1["id"])
        assert job1_after["status"] == "SUPERSEDED"
        assert job1_after["superseded_by_job_id"] == job2["id"]
        document = validate_success(api.get_document(doc_id, coordinator_headers))
        assert document["translated_language_codes"] == ["es"], (
            "the superseded job is excluded; the language appears exactly once"
        )
        assert get_contract(ws["contract"]["id"])["spent_cents"] == 30000


class TestReviewerGates:
    def test_reviewer_tier_insufficient_error(self, api):
        """PRD §3.4: "Review is performed by a `QualityReviewer` whose identity
        must resolve to an existing interpreter record
        (`ERR_INTERPRETER_NOT_FOUND`) holding the `CERTIFIED` tier
        (`ERR_REVIEWER_TIER_INSUFFICIENT`) and differing from the job's
        translator (`ERR_SEGREGATION_OF_DUTIES_VIOLATION`)"

        Design: Corner/errors/reviewer_tier_insufficient_error
        """
        ws = setup_translation_workspace(translator_tier="CERTIFIED",
                                         reviewer_tier="REGISTERED")
        job = create_job_in_quality_review(ws, word_count=100,
                                           submitted_word_count=100)
        # REGISTERED reviewer: tier gate fails even though this is not the
        # translator (segregation is satisfied).
        resp = api.review_translation_job(
            job["id"], {"decision": "APPROVE"},
            make_reviewer_headers(ws["reviewer"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_REVIEWER_TIER_INSUFFICIENT.value)
        assert get_translation_job(job["id"])["status"] == "QUALITY_REVIEW"

    def test_reviewer_cannot_review_own_translation(self, api):
        """PRD §3.4: "Review is performed by a `QualityReviewer` whose identity
        must resolve to an existing interpreter record
        (`ERR_INTERPRETER_NOT_FOUND`) holding the `CERTIFIED` tier
        (`ERR_REVIEWER_TIER_INSUFFICIENT`) and differing from the job's
        translator (`ERR_SEGREGATION_OF_DUTIES_VIOLATION`)"

        Design: Corner/rbac/reviewer_cannot_review_own_translation
        """
        ws = setup_translation_workspace(translator_tier="CERTIFIED")
        job = create_job_in_quality_review(ws, word_count=100,
                                           submitted_word_count=100)
        # The translator holds CERTIFIED, so the tier gate passes and the
        # segregation-of-duties rule is what rejects the review.
        resp = api.review_translation_job(
            job["id"], {"decision": "APPROVE"},
            make_reviewer_headers(ws["translator"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION.value)
        job_after = get_translation_job(job["id"])
        assert job_after["status"] == "QUALITY_REVIEW"
        assert job_after["reviewer_id"] is None


class TestAssignGates:
    def test_assign_confidentiality_not_current_error(self, api):
        """PRD §3.4: "their confidentiality must be current, meaning
        `confidentiality_signed_at` is set to an instant no earlier than 365
        days before the current logical time
        (`ERR_CONFIDENTIALITY_NOT_CURRENT`)"

        Design: Corner/errors/assign_confidentiality_not_current_error
        """
        dept = create_department(name="Dept Conf", annual_budget_cents=100000)
        contract = create_active_contract(vendor_name="VendorConf",
                                          ceiling_cents=500000)
        translator = create_interpreter(contract["id"], full_name="NoConf Ned",
                                        tier="REGISTERED",
                                        sign_confidentiality=False)
        document = create_document(dept["id"], title="Conf Doc")
        job = create_translation_job(document["id"], contract["id"],
                                     target_language_code="es", word_count=100)
        resp = api.assign_translation_job(
            job["id"], {"translator_id": translator["id"]}, COORDINATOR)
        validate_error(resp, ApiErrorId.ERR_CONFIDENTIALITY_NOT_CURRENT.value)
        job_after = get_translation_job(job["id"])
        assert job_after["status"] == "QUEUED"
        assert job_after["translator_id"] is None

    def test_assign_provisional_tier_rejected(self, api):
        """PRD §3.4: "the `target_language_code` must appear among the
        interpreter's `language_codes` (`ERR_VALIDATION`); and the interpreter's
        `tier` must be `REGISTERED` or `CERTIFIED`
        (`ERR_TRANSLATOR_TIER_INSUFFICIENT`)."

        Design: Corner/errors/assign_provisional_tier_rejected
        """
        dept = create_department(name="Dept Prov", annual_budget_cents=100000)
        contract = create_active_contract(vendor_name="VendorProv",
                                          ceiling_cents=500000)
        translator = create_interpreter(contract["id"], full_name="Prov Pat",
                                        tier="PROVISIONAL")
        document = create_document(dept["id"], title="Prov Doc")
        job = create_translation_job(document["id"], contract["id"],
                                     target_language_code="es", word_count=100)
        resp = api.assign_translation_job(
            job["id"], {"translator_id": translator["id"]}, COORDINATOR)
        validate_error(resp, ApiErrorId.ERR_TRANSLATOR_TIER_INSUFFICIENT.value)
        assert get_translation_job(job["id"])["status"] == "QUEUED"

    def test_assign_suspended_interpreter_rejected(self, api):
        """PRD §3.4: "that interpreter must be `ACTIVE`
        (`ERR_INTERPRETER_SUSPENDED`)"

        Design: Corner/errors/assign_suspended_interpreter_rejected
        """
        dept = create_department(name="Dept Susp", annual_budget_cents=100000)
        contract = create_active_contract(vendor_name="VendorSusp",
                                          ceiling_cents=500000)
        translator = create_interpreter(contract["id"], full_name="Susp Sam",
                                        tier="CERTIFIED")
        validate_success(api.patch_interpreter(
            translator["id"], {"status": "SUSPENDED"}, make_officer_headers()))
        document = create_document(dept["id"], title="Susp Doc")
        job = create_translation_job(document["id"], contract["id"],
                                     target_language_code="es", word_count=100)
        resp = api.assign_translation_job(
            job["id"], {"translator_id": translator["id"]}, COORDINATOR)
        validate_error(resp, ApiErrorId.ERR_INTERPRETER_SUSPENDED.value)
        assert get_translation_job(job["id"])["status"] == "QUEUED"


class TestPipelineNotFound:
    def test_get_document_not_found_returns_404(self, api, coordinator_headers):
        """PRD §2.8: "Each unresolvable reference produces the not-found
        identifier for its own resource type: `ERR_DEPARTMENT_NOT_FOUND`,
        `ERR_ASSESSMENT_NOT_FOUND`, `ERR_DOCUMENT_NOT_FOUND`, `ERR_JOB_NOT_FOUND`,
        `ERR_INTERPRETER_NOT_FOUND`, `ERR_REQUEST_NOT_FOUND`,
        `ERR_CONTRACT_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND`, or
        `ERR_PLAN_NOT_FOUND`."

        Design: Corner/errors/get_document_not_found_returns_404
        """
        resp = api.get_document(NON_EXISTENT_UUID, coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_DOCUMENT_NOT_FOUND.value)

    def test_get_job_not_found_returns_404(self, api, coordinator_headers):
        """PRD §2.8: "Each unresolvable reference produces the not-found
        identifier for its own resource type: `ERR_DEPARTMENT_NOT_FOUND`,
        `ERR_ASSESSMENT_NOT_FOUND`, `ERR_DOCUMENT_NOT_FOUND`, `ERR_JOB_NOT_FOUND`,
        `ERR_INTERPRETER_NOT_FOUND`, `ERR_REQUEST_NOT_FOUND`,
        `ERR_CONTRACT_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND`, or
        `ERR_PLAN_NOT_FOUND`."

        Design: Corner/errors/get_job_not_found_returns_404
        """
        resp = api.get_translation_job(NON_EXISTENT_UUID, coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_JOB_NOT_FOUND.value)
