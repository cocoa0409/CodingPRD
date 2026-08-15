"""Application lifecycle: filing, window deadlines, review, correction loop."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    add_spend_entry,
    approve_application,
    claim_application,
    create_application,
    create_application_payload,
    create_production,
    create_production_payload,
    create_program,
    deny_application,
    engage_audit,
    get_application,
    make_producer_headers,
    make_reviewer_headers,
    open_program,
    register_company,
    register_vendor,
    request_corrections,
    resubmit_application,
    set_logical_clock,
    setup_approved_application,
    submit_application,
    transition_program,
    validate_error,
    validate_paginated,
    validate_success,
    withdraw_application,
)

ADMIN = TEST_USERS["admin_headers"]
REVIEWER1 = TEST_USERS["reviewer1_headers"]
REVIEWER2 = TEST_USERS["reviewer2_headers"]
CPA1 = TEST_USERS["cpa1_headers"]


class TestCreationShape:
    def test_production_create_invalid_enum_returns_invalid_request(self, api):
        """PRD §3.2: "The producer then creates **Production** records under a
        company it owns — a `production_company_id` that does not match the
        caller's identity is rejected with `ERR_NOT_OWNER` — supplying a `title`,
        a `production_type` of `FEATURE`, `SERIES`, `DOCUMENTARY`, or
        `COMMERCIAL`, a `scheduled_start_date` that must fall strictly before the
        `scheduled_wrap_date`, and a positive `total_budget_cents`; violations of
        the date ordering or amount rules are rejected with
        `ERR_INVALID_REQUEST`."

        Design: Corner/entities/production_create_invalid_enum_returns_invalid_request
        """
        company = register_company()
        producer = make_producer_headers(company["id"])
        payload = create_production_payload(company["id"],
                                            production_type="BLOCKBUSTER")
        resp = api.create_production(payload, producer)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        data, meta = validate_paginated(api.list_productions(
            producer, params={"production_company_id": company["id"]}))
        assert data == [], "no production may be persisted on a shape failure"
        assert meta["total_count"] == 0

    def test_application_create_with_unknown_production_returns_not_found(self, api):
        """PRD §2.10: "Requests that carry resource identifiers resolve them in a
        fixed order: identifiers in the path first, from left to right, then
        foreign-key references in the request body. The first identifier that
        does not resolve to an existing resource rejects the request with
        `ERR_NOT_FOUND`, and no further validation runs."

        Design: Corner/entities/application_create_with_unknown_production_returns_not_found
        """
        program = create_program()
        company = register_company()
        producer = make_producer_headers(company["id"])
        payload = create_application_payload(NON_EXISTENT_UUID, program["id"])
        resp = api.create_application(payload, producer)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestInitialStates:
    def test_initial_states_on_creation(self, api):
        """PRD §3.1: "A new program starts in `DRAFT` status with
        `allocated_credit_cents` at zero and `remaining_cap_cents` equal to the
        annual cap."
        PRD §3.3: "A new application starts in `DRAFT` with all computed totals
        at zero, `allocation_share_pct` at zero, `submitted_at` null, and
        `final_credit_cents` null."
        PRD §3.2: "A new vendor starts with `residency_status` `UNVERIFIED`."
        PRD §3.4: "A new entry starts in `PENDING_REVIEW` with
        `effective_amount_cents` at zero"
        PRD §3.5: "The package starts `ENGAGED`, with the caller's operator id
        recorded as `cpa_user_id` and `exception_count` at zero."

        Design: Corner/state_machines/initial_states_on_creation
        """
        program = create_program()
        assert program["status"] == "DRAFT"
        program = transition_program(program, "OPEN")

        company = register_company()
        production = create_production(company)
        app_resp = api.create_application(
            create_application_payload(production["id"], program["id"]),
            make_producer_headers(company["id"]))
        application = validate_success(app_resp, 201)
        assert application["status"] == "DRAFT"
        assert application["atl_qualified_cents"] == 0
        assert application["btl_qualified_cents"] == 0
        assert application["capped_total_qualified_cents"] == 0
        assert application["provisional_credit_cents"] == 0
        assert application["allocation_share_pct"] == 0
        assert application["submitted_at"] is None
        assert application["final_credit_cents"] is None

        submit_application(application, company)
        claim_application(application)
        application = approve_application(application)

        vendor = register_vendor(production, company)
        assert vendor["residency_status"] == "UNVERIFIED"

        entry = add_spend_entry(application, vendor, company, amount_cents=1000)
        assert entry["status"] == "PENDING_REVIEW"
        assert entry["effective_amount_cents"] == 0

        package = engage_audit(application)
        assert package["status"] == "ENGAGED"
        assert package["cpa_user_id"] == "cpa-1"
        assert package["exception_count"] == 0


class TestUniquenessAndWithdrawal:
    def test_second_open_application_rejected_then_allowed_after_withdraw(self, api):
        """PRD §3.3: "Only one open application may exist for a
        production-and-program pair: if another application with the same
        `production_id` and `jurisdiction_program_id` exists in any status other
        than `DENIED`, `WITHDRAWN`, or `REVOKED`, creation is rejected with
        `ERR_APPLICATION_ALREADY_OPEN`; reaching one of those three terminal
        states frees the pair for a fresh filing."

        Design: Corner/validations/second_open_application_rejected_then_allowed_after_withdraw
        """
        program = open_program()
        company = register_company()
        production = create_production(company)
        producer = make_producer_headers(company["id"])
        first = create_application(production, program)

        payload = create_application_payload(
            production["id"], program["id"],
            estimated_qualified_spend_cents=300_000_000)
        blocked = api.create_application(payload, producer)
        validate_error(blocked, ApiErrorId.ERR_APPLICATION_ALREADY_OPEN)

        withdraw_application(first, company)
        freed = api.create_application(payload, producer)
        second = validate_success(freed, 201)
        assert second["status"] == "DRAFT"
        assert second["id"] != first["id"]

    def test_withdraw_after_approval_returns_invalid_state(self, api):
        """PRD §3.3: "Withdrawal is available to the owning producer from
        `DRAFT`, from `SUBMITTED`, from `UNDER_REVIEW`, and from
        `CORRECTION_REQUESTED`, each moving the application to the terminal
        `WITHDRAWN` state."
        PRD §3.3: "Any action attempted from a state where that transition is
        not declared — submitting an application that is not in `DRAFT`, for
        instance — is rejected with `ERR_INVALID_STATE_TRANSITION`."

        Design: Corner/state_machines/withdraw_after_approval_returns_invalid_state
        """
        scenario = setup_approved_application()
        application = scenario.application
        assert application["status"] == "APPROVED"
        resp = api.withdraw_application(
            application["id"], make_producer_headers(scenario.company["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        assert get_application(application)["status"] == "APPROVED"


class TestSubmissionWindow:
    def test_submit_twice_returns_invalid_state(self, api):
        """PRD §3.3: "Any action attempted from a state where that transition is
        not declared — submitting an application that is not in `DRAFT`, for
        instance — is rejected with `ERR_INVALID_STATE_TRANSITION`."

        Design: Corner/state_machines/submit_twice_returns_invalid_state
        """
        program = open_program()
        company = register_company()
        production = create_production(company)
        producer = make_producer_headers(company["id"])
        application = create_application(production, program)
        first = submit_application(application, company)
        assert first["status"] == "SUBMITTED"

        second = api.submit_application(application["id"], producer)
        validate_error(second, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        current = get_application(application)
        assert current["status"] == "SUBMITTED"
        assert current["submitted_at"] == first["submitted_at"], (
            "the rejected second submit must not re-stamp submitted_at")

    def test_submit_before_window_open_rejected(self, api):
        """PRD §3.3: "the clock must have reached `window_opens_at`, or the
        attempt is rejected with `ERR_WINDOW_NOT_YET_OPEN`"

        Design: Corner/validations/submit_before_window_open_rejected
        """
        program = open_program(window_opens_at="2026-09-01T00:00:00Z")
        company = register_company()
        production = create_production(company)
        application = create_application(production, program)
        resp = api.submit_application(
            application["id"], make_producer_headers(company["id"]))
        validate_error(resp, ApiErrorId.ERR_WINDOW_NOT_YET_OPEN)
        assert get_application(application)["status"] == "DRAFT"

    def test_submit_at_exact_deadline_succeeds(self, api):
        """PRD §3.3: "and the clock must not have passed `window_closes_at` —
        the deadline boundary is inclusive, so submission at the exact closing
        instant is allowed, and any later attempt is rejected with
        `ERR_APPLICATION_DEADLINE_PASSED`."
        PRD §3.3: "Submission moves an application from `DRAFT` to `SUBMITTED`
        and stamps `submitted_at` with the logical-clock instant."

        Design: Difficulty/boundary_precision_check/submit_at_exact_deadline_inclusive
        """
        program = open_program(window_closes_at="2027-01-15T12:00:00Z")
        company = register_company()
        production = create_production(company)
        application = create_application(production, program)
        set_logical_clock("2027-01-15T12:00:00Z")

        resp = api.submit_application(
            application["id"], make_producer_headers(company["id"]))
        submitted = validate_success(resp, 200)
        assert submitted["status"] == "SUBMITTED", (
            "submission at exactly window_closes_at is allowed (inclusive)")
        assert submitted["submitted_at"].startswith("2027-01-15T12:00:00"), (
            "submitted_at is stamped with the logical-clock instant")

    def test_submit_one_second_after_deadline_rejected(self, api):
        """PRD §3.3: "and the clock must not have passed `window_closes_at` —
        the deadline boundary is inclusive, so submission at the exact closing
        instant is allowed, and any later attempt is rejected with
        `ERR_APPLICATION_DEADLINE_PASSED`."

        Design: Difficulty/boundary_precision_check/submit_at_exact_deadline_inclusive
        """
        program = open_program(window_closes_at="2027-01-15T12:00:00Z")
        company = register_company()
        production = create_production(company)
        application = create_application(production, program)
        set_logical_clock("2027-01-15T12:00:01Z")

        resp = api.submit_application(
            application["id"], make_producer_headers(company["id"]))
        validate_error(resp, ApiErrorId.ERR_APPLICATION_DEADLINE_PASSED)
        assert get_application(application)["status"] == "DRAFT"


class TestErrorPrecedenceOnSubmit:
    def test_withdrawn_submit_after_deadline_surfaces_state_error(self, api):
        """PRD §2.9: "When a single request violates several rules, the failure
        that surfaces is the one belonging to the earliest category in the
        following evaluation order:"
        PRD §2.9: "5. **State-transition legality** — the target resource is in a
        state from which the requested transition is declared
        (`ERR_INVALID_STATE_TRANSITION`)."
        PRD §2.9: "9. **Temporal windows** — the logical-clock checks on
        submission windows, vendor verification validity, certificate expiry,
        transfer expiry, the appeal window, and the notice quiet period
        (`ERR_WINDOW_NOT_YET_OPEN`, `ERR_APPLICATION_DEADLINE_PASSED`,
        `ERR_VERIFICATION_WINDOW_EXPIRED`, `ERR_CERTIFICATE_EXPIRED`,
        `ERR_TRANSFER_EXPIRED`, `ERR_APPEAL_WINDOW_CLOSED`,
        `ERR_NOTICE_WINDOW_ACTIVE`)."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_temporal_on_deadline_submit
        """
        program = open_program(window_closes_at="2027-01-15T12:00:00Z")
        company = register_company()
        production = create_production(company)
        producer = make_producer_headers(company["id"])
        application = create_application(production, program)
        submit_application(application, company)
        withdraw_application(application, company)
        set_logical_clock("2027-02-01T00:00:00Z")  # past the deadline

        resp = api.submit_application(application["id"], producer)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    def test_withdrawn_submit_after_deadline_leaves_no_mutation(self, api):
        """PRD §2.9: "5. **State-transition legality** — the target resource is
        in a state from which the requested transition is declared
        (`ERR_INVALID_STATE_TRANSITION`)."
        PRD §3.3: "Withdrawal is available to the owning producer from `DRAFT`,
        from `SUBMITTED`, from `UNDER_REVIEW`, and from `CORRECTION_REQUESTED`,
        each moving the application to the terminal `WITHDRAWN` state."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_temporal_on_deadline_submit
        """
        program = open_program(window_closes_at="2027-01-15T12:00:00Z")
        company = register_company()
        production = create_production(company)
        producer = make_producer_headers(company["id"])
        application = create_application(production, program)
        submit_application(application, company)
        withdrawn = withdraw_application(application, company)
        assert withdrawn["status"] == "WITHDRAWN"
        set_logical_clock("2027-02-01T00:00:00Z")

        api.submit_application(application["id"], producer)
        current = get_application(application)
        assert current["status"] == "WITHDRAWN", (
            "a dual-failing request must not mutate the application")


class TestReviewAndDecision:
    def test_foreign_producer_cannot_submit_application_not_owner(self, api):
        """PRD §2.1: "Ownership checks on any resource that references a
        `ProductionCompany` — directly or through the chain from an application
        or certificate back to its production — compare the resource's
        `production_company_id` to `X-User-ID`, and a mismatch is rejected with
        `ERR_NOT_OWNER`."

        Design: Corner/validations/foreign_producer_cannot_submit_application_not_owner
        """
        program = open_program()
        company_a = register_company(legal_name="Peachtree Pictures LLC")
        company_b = register_company(legal_name="Interloper Films LLC")
        production = create_production(company_a)
        application = create_application(production, program)

        resp = api.submit_application(
            application["id"], make_producer_headers(company_b["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_OWNER)
        assert get_application(application)["status"] == "DRAFT"

    def test_approver_equals_reviewer_rejected_sod(self, api):
        """PRD §2.11: "An application may be approved or denied only by a
        `FilmOfficeReviewer` whose `X-User-ID` differs from the
        `reviewer_user_id` who claimed the review."
        PRD §3.3: "Approval moves the application to `APPROVED`, records the
        decider as `decided_by_user_id`, and recomputes the
        `allocation_share_pct` of this application and of every sibling
        application of the same production (§3.9)."

        Design: Corner/validations/approver_equals_reviewer_rejected_sod
        """
        program = open_program()
        company = register_company()
        production = create_production(company)
        application = create_application(production, program)
        submit_application(application, company)
        claim_application(application, "reviewer-1")

        same_reviewer = api.approve_application(
            application["id"], make_reviewer_headers("reviewer-1"))
        validate_error(same_reviewer, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        assert get_application(application)["status"] == "UNDER_REVIEW"

        other = api.approve_application(
            application["id"], make_reviewer_headers("reviewer-2"))
        approved = validate_success(other, 200)
        assert approved["status"] == "APPROVED"
        assert approved["decided_by_user_id"] == "reviewer-2"

    def test_cpa_cannot_approve_application_forbidden(self, api):
        """PRD §2.1: "A request whose role is not on the target endpoint's
        authorized list is rejected with `ERR_FORBIDDEN_FOR_ROLE`."
        PRD §4: "| POST | `/api/applications/{applicationId}/approve` | Approve
        an `UNDER_REVIEW` application; approver must differ from the claiming
        reviewer | FilmOfficeReviewer |"

        Design: Corner/rbac/cpa_cannot_approve_application_forbidden
        """
        program = open_program()
        company = register_company()
        production = create_production(company)
        application = create_application(production, program)
        submit_application(application, company)
        claim_application(application, "reviewer-1")

        resp = api.approve_application(application["id"], CPA1)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
        assert get_application(application)["status"] == "UNDER_REVIEW"

    def test_denied_application_terminal_lockdown(self, api):
        """PRD §3.3: "Denial moves the application to the terminal `DENIED`
        state — an optional `reason` may accompany the request — and likewise
        records `decided_by_user_id`."
        PRD §3.3: "Any action attempted from a state where that transition is
        not declared — submitting an application that is not in `DRAFT`, for
        instance — is rejected with `ERR_INVALID_STATE_TRANSITION`."

        Design: Corner/state_machines/denied_application_terminal_lockdown
        """
        program = open_program()
        company = register_company()
        production = create_production(company)
        producer = make_producer_headers(company["id"])
        application = create_application(production, program)
        submit_application(application, company)
        claim_application(application, "reviewer-1")
        denied = deny_application(application, "reviewer-2", reason="ineligible genre")
        assert denied["status"] == "DENIED"
        assert denied["decided_by_user_id"] == "reviewer-2"

        for resp in (
            api.submit_application(application["id"], producer),
            api.withdraw_application(application["id"], producer),
            api.approve_application(application["id"], make_reviewer_headers("reviewer-3")),
        ):
            validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        assert get_application(application)["status"] == "DENIED"


class TestCorrectionLoop:
    def _setup_under_review(self, api):
        program = open_program()
        company = register_company()
        production = create_production(company)
        application = create_application(production, program)
        submit_application(application, company)
        claim_application(application, "reviewer-1")
        return program, company, production, application

    def test_correction_loop_cycles_twice_and_preserves_claim(self, api):
        """PRD §3.3: "The claiming reviewer may send the application back for
        corrections — an optional `notes` message may accompany the request —
        moving it to `CORRECTION_REQUESTED`, and the owning producer may
        resubmit, cycling it back to `UNDER_REVIEW`. The correction loop is
        unbounded: an application may pass through `UNDER_REVIEW` and
        `CORRECTION_REQUESTED` any number of times."
        PRD §3.3: "Once an application is `SUBMITTED`, a `FilmOfficeReviewer`
        claims it, moving it to `UNDER_REVIEW` and recording their operator id as
        `reviewer_user_id`."

        Design: Difficulty/non_linear_state_machine/application_correction_loop_cycle
        """
        _program, company, _production, application = self._setup_under_review(api)

        first = request_corrections(application, "reviewer-1",
                                    notes="missing budget top-sheet")
        assert first["status"] == "CORRECTION_REQUESTED"
        back = resubmit_application(first, company)
        assert back["status"] == "UNDER_REVIEW"

        second = request_corrections(back, "reviewer-1",
                                     notes="vendor list incomplete")
        assert second["status"] == "CORRECTION_REQUESTED"
        back_again = resubmit_application(second, company)
        assert back_again["status"] == "UNDER_REVIEW", (
            "two full correction loops must complete without error")
        assert back_again["reviewer_user_id"] == "reviewer-1", (
            "the claim survives the correction cycles")

    def test_correction_loop_then_approve(self, api):
        """PRD §3.3: "The correction loop is unbounded: an application may pass
        through `UNDER_REVIEW` and `CORRECTION_REQUESTED` any number of times."
        PRD §3.3: "Approval moves the application to `APPROVED`, records the
        decider as `decided_by_user_id`, and recomputes the
        `allocation_share_pct` of this application and of every sibling
        application of the same production (§3.9)."

        Design: Difficulty/non_linear_state_machine/application_correction_loop_cycle
        """
        _program, company, _production, application = self._setup_under_review(api)
        returned = request_corrections(application, "reviewer-1")
        resubmit_application(returned, company)
        returned = request_corrections(get_application(application), "reviewer-1")
        resubmit_application(returned, company)

        approved = approve_application(application, "reviewer-2")
        assert approved["status"] == "APPROVED"
        assert approved["decided_by_user_id"] == "reviewer-2"


class TestListingPagination:
    def test_list_applications_pagination_envelope(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of items returned;
        it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset`
        parameter skips a number of items and defaults to 0."
        PRD §2.3: "The `meta` object of a list response carries `limit`,
        `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/list_applications_pagination_envelope
        """
        program = open_program()
        company = register_company()
        production_a = create_production(company, title="Atlantic Crossing")
        production_b = create_production(company, title="Okefenokee Nights",
                                         production_type="SERIES",
                                         total_budget_cents=200_000_000)
        app_a = create_application(production_a, program)
        app_b = create_application(
            production_b, program, estimated_qualified_spend_cents=150_000_000)

        page1, meta1 = validate_paginated(api.list_applications(
            REVIEWER1, params={"jurisdiction_program_id": program["id"],
                               "limit": 1, "offset": 0}))
        assert len(page1) == 1
        assert meta1["total_count"] == 2
        assert meta1["has_more"] is True
        assert meta1["limit"] == 1
        assert meta1["offset"] == 0

        page2, meta2 = validate_paginated(api.list_applications(
            REVIEWER1, params={"jurisdiction_program_id": program["id"],
                               "limit": 1, "offset": 1}))
        assert len(page2) == 1
        assert meta2["total_count"] == 2
        assert meta2["has_more"] is False
        assert meta2["offset"] == 1

        page_ids = {page1[0]["id"], page2[0]["id"]}
        assert page_ids == {app_a["id"], app_b["id"]}, (
            "the two pages must partition the two applications")
