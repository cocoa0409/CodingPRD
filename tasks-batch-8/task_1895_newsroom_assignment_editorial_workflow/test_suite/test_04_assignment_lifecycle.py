"""Assignment lifecycle: proposal validation, accept/decline/cancel state
rules, ownership, half-open overlap, the acceptance cap, the live employment
gate, the workload counter invariant, and validation-order pairs."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    create_assignment_payload,
    create_greenlit_story,
    get_success_data,
    make_reporter_headers,
    make_staff,
    patch_staff,
    propose_and_accept,
    propose_assignment,
    setup_newsroom,
    validate_error,
    validate_paginated,
    validate_success,
)

ND = TEST_USERS["news_director_headers"]


class TestProposalValidation:
    def test_invalid_interval_on_assignment(self, api):
        """PRD §3.3: "The window must be sane: `end_at` must fall strictly
        after `start_at`, otherwise `ERR_INVALID_INTERVAL` (HTTP 422)."

        Design: Corner/validations/invalid_interval_on_assignment
        """
        ctx = setup_newsroom()
        _pitch, story_id = create_greenlit_story(ctx)
        payload = create_assignment_payload(
            story_id, ctx["reporter"]["id"],
            start_at="2026-08-01T09:00:00Z", end_at="2026-08-01T09:00:00Z",
            planned_effort_minutes=30)
        resp = api.create_assignment(payload, ctx["desk_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_INTERVAL)

    def test_capability_mismatch_on_propose(self, api):
        """PRD §3.3: "the staff member's `employment_status` must be `ACTIVE`
        (`ERR_STAFF_INACTIVE`, HTTP 422), and the proposed `assignment_role`
        must equal the staff member's `role_capability` — a photographer
        cannot be crewed as a reporter (`ERR_CAPABILITY_MISMATCH`, HTTP 422)."

        Design: Corner/validations/capability_mismatch_on_propose
        """
        ctx = setup_newsroom()
        _pitch, story_id = create_greenlit_story(ctx)
        payload = create_assignment_payload(
            story_id, ctx["reporter"]["id"], assignment_role="PHOTOGRAPHER",
            planned_effort_minutes=30)
        resp = api.create_assignment(payload, ctx["desk_headers"])
        validate_error(resp, ApiErrorId.ERR_CAPABILITY_MISMATCH)

    def test_body_fk_story_not_found(self, api):
        """PRD §2.6: "Foreign keys supplied in request bodies are checked after
        path resolution: proposing an assignment rejects an unknown `story_id`
        with `ERR_STORY_NOT_FOUND` and an unknown `staff_id` with
        `ERR_STAFF_NOT_FOUND`; scheduling rejects an unknown `slot_id` with
        `ERR_SLOT_NOT_FOUND`; linking a follow-up rejects an unknown
        `superseding_story_id` with `ERR_STORY_NOT_FOUND`."

        Design: Corner/validations/body_fk_story_not_found
        """
        ctx = setup_newsroom()
        payload = create_assignment_payload(
            NON_EXISTENT_UUID, ctx["reporter"]["id"],
            planned_effort_minutes=30)
        resp = api.create_assignment(payload, ctx["desk_headers"])
        validate_error(resp, ApiErrorId.ERR_STORY_NOT_FOUND)


class TestAssignmentAnswerRules:
    def test_assignment_double_accept_rejected(self, api):
        """PRD §3.3: "Accepting or declining is restricted to `Reporter` and
        `Photographer` roles acting on their own assignments — the ownership
        check compares `X-User-ID` to the assignment's `staff_id` and rejects
        others with `ERR_FORBIDDEN` — and only a `PROPOSED` assignment can be
        answered (`ERR_INVALID_STATE` otherwise)."

        Design: Corner/state_machines/assignment_double_accept_rejected
        """
        ctx = setup_newsroom()
        _pitch, story_id = create_greenlit_story(ctx)
        asg = propose_assignment(ctx, story_id, ctx["reporter"]["id"])
        first = api.accept_assignment(asg["id"], ctx["reporter_headers"])
        assert validate_success(first)["status"] == "ACCEPTED"
        second = api.accept_assignment(asg["id"], ctx["reporter_headers"])
        validate_error(second, ApiErrorId.ERR_INVALID_STATE)

    def test_assignment_decline_then_accept_rejected(self, api):
        """PRD §3.3: "Accepting or declining is restricted to `Reporter` and
        `Photographer` roles acting on their own assignments — the ownership
        check compares `X-User-ID` to the assignment's `staff_id` and rejects
        others with `ERR_FORBIDDEN` — and only a `PROPOSED` assignment can be
        answered (`ERR_INVALID_STATE` otherwise)."

        Design: Corner/state_machines/assignment_decline_then_accept_rejected
        """
        ctx = setup_newsroom()
        _pitch, story_id = create_greenlit_story(ctx)
        asg = propose_assignment(ctx, story_id, ctx["reporter"]["id"])
        declined = api.decline_assignment(asg["id"], ctx["reporter_headers"])
        assert validate_success(declined)["status"] == "DECLINED"
        resp = api.accept_assignment(asg["id"], ctx["reporter_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_accept_by_other_staff_forbidden(self, api):
        """PRD §3.3: "Accepting or declining is restricted to `Reporter` and
        `Photographer` roles acting on their own assignments — the ownership
        check compares `X-User-ID` to the assignment's `staff_id` and rejects
        others with `ERR_FORBIDDEN` — and only a `PROPOSED` assignment can be
        answered (`ERR_INVALID_STATE` otherwise)."

        Design: Corner/validations/accept_by_other_staff_forbidden
        """
        ctx = setup_newsroom()
        other = make_staff("Rep Two AO", "REPORTER", home_desk="SPORTS")
        other_h = make_reporter_headers(other["id"])
        _pitch, story_id = create_greenlit_story(ctx)
        asg = propose_assignment(ctx, story_id, ctx["reporter"]["id"])
        resp = api.accept_assignment(asg["id"], other_h)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


class TestStaffTimeOverlap:
    def _three_stories(self, ctx):
        return [create_greenlit_story(ctx, title=t)[1] for t in "ABC"]

    def test_adjacent_half_open_windows_do_not_conflict(self, api):
        """PRD §3.3: "A proposal conflicts with any other assignment of the
        same staff member in `PROPOSED` or `ACCEPTED` status when the new
        `start_at` falls before the other's `end_at` and the new `end_at`
        falls after the other's `start_at`; windows that merely touch
        end-to-start do not conflict."

        Design: Difficulty/resource_temporal_overlap/staff_assignment_half_open_adjacency
        """
        ctx = setup_newsroom()
        sa, sb, _sc = self._three_stories(ctx)
        rep = ctx["reporter"]["id"]
        a1 = propose_assignment(ctx, sa, rep, start_at="2026-08-01T10:00:00Z",
                                end_at="2026-08-01T12:00:00Z")
        assert a1["status"] == "PROPOSED"
        # [12:00,14:00) touches [10:00,12:00) end-to-start: no conflict.
        a2 = propose_assignment(ctx, sb, rep, start_at="2026-08-01T12:00:00Z",
                                end_at="2026-08-01T14:00:00Z")
        assert a2["status"] == "PROPOSED", \
            "adjacent half-open windows are both allowed"

    def test_overlapping_window_conflicts(self, api):
        """PRD §3.3: "A proposal conflicts with any other assignment of the
        same staff member in `PROPOSED` or `ACCEPTED` status when the new
        `start_at` falls before the other's `end_at` and the new `end_at`
        falls after the other's `start_at`; windows that merely touch
        end-to-start do not conflict."
        PRD §3.3: "A conflicting proposal is rejected with
        `ERR_STAFF_TIME_CONFLICT` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/staff_assignment_half_open_adjacency
        """
        ctx = setup_newsroom()
        sa, sb, sc = self._three_stories(ctx)
        rep = ctx["reporter"]["id"]
        propose_assignment(ctx, sa, rep, start_at="2026-08-01T10:00:00Z",
                           end_at="2026-08-01T12:00:00Z")
        propose_assignment(ctx, sb, rep, start_at="2026-08-01T12:00:00Z",
                           end_at="2026-08-01T14:00:00Z")
        # [13:00,15:00) intersects [12:00,14:00): 13:00 < 14:00 and 15:00 >
        # 12:00.
        payload = create_assignment_payload(
            sc, rep, start_at="2026-08-01T13:00:00Z",
            end_at="2026-08-01T15:00:00Z")
        resp = api.create_assignment(payload, ctx["desk_headers"])
        validate_error(resp, ApiErrorId.ERR_STAFF_TIME_CONFLICT)


class TestAssignmentCap:
    def _capped_reporter(self, ctx):
        """Two greenlit stories; A1 accepted, A2 proposed (cap is 1)."""
        sa = create_greenlit_story(ctx, title="Story A")[1]
        sb = create_greenlit_story(ctx, title="Story B")[1]
        rep = ctx["reporter"]["id"]
        propose_and_accept(ctx, sa, "reporter",
                           start_at="2026-08-01T08:00:00Z",
                           end_at="2026-08-01T09:00:00Z",
                           planned_effort_minutes=30)
        a2 = propose_assignment(ctx, sb, rep,
                                start_at="2026-08-01T10:00:00Z",
                                end_at="2026-08-01T11:00:00Z",
                                planned_effort_minutes=30)
        return sb, a2

    def test_second_accept_rejected_exactly_at_cap(self, api):
        """PRD §3.3: "Acceptance re-verifies the world at the moment of
        answer: the staff member must still be `ACTIVE`
        (`ERR_STAFF_INACTIVE`), the half-open overlap check runs again against
        their other `PROPOSED` and `ACCEPTED` assignments
        (`ERR_STAFF_TIME_CONFLICT`), and the acceptance cap applies — the
        staff member's count of `ACCEPTED` assignments must be below their
        `max_concurrent_assignments`, with rejection exactly when the count
        already equals the cap (`ERR_ASSIGNMENT_CAP_REACHED`, HTTP 422)."

        Design: Difficulty/boundary_precision_check/assignment_cap_at_max
        """
        ctx = setup_newsroom(reporter_max=1)
        sb, a2 = self._capped_reporter(ctx)
        resp = api.accept_assignment(a2["id"], ctx["reporter_headers"])
        validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_CAP_REACHED)

        assignments, meta = validate_paginated(
            api.get_story_assignments(sb, ctx["desk_headers"]))
        assert meta["total_count"] == 1
        assert assignments[0]["status"] == "PROPOSED", \
            "the failed accept did not transition the assignment"

    def test_failed_accept_leaves_workload_counter_unchanged(self, api):
        """PRD §3.3: "Because `PROPOSED` and `ACCEPTED` both count toward
        `active_assignment_count`, acceptance leaves that counter's value
        unchanged."
        PRD §2.11: "A staff member's `active_assignment_count` is the number
        of their assignments in `PROPOSED` or `ACCEPTED` status — declined,
        cancelled, completed, and bumped assignments do not count — and it is
        recomputed on every assignment status mutation affecting that staff
        member."

        Design: Difficulty/boundary_precision_check/assignment_cap_at_max
        """
        ctx = setup_newsroom(reporter_max=1)
        _sb, a2 = self._capped_reporter(ctx)
        resp = api.accept_assignment(a2["id"], ctx["reporter_headers"])
        validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_CAP_REACHED)
        staff = get_success_data(api.get_staff(ctx["reporter"]["id"], ND))
        assert staff["active_assignment_count"] == 2, \
            "one PROPOSED plus one ACCEPTED; the failed accept changed nothing"


class TestStaffLiveStateGate:
    def test_accept_rejected_while_staff_on_leave(self, api):
        """PRD §3.3: "Acceptance re-verifies the world at the moment of
        answer: the staff member must still be `ACTIVE`
        (`ERR_STAFF_INACTIVE`), the half-open overlap check runs again against
        their other `PROPOSED` and `ACCEPTED` assignments
        (`ERR_STAFF_TIME_CONFLICT`), and the acceptance cap applies — the
        staff member's count of `ACCEPTED` assignments must be below their
        `max_concurrent_assignments`, with rejection exactly when the count
        already equals the cap (`ERR_ASSIGNMENT_CAP_REACHED`, HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/assignment_accept_requires_active_staff
        """
        ctx = setup_newsroom()
        _pitch, story_id = create_greenlit_story(ctx)
        asg = propose_assignment(ctx, story_id, ctx["reporter"]["id"],
                                 planned_effort_minutes=45)
        patch_staff(ctx["reporter"]["id"], employment_status="ON_LEAVE")
        resp = api.accept_assignment(asg["id"], ctx["reporter_headers"])
        validate_error(resp, ApiErrorId.ERR_STAFF_INACTIVE)

    def test_accept_succeeds_after_reactivation(self, api):
        """PRD §3.3: "Acceptance re-verifies the world at the moment of
        answer: the staff member must still be `ACTIVE`
        (`ERR_STAFF_INACTIVE`), the half-open overlap check runs again against
        their other `PROPOSED` and `ACCEPTED` assignments
        (`ERR_STAFF_TIME_CONFLICT`), and the acceptance cap applies — the
        staff member's count of `ACCEPTED` assignments must be below their
        `max_concurrent_assignments`, with rejection exactly when the count
        already equals the cap (`ERR_ASSIGNMENT_CAP_REACHED`, HTTP 422)."
        PRD §3.1: "Only staff whose `employment_status` is `ACTIVE` may be
        proposed for or accept new work, so leave and separation immediately
        close the staffing pipeline without touching history."

        Design: Difficulty/cross_entity_state_dependency/assignment_accept_requires_active_staff
        """
        ctx = setup_newsroom()
        _pitch, story_id = create_greenlit_story(ctx)
        asg = propose_assignment(ctx, story_id, ctx["reporter"]["id"],
                                 planned_effort_minutes=45)
        patch_staff(ctx["reporter"]["id"], employment_status="ON_LEAVE")
        resp = api.accept_assignment(asg["id"], ctx["reporter_headers"])
        validate_error(resp, ApiErrorId.ERR_STAFF_INACTIVE)

        patch_staff(ctx["reporter"]["id"], employment_status="ACTIVE")
        ok = api.accept_assignment(asg["id"], ctx["reporter_headers"])
        assert validate_success(ok)["status"] == "ACCEPTED", \
            "the gate reads the live employment_status, not proposal-time"


class TestActiveCountRoundTrip:
    def test_propose_then_cancel_compensate(self, api):
        """PRD §2.11: "A staff member's `active_assignment_count` is the
        number of their assignments in `PROPOSED` or `ACCEPTED` status —
        declined, cancelled, completed, and bumped assignments do not count —
        and it is recomputed on every assignment status mutation affecting
        that staff member."
        PRD §3.3: "The desk may also cancel an assignment in `PROPOSED` or
        `ACCEPTED` status, moving it to `CANCELLED` and recomputing the staff
        counter down by one; the same cancellation arrives as a side effect
        when a story is killed (§3.5)."

        Design: Difficulty/compensating_invariant/staff_active_count_round_trip
        """
        ctx = setup_newsroom()
        rep_id = ctx["reporter"]["id"]
        story_a = create_greenlit_story(ctx, title="Story A")[1]
        a1 = propose_assignment(ctx, story_a, rep_id,
                                planned_effort_minutes=30)
        staff = get_success_data(api.get_staff(rep_id, ND))
        assert staff["active_assignment_count"] == 1, \
            "the new proposal raises the counter by one"

        get_success_data(api.cancel_assignment(a1["id"], ctx["desk_headers"]))
        staff = get_success_data(api.get_staff(rep_id, ND))
        assert staff["active_assignment_count"] == 0, \
            "cancel compensates the proposal exactly"

    def test_accept_then_complete_round_trip(self, api):
        """PRD §2.11: "A staff member's `active_assignment_count` is the
        number of their assignments in `PROPOSED` or `ACCEPTED` status —
        declined, cancelled, completed, and bumped assignments do not count —
        and it is recomputed on every assignment status mutation affecting
        that staff member."
        PRD §3.3: "Completion records reality. The assigned field staff member
        — or an `AssignmentEditor` on their behalf — completes an `ACCEPTED`
        assignment by supplying `actual_effort_minutes` (at least 1); the
        server stamps `completed_at` with the logical clock, recomputes the
        staff member's `active_assignment_count` down by one, and settles
        cost."

        Design: Difficulty/compensating_invariant/staff_active_count_round_trip
        """
        ctx = setup_newsroom()
        rep_id = ctx["reporter"]["id"]
        story_b = create_greenlit_story(ctx, title="Story B")[1]
        a2 = propose_assignment(ctx, story_b, rep_id,
                                start_at="2026-08-01T10:00:00Z",
                                end_at="2026-08-01T11:00:00Z",
                                planned_effort_minutes=30)
        staff = get_success_data(api.get_staff(rep_id, ND))
        assert staff["active_assignment_count"] == 1

        get_success_data(api.accept_assignment(a2["id"],
                                               ctx["reporter_headers"]))
        staff = get_success_data(api.get_staff(rep_id, ND))
        assert staff["active_assignment_count"] == 1, \
            "PROPOSED and ACCEPTED both count, so acceptance changes nothing"

        get_success_data(api.complete_assignment(
            a2["id"], {"actual_effort_minutes": 30}, ctx["reporter_headers"]))
        staff = get_success_data(api.get_staff(rep_id, ND))
        assert staff["active_assignment_count"] == 0, \
            "completion releases the count"


class TestStateBeatsConstraint:
    def _killed_story_with_overlap(self, api, ctx):
        """Reporter holds an ACCEPTED assignment 10:00-12:00 on story A;
        story B is greenlit then KILLED. Returns (story_b_id, rep_id)."""
        rep_id = ctx["reporter"]["id"]
        sa = create_greenlit_story(ctx, title="Story A")[1]
        propose_and_accept(ctx, sa, "reporter",
                           start_at="2026-08-01T10:00:00Z",
                           end_at="2026-08-01T12:00:00Z")
        sb = create_greenlit_story(ctx, title="Story B")[1]
        get_success_data(
            api.kill_story(sb, ctx["managing_editor_headers"]))
        return sb, rep_id

    def test_killed_story_proposal_reports_state_error(self, api):
        """PRD §2.7: "Every write request passes through a single ordered
        validation pipeline, and the first failing check determines the error
        returned."
        PRD §2.7: "8. From-state legality — the target resource is in a
        from-state of the invoked transition; failures yield
        `ERR_INVALID_STATE` (HTTP 409), except that proposing a correction or
        ingesting analytics against a story that is not published yields
        `ERR_STORY_NOT_PUBLISHED` (HTTP 409)."
        PRD §2.7: "13. Mutual exclusion and uniqueness — staff time overlap
        (`ERR_STAFF_TIME_CONFLICT`, HTTP 409), same-channel slot window
        spacing (`ERR_SLOT_WINDOW_CONFLICT`, HTTP 409), analytics window
        uniqueness (`ERR_DUPLICATE_ANALYTICS_WINDOW`, HTTP 409), slot
        cancellation with reservations outstanding (`ERR_SLOT_NOT_EMPTY`,
        HTTP 409), and the pitch rework limit (`ERR_PITCH_REWORK_LIMIT`,
        HTTP 422)."
        PRD §3.3: "A story in `DRAFT`, `IN_EDIT`, or `ON_HOLD` may be crewed;
        proposing an assignment against a story in any other state is rejected
        with `ERR_INVALID_STATE`."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_constraint_on_assign
        """
        ctx = setup_newsroom(managing_editor=True)
        sb, rep_id = self._killed_story_with_overlap(api, ctx)
        # Both failures are latent: story B is KILLED (state) and
        # [11:00,13:00) overlaps the reporter's ACCEPTED 10:00-12:00
        # (constraint). The state check fires first.
        payload = create_assignment_payload(
            sb, rep_id, start_at="2026-08-01T11:00:00Z",
            end_at="2026-08-01T13:00:00Z", planned_effort_minutes=30)
        resp = api.create_assignment(payload, ctx["desk_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_rejected_proposal_persists_nothing(self, api):
        """PRD §3.3: "A story in `DRAFT`, `IN_EDIT`, or `ON_HOLD` may be
        crewed; proposing an assignment against a story in any other state is
        rejected with `ERR_INVALID_STATE`."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_constraint_on_assign
        """
        ctx = setup_newsroom(managing_editor=True)
        sb, rep_id = self._killed_story_with_overlap(api, ctx)
        payload = create_assignment_payload(
            sb, rep_id, start_at="2026-08-01T11:00:00Z",
            end_at="2026-08-01T13:00:00Z", planned_effort_minutes=30)
        resp = api.create_assignment(payload, ctx["desk_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assignments, meta = validate_paginated(
            api.get_story_assignments(sb, ctx["desk_headers"]))
        assert meta["total_count"] == 0 and assignments == [], \
            "a rejected proposal persists no assignment"

