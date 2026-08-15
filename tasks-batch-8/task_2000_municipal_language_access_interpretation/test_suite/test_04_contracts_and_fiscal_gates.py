"""Vendor contract accounting: ceilings, exhaustion, cascades, fiscal gates."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    NON_EXISTENT_UUID,
    activate_contract,
    assert_translation_job,
    assign_translator,
    create_active_contract,
    create_contract,
    create_department,
    create_document,
    create_job_in_quality_review,
    create_translation_job,
    get_contract,
    get_translation_job,
    review_job,
    setup_translation_workspace,
    submit_translation,
    validate_error,
    validate_paginated,
    validate_success,
)

COORDINATOR = TEST_USERS["coordinator_headers"]


class TestValidationOrderingStateBeforeFiscal:
    def _retired_document_and_tight_contract(self, api):
        dept = create_department(name="Dept Aging", service_area_code="SA-8")
        contract = create_active_contract(vendor_name="VendorEight",
                                          ceiling_cents=100)
        document = create_document(dept["id"], title="Old Form",
                                   document_type="FORM")
        validate_success(api.retire_document(document["id"], COORDINATOR))
        return dept, contract, document

    def test_retired_document_error_wins_over_ceiling(self, api):
        """PRD §2.10: "Incoming writes are checked against an ordered cascade,
        and an earlier failure masks every later check."
        PRD §2.10: "The target entity sits in a valid from-state for the
        requested transition (`ERR_INVALID_TRANSITION`); a new translation job
        additionally requires an `ACTIVE` document (`ERR_DOCUMENT_RETIRED`) and
        an `ACTIVE` contract (`ERR_CONTRACT_NOT_ACTIVE`)."
        PRD §2.10: "A new job's provisional commitment must fit under the
        contract ceiling, equality allowed (`ERR_CONTRACT_CEILING_EXCEEDED`)"

        Design: Difficulty/priority_pair_validation_conflict/job_create_retired_document_state_beats_ceiling_fiscal
        """
        _, contract, document = self._retired_document_and_tight_contract(api)
        # 1000 words x 20c = 20000 cents would overflow the 100-cent ceiling,
        # but the retired-document state failure is earlier in the cascade.
        resp = api.create_translation_job(
            {"document_id": document["id"], "vendor_contract_id": contract["id"],
             "target_language_code": "es", "word_count": 1000},
            COORDINATOR,
        )
        validate_error(resp, ApiErrorId.ERR_DOCUMENT_RETIRED.value)

    def test_rejected_job_leaves_no_commitment(self, api):
        """PRD §2.10: "Incoming writes are checked against an ordered cascade,
        and an earlier failure masks every later check."
        PRD §3.4: "The provisional price — `word_count` multiplied by the
        contract's `translation_per_word_cents` — is computed and stored as
        `provisional_cost_cents` and committed against the ceiling at creation"

        Design: Difficulty/priority_pair_validation_conflict/job_create_retired_document_state_beats_ceiling_fiscal
        """
        _, contract, document = self._retired_document_and_tight_contract(api)
        resp = api.create_translation_job(
            {"document_id": document["id"], "vendor_contract_id": contract["id"],
             "target_language_code": "es", "word_count": 1000},
            COORDINATOR,
        )
        validate_error(resp, ApiErrorId.ERR_DOCUMENT_RETIRED.value)
        contract_after = get_contract(contract["id"])
        assert contract_after["committed_cents"] == 0, (
            "a rejected creation must not leak a provisional commitment"
        )


class TestJobRequiresActiveContract:
    def _dept_doc_and_draft_contract(self):
        dept = create_department(name="Dept Streets", service_area_code="SA-12")
        contract = create_contract(vendor_name="VendorTen", ceiling_cents=1_000_000)
        document = create_document(dept["id"], title="Sweeping Schedule",
                                   document_type="NOTICE")
        return dept, contract, document

    def test_job_create_rejected_while_contract_draft(self, api):
        """PRD §3.4: "Creation refuses a `RETIRED` document with
        `ERR_DOCUMENT_RETIRED`, a contract not in `ACTIVE` status with
        `ERR_CONTRACT_NOT_ACTIVE`, and a document-owning department in
        `NONCOMPLIANT` posture with `ERR_DEPARTMENT_NONCOMPLIANT`."

        Design: Difficulty/cross_entity_state_dependency/job_create_requires_active_contract
        """
        _, contract, document = self._dept_doc_and_draft_contract()
        resp = api.create_translation_job(
            {"document_id": document["id"], "vendor_contract_id": contract["id"],
             "target_language_code": "es", "word_count": 100},
            COORDINATOR,
        )
        validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_ACTIVE.value)

    def test_job_create_succeeds_after_activation(self, api):
        """PRD §3.4: "Creation refuses a `RETIRED` document with
        `ERR_DOCUMENT_RETIRED`, a contract not in `ACTIVE` status with
        `ERR_CONTRACT_NOT_ACTIVE`, and a document-owning department in
        `NONCOMPLIANT` posture with `ERR_DEPARTMENT_NONCOMPLIANT`."
        PRD §3.3: "A contract begins in `DRAFT` with `committed_cents` and
        `spent_cents` at zero and becomes billable only when the Coordinator
        activates it, moving `DRAFT` → `ACTIVE`"

        Design: Difficulty/cross_entity_state_dependency/job_create_requires_active_contract
        """
        _, contract, document = self._dept_doc_and_draft_contract()
        blocked = api.create_translation_job(
            {"document_id": document["id"], "vendor_contract_id": contract["id"],
             "target_language_code": "es", "word_count": 100},
            COORDINATOR,
        )
        validate_error(blocked, ApiErrorId.ERR_CONTRACT_NOT_ACTIVE.value)

        activate_contract(contract["id"])
        job = validate_success(api.create_translation_job(
            {"document_id": document["id"], "vendor_contract_id": contract["id"],
             "target_language_code": "es", "word_count": 100},
            COORDINATOR,
        ), 201)
        assert_translation_job(job)
        assert job["status"] == "QUEUED"
        assert job["provisional_cost_cents"] == 2000


class TestCeilingBoundary:
    def _tight_ceiling_workspace(self):
        dept = create_department(name="Dept Finance", service_area_code="SA-11")
        contract = create_active_contract(vendor_name="VendorNine",
                                          ceiling_cents=100000)
        document = create_document(dept["id"], title="Budget Notice",
                                   document_type="NOTICE")
        return dept, contract, document

    def test_commitments_exactly_at_ceiling_allowed(self, api):
        """PRD §3.3: "A new commitment is admitted only while existing
        commitments plus settled spend plus the prospective amount still fit
        under the ceiling — an exact fit is allowed — so job creation that would
        overflow fails with `ERR_CONTRACT_CEILING_EXCEEDED`"

        Design: Difficulty/boundary_precision_check/contract_ceiling_exact_cent_allowed_one_cent_over_rejected
        """
        _, contract, document = self._tight_ceiling_workspace()
        job1 = create_translation_job(document["id"], contract["id"],
                                      target_language_code="es", word_count=4500)
        job2 = create_translation_job(document["id"], contract["id"],
                                      target_language_code="fr", word_count=500)
        assert job1["provisional_cost_cents"] == 90000
        assert job2["provisional_cost_cents"] == 10000
        contract_after = get_contract(contract["id"])
        assert contract_after["committed_cents"] == 100000, (
            "commitments totalling exactly the ceiling must be admitted"
        )
        assert contract_after["committed_cents"] == contract_after["ceiling_cents"]

    def test_one_cent_over_ceiling_rejected(self, api):
        """PRD §3.3: "A new commitment is admitted only while existing
        commitments plus settled spend plus the prospective amount still fit
        under the ceiling — an exact fit is allowed — so job creation that would
        overflow fails with `ERR_CONTRACT_CEILING_EXCEEDED`"

        Design: Difficulty/boundary_precision_check/contract_ceiling_exact_cent_allowed_one_cent_over_rejected
        """
        _, contract, document = self._tight_ceiling_workspace()
        create_translation_job(document["id"], contract["id"],
                               target_language_code="es", word_count=4500)
        create_translation_job(document["id"], contract["id"],
                               target_language_code="fr", word_count=500)
        # One more word costs 20 cents: 100020 > 100000.
        resp = api.create_translation_job(
            {"document_id": document["id"], "vendor_contract_id": contract["id"],
             "target_language_code": "vi", "word_count": 1},
            COORDINATOR,
        )
        validate_error(resp, ApiErrorId.ERR_CONTRACT_CEILING_EXCEEDED.value)
        assert get_contract(contract["id"])["committed_cents"] == 100000, (
            "a rejected creation must leave the committed ledger unchanged"
        )


class TestCommitmentInvariant:
    def test_job_creation_commits_provisional_cost(self, api):
        """PRD §3.3: "`available_cents` is the ceiling minus both pockets."
        PRD §3.4: "The provisional price — `word_count` multiplied by the
        contract's `translation_per_word_cents` — is computed and stored as
        `provisional_cost_cents` and committed against the ceiling at creation"

        Design: Difficulty/compensating_invariant/contract_commitment_create_cancel_restores_available
        """
        dept = create_department(name="Dept Forestry", service_area_code="SA-16")
        contract = create_active_contract(vendor_name="VendorTwelve",
                                          ceiling_cents=500000)
        document = create_document(dept["id"], title="Fire Safety Guide",
                                   document_type="GUIDE")
        job = create_translation_job(document["id"], contract["id"],
                                     target_language_code="es", word_count=1000)
        assert job["provisional_cost_cents"] == 20000
        contract_after = get_contract(contract["id"])
        assert contract_after["committed_cents"] == 20000
        assert contract_after["available_cents"] == 480000
        assert (contract_after["committed_cents"] + contract_after["spent_cents"]
                + contract_after["available_cents"]
                == contract_after["ceiling_cents"]), (
            "committed + spent + available must always equal the ceiling"
        )

    def test_cancel_releases_commitment_exactly(self, api):
        """PRD §3.4: "Every such cancellation releases the job's provisional
        commitment from the contract's `committed_cents`."
        PRD §3.3: "`available_cents` is the ceiling minus both pockets."

        Design: Difficulty/compensating_invariant/contract_commitment_create_cancel_restores_available
        """
        dept = create_department(name="Dept Forestry", service_area_code="SA-16")
        contract = create_active_contract(vendor_name="VendorTwelve",
                                          ceiling_cents=500000)
        document = create_document(dept["id"], title="Fire Safety Guide",
                                   document_type="GUIDE")
        job = create_translation_job(document["id"], contract["id"],
                                     target_language_code="es", word_count=1000)
        cancelled = validate_success(api.cancel_translation_job(job["id"],
                                                                COORDINATOR))
        assert cancelled["status"] == "CANCELLED"
        contract_after = get_contract(contract["id"])
        assert contract_after["committed_cents"] == 0
        assert contract_after["spent_cents"] == 0
        assert contract_after["available_cents"] == 500000, (
            "the create/cancel pair must restore the invariant exactly"
        )


class TestContractExhaustion:
    def _exhaustion_workspace(self):
        ws = setup_translation_workspace(word_rate=20, ceiling_cents=100000)
        job_a = create_translation_job(ws["document"]["id"], ws["contract"]["id"],
                                       target_language_code="es", word_count=4500)
        job_b = create_translation_job(ws["document"]["id"], ws["contract"]["id"],
                                       target_language_code="fr", word_count=500)
        assign_translator(job_a["id"], ws["translator"]["id"])
        submit_translation(job_a["id"], ws["translator"]["id"], 4500)
        return ws, job_a, job_b

    def test_approval_at_ninety_percent_exhausts_contract(self, api):
        """PRD §3.3: "Exhaustion is automatic rather than declared: whenever
        `spent_cents` recomputes to at least ninety percent of `ceiling_cents`,
        the contract moves `ACTIVE` → `EXHAUSTED`."
        PRD §3.4: "Settlement then moves money: the contract's `committed_cents`
        drops by the provisional amount while its `spent_cents` rises by the
        final"

        Design: Difficulty/transitive_cascade/translation_approval_exhaustion_cancels_queued_jobs
        """
        ws, job_a, _ = self._exhaustion_workspace()
        approved = review_job(job_a["id"], ws["reviewer"]["id"], "APPROVE")
        assert approved["status"] == "APPROVED"
        assert approved["final_cost_cents"] == 90000
        contract = get_contract(ws["contract"]["id"])
        assert contract["spent_cents"] == 90000, (
            "90000 of the 100000 ceiling is exactly the ninety-percent mark"
        )
        assert contract["status"] == "EXHAUSTED"

    def test_exhaustion_cancels_queued_job_and_releases(self, api):
        """PRD §3.3: "The transition immediately cancels every `QUEUED`
        translation job billed to the contract and releases each one's
        provisional commitment."
        PRD §3.4: "If the contract's spend thereby reaches at least ninety
        percent of its ceiling, contract exhaustion fires with its `QUEUED`-job
        cancellation cascade."

        Design: Difficulty/transitive_cascade/translation_approval_exhaustion_cancels_queued_jobs
        """
        ws, job_a, job_b = self._exhaustion_workspace()
        review_job(job_a["id"], ws["reviewer"]["id"], "APPROVE")
        assert get_translation_job(job_b["id"])["status"] == "CANCELLED", (
            "the unrelated QUEUED job is cancelled by the exhaustion cascade"
        )
        contract = get_contract(ws["contract"]["id"])
        assert contract["committed_cents"] == 0, (
            "both the settled 90000 and the cascaded 10000 release leave zero"
        )
        assert contract["available_cents"] == 10000

    def test_contract_below_exhaustion_threshold_stays_active(self, api):
        """PRD §3.3: "Exhaustion is automatic rather than declared: whenever
        `spent_cents` recomputes to at least ninety percent of `ceiling_cents`,
        the contract moves `ACTIVE` → `EXHAUSTED`."
        PRD §3.3: "`available_cents` is the ceiling minus both pockets."

        Design: Corner/calculations/contract_below_exhaustion_threshold_stays_active
        """
        ws = setup_translation_workspace(word_rate=20, ceiling_cents=100000)
        job = create_job_in_quality_review(ws, word_count=4495,
                                           submitted_word_count=4495)
        approved = review_job(job["id"], ws["reviewer"]["id"], "APPROVE")
        assert approved["final_cost_cents"] == 89900
        contract = get_contract(ws["contract"]["id"])
        assert contract["spent_cents"] == 89900, (
            "89900 is below the 90000 exhaustion threshold"
        )
        assert contract["status"] == "ACTIVE", (
            "below ninety percent no exhaustion transition fires"
        )
        assert contract["committed_cents"] == 0
        assert contract["available_cents"] == 10100


class TestContractAndJobListing:
    def test_translation_jobs_filtered_by_document(self, api, coordinator_headers):
        """PRD §2.3: "List endpoints also accept optional equality filters named
        for the resource's own fields — across the API these are `department_id`,
        `plan_year`, `status`, `document_id`, `vendor_contract_id`,
        `translator_id`, `reviewer_id`, `superseded_by_job_id`, `interpreter_id`,
        `interpretation_request_id`, `language_code`, `modality`, and `tier` —
        alongside `limit` and `offset`."

        Design: Corner/endpoints/translation_jobs_filtered_by_document
        """
        dept = create_department(name="Dept Filt", annual_budget_cents=100000)
        contract = create_active_contract(vendor_name="VendorFilt",
                                          ceiling_cents=500000)
        doc1 = create_document(dept["id"], title="Doc One")
        doc2 = create_document(dept["id"], title="Doc Two")
        job1 = create_translation_job(doc1["id"], contract["id"],
                                      target_language_code="es", word_count=100)
        job2 = create_translation_job(doc2["id"], contract["id"],
                                      target_language_code="fr", word_count=100)
        data, meta = validate_paginated(api.list_translation_jobs(
            coordinator_headers, params={"document_id": doc1["id"]}))
        assert meta["total_count"] == 1
        assert [row["id"] for row in data] == [job1["id"]], (
            f"filter must exclude {job2['id']} which belongs to another document"
        )

    def test_get_contract_not_found_returns_404(self, api, coordinator_headers):
        """PRD §2.8: "Each unresolvable reference produces the not-found
        identifier for its own resource type: `ERR_DEPARTMENT_NOT_FOUND`,
        `ERR_ASSESSMENT_NOT_FOUND`, `ERR_DOCUMENT_NOT_FOUND`, `ERR_JOB_NOT_FOUND`,
        `ERR_INTERPRETER_NOT_FOUND`, `ERR_REQUEST_NOT_FOUND`,
        `ERR_CONTRACT_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND`, or
        `ERR_PLAN_NOT_FOUND`."

        Design: Corner/errors/get_contract_not_found_returns_404
        """
        resp = api.get_vendor_contract(NON_EXISTENT_UUID, coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_FOUND.value)
