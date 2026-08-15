"""Membership application filing, documentation loop, adjudication, and the
application list endpoint."""
from test_helpers import (
    ApiErrorId,
    assert_member,
    assert_membership_application,
    create_member,
    create_membership_application_payload,
    file_application,
    flag_review,
    get_member,
    request_documents_payload,
    setup_charter,
    submit_documents_payload,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

FILER = TEST_USERS["membership_officer_headers"]
DECIDER = TEST_USERS["membership_officer_2_headers"]
CO1 = TEST_USERS["compliance_officer_headers"]


class TestApplicationSyntacticValidation:
    def test_application_missing_basis_rejected(self, api):
        """PRD §2.6: "Required fields must be present, types must be correct,
        enum values must be in range, and basis-dependent field combinations
        must hold — a SEGMENT_MATCH application requires `segment_id`; a FAMILY
        or HOUSEHOLD application requires `sponsor_member_id` and
        `relationship_to_sponsor`; an ADD_SEGMENT amendment requires the
        `proposed_segment_type`, `proposed_segment_descriptor`, and
        `proposed_segment_required_documents` fields; a RETIRE_SEGMENT
        amendment requires a non-empty `retire_segment_ids`. Any failure is
        `ERR_VALIDATION_FAILED` (400)."

        Design: Corner/entities/application_missing_basis_rejected
        """
        resp = api.create_membership_application(
            {"applicant_full_name": "No Basis", "date_of_birth": "1990-01-01",
             "documents_provided": []},
            FILER,
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION_FAILED)

    def test_segment_match_application_requires_segment_id(self, api):
        """PRD §3.3: "a SEGMENT_MATCH application must reference a
        `segment_id`, while FAMILY and HOUSEHOLD applications must name a
        `sponsor_member_id` and a `relationship_to_sponsor`"
        PRD §3.3: "Combinations that do not match the declared basis are
        rejected with `ERR_VALIDATION_FAILED`."

        Design: Corner/entities/segment_match_application_requires_segment_id
        """
        setup_charter()
        resp = api.create_membership_application(
            create_membership_application_payload(
                applicant_full_name="No Seg", basis="SEGMENT_MATCH",
                segment_id=None),
            FILER,
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION_FAILED)


class TestApplicationStateMachine:
    def test_application_approve_from_docs_requested_rejected(self, api):
        """PRD §3.3: "Each leg of the loop requires its matching from-state;
        requesting documents from an application that is not UNDER_REVIEW, or
        submitting against one that is not DOCS_REQUESTED, fails with
        `ERR_APPLICATION_INVALID_STATE`."
        PRD §3.3: "Approval is the gate to membership, and it enforces four
        conditions: `docs_complete` must be true, otherwise
        `ERR_DOCUMENTATION_INCOMPLETE`; a SEGMENT_MATCH application's segment
        must be ACTIVE at approval time, otherwise `ERR_SEGMENT_NOT_ACTIVE`"

        Design: Corner/state_machines/application_approve_from_docs_requested_rejected
        """
        _charter, seg_ids = setup_charter()
        app = file_application(segment_id=seg_ids[0], name="State Sam")
        assert app["docs_complete"] is True
        moved = validate_success(api.request_documents(
            app["id"], request_documents_payload(["ADDRESS_PROOF"]), FILER))
        assert moved["status"] == "DOCS_REQUESTED"
        assert moved["requested_document_codes"] == ["ADDRESS_PROOF"]

        resp = api.approve_membership_application(app["id"], DECIDER)
        validate_error(resp, ApiErrorId.ERR_APPLICATION_INVALID_STATE)

        members, meta = validate_paginated(api.list_members(FILER))
        assert meta["total_count"] == 0, "No Member is created by the rejection"

    def test_application_terminal_lockdown_after_deny(self, api):
        """PRD §3.3: "Denial is available from both UNDER_REVIEW and
        DOCS_REQUESTED, and in either state it demands the same segregation of
        duties — a decider who filed the application is rejected with
        `ERR_SEGREGATION_OF_DUTIES` — records the supplied `denial_reason`, and
        lands the application in DENIED, its other terminal state."

        Design: Corner/state_machines/application_terminal_lockdown_after_deny
        """
        _charter, seg_ids = setup_charter()
        app = file_application(segment_id=seg_ids[0], name="Denied Dan",
                               documents_provided=["GOVERNMENT_ID"])
        denied = validate_success(api.deny_membership_application(
            app["id"], {"denial_reason": "insufficient documentation"},
            DECIDER))
        assert denied["status"] == "DENIED"
        assert denied["denial_reason"] == "insufficient documentation"

        resp = api.approve_membership_application(app["id"], DECIDER)
        validate_error(resp, ApiErrorId.ERR_APPLICATION_INVALID_STATE)


class TestApprovalGates:
    def test_documentation_incomplete_blocks_approval(self, api):
        """PRD §3.3: "Approval is the gate to membership, and it enforces four
        conditions: `docs_complete` must be true, otherwise
        `ERR_DOCUMENTATION_INCOMPLETE`"
        PRD §3.3: "The boolean `docs_complete` is true exactly when every
        required code appears among the `documents_provided`."

        Design: Corner/validations/documentation_incomplete_blocks_approval
        """
        _charter, seg_ids = setup_charter()
        app = file_application(segment_id=seg_ids[0], name="Docs Dana",
                               documents_provided=["GOVERNMENT_ID"])
        assert app["docs_complete"] is False, (
            "EMPLOYER_LETTER is required by the segment and was not provided")

        resp = api.approve_membership_application(app["id"], DECIDER)
        validate_error(resp, ApiErrorId.ERR_DOCUMENTATION_INCOMPLETE)

    def test_sponsor_not_active_at_approval(self, api):
        """PRD §3.3: "a FAMILY or HOUSEHOLD application whose sponsor member is
        not ACTIVE is rejected with `ERR_SPONSOR_NOT_ELIGIBLE`. Both checks are
        re-evaluated at approval time."
        PRD §3.3: "a FAMILY or HOUSEHOLD application's sponsor must be ACTIVE
        at approval time, otherwise `ERR_SPONSOR_NOT_ELIGIBLE`"

        Design: Corner/validations/sponsor_not_active_at_approval
        """
        _charter, seg_ids = setup_charter()
        sponsor = create_member(segment_id=seg_ids[0], name="Sponsor Sue",
                                date_of_birth="1985-01-01")
        app = file_application(
            basis="FAMILY", sponsor_member_id=sponsor,
            relationship_to_sponsor="SPOUSE", name="Family Fred",
            date_of_birth="1992-02-02",
            documents_provided=["GOVERNMENT_ID", "RELATIONSHIP_PROOF"])
        assert app["docs_complete"] is True

        flag_review(sponsor)  # sponsor -> INELIGIBLE_UNDER_REVIEW
        assert get_member(sponsor)["status"] == "INELIGIBLE_UNDER_REVIEW"

        resp = api.approve_membership_application(app["id"], DECIDER)
        validate_error(resp, ApiErrorId.ERR_SPONSOR_NOT_ELIGIBLE)

    def test_segregation_filer_cannot_approve_own_application(self, api):
        """PRD §2.10: "The officer who files a membership application (recorded
        as `filed_by_user_id`) may never be the one who approves or denies it"
        PRD §2.10: "A deciding user whose `X-User-ID` equals the filer's or
        flagger's is rejected with `ERR_SEGREGATION_OF_DUTIES` (403)."

        Design: Corner/validations/segregation_filer_cannot_approve_own_application
        """
        _charter, seg_ids = setup_charter()
        app = file_application(segment_id=seg_ids[0], name="Self Approve")
        assert app["filed_by_user_id"] == "officer-1"

        resp = api.approve_membership_application(app["id"], FILER)
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        approved = validate_success(
            api.approve_membership_application(app["id"], DECIDER))
        assert approved["status"] == "APPROVED"
        assert approved["resulting_member_id"] is not None


class TestDocumentationLoop:
    def _setup_loop(self, api):
        _charter, seg_ids = setup_charter()
        return file_application(segment_id=seg_ids[0], name="Loopy Lou",
                                date_of_birth="1993-03-03",
                                documents_provided=["GOVERNMENT_ID"])

    def test_documentation_loop_first_cycle(self, api):
        """PRD §3.3: "While an application is UNDER_REVIEW, an officer may
        request additional documents, which moves it to DOCS_REQUESTED and
        replaces `requested_document_codes` with the codes named in the
        request. When the applicant's supplemental evidence arrives, submitting
        documents returns the application to UNDER_REVIEW: the newly supplied
        `documents_provided` are unioned with those already on file — earlier
        evidence is never lost — and `docs_complete` is recomputed."

        Design: Difficulty/non_linear_state_machine/application_documentation_loop_cycles_twice
        """
        app = self._setup_loop(api)
        assert app["status"] == "UNDER_REVIEW"
        assert app["docs_complete"] is False

        requested = validate_success(api.request_documents(
            app["id"], request_documents_payload(["EMPLOYER_LETTER"]), FILER))
        assert requested["status"] == "DOCS_REQUESTED"
        assert requested["requested_document_codes"] == ["EMPLOYER_LETTER"]

        back = validate_success(api.submit_documents(
            app["id"], submit_documents_payload(["EMPLOYER_LETTER"]), FILER))
        assert back["status"] == "UNDER_REVIEW"
        assert back["docs_complete"] is True
        assert sorted(back["documents_provided"]) == [
            "EMPLOYER_LETTER", "GOVERNMENT_ID"]

    def test_documentation_loop_cycles_twice_then_approved(self, api):
        """PRD §3.3: "The loop may cycle as many times as the evidence
        demands."
        PRD §3.3: "An approved application becomes APPROVED — terminal — and in
        the same atomic step the system creates the Member: status ACTIVE, tier
        STANDARD, `membership_effective_date` set to the current clock date"

        Design: Difficulty/non_linear_state_machine/application_documentation_loop_cycles_twice
        """
        app = self._setup_loop(api)

        # First traversal of the UNDER_REVIEW <-> DOCS_REQUESTED cycle.
        validate_success(api.request_documents(
            app["id"], request_documents_payload(["EMPLOYER_LETTER"]), FILER))
        validate_success(api.submit_documents(
            app["id"], submit_documents_payload(["EMPLOYER_LETTER"]), FILER))

        # Second traversal — the cycle is re-entered, not locked out.
        second_request = validate_success(api.request_documents(
            app["id"], request_documents_payload(["ADDRESS_PROOF"]), FILER))
        assert second_request["status"] == "DOCS_REQUESTED"
        second_return = validate_success(api.submit_documents(
            app["id"], submit_documents_payload(["ADDRESS_PROOF"]), FILER))
        assert second_return["status"] == "UNDER_REVIEW"

        approved = validate_success(
            api.approve_membership_application(app["id"], DECIDER))
        assert approved["status"] == "APPROVED"
        member_id = approved["resulting_member_id"]
        assert member_id is not None

        member = validate_success(api.get_member(member_id, FILER))
        assert_member(member)
        assert member["status"] == "ACTIVE"
        assert member["tier"] == "STANDARD"
        assert member["membership_effective_date"] == "2026-08-01"


class TestApplicationListing:
    def test_list_envelope_and_pagination_defaults(self, api):
        """PRD §2.2: "The `api_request_id` is a server-generated unique
        identifier for the request that starts with `req_`."
        PRD §2.3: "The `limit` parameter caps the number of items returned: it
        defaults to 10, may not be less than 1, and may not exceed 100. The
        `offset` parameter states how many items to skip and defaults to 0."
        PRD §2.3: "Paginated list responses carry `limit`, `offset`,
        `total_count`, and `has_more` in the `meta` object of the response
        envelope."

        Design: Corner/endpoints/list_envelope_and_pagination_defaults
        """
        _charter, seg_ids = setup_charter()
        file_application(segment_id=seg_ids[0], name="Page Pam",
                         documents_provided=["GOVERNMENT_ID"])

        resp = api.list_membership_applications(FILER)
        body = resp.json()
        assert body["response_type"] == "array"
        assert isinstance(body["meta"]["api_request_id"], str)
        assert body["meta"]["api_request_id"].startswith("req_")
        assert isinstance(body["meta"]["api_request_timestamp"], str)

        data, meta = validate_paginated(resp)
        assert meta["limit"] == 10, "limit defaults to 10"
        assert meta["offset"] == 0, "offset defaults to 0"
        assert meta["total_count"] == 1
        assert meta["has_more"] is False
        assert_membership_application(data[0])

    def test_pagination_limit_offset_and_bounds(self, api):
        """PRD §2.3: "Unless otherwise specified, every list endpoint returns
        its resources sorted by creation timestamp in ascending order."
        PRD §2.3: "The `limit` parameter caps the number of items returned: it
        defaults to 10, may not be less than 1, and may not exceed 100."

        Design: Corner/endpoints/pagination_limit_offset_and_bounds
        """
        _charter, seg_ids = setup_charter()
        app_a = file_application(segment_id=seg_ids[0], name="Page A",
                                 date_of_birth="1990-01-01",
                                 documents_provided=[])
        file_application(segment_id=seg_ids[0], name="Page B",
                         date_of_birth="1990-01-02", documents_provided=[])
        app_c = file_application(segment_id=seg_ids[0], name="Page C",
                                 date_of_birth="1990-01-03",
                                 documents_provided=[])

        page1, meta1 = validate_paginated(api.list_membership_applications(
            FILER, params={"limit": 2, "offset": 0}))
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert len(page1) == 2
        assert page1[0]["id"] == app_a["id"], "created_at ASC ordering"
        assert page1[0]["applicant_full_name"] == "Page A"
        assert page1[1]["applicant_full_name"] == "Page B"

        page2, meta2 = validate_paginated(api.list_membership_applications(
            FILER, params={"limit": 2, "offset": 2}))
        assert meta2["has_more"] is False
        assert len(page2) == 1
        assert page2[0]["id"] == app_c["id"]

        bad = api.list_membership_applications(FILER, params={"limit": 0})
        validate_error(bad, ApiErrorId.ERR_VALIDATION_FAILED)
