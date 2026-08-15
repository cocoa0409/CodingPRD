"""The editorial pipeline: edit, fact-check and legal review, revision loops,
segregation of duties, review records, and review-token concurrency."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_review_record,
    create_greenlit_story,
    create_review_payload,
    drive_story_to_cleared,
    file_review,
    get_success_data,
    greenlight,
    make_copy_editor_headers,
    make_fact_checker_headers,
    make_reporter_headers,
    make_staff,
    propose_and_accept,
    setup_newsroom,
    story_version,
    submit_pitch,
    validate_error,
    validate_paginated,
    validate_success,
)

ND = TEST_USERS["news_director_headers"]


def _drive_to_fact_check(api, ctx, story_id):
    """DRAFT -> IN_EDIT -> FACT_CHECK with an accepted reporter assignment.
    Returns the story's current version (the OCC token for the next filing)."""
    propose_and_accept(ctx, story_id, "reporter")
    get_success_data(api.submit_story_edit(story_id, ctx["reporter_headers"]))
    get_success_data(
        api.complete_story_edit(story_id, ctx["copy_editor_headers"]))
    return story_version(story_id)


class TestStageGates:
    def test_complete_edit_from_draft_rejected(self, api):
        """PRD §3.4: "From `IN_EDIT`, a `CopyEditor` completes the edit and
        advances the story to `FACT_CHECK` — provided the copy editor is not
        the story's author, per §2.9."
        PRD §2.7: "8. From-state legality — the target resource is in a
        from-state of the invoked transition; failures yield
        `ERR_INVALID_STATE` (HTTP 409), except that proposing a correction or
        ingesting analytics against a story that is not published yields
        `ERR_STORY_NOT_PUBLISHED` (HTTP 409)."

        Design: Corner/state_machines/story_complete_edit_from_draft_rejected
        """
        ctx = setup_newsroom(copy_editor=True)
        _pitch, story_id = create_greenlit_story(ctx)
        resp = api.complete_story_edit(story_id, ctx["copy_editor_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_submit_edit_empty_reporter_set_rejected(self, api):
        """PRD §3.4: "The newsroom refuses to edit uncrewed copy: submission
        requires at least one assignment on the story with `assignment_role`
        `REPORTER` in `ACCEPTED` or `COMPLETED` status, and without one the
        request is rejected with `ERR_NO_REPORTING_ASSIGNMENT` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/submit_edit_empty_reporter_set
        """
        ctx = setup_newsroom(photographer=True)
        _pitch, story_id = create_greenlit_story(ctx, desk="FEATURES")

        # Empty reporter set.
        resp1 = api.submit_story_edit(story_id, ctx["reporter_headers"])
        validate_error(resp1, ApiErrorId.ERR_NO_REPORTING_ASSIGNMENT)

        # A PHOTOGRAPHER assignment does not count toward the reporter gate.
        photog = propose_and_accept(
            ctx, story_id, "photographer", assignment_role="PHOTOGRAPHER",
            planned_effort_minutes=45)
        assert photog["status"] == "ACCEPTED"
        resp2 = api.submit_story_edit(story_id, ctx["reporter_headers"])
        validate_error(resp2, ApiErrorId.ERR_NO_REPORTING_ASSIGNMENT)

    def test_submit_edit_with_one_accepted_reporter_admitted(self, api):
        """PRD §3.4: "The newsroom refuses to edit uncrewed copy: submission
        requires at least one assignment on the story with `assignment_role`
        `REPORTER` in `ACCEPTED` or `COMPLETED` status, and without one the
        request is rejected with `ERR_NO_REPORTING_ASSIGNMENT` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/submit_edit_empty_reporter_set
        """
        ctx = setup_newsroom()
        _pitch, story_id = create_greenlit_story(ctx, desk="FEATURES")
        propose_and_accept(ctx, story_id, "reporter")
        resp = api.submit_story_edit(story_id, ctx["reporter_headers"])
        story = validate_success(resp)
        assert story["status"] == "IN_EDIT", \
            "exactly one ACCEPTED REPORTER assignment crosses the boundary"

    def test_review_type_stage_mismatch_rejected(self, api):
        """PRD §3.4: "A filing whose `review_type` does not match the story's
        current stage, or that arrives in any other state, is rejected with
        `ERR_INVALID_STATE`; a filing by the story's author is rejected per
        §2.9; and every filing must pin the story version under review via
        `expected_story_version` as §2.8 describes, with a stale pin rejected
        by `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/validations/review_type_stage_mismatch
        """
        ctx = setup_newsroom(copy_editor=True, legal_reviewer=True)
        _pitch, story_id = create_greenlit_story(ctx)
        v4 = _drive_to_fact_check(api, ctx, story_id)
        # LEGAL review while the story sits in FACT_CHECK; the version token
        # is current, so only the stage check can explain the rejection.
        resp = file_review(story_id, "LEGAL", "PASS",
                           ctx["legal_reviewer_headers"],
                           expected_story_version=v4)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestFactCheckRevisionLoop:
    def _looped_story(self, api, ctx, story_id):
        """Run FAIL, FAIL, PASS fact-check rounds. Returns the recorded
        review bodies in order."""
        v = _drive_to_fact_check(api, ctx, story_id)
        reviews = []
        for verdict, notes in (("FAIL", "wrong figure"),
                               ("FAIL", "still wrong"),
                               ("PASS", None)):
            resp = file_review(story_id, "FACT_CHECK", verdict,
                               ctx["fact_checker_headers"],
                               expected_story_version=v, notes=notes)
            reviews.append(validate_success(resp, 201))
            if verdict == "FAIL":
                # Looped back to IN_EDIT; complete the edit to re-enter
                # FACT_CHECK.
                get_success_data(
                    api.complete_story_edit(story_id,
                                            ctx["copy_editor_headers"]))
            v = story_version(story_id)
        return reviews

    def test_fail_loops_back_and_third_pass_advances(self, api):
        """PRD §3.4: "A `PASS` in `FACT_CHECK` advances the story `FACT_CHECK →
        LEGAL_REVIEW`; a `PASS` in `LEGAL_REVIEW` advances it `LEGAL_REVIEW →
        CLEARED`. A `FAIL` in either stage loops the story back to `IN_EDIT`
        for revision, and the round counter ensures each pass through the loop
        is recorded as a new round rather than overwriting history."

        Design: Difficulty/non_linear_state_machine/story_factcheck_revision_loop
        """
        ctx = setup_newsroom(copy_editor=True, fact_checker=True)
        _pitch, story_id = create_greenlit_story(ctx)
        reviews = self._looped_story(api, ctx, story_id)
        assert [r["review_round"] for r in reviews] == [1, 2, 3], \
            "per-type chronological rounds"
        final = get_success_data(api.get_story(story_id, ND))
        assert final["status"] == "LEGAL_REVIEW", \
            "the round-3 PASS advanced the same story out of the loop"

    def test_earlier_same_type_reviews_flip_is_current(self, api):
        """PRD §3.4: "Each accepted filing creates a `ReviewRecord` — a
        201-created, immutable measurement whose `story_id` comes from the path
        and whose `reviewer_staff_id` comes from `X-User-ID`, which pins the
        supplied version in `reviewed_story_version`, whose `review_round` is
        the count of prior reviews of the same type for the story plus one, and
        whose `is_current` flag is true only on the latest review of its type
        for the story: recording a newer review of that type flips every
        earlier same-type review of the story to `is_current` false."

        Design: Difficulty/non_linear_state_machine/story_factcheck_revision_loop
        """
        ctx = setup_newsroom(copy_editor=True, fact_checker=True)
        _pitch, story_id = create_greenlit_story(ctx)
        reviews = self._looped_story(api, ctx, story_id)
        assert reviews[0]["is_current"] is True, \
            "a review is current at creation"

        listed, meta = validate_paginated(api.get_story_reviews(
            story_id, ctx["desk_headers"]))
        assert meta["total_count"] == 3
        assert listed[0]["is_current"] is False, \
            "round 1 was superseded by round 3"
        assert listed[1]["is_current"] is False
        assert listed[2]["is_current"] is True, \
            "only the latest same-type review stays current"


class TestSegregationOfDuties:
    def test_sod_complete_edit_own_story(self, api):
        """PRD §2.9: "Three hand-offs forbid self-dealing, each enforced with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 422). The copy editor who completes
        an edit and advances a story toward fact-check must not be the story's
        author."

        Design: Corner/rbac/sod_complete_edit_own_story
        """
        ctx = setup_newsroom()
        ce_author = make_staff("Ed Author SE", "COPY_EDITOR",
                               hourly_rate_cents=7000)
        ce_other = make_staff("Ed Other SE", "COPY_EDITOR", home_desk="BUSINESS",
                              hourly_rate_cents=7000)
        ce1_h = make_copy_editor_headers(ce_author["id"])
        ce2_h = make_copy_editor_headers(ce_other["id"])

        pitch = submit_pitch(ctx, title="SE", author_headers=ce1_h)
        pitch = greenlight(ctx, pitch["id"], story_type="PRINT")
        story_id = pitch["greenlit_story_id"]
        propose_and_accept(ctx, story_id, "reporter")
        get_success_data(api.submit_story_edit(story_id, ce1_h))

        resp = api.complete_story_edit(story_id, ce1_h)
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        ok = api.complete_story_edit(story_id, ce2_h)
        story = validate_success(ok)
        assert story["status"] == "FACT_CHECK", \
            "an independent copy editor completes the edit"

    def test_sod_review_own_story(self, api):
        """PRD §2.9: "Three hand-offs forbid self-dealing, each enforced with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 422). The copy editor who completes
        an edit and advances a story toward fact-check must not be the story's
        author. The reviewer filing a fact-check or legal verdict must not be
        the story's author. And the managing editor who approves a correction
        must not be the staff member who proposed it."

        Design: Corner/rbac/sod_review_own_story
        """
        ctx = setup_newsroom(copy_editor=True)
        fc_author = make_staff("Fact Author SR", "FACT_CHECKER",
                               hourly_rate_cents=7000)
        fc_other = make_staff("Fact Other SR", "FACT_CHECKER",
                              home_desk="BUSINESS", hourly_rate_cents=7000)
        fc1_h = make_fact_checker_headers(fc_author["id"])
        fc2_h = make_fact_checker_headers(fc_other["id"])

        pitch = submit_pitch(ctx, title="SR", author_headers=fc1_h)
        pitch = greenlight(ctx, pitch["id"], story_type="PRINT")
        story_id = pitch["greenlit_story_id"]
        propose_and_accept(ctx, story_id, "reporter")
        get_success_data(api.submit_story_edit(story_id, fc1_h))
        get_success_data(
            api.complete_story_edit(story_id, ctx["copy_editor_headers"]))
        v4 = story_version(story_id)

        resp = file_review(story_id, "FACT_CHECK", "PASS", fc1_h,
                           expected_story_version=v4)
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        ok = file_review(story_id, "FACT_CHECK", "PASS", fc2_h,
                         expected_story_version=v4)
        record = validate_success(ok, 201)
        assert record["review_round"] == 1
        story = get_success_data(api.get_story(story_id, ND))
        assert story["status"] == "LEGAL_REVIEW", \
            "the independent fact checker's PASS advances the story"


class TestReviewRecords:
    def test_review_record_immutable_and_reverse_reachable(self, api):
        """PRD §2.5: "A `ReviewRecord` and an `AnalyticsReport` are immutable
        measurements: each carries only `id` and `created_at`, and both
        `updated_at` and `version` are absent from their representations."
        PRD §3.4: "Stories support list filtering by `status`, `desk`,
        `author_staff_id`, and `superseded_by_story_id`; a story's assignments,
        its review records (filterable by `review_type`), its corrections
        (filterable by `status`), and its analytics reports (filterable by
        `variant`) are each readable as reverse collections, with the review
        and assignment collections restricted to the desk and review roles."

        Design: Corner/entities/review_record_immutable_no_version
        """
        ctx = setup_newsroom(copy_editor=True, fact_checker=True)
        _pitch, story_id = create_greenlit_story(ctx)
        v4 = _drive_to_fact_check(api, ctx, story_id)
        resp = file_review(story_id, "FACT_CHECK", "FAIL",
                           ctx["fact_checker_headers"],
                           expected_story_version=v4, notes="wrong figure")
        record = validate_success(resp, 201)
        assert_review_record(record)
        assert record["reviewed_story_version"] == v4
        assert record["review_round"] == 1
        assert record["is_current"] is True
        assert record["reviewer_staff_id"] == ctx["fact_checker"]["id"]

        story_side, _m1 = validate_paginated(api.get_story_reviews(
            story_id, ctx["desk_headers"]))
        assert story_side[0]["id"] == record["id"]
        assert_review_record(story_side[0])

        staff_side, _m2 = validate_paginated(api.get_staff_reviews(
            ctx["fact_checker"]["id"], ND))
        assert staff_side[0]["id"] == record["id"], \
            "both FK reverse paths resolve the same record"
        assert_review_record(staff_side[0])


class TestStoryListing:
    def test_stories_list_filter_by_author(self, api):
        """PRD §3.4: "Stories support list filtering by `status`, `desk`,
        `author_staff_id`, and `superseded_by_story_id`; a story's assignments,
        its review records (filterable by `review_type`), its corrections
        (filterable by `status`), and its analytics reports (filterable by
        `variant`) are each readable as reverse collections, with the review
        and assignment collections restricted to the desk and review roles."

        Design: Corner/entities/stories_list_filter_by_author
        """
        ctx = setup_newsroom()
        rep2 = make_staff("Rep Two LF", "REPORTER", home_desk="SPORTS")
        rep2_h = make_reporter_headers(rep2["id"])

        _p1, s1_id = create_greenlit_story(ctx, title="S1")
        _p2, s2_id = create_greenlit_story(
            ctx, title="S2", desk="SPORTS", urgency="URGENT",
            author_headers=rep2_h, story_type="DIGITAL")

        stories, meta = validate_paginated(api.list_stories(
            ctx["desk_headers"],
            params={"author_staff_id": rep2["id"]}))
        assert meta["total_count"] == 1, "the other author's story is excluded"
        assert stories[0]["id"] == s2_id
        assert stories[0]["author_staff_id"] == rep2["id"]


class TestReviewConcurrency:
    def test_stale_review_after_pipeline_advance(self, api):
        """PRD §2.8: "A review verdict pins the exact story version it
        reviewed: if the story's `version` has advanced since the reviewer's
        reading — for instance because the author filed a new edit — the
        verdict is rejected with `ERR_STALE_VERSION` (HTTP 412), so reviews
        never attach to content the reviewer did not see."
        PRD §2.7: "7. Optimistic concurrency on the two OCC-guarded writes
        (§2.8); a stale token yields `ERR_STALE_VERSION` (HTTP 412). This check
        runs before the from-state check, so a stale token produces 412 even
        when the target's state is also wrong."

        Design: Corner/cross_cutting_layers/occ_stale_review_after_pipeline_advance
        """
        ctx = setup_newsroom(copy_editor=True, fact_checker=True,
                             legal_reviewer=True)
        _pitch, story_id = create_greenlit_story(ctx)
        story = drive_story_to_cleared(ctx, story_id)
        assert story["status"] == "CLEARED"

        # Replay the LEGAL PASS with the version token captured while the
        # story sat in LEGAL_REVIEW: the pipeline has advanced since.
        stale_version = story["version"] - 1
        resp = api.create_story_review(
            story_id,
            create_review_payload("LEGAL", "PASS", stale_version),
            ctx["legal_reviewer_headers"])
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        reviews, meta = validate_paginated(
            api.get_story_reviews(story_id, ND))
        assert meta["total_count"] == 2, "no third record was persisted"
        assert all(r["review_round"] == 1 for r in reviews)
