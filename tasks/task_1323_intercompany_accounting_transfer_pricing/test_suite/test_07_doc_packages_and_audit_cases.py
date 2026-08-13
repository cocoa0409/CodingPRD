"""Documentation packages (review chain, filing obligations, uniqueness) and
audit cases / advance pricing agreements (defense file, branching resolve)."""
from test_helpers import (
    ANALYST,
    MANAGER,
    TP_LEAD,
    ApiErrorId,
    create_approved_doc,
    create_audit_case,
    create_doc,
    create_fiscal_year,
    create_legal_entity,
    make_tax_analyst_headers,
    make_tax_manager_headers,
    setup_apa_locked_agreement,
    submit_doc,
    validate_error,
    validate_success,
    api_client,
)


class TestDocReviewChain:

    def test_doc_approve_from_draft_rejected(self):
        """PRD section 3.6: "The package then walks a three-step review
        chain. Submission by a `TaxAnalyst` (`DRAFT → SUBMITTED`) records
        `submitted_by_user_id`. Approval by a `TaxManager` (`SUBMITTED →
        APPROVED`) is segregation-guarded against the submitter
        (`ERR_SEGREGATION_OF_DUTIES`) and records `approved_by_user_id`."
        PRD section 2.8: "4. **State legality** — the target resource must be
        in a state from which the requested transition or operation is
        defined, else `ERR_INVALID_STATE_TRANSITION` (HTTP 409)."

        Design: Corner/state_machines/doc_approve_from_draft_rejected
        """
        fy = create_fiscal_year()
        doc = create_doc(fy["id"], "MASTER_FILE")

        resp = api_client.approve_doc_package(doc["id"], MANAGER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

        after = validate_success(api_client.get_doc_package(doc["id"], MANAGER),
                                 200)
        assert after["status"] == "DRAFT"

    def test_analyst_cannot_approve_submitted_doc(self):
        """PRD section 2.1: "Each write endpoint admits a specific subset of
        these roles (enumerated in §4); a caller whose role is not admitted
        by the endpoint is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP
        403)."
        PRD section 4: the doc-package approve endpoint admits TaxManager.

        Design: Corner/validations/analyst_cannot_approve_submitted_doc
        """
        fy = create_fiscal_year()
        doc = create_doc(fy["id"], "MASTER_FILE")
        submit_doc(doc["id"])

        # A second analyst (different user id, still the TaxAnalyst role).
        resp = api_client.approve_doc_package(
            doc["id"], make_tax_analyst_headers("ana-2"))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

        after = validate_success(api_client.get_doc_package(doc["id"], MANAGER),
                                 200)
        assert after["status"] == "SUBMITTED"

    def test_same_user_approve_rejected_segregation(self):
        """PRD section 2.10: "Preparer and approver are always different
        people. Five operations enforce this by comparing the acting
        `X-User-ID` against a stored user identifier on the target resource:
        ... approving a documentation package compares against
        `submitted_by_user_id`. In each case, an approver whose `X-User-ID`
        equals the stored identifier is rejected with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 409)."

        Design: Corner/validations/same_user_approve_rejected_segregation
        """
        fy = create_fiscal_year()
        doc = create_doc(fy["id"], "MASTER_FILE")
        submit_doc(doc["id"])  # submitted_by_user_id == ana-1

        # Same person (ana-1) acting in the TaxManager capacity.
        resp = api_client.approve_doc_package(
            doc["id"], make_tax_manager_headers("ana-1"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        after = validate_success(api_client.get_doc_package(doc["id"], MANAGER),
                                 200)
        assert after["status"] == "SUBMITTED"


class TestFilingObligations:

    def test_cbc_filing_when_not_required_rejected(self):
        """PRD section 3.6: "Filing by a `TaxManager` (`APPROVED → FILED`)
        enforces three obligations: the fiscal year must not be `CLOSED`
        (`ERR_BOOKS_CLOSED`); a `CBC_REPORT` may only be filed for a year
        whose `cbc_required` is true (`ERR_CBC_NOT_REQUIRED`)"

        Design: Corner/errors/cbc_filing_when_not_required_rejected
        """
        fy = create_fiscal_year(year_index=2026, group_revenue_eur=600_000_000)
        assert fy["cbc_required"] is False
        doc = create_approved_doc(fy["id"], "CBC_REPORT")

        resp = api_client.file_doc_package(doc["id"], MANAGER)
        validate_error(resp, ApiErrorId.ERR_CBC_NOT_REQUIRED)

        after = validate_success(api_client.get_doc_package(doc["id"], MANAGER),
                                 200)
        assert after["status"] == "APPROVED"

    def test_duplicate_cbc_report_rejected(self):
        """PRD section 3.6: "At most one `CBC_REPORT` package may exist per
        fiscal year; a second is rejected with `ERR_DUPLICATE_CBC_REPORT`."

        Design: Corner/errors/duplicate_cbc_report_rejected
        """
        fy = create_fiscal_year(year_index=2026, group_revenue_eur=800_000_000)
        create_doc(fy["id"], "CBC_REPORT")

        resp = api_client.create_doc_package(
            {"fiscal_year_id": fy["id"], "doc_type": "CBC_REPORT"}, ANALYST)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_CBC_REPORT)

        # A MASTER_FILE for the same year is unaffected.
        master = validate_success(
            api_client.create_doc_package(
                {"fiscal_year_id": fy["id"], "doc_type": "MASTER_FILE"},
                ANALYST),
            expected_status=201)
        assert master["status"] == "DRAFT"


class TestDefenseFile:

    def test_audit_case_first_attach_auto_advances(self):
        """PRD section 3.7: "Each attachment names a `doc_package_id` and
        requires the package to be `APPROVED` or `FILED` (`ERR_DOC_NOT_FINAL`);
        the identifier is appended to `defense_doc_ids` in order. The first
        successful attachment automatically advances the case `OPENED →
        ACTIVE_PREP`; subsequent attachments are self-transitions within
        `ACTIVE_PREP`."

        Design: Corner/state_machines/audit_case_first_attach_auto_advances
        """
        fy = create_fiscal_year()
        entity = create_legal_entity()
        doc = create_approved_doc(fy["id"], "MASTER_FILE")
        case = create_audit_case(entity["id"], case_type="AUDIT")
        assert case["status"] == "OPENED"
        assert case["defense_doc_ids"] == []

        resp = api_client.attach_doc(case["id"], {"doc_package_id": doc["id"]},
                                     TP_LEAD)
        attached = validate_success(resp, 200)
        assert attached["status"] == "ACTIVE_PREP", \
            "first successful attach auto-advances the case"
        assert attached["defense_doc_ids"] == [doc["id"]]

    def test_attach_draft_doc_rejected(self):
        """PRD section 3.7: "Each attachment names a `doc_package_id` and
        requires the package to be `APPROVED` or `FILED`
        (`ERR_DOC_NOT_FINAL`)"

        Design: Corner/errors/attach_draft_doc_rejected
        """
        fy = create_fiscal_year()
        entity = create_legal_entity()
        doc = create_doc(fy["id"], "MASTER_FILE")  # stays DRAFT
        case = create_audit_case(entity["id"], case_type="AUDIT")

        resp = api_client.attach_doc(case["id"], {"doc_package_id": doc["id"]},
                                     TP_LEAD)
        validate_error(resp, ApiErrorId.ERR_DOC_NOT_FINAL)

        after = validate_success(api_client.get_audit_case(case["id"], TP_LEAD),
                                 200)
        assert after["status"] == "OPENED", \
            "a failed attach does not auto-advance the case"
        assert after["defense_doc_ids"] == []

    def test_submit_response_without_defense_docs_rejected(self):
        """PRD section 3.7: "When the file is ready, the lead submits the
        response to the authority, moving the case from either `OPENED` or
        `ACTIVE_PREP` to `SUBMITTED_TO_AUTHORITY`; submitting with an empty
        defense file is rejected with `ERR_DEFENSE_FILE_EMPTY` — a business
        error, raised even from `OPENED`, since the submission transition
        itself is defined from both states."

        Design: Corner/errors/submit_response_without_defense_docs_rejected
        """
        entity = create_legal_entity()
        case = create_audit_case(entity["id"], case_type="AUDIT")

        resp = api_client.submit_response(case["id"], TP_LEAD)
        validate_error(resp, ApiErrorId.ERR_DEFENSE_FILE_EMPTY)

        after = validate_success(api_client.get_audit_case(case["id"], TP_LEAD),
                                 200)
        assert after["status"] == "OPENED"


class TestApaYearDisjointness:

    def test_apa_overlapping_years_rejected(self):
        """PRD section 3.7: "An APA case additionally requires
        `covered_year_indexes`, the integer year indexes the arrangement
        covers; those years must be disjoint from the covered years of every
        other APA case for the same entity whose status is `OPENED`,
        `ACTIVE_PREP`, `SUBMITTED_TO_AUTHORITY`, or `CLOSED_AGREED` — a
        resolved APA no longer blocks — and an intersection is rejected with
        `ERR_APA_YEAR_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/apa_covered_year_set_disjointness
        """
        entity = create_legal_entity()
        create_audit_case(entity["id"], case_type="APA",
                          covered_year_indexes=[2024, 2025])

        resp = api_client.create_audit_case(
            {"entity_id": entity["id"], "case_type": "APA",
             "authority_country": "DE", "covered_year_indexes": [2025, 2026]},
            TP_LEAD,
        )
        validate_error(resp, ApiErrorId.ERR_APA_YEAR_OVERLAP)

    def test_apa_disjoint_years_accepted(self):
        """PRD section 3.7: "An APA case additionally requires
        `covered_year_indexes`, the integer year indexes the arrangement
        covers; those years must be disjoint from the covered years of every
        other APA case for the same entity whose status is `OPENED`,
        `ACTIVE_PREP`, `SUBMITTED_TO_AUTHORITY`, or `CLOSED_AGREED` — a
        resolved APA no longer blocks — and an intersection is rejected with
        `ERR_APA_YEAR_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/apa_covered_year_set_disjointness
        """
        entity = create_legal_entity()
        create_audit_case(entity["id"], case_type="APA",
                          covered_year_indexes=[2024, 2025])

        resp = api_client.create_audit_case(
            {"entity_id": entity["id"], "case_type": "APA",
             "authority_country": "DE", "covered_year_indexes": [2026, 2027]},
            TP_LEAD,
        )
        apa3 = validate_success(resp, expected_status=201)
        assert apa3["status"] == "OPENED"


class TestApaLock:

    def test_amendment_blocked_by_apa_lock(self):
        """PRD section 3.7: "Resolving an `APA` case lands in `CLOSED_AGREED`
        and locks the covered pricing: every agreement whose provider or
        recipient is the case entity, whose status is `ACTIVE` or
        `UNDER_AMENDMENT`, and whose effective window covers the first of
        January of at least one year in `covered_year_indexes` — that is,
        `effective_from` on or before that January 1 and `effective_to` after
        it — has its `apa_locked` flag set to true for the APA term. While
        `apa_locked` is true, starting an amendment or terminating the
        agreement is refused with `ERR_APA_LOCKED`, as described in §3.3."

        Design: Corner/errors/amendment_blocked_by_apa_lock_rejected
        """
        ctx = setup_apa_locked_agreement(covered_year_indexes=[2026])
        assert ctx["apa_case"]["status"] == "CLOSED_AGREED"

        agreement = validate_success(
            api_client.get_agreement(ctx["agreement"]["id"], MANAGER), 200)
        assert agreement["apa_locked"] is True

        resp = api_client.start_amendment(ctx["agreement"]["id"],
                                          {"new_markup_bp": 300}, ANALYST)
        validate_error(resp, ApiErrorId.ERR_APA_LOCKED)

        after = validate_success(
            api_client.get_agreement(ctx["agreement"]["id"], MANAGER), 200)
        assert after["status"] == "ACTIVE"
        assert after["markup_bp"] == 200


class TestAuditCaseRbac:

    def test_analyst_cannot_create_audit_case(self):
        """PRD section 2.1: "Each write endpoint admits a specific subset of
        these roles (enumerated in §4); a caller whose role is not admitted
        by the endpoint is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP
        403)."
        PRD section 4: the audit-case creation endpoint admits
        TransferPricingLead.

        Design: Corner/rbac/analyst_cannot_create_audit_case
        """
        entity = create_legal_entity()
        resp = api_client.create_audit_case(
            {"entity_id": entity["id"], "case_type": "AUDIT",
             "authority_country": "US"},
            ANALYST,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

    def test_any_role_can_read_audit_case(self):
        """PRD section 2.1: "All read endpoints are shared: every one of the
        five roles may call any GET operation."

        Design: Corner/rbac/any_role_can_read_audit_case
        """
        entity = create_legal_entity()
        case = create_audit_case(entity["id"], case_type="AUDIT")

        resp = api_client.get_audit_case(case["id"], ANALYST)
        fetched = validate_success(resp, 200)
        assert fetched["id"] == case["id"]
        assert fetched["status"] == "OPENED"
        assert fetched["entity_id"] == entity["id"]
