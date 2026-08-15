"""Deficiency comments: raise/issue/respond/verify/reopen/waive loops, the
unresolved-count invariant, listing filters and pagination (PRD §3.5)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    approve_cycle,
    assert_comment_response,
    assign_cycle,
    create_comment_payload,
    get_comment,
    get_cycle,
    get_engagement,
    issue_comments,
    make_applicant_headers,
    make_chief,
    make_chief_reviewer_headers,
    make_engagement,
    make_jurisdiction,
    make_reviewer,
    make_reviewer_headers,
    open_cycle,
    raise_comment,
    respond_to_comment,
    setup_comments_issued,
    setup_in_review_cycle,
    setup_registered_engagement,
    validate_error,
    validate_paginated,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]


class TestCommentLoop:
    def _drive_loop(self, api):
        """OPEN -> ADDRESSED -> REOPENED -> ADDRESSED -> VERIFIED across three
        cycles."""
        bundle = setup_registered_engagement(
            jur_overrides={"state_code": "AZ", "sla_mode": "BUSINESS"})
        eng, rev = bundle["engagement"], bundle["reviewer"]
        rh = make_reviewer_headers(rev["id"])
        cyc1 = open_cycle(eng["id"], documents_ref="s3://loop-v1")
        assign_cycle(cyc1, rev["id"])
        com = raise_comment(cyc1["id"], rev["id"], code_section_ref="1605.2",
                            severity="MAJOR", category="LOAD_PATH",
                            comment_text="Load path discontinuity at transfer girder")
        issue_comments(cyc1["id"], rev["id"])
        respond_to_comment(com["id"], response_text="Added collector, see S3.0")
        cyc2 = open_cycle(eng["id"], documents_ref="s3://loop-v2",
                          as_applicant=True)
        assign_cycle(cyc2, rev["id"])
        validate_success(api.reopen_comment(
            com["id"], {"reopen_note": "Collector overstressed at level 2"}, rh), 200)
        issue_comments(cyc2["id"], rev["id"])
        respond_to_comment(com["id"],
                           response_text="Collector upsized to W18, calc attached")
        cyc3 = open_cycle(eng["id"], documents_ref="s3://loop-v3",
                          as_applicant=True)
        assign_cycle(cyc3, rev["id"])
        validate_success(api.verify_comment(com["id"], rh), 200)
        return bundle, com, cyc1, cyc2

    def test_comment_full_reopen_loop_reaches_verified(self, api):
        """PRD §3.5: "A successful response creates an immutable
        `CommentResponse` recording the `comment_id` and the
        `responder_contact_id` taken from the caller, increments the comment's
        `response_count` by 1, and moves the comment to `ADDRESSED` — from
        `OPEN` or from `REOPENED` alike."
        PRD §3.5: "Reopening instead moves it `ADDRESSED → REOPENED`, leaves
        the count unchanged (a `REOPENED` comment is still unresolved)."
        PRD §3.5: "Verifying a response moves the comment `ADDRESSED →
        VERIFIED` and decrements the engagement's `unresolved_comment_count` by
        1."

        Design: Difficulty/non_linear_state_machine/comment_open_addressed_reopened_addressed_verified_loop
        """
        bundle, com, _, _ = self._drive_loop(api)
        final = get_comment(com["id"])
        assert final["status"] == "VERIFIED"
        assert final["response_count"] == 2
        assert get_engagement(bundle["engagement"]["id"])["unresolved_comment_count"] == 0

    def test_superseded_cycles_are_terminal_after_loop(self, api):
        """PRD §3.3: "If the previous cycle rests at `COMMENTS_ISSUED`, the new
        cycle supersedes it: the old cycle moves `COMMENTS_ISSUED → SUPERSEDED`
        — a terminal state, like `APPROVED` and `CANCELLED`."

        Design: Difficulty/non_linear_state_machine/comment_open_addressed_reopened_addressed_verified_loop
        """
        bundle, com, cyc1, cyc2 = self._drive_loop(api)
        assert get_cycle(cyc1["id"])["status"] == "SUPERSEDED"
        assert get_cycle(cyc2["id"])["status"] == "SUPERSEDED"


class TestResponseReopenInvariant:
    def _setup(self, api):
        bundle = setup_registered_engagement(
            jur_overrides={"state_code": "MT", "sla_mode": "BUSINESS"})
        eng, rev = bundle["engagement"], bundle["reviewer"]
        cyc1 = open_cycle(eng["id"], documents_ref="s3://cnt-v1")
        assign_cycle(cyc1, rev["id"])
        com = raise_comment(cyc1["id"], rev["id"], code_section_ref="1604.3",
                            severity="MAJOR", category="LOAD_PATH",
                            comment_text="Drag strut force not shown")
        issue_comments(cyc1["id"], rev["id"])
        return bundle, cyc1, com

    def test_response_leaves_unresolved_count_unchanged(self, api):
        """PRD §3.5: "Note what does *not* happen: the engagement's
        `unresolved_comment_count` is unchanged, because `ADDRESSED` still
        counts as unresolved."

        Design: Difficulty/compensating_invariant/response_reopen_conserve_unresolved_comment_count
        """
        bundle, _, com = self._setup(api)
        assert get_engagement(bundle["engagement"]["id"])["unresolved_comment_count"] == 1
        respond_to_comment(com["id"],
                           response_text="Drag strut forces added to S4.1")
        eng = get_engagement(bundle["engagement"]["id"])
        assert eng["unresolved_comment_count"] == 1
        assert get_comment(com["id"])["status"] == "ADDRESSED"

    def test_reopen_conserves_unresolved_count(self, api):
        """PRD §3.5: "Reopening instead moves it `ADDRESSED → REOPENED`, leaves
        the count unchanged (a `REOPENED` comment is still unresolved), and
        requires a `reopen_note` in the payload — its absence is an
        `ERR_INVALID_REQUEST`."

        Design: Difficulty/compensating_invariant/response_reopen_conserve_unresolved_comment_count
        """
        bundle, _, com = self._setup(api)
        rev = bundle["reviewer"]
        respond_to_comment(com["id"],
                           response_text="Drag strut forces added to S4.1")
        cyc2 = open_cycle(bundle["engagement"]["id"], documents_ref="s3://cnt-v2")
        assign_cycle(cyc2, rev["id"])
        validate_success(api.reopen_comment(
            com["id"],
            {"reopen_note": "Forces still inconsistent with roof diaphragm"},
            make_reviewer_headers(rev["id"])), 200)
        assert get_engagement(bundle["engagement"]["id"])["unresolved_comment_count"] == 1
        assert get_comment(com["id"])["status"] == "REOPENED"


class TestCycleApprovalGatedByComments:
    def _setup_open_comment(self, api):
        bundle = setup_in_review_cycle(
            jur_overrides={"state_code": "OH", "sla_mode": "CALENDAR"})
        com = raise_comment(bundle["cycle"]["id"], bundle["reviewer"]["id"],
                            code_section_ref="1609.1", severity="MAJOR",
                            category="LATERAL_SYSTEM",
                            comment_text="Shear wall schedule incomplete")
        return bundle, com

    def test_open_comment_blocks_approval(self, api):
        """PRD §3.7: "Approval also requires the engagement's
        `unresolved_comment_count` to be exactly zero
        (`ERR_UNRESOLVED_COMMENTS_REMAIN` while any comment remains `OPEN`,
        `ADDRESSED`, or `REOPENED`)."

        Design: Difficulty/cross_entity_state_dependency/cycle_approval_gated_by_comment_states
        """
        bundle, com = self._setup_open_comment(api)
        rev = bundle["reviewer"]
        resp = api.approve_cycle(
            bundle["cycle"]["id"],
            {"load_path_confirmed": True, "lateral_system_confirmed": True},
            make_reviewer_headers(rev["id"]))
        validate_error(resp, ApiErrorId.ERR_UNRESOLVED_COMMENTS_REMAIN, 409)
        assert get_cycle(bundle["cycle"]["id"])["status"] == "IN_REVIEW"

    def test_approval_succeeds_after_verification_in_next_cycle(self, api):
        """PRD §3.7: "Approval also requires the engagement's
        `unresolved_comment_count` to be exactly zero
        (`ERR_UNRESOLVED_COMMENTS_REMAIN` while any comment remains `OPEN`,
        `ADDRESSED`, or `REOPENED`)."
        PRD §3.7: "On success the cycle moves `IN_REVIEW → APPROVED`."

        Design: Difficulty/cross_entity_state_dependency/cycle_approval_gated_by_comment_states
        """
        bundle, com = self._setup_open_comment(api)
        eng, rev = bundle["engagement"], bundle["reviewer"]
        cyc1 = bundle["cycle"]
        issue_comments(cyc1["id"], rev["id"])
        respond_to_comment(com["id"], response_text="Shear wall schedule added")
        cyc2 = open_cycle(eng["id"], documents_ref="s3://gate-v2")
        assign_cycle(cyc2, rev["id"])
        validate_success(
            api.verify_comment(com["id"], make_reviewer_headers(rev["id"])), 200)
        assert get_engagement(eng["id"])["unresolved_comment_count"] == 0
        approved = approve_cycle(cyc2["id"], rev["id"])
        assert approved["status"] == "APPROVED"
        assert get_cycle(cyc1["id"])["status"] == "SUPERSEDED"


class TestCommentCreationGuards:
    def test_comment_by_unassigned_reviewer_rejected(self, api):
        """PRD §3.5: "a caller who is not the reviewer on that cycle's `ACTIVE`
        assignment fails with `ERR_NOT_ASSIGNED_REVIEWER`."

        Design: Corner/validations/comment_by_unassigned_reviewer_rejected
        """
        bundle = setup_in_review_cycle()
        bystander = make_reviewer(name="Bystander", state_code="CA")
        resp = api.create_comment(
            create_comment_payload(bundle["cycle"]["id"],
                                   comment_text="bystander comment"),
            make_reviewer_headers(bystander["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_ASSIGNED_REVIEWER, 403)
        assert get_engagement(bundle["engagement"]["id"])["unresolved_comment_count"] == 0

    def test_comment_wrong_code_edition_rejected(self, api):
        """PRD §3.5: "Because the engagement is reviewed against its pinned
        editions, the `reference_edition` must equal the engagement's
        `pinned_ibc_edition`; a mismatch is rejected with
        `ERR_CODE_EDITION_MISMATCH`."

        Design: Corner/validations/comment_wrong_code_edition_rejected
        """
        bundle = setup_in_review_cycle(
            jur_overrides={"ibc_edition": "IBC_2018", "asce7_edition": "ASCE7_16"})
        rev = bundle["reviewer"]
        resp = api.create_comment(
            create_comment_payload(bundle["cycle"]["id"],
                                   reference_edition="IBC_2021",
                                   comment_text="cites wrong edition"),
            make_reviewer_headers(rev["id"]))
        validate_error(resp, ApiErrorId.ERR_CODE_EDITION_MISMATCH, 422)
        assert get_engagement(bundle["engagement"]["id"])["pinned_ibc_edition"] == "IBC_2018"


class TestIssueComments:
    def test_issue_comments_with_empty_comment_set_rejected(self, api):
        """PRD §3.5: "Issuance requires something to say: at least one comment
        raised in this cycle, or at least one comment of the engagement
        currently `REOPENED` and awaiting a new response round; otherwise the
        request fails with `ERR_NO_COMMENTS_TO_ISSUE`."

        Design: Corner/validations/issue_comments_with_empty_comment_set_rejected
        """
        bundle = setup_in_review_cycle()
        resp = api.issue_comments(
            bundle["cycle"]["id"],
            make_reviewer_headers(bundle["reviewer"]["id"]))
        validate_error(resp, ApiErrorId.ERR_NO_COMMENTS_TO_ISSUE, 409)
        assert get_cycle(bundle["cycle"]["id"])["status"] == "IN_REVIEW"


class TestResponses:
    def test_response_by_non_owner_rejected(self, api):
        """PRD §3.5: "As with all applicant-scoped actions, `X-User-ID` must
        equal the engagement's `applicant_contact_id`
        (`ERR_NOT_ENGAGEMENT_APPLICANT`)."

        Design: Corner/validations/response_by_non_owner_rejected
        """
        bundle = setup_comments_issued()
        resp = api.create_response(
            bundle["comment"]["id"], {"response_text": "impostor response"},
            make_applicant_headers("app-2"))
        validate_error(resp, ApiErrorId.ERR_NOT_ENGAGEMENT_APPLICANT, 403)
        assert get_comment(bundle["comment"]["id"])["status"] == "OPEN"

    def test_comment_response_is_immutable_event(self, api):
        """PRD §2.5: "`CommentResponse` is the deliberate exception. As an
        immutable ledger entry it carries only `id` and `created_at`; both
        `updated_at` and `version` are absent, because a response is never
        modified once posted."
        PRD §3.5: "A successful response creates an immutable `CommentResponse`
        recording the `comment_id` and the `responder_contact_id` taken from
        the caller."

        Design: Corner/entities/comment_response_is_immutable_event
        """
        bundle = setup_comments_issued()
        resp = api.create_response(
            bundle["comment"]["id"],
            {"response_text": "Lap splice noted on S5.1"},
            make_applicant_headers("app-1"))
        row = validate_success(resp, 201)
        assert_comment_response(row)
        assert row["responder_contact_id"] == "app-1"
        rows, meta = validate_paginated(
            api.list_responses(bundle["comment"]["id"], COORD))
        assert len(rows) == 1
        assert rows[0]["comment_id"] == bundle["comment"]["id"]


class TestVerifyReopenGuards:
    def _setup_addressed(self, api):
        """Comment ADDRESSED; cycle 2 IN_REVIEW (an active review window)."""
        bundle = setup_comments_issued()
        respond_to_comment(bundle["comment"]["id"])
        return bundle

    def test_verify_without_in_review_cycle_rejected(self, api):
        """PRD §3.5: "Both actions demand the current-cycle `IN_REVIEW`
        condition (`ERR_NO_ACTIVE_REVIEW_CYCLE` otherwise), the
        assigned-reviewer identity check (`ERR_NOT_ASSIGNED_REVIEWER`), and a
        comment actually sitting in `ADDRESSED` (`ERR_COMMENT_NOT_ADDRESSED` on
        any other state)."

        Design: Corner/validations/verify_without_in_review_cycle_rejected
        """
        bundle = setup_comments_issued()
        respond_to_comment(bundle["comment"]["id"],
                           response_text="torsion check added")
        # No resubmittal opened: current non-terminal cycle is COMMENTS_ISSUED.
        resp = api.verify_comment(
            bundle["comment"]["id"],
            make_reviewer_headers(bundle["reviewer"]["id"]))
        validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_REVIEW_CYCLE, 409)
        assert get_comment(bundle["comment"]["id"])["status"] == "ADDRESSED"

    def test_addressed_comment_still_blocks_approval(self, api):
        """PRD §3.5: "The engagement's `unresolved_comment_count` is defined as
        the number of its deficiency comments in `OPEN`, `ADDRESSED`, or
        `REOPENED` status; only `VERIFIED` and `WAIVED` leave the unresolved
        set."
        PRD §3.7: "Approval also requires the engagement's
        `unresolved_comment_count` to be exactly zero
        (`ERR_UNRESOLVED_COMMENTS_REMAIN` while any comment remains `OPEN`,
        `ADDRESSED`, or `REOPENED`)."

        Design: Corner/calculations/addressed_comment_still_blocks_approval
        """
        bundle = self._setup_addressed(api)
        rev = bundle["reviewer"]
        cyc2 = open_cycle(bundle["engagement"]["id"], documents_ref="s3://addr-v2")
        assign_cycle(cyc2, rev["id"])
        resp = api.approve_cycle(
            cyc2["id"],
            {"load_path_confirmed": True, "lateral_system_confirmed": True},
            make_reviewer_headers(rev["id"]))
        validate_error(resp, ApiErrorId.ERR_UNRESOLVED_COMMENTS_REMAIN, 409)
        assert get_engagement(bundle["engagement"]["id"])["unresolved_comment_count"] == 1
        assert get_cycle(cyc2["id"])["status"] == "IN_REVIEW"

    def test_verified_comment_rejects_reopen(self, api):
        """PRD §3.5: "Both actions demand the current-cycle `IN_REVIEW`
        condition (`ERR_NO_ACTIVE_REVIEW_CYCLE` otherwise), the
        assigned-reviewer identity check (`ERR_NOT_ASSIGNED_REVIEWER`), and a
        comment actually sitting in `ADDRESSED` (`ERR_COMMENT_NOT_ADDRESSED` on
        any other state)."

        Design: Corner/state_machines/verified_comment_rejects_reopen
        """
        bundle = self._setup_addressed(api)
        rev = bundle["reviewer"]
        cyc2 = open_cycle(bundle["engagement"]["id"], documents_ref="s3://lock-v2")
        assign_cycle(cyc2, rev["id"])
        validate_success(
            api.verify_comment(bundle["comment"]["id"],
                               make_reviewer_headers(rev["id"])), 200)
        resp = api.reopen_comment(
            bundle["comment"]["id"], {"reopen_note": "changed my mind"},
            make_reviewer_headers(rev["id"]))
        validate_error(resp, ApiErrorId.ERR_COMMENT_NOT_ADDRESSED, 409)
        assert get_comment(bundle["comment"]["id"])["status"] == "VERIFIED"


class TestWaiver:
    def _setup_waivable(self, api, severity="MINOR", chief_is_ror=False):
        bundle = setup_in_review_cycle()
        rev = bundle["reviewer"]
        com = raise_comment(bundle["cycle"]["id"], rev["id"],
                            severity=severity, category="DETAILING",
                            comment_text="blocking missing at panel edges")
        chief = rev if chief_is_ror else make_chief(state_code="CA")
        return bundle, com, chief

    def test_waive_critical_comment_rejected(self, api):
        """PRD §3.5: "Two bars apply with equal force on all three source
        states: a `CRITICAL` comment can never be waived
        (`ERR_CRITICAL_COMMENT_NOT_WAIVERABLE`), and the acting chief reviewer
        must not be the engagement's `reviewer_of_record_id` — segregation of
        duties forbids engineers from waiving findings on their own engagements
        (`ERR_WAIVER_SEGREGATION_VIOLATION`)."

        Design: Corner/validations/waive_critical_comment_rejected
        """
        bundle, com, chief = self._setup_waivable(api, severity="CRITICAL")
        resp = api.waive_comment(com["id"], {"justification": "waive it"},
                                 make_chief_reviewer_headers(chief["id"]))
        validate_error(resp, ApiErrorId.ERR_CRITICAL_COMMENT_NOT_WAIVERABLE, 422)
        assert get_comment(com["id"])["status"] == "OPEN"

    def test_waive_by_reviewer_of_record_rejected(self, api):
        """PRD §3.5: "Two bars apply with equal force on all three source
        states: a `CRITICAL` comment can never be waived
        (`ERR_CRITICAL_COMMENT_NOT_WAIVERABLE`), and the acting chief reviewer
        must not be the engagement's `reviewer_of_record_id` — segregation of
        duties forbids engineers from waiving findings on their own engagements
        (`ERR_WAIVER_SEGREGATION_VIOLATION`)."

        Design: Corner/validations/waive_by_reviewer_of_record_rejected
        """
        bundle, com, chief = self._setup_waivable(api, chief_is_ror=True)
        resp = api.waive_comment(
            com["id"], {"justification": "self waiver attempt"},
            make_chief_reviewer_headers(chief["id"]))
        validate_error(resp, ApiErrorId.ERR_WAIVER_SEGREGATION_VIOLATION, 403)
        assert get_comment(com["id"])["status"] == "OPEN"

    def test_chief_reviewer_waive_success(self, api):
        """PRD §3.5: "Waiving moves a comment from `OPEN`, `ADDRESSED`, or
        `REOPENED` to `WAIVED` and decrements `unresolved_comment_count` by 1;
        the payload carries a `justification`."

        Design: Corner/rbac/chief_reviewer_waive_success
        """
        bundle, com, chief = self._setup_waivable(api)
        resp = api.waive_comment(
            com["id"], {"justification": "editorial comment, no code impact"},
            make_chief_reviewer_headers(chief["id"]))
        waived = validate_success(resp, 200)
        assert waived["status"] == "WAIVED"
        assert get_engagement(bundle["engagement"]["id"])["unresolved_comment_count"] == 0


class TestCommentListing:
    def test_comment_list_status_filter(self, api):
        """PRD §3.5: "The comments listing accepts optional `engagement_id`,
        `raised_in_cycle_id`, `raised_by_reviewer_id`, and `status` filters."
        PRD §3.5: "Waiving moves a comment from `OPEN`, `ADDRESSED`, or
        `REOPENED` to `WAIVED` and decrements `unresolved_comment_count` by 1."

        Design: Corner/endpoints/comment_list_status_filter
        """
        bundle = setup_in_review_cycle()
        rev = bundle["reviewer"]
        com1 = raise_comment(bundle["cycle"]["id"], rev["id"],
                             code_section_ref="1602.1", comment_text="f1")
        raise_comment(bundle["cycle"]["id"], rev["id"],
                      code_section_ref="1602.2", comment_text="f2")
        chief = make_chief(state_code="CA")
        validate_success(api.waive_comment(
            com1["id"], {"justification": "non-code item, note only"},
            make_chief_reviewer_headers(chief["id"])), 200)
        eng_id = bundle["engagement"]["id"]
        open_rows, open_meta = validate_paginated(
            api.list_comments(COORD, params={"engagement_id": eng_id,
                                             "status": "OPEN"}))
        waived_rows, waived_meta = validate_paginated(
            api.list_comments(COORD, params={"engagement_id": eng_id,
                                             "status": "WAIVED"}))
        assert open_meta["total_count"] == 1
        assert waived_meta["total_count"] == 1
        assert waived_rows[0]["id"] == com1["id"]
        assert get_engagement(eng_id)["unresolved_comment_count"] == 1

    def test_comment_list_pagination_defaults(self, api):
        """PRD §2.3: "`limit` sets the maximum number of items returned; it
        defaults to 10 when omitted, with a minimum of 1 and a maximum of 100.
        `offset` sets the number of items skipped and defaults to 0, and must
        never be negative. A `limit` below 1 or above 100, or an `offset` below
        0, is rejected with `ERR_INVALID_PAGINATION_PARAMETERS`."

        Design: Corner/endpoints/comment_list_pagination_defaults
        """
        bundle = setup_in_review_cycle()
        rev = bundle["reviewer"]
        eng_id = bundle["engagement"]["id"]
        for i in range(1, 12):
            raise_comment(bundle["cycle"]["id"], rev["id"],
                          code_section_ref=f"1601.{i}", comment_text=f"c{i:02d}")
        rows, meta = validate_paginated(
            api.list_comments(COORD, params={"engagement_id": eng_id}))
        assert len(rows) == 10
        assert meta["total_count"] == 11
        assert meta["has_more"] is True
        rows2, meta2 = validate_paginated(
            api.list_comments(COORD, params={"engagement_id": eng_id,
                                             "offset": 10}))
        assert len(rows2) == 1
        assert meta2["has_more"] is False
        resp = api.list_comments(COORD, params={"engagement_id": eng_id,
                                                "limit": 0})
        validate_error(resp, ApiErrorId.ERR_INVALID_PAGINATION_PARAMETERS, 400)
