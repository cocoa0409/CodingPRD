"""Program creation/update semantics, authentication, RBAC, envelope shape,
not-found handling, and application listing pagination."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    advance_cycle_to_decisions_released,
    assert_admission_cycle,
    assert_program,
    assign_review,
    create_admitted_application,
    create_applicant,
    create_application_for_new_applicant,
    create_cycle,
    create_cycle_payload,
    create_program,
    create_program_payload,
    make_applicant_headers,
    make_reader_headers,
    set_clock,
    setup_open_cycle_with_program,
    submit_application,
    submit_review_payload,
    transition_application,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["system_admin_headers"]
MANAGER = TEST_USERS["enrollment_manager_headers"]
OFFICER = TEST_USERS["admissions_officer_headers"]
AID_OFFICER = TEST_USERS["financial_aid_officer_headers"]
READER = TEST_USERS["application_reader_headers"]


class TestProgramCreation:
    def test_program_default_auto_waitlist_flag_false(self, api):
        """PRD 3.2: "An optional `auto_waitlist_activation` flag — defaulting
        to false when omitted — controls whether a freed seat automatically
        activates the top-ranked active waitlist entry"
        PRD 3.2: "At creation every counter is zero, so `seats_open` equals
        `capacity_seats`, `scholarship_available_cents` equals
        `scholarship_budget_cents`, and `intake_posture` is computed per
        §2.6."

        Design: Corner/entities/program_default_auto_waitlist_flag_false
        """
        cycle = create_cycle()
        program = validate_success(api.create_program(
            create_program_payload(cycle["id"], name="DEF", capacity_seats=4,
                                   target_enrollment=2,
                                   scholarship_budget_cents=1_000_000),
            MANAGER), 201)
        assert_program(program)
        assert program["auto_waitlist_activation"] is False, \
            "Omitting the flag defaults it to false"
        assert program["seats_open"] == 4
        assert program["scholarship_committed_cents"] == 0
        assert program["scholarship_available_cents"] == 1_000_000

    def test_program_computed_fields_input_ignored(self, api):
        """PRD 3.2: "At creation every counter is zero, so `seats_open` equals
        `capacity_seats`, `scholarship_available_cents` equals
        `scholarship_budget_cents`, and `intake_posture` is computed per
        §2.6."
        PRD 2.6: "Posture is a computed field, never set directly, and it
        gates admissions and waitlist activations wherever those workflows
        appear in §3."

        Design: Corner/entities/program_computed_fields_input_ignored
        """
        cycle = create_cycle()
        payload = create_program_payload(
            cycle["id"], name="IGN", capacity_seats=4, target_enrollment=2,
            scholarship_budget_cents=1_000_000)
        payload["scholarship_committed_cents"] = 999_999
        payload["seats_open"] = 0
        program = validate_success(api.create_program(payload, MANAGER), 201)
        assert program["scholarship_committed_cents"] == 0, \
            "Client-supplied committed total is ignored; counters start at zero"
        assert program["seats_open"] == 4, \
            "Client-supplied seats_open is ignored; it equals capacity_seats"
        assert program["scholarship_available_cents"] == 1_000_000

    def test_create_response_immediately_consistent(self, api):
        """PRD 3.2: "At creation every counter is zero, so `seats_open` equals
        `capacity_seats`, `scholarship_available_cents` equals
        `scholarship_budget_cents`, and `intake_posture` is computed per
        §2.6."
        PRD 2.6: "Each program maintains two conserved ledger fields that the
        system recomputes immediately on every funnel mutation, with no
        eventual-consistency lag."

        Design: Corner/consistency_model/create_response_immediately_consistent
        """
        cycle = create_cycle()
        program = validate_success(api.create_program(
            create_program_payload(cycle["id"], name="IMM", capacity_seats=7,
                                   target_enrollment=3,
                                   scholarship_budget_cents=900_000),
            MANAGER), 201)
        assert program["seats_open"] == 7, \
            "The create response itself carries seats_open == capacity_seats"
        assert program["scholarship_available_cents"] == 900_000, \
            "The create response itself carries the full available budget"
        assert program["scholarship_committed_cents"] == 0


class TestProgramOcc:
    def test_occ_program_patch_stale_rejected(self, api):
        """PRD 2.8: "A request to `PATCH /enrollment/programs/{programId}` must
        likewise carry `expected_program_version`, the client's last observed
        `version` of the program, as a non-optional field. A mismatch with the
        program's current `version` is rejected with `ERR_STALE_VERSION`
        (HTTP 412)"
        PRD 3.2: "Every successful update recomputes `seats_open`,
        `scholarship_available_cents`, and `intake_posture`, and increments
        the program's `version` by one."

        Design: Corner/cross_cutting_layers/occ_program_patch_stale_rejected
        """
        cycle = create_cycle()
        program = create_program(cycle["id"], name="OCC1", capacity_seats=4,
                                 target_enrollment=2)
        observed_version = program["version"]

        updated = validate_success(api.patch_program(
            program["id"],
            {"auto_waitlist_activation": True,
             "expected_program_version": observed_version},
            MANAGER))
        assert updated["version"] == observed_version + 1, \
            "A successful guarded write increments the program version by one"
        assert updated["auto_waitlist_activation"] is True

        stale = api.patch_program(
            program["id"],
            {"target_enrollment": 3,
             "expected_program_version": observed_version},
            MANAGER)
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
        after = validate_success(api.get_program(program["id"], MANAGER))
        assert after["target_enrollment"] == 2, \
            "The stale write is rejected wholesale; target stays unchanged"


class TestAuthAndNotFound:
    def test_auth_missing_headers_returns_unauthenticated(self, api):
        """PRD 2.1: "A request missing either header, or carrying a role
        string outside this set, is rejected with `ERR_UNAUTHENTICATED`
        (HTTP 401)."

        Design: Corner/validations/auth_missing_headers_returns_unauthenticated
        """
        resp = api.create_cycle(create_cycle_payload(), None)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)

    def test_get_application_not_found_returns_404(self, api):
        """PRD 2.9: "Third, existence — any path identifier or body foreign
        key (`applicant_id`, `program_id`, `cycle_id`, `application_id`) that
        does not resolve yields `ERR_NOT_FOUND`."

        Design: Corner/entities/get_application_not_found_returns_404
        """
        resp = api.get_application(NON_EXISTENT_UUID, OFFICER)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestResponseEnvelopeShape:
    def test_response_envelope_shape(self, api):
        """PRD 2.2: "The `response_type` is either "object" for a single
        resource or "array" for a list of resources."
        PRD 2.3: "Paginated list responses carry `limit`, `offset`,
        `total_count`, and `has_more` in the `meta` object of the envelope."
        PRD 2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."

        Design: Corner/endpoints/response_envelope_shape
        """
        create_cycle()
        list_resp = api.list_applications(MANAGER)
        assert list_resp.status_code == 200
        body = list_resp.json()
        assert isinstance(body["meta"].get("api_request_id"), str)
        assert isinstance(body["meta"].get("api_request_timestamp"), str)
        assert body["response_type"] == "array"
        meta = body["meta"]
        assert meta["total_count"] == 0
        assert meta["limit"] == 10, "The default limit is 10"
        assert meta["offset"] == 0, "The default offset is 0"
        assert meta["has_more"] is False

        err_resp = api.get_cycle(NON_EXISTENT_UUID, MANAGER)
        assert err_resp.status_code == 404
        err_body = err_resp.json()
        assert err_body["response_type"] == "error"
        assert set(err_body["meta"].keys()) == {
            "api_request_id", "api_request_timestamp"}, \
            "Error meta contains only the id and timestamp"
        assert err_body["data"]["error_id"] == "ERR_NOT_FOUND"
        assert len(err_body["data"]["message"].strip()) > 0


class TestRbac:
    def test_rbac_applicant_cannot_create_review(self, api):
        """PRD 2.1: "A request whose authenticated role is not in the
        endpoint's allowed set is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD 4: POST /enrollment/reviews is authorized for AdmissionsOfficer.

        Design: Corner/rbac/rbac_applicant_cannot_create_review
        """
        setup = setup_open_cycle_with_program(name="RB1")
        pair = _create_submitted_application(setup)
        resp = api.create_review(
            {"application_id": pair["application"]["id"],
             "reader_id": "reader-1",
             "window_start_at": "2026-08-01T00:00:00Z",
             "window_end_at": "2027-01-01T00:00:00Z"},
            make_applicant_headers(pair["applicant"]["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_rbac_reader_cannot_advance_cycle(self, api):
        """PRD 2.1: "A request whose authenticated role is not in the
        endpoint's allowed set is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD 4: POST /enrollment/cycles/{cycleId}/advance is authorized for
        EnrollmentManager.

        Design: Corner/rbac/rbac_reader_cannot_advance_cycle
        """
        cycle = create_cycle()
        create_program(cycle["id"], name="RB2")
        resp = api.advance_cycle(cycle["id"], "OPEN", READER)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        after = validate_success(api.get_cycle(cycle["id"], MANAGER))
        assert after["status"] == "SETUP", "The rejected advance changes nothing"

    def test_rbac_aid_officer_cannot_pay_deposit(self, api):
        """PRD 2.1: "A request whose authenticated role is not in the
        endpoint's allowed set is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD 4: POST /enrollment/deposits is authorized for Applicant.

        Design: Corner/rbac/rbac_aid_officer_cannot_pay_deposit
        """
        setup = setup_open_cycle_with_program(name="RB3")
        pair = _create_submitted_application(setup)
        resp = api.create_deposit(
            {"application_id": pair["application"]["id"],
             "amount_cents": 50_000},
            AID_OFFICER)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_rbac_applicant_not_owner_deposit_rejected(self, api):
        """PRD 2.1: "When `X-User-Role` is `Applicant`, `X-User-ID` is the
        `id` of the acting `Applicant` record; ownership checks on any
        resource that references an applicant — deposit payment, aid-offer
        response, application withdrawal, and applicant self-reads — compare
        the resource's applicant foreign key to `X-User-ID`, and a mismatch
        is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

        Design: Corner/rbac/rbac_applicant_not_owner_deposit_rejected
        """
        setup = setup_open_cycle_with_program(name="RB4")
        cycle_id = setup["cycle"]["id"]
        program_id = setup["program"]["id"]
        pair_a = create_admitted_application(cycle_id, program_id,
                                             academic_score=80)
        other = create_applicant(cycle_id, full_name="Own B")
        advance_cycle_to_decisions_released(cycle_id)
        set_clock("2027-04-01T00:00:00Z")

        resp = api.create_deposit(
            {"application_id": pair_a["application"]["id"],
             "amount_cents": 50_000},
            make_applicant_headers(other["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)
        app_after = validate_success(
            api.get_application(pair_a["application"]["id"], OFFICER))
        assert app_after["status"] == "ADMITTED", \
            "No deposit is created against a non-owner request"
        deposits, meta = validate_paginated(api.list_deposits(
            MANAGER, params={"application_id": pair_a["application"]["id"]}))
        assert meta["total_count"] == 0

    def test_rbac_reviewer_mismatch_rejected(self, api):
        """PRD 2.1: "it is, however, compared against a committee review's
        `reader_id` at submission time, and a mismatch is rejected with
        `ERR_REVIEWER_MISMATCH` (HTTP 403)."
        PRD 3.4: "Submitting a read is the reader's own act: the caller's
        `X-User-ID` must equal the review's `reader_id`, or the submission is
        rejected with `ERR_REVIEWER_MISMATCH`."

        Design: Corner/rbac/rbac_reviewer_mismatch_rejected
        """
        setup = setup_open_cycle_with_program(name="RB5")
        pair = _create_submitted_application(setup)
        transition_application(pair["application"]["id"], "IN_REVIEW")
        review = assign_review(pair["application"]["id"], "reader-1")

        resp = api.submit_review(review["id"], submit_review_payload(),
                                 make_reader_headers("reader-2"))
        validate_error(resp, ApiErrorId.ERR_REVIEWER_MISMATCH)
        after = validate_success(api.get_review(review["id"], OFFICER))
        assert after["status"] == "ASSIGNED", \
            "The mismatched submit leaves the review ASSIGNED"


class TestApplicationListingPagination:
    def test_list_applications_pagination(self, api):
        """PRD 2.3: "The `limit` parameter specifies the maximum number of
        items to return; it defaults to 10, with a minimum of 1 and a maximum
        of 100. The `offset` parameter specifies how many items to skip and
        defaults to 0."
        PRD 3.3: "The application listing can be filtered by `cycle_id`,
        `program_id`, `applicant_id`, and `status`."

        Design: Corner/entities/list_applications_pagination
        """
        setup = setup_open_cycle_with_program(name="PAG", capacity_seats=9,
                                              target_enrollment=5)
        cycle_id = setup["cycle"]["id"]
        program_id = setup["program"]["id"]
        for score in (80, 81, 82):
            applicant = create_applicant(cycle_id)
            submit_application(cycle_id, program_id, applicant["id"],
                               academic_score=score)

        page1, meta1 = validate_paginated(
            api.list_applications(OFFICER, params={"limit": 2}))
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert meta1["limit"] == 2
        assert meta1["offset"] == 0

        page2, meta2 = validate_paginated(api.list_applications(
            OFFICER, params={"limit": 2, "offset": 2}))
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

        filtered, meta3 = validate_paginated(api.list_applications(
            OFFICER, params={"program_id": program_id}))
        assert meta3["total_count"] == 3, \
            "Filtering by program_id returns the same three filings"


def _create_submitted_application(setup):
    return create_application_for_new_applicant(
        setup["cycle"]["id"], setup["program"]["id"], academic_score=80)
