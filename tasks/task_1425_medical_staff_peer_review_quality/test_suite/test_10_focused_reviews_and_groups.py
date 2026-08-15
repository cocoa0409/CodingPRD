"""Focused reviews and focus groups: existence variants, the ACTIVE-parent
gate, half-open interval adjacency, membership uniqueness, and the
deliberation quorum fed by group membership."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    add_focus_group_member,
    assert_focused_review,
    assert_instant_equals,
    close_focused_review,
    close_focused_review_payload,
    create_focus_group,
    create_focused_review,
    create_provider,
    finalize_deliberation,
    get_case,
    make_committee_member_headers,
    seat_member,
    set_clock,
    setup_case_in_deliberation,
    validate_error,
    validate_paginated,
    validate_success,
)

QD = TEST_USERS["quality_director_headers"]


class TestFocusedReviewExistence:
    def test_focused_review_get_not_found_returns_404(self, quality_director_headers):
        """PRD §2.8: "The 404 variant names the resource that failed to
        resolve: `ERR_PROVIDER_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`,
        `ERR_CASE_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`,
        `ERR_CONFLICT_NOT_FOUND`, `ERR_FOCUSED_REVIEW_NOT_FOUND`,
        `ERR_FOCUS_GROUP_NOT_FOUND`, or `ERR_MEMBERSHIP_NOT_FOUND`."

        Design: Corner/entities/focused_review_get_not_found_returns_404
        """
        resp = api_client.get_focused_review(NON_EXISTENT_UUID, quality_director_headers)
        validate_error(resp, ApiErrorId.ERR_FOCUSED_REVIEW_NOT_FOUND.value, expected_status=404)

    def test_focus_group_get_not_found_returns_404(self, quality_director_headers):
        """PRD §2.8: "The 404 variant names the resource that failed to
        resolve: `ERR_PROVIDER_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`,
        `ERR_CASE_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`,
        `ERR_CONFLICT_NOT_FOUND`, `ERR_FOCUSED_REVIEW_NOT_FOUND`,
        `ERR_FOCUS_GROUP_NOT_FOUND`, or `ERR_MEMBERSHIP_NOT_FOUND`."

        Design: Corner/entities/focus_group_get_not_found_returns_404
        """
        resp = api_client.get_focus_group(NON_EXISTENT_UUID, quality_director_headers)
        validate_error(resp, ApiErrorId.ERR_FOCUS_GROUP_NOT_FOUND.value, expected_status=404)


class TestFocusGroupStateGate:
    def test_group_creation_succeeds_under_active_review(self, quality_director_headers):
        """PRD §3.8: "The `QualityDirector` creates one under an `ACTIVE`
        review by supplying a non-empty `name`; the group records the
        `focus_id` of the review it serves."

        Design: Difficulty/cross_entity_state_dependency/focus_group_requires_active_focused_review
        """
        subject = create_provider("Subj Sixteen", "CARDIOLOGY")
        review = create_focused_review(subject["id"], "pattern of complaints")
        group = validate_success(api_client.create_focus_group(
            review["id"], {"name": "panel-1"}, quality_director_headers), expected_status=201)
        assert group["focus_id"] == review["id"]

    def test_group_creation_rejected_after_review_closed(self, quality_director_headers):
        """PRD §3.8: "Existing focus groups survive closure, but creating new
        groups or adding members under a `CLOSED` review is rejected with
        `ERR_INVALID_STATE`."

        Design: Difficulty/cross_entity_state_dependency/focus_group_requires_active_focused_review
        """
        subject = create_provider("Subj Sixteen", "CARDIOLOGY")
        review = create_focused_review(subject["id"], "pattern of complaints")
        create_focus_group(review["id"], "panel-1")
        close_focused_review(review["id"], "completed")

        resp = api_client.create_focus_group(review["id"], {"name": "panel-2"},
                                             quality_director_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)


class TestFocusedReviewIntervalAdjacency:
    def test_overlapping_manual_open_rejected(self, quality_director_headers):
        """PRD §3.8: "At most one `ACTIVE` focused review may exist per
        provider at any time — a manual open while one is active is rejected
        with `ERR_FOCUSED_REVIEW_ALREADY_ACTIVE`".

        Design: Difficulty/resource_temporal_overlap/focused_review_half_open_interval_adjacency
        """
        subject = create_provider("Subj Eighteen", "SURGERY")
        create_focused_review(subject["id"], "first")
        resp = api_client.create_focused_review(
            {"provider_id": subject["id"], "basis": "overlap attempt"},
            quality_director_headers)
        validate_error(resp, ApiErrorId.ERR_FOCUSED_REVIEW_ALREADY_ACTIVE.value,
                       expected_status=409)

    def test_open_at_exact_close_instant_allowed(self, quality_director_headers):
        """PRD §3.8: "with half-open interval semantics: a new review may open
        at the exact instant the prior one closed."
        PRD §3.8: "Focused reviews can be listed with filters on `provider_id`
        and `status`."

        Design: Difficulty/resource_temporal_overlap/focused_review_half_open_interval_adjacency
        """
        subject = create_provider("Subj Eighteen", "SURGERY")
        first = create_focused_review(subject["id"], "first")
        set_clock("2026-08-10T00:00:00Z")
        closed = close_focused_review(first["id"], "done")
        assert_instant_equals(closed["closed_at"], "2026-08-10T00:00:00Z")

        second = validate_success(api_client.create_focused_review(
            {"provider_id": subject["id"], "basis": "adjacent reopen"},
            quality_director_headers), expected_status=201)
        assert_focused_review(second)
        assert_instant_equals(second["opened_at"], "2026-08-10T00:00:00Z")

        active, meta = validate_paginated(api_client.list_provider_focused_reviews(
            subject["id"], quality_director_headers, params={"status": "ACTIVE"}))
        assert [r["id"] for r in active] == [second["id"]]
        assert meta["total_count"] == 1


class TestFocusGroupMembership:
    def _review_with_group_and_member(self):
        subject = create_provider("Subj FG", "SURGERY")
        member = seat_member(create_provider("Rev B", "SURGERY")["id"], "MEMBER")
        review = create_focused_review(subject["id"], "manual")
        group = create_focus_group(review["id"], "g1")
        return subject, member, review, group

    def test_duplicate_focus_member_rejected(self, quality_director_headers):
        """PRD §3.8: "Members are added by `member_id` and must be `ACTIVE` at
        add time (`ERR_REVIEWER_INACTIVE` otherwise); at most one membership
        row exists per (`focus_group_id`, `member_id`) pair, and a duplicate
        addition is rejected with `ERR_DUPLICATE_FOCUS_MEMBER`."

        Design: Corner/validations/duplicate_focus_member_rejected
        """
        _, member, _, group = self._review_with_group_and_member()
        add_focus_group_member(group["id"], member["id"])
        resp = api_client.add_focus_group_member(group["id"], {"member_id": member["id"]},
                                                 quality_director_headers)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_FOCUS_MEMBER.value, expected_status=409)
        members = validate_success(
            api_client.list_focus_group_members(group["id"], quality_director_headers))
        assert len(members) == 1

    def test_membership_remove_not_found_returns_404(self, quality_director_headers):
        """PRD §3.8: "Removing a member deletes the membership row outright,
        and a removal naming a pair with no membership row is rejected with
        `ERR_MEMBERSHIP_NOT_FOUND`."

        Design: Corner/validations/membership_remove_not_found_returns_404
        """
        _, member, _, group = self._review_with_group_and_member()
        resp = api_client.remove_focus_group_member(group["id"], member["id"],
                                                    quality_director_headers)
        validate_error(resp, ApiErrorId.ERR_MEMBERSHIP_NOT_FOUND.value, expected_status=404)


class TestFocusedReviewClose:
    def test_close_on_already_closed_review_returns_invalid_state(self, quality_director_headers):
        """PRD §2.8: "The target entity must be in a state from which the
        requested transition exists; otherwise `ERR_INVALID_STATE` (409)."
        PRD §3.8: "Closing one requires the director's `resolution_note` —
        omitting it is rejected with `ERR_VALIDATION` — and stamps
        `closed_at`, sets the status to `CLOSED`, and increments the version."

        Design: Corner/state_machines/focused_review_close_on_closed_returns_invalid_state
        """
        subject = create_provider("Subj FR", "CARDIOLOGY")
        review = create_focused_review(subject["id"], "manual")
        close_focused_review(review["id"], "done once")

        resp = api_client.close_focused_review(
            review["id"], close_focused_review_payload(resolution_note="done twice"),
            quality_director_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)

        after = validate_success(api_client.get_focused_review(review["id"], QD))
        assert_instant_equals(after["closed_at"], "2026-08-01T00:00:00Z")
        assert after["resolution_note"] == "done once"


class TestFocusPanelQuorum:
    def _deliberation_case_with_focus_group(self, num_panelists):
        """Case in DELIBERATION with scores (4,4,4); the subject is under an
        ACTIVE MANUAL FocusedReview with one group holding the first
        `num_panelists` of the case's three reviewers."""
        ctx = setup_case_in_deliberation(
            scores=((4, None), (4, None), (4, None)),
            subject_specialty="PEDIATRICS",
            member_specialties=("PEDIATRICS", "SURGERY", "CARDIOLOGY"))
        review = create_focused_review(ctx["subject"]["id"], "prior trend")
        group = create_focus_group(review["id"], "quorum-panel")
        for member in ctx["members"][:num_panelists]:
            add_focus_group_member(group["id"], member["id"])
        return ctx, group

    def test_finalize_rejected_with_insufficient_panel_quorum(self):
        """PRD §3.5: "One quorum rule can stand in the way: when the subject
        provider has an `ACTIVE` focused review, at least two of the case's
        three `SUBMITTED` reviewers must be members of at least one focus
        group belonging to that focused review, otherwise the finalization is
        rejected with `ERR_FOCUS_PANEL_QUORUM_NOT_MET` (409)."

        Design: Difficulty/cross_entity_state_dependency/finalize_quorum_requires_focus_group_membership
        """
        ctx, _ = self._deliberation_case_with_focus_group(num_panelists=1)
        resp = api_client.finalize_deliberation(
            ctx["case"]["id"], {"rationale_note": "attempt with one panelist"},
            make_committee_member_headers(ctx["chair"]["id"]))
        validate_error(resp, ApiErrorId.ERR_FOCUS_PANEL_QUORUM_NOT_MET.value,
                       expected_status=409)
        case_after = get_case(ctx["case"]["id"])
        assert case_after["status"] == "DELIBERATION", (
            "the rejected finalization must not move the case")

    def test_finalize_succeeds_once_quorum_met(self):
        """PRD §3.5: "when the subject provider has an `ACTIVE` focused
        review, at least two of the case's three `SUBMITTED` reviewers must be
        members of at least one focus group belonging to that focused review,
        otherwise the finalization is rejected with
        `ERR_FOCUS_PANEL_QUORUM_NOT_MET` (409)."
        PRD §3.5: "The case then moves to `NOTIFIED` with its `version`
        incremented".

        Design: Difficulty/cross_entity_state_dependency/finalize_quorum_requires_focus_group_membership
        """
        ctx, group = self._deliberation_case_with_focus_group(num_panelists=1)
        # Seat a second panelist; the identical finalize now meets the quorum.
        add_focus_group_member(group["id"], ctx["members"][1]["id"])
        deliberation = finalize_deliberation(
            ctx["case"]["id"], ctx["chair"]["id"], "quorum met")
        assert deliberation["rating"] == "APPROPRIATE"
        case_after = get_case(ctx["case"]["id"])
        assert case_after["status"] == "NOTIFIED"
