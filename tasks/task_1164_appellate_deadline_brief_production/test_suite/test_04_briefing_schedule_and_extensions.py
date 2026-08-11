"""Briefing schedule activation, extension-motion cascades, OCC guards, vacate."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    assert_briefing_schedule, assert_extension_motion, assert_brief,
    assert_instant_equal, add_calendar_days, iso_utc, parse_ts,
    assert_schedule_dates_ordered, find_deadline,
    attorney_headers,
    setup_briefing_case,
    create_court, create_attorney, create_case, file_and_accept_notice,
    get_case_schedule, reset_clock,
    create_brief, submit_brief, approve_brief, create_motion, grant_motion,
    get_schedule_version, get_case_version, list_case_deadlines,
    walk_brief_to_ready, walk_brief_to_efiled,
    CLERK, ADMIN,
)


class TestScheduleActivationDates:
    def test_schedule_dates_forward_anchored_on_record_completion(self, api):
        """PRD §3.4: "The moment the record reaches `COMPLETE`, the schedule
        moves from `PENDING` to `ACTIVE` and its three dates are computed by
        forward anchoring on the record's completion instant: `opening_due_at` is
        the anchor plus the court's opening-brief window (forty days by default),
        `response_due_at` is the opening date plus the court's response window
        (thirty days by default), and `reply_due_at` is the response date plus
        the court's `reply_brief_window_days`."

        Design: Difficulty/combinatorial_formula/briefing_schedule_multi_input_cascade
        """
        ctx = setup_briefing_case(
            court_overrides={"code": "CA9", "reply_brief_window_days": 14},
            complete_clock="2026-07-01T00:00:00Z",
        )
        schedule = ctx["schedule"]
        assert_briefing_schedule(schedule)
        assert schedule["status"] == "ACTIVE"
        assert_instant_equal(schedule["opening_due_at"], "2026-08-10T00:00:00Z")
        assert_instant_equal(schedule["response_due_at"], "2026-09-09T00:00:00Z")
        assert_instant_equal(schedule["reply_due_at"], "2026-09-23T00:00:00Z")
        assert_schedule_dates_ordered(schedule)

    def test_opening_grant_cascades_to_response_and_reply(self, api):
        """PRD §3.4: "targeting `OPENING` shifts `opening_due_at`,
        `response_due_at`, and `reply_due_at` all forward by the same delta,
        because the response is anchored to the opening and the reply to the
        response; targeting `RESPONSE` shifts `response_due_at` and
        `reply_due_at`; targeting `REPLY` shifts `reply_due_at` alone."

        Design: Difficulty/combinatorial_formula/briefing_schedule_multi_input_cascade
        """
        ctx = setup_briefing_case(
            court_overrides={"code": "CA9M", "reply_brief_window_days": 14},
            complete_clock="2026-07-01T00:00:00Z",
        )
        motion = create_motion(ctx, target="OPENING", requested_days=7)
        version = get_schedule_version(ctx)
        res = grant_motion(motion, granted_days=7, expected_schedule_version=version)
        granted = validate_success(res, 200)
        assert_extension_motion(granted)
        assert granted["status"] == "GRANTED"
        assert granted["granted_days"] == 7

        schedule = validate_success(
            api.get_schedule(ctx["schedule"]["id"], attorney_headers(ctx["attorney"])), 200
        )
        assert_instant_equal(schedule["opening_due_at"], "2026-08-17T00:00:00Z")
        assert_instant_equal(schedule["response_due_at"], "2026-09-16T00:00:00Z")
        assert_instant_equal(schedule["reply_due_at"], "2026-09-30T00:00:00Z")
        assert schedule["extensions_granted_count"] == 1
        assert_schedule_dates_ordered(schedule)


class TestExtensionCascadeDepth:
    def test_grant_rederives_brief_due_at_from_shifted_schedule(self, api):
        """PRD §3.4: "Every brief whose `brief_type` matches the target or any
        cascaded target has its `due_at` re-derived from the shifted schedule,
        every deadline row of the matching kind has its `final_due_at` recomputed
        as its `provisional_due_at` plus the total granted days, and the
        schedule's `extensions_granted_count` increments by one."

        Design: Difficulty/transitive_cascade/extension_grant_cascade_depth3_motion_to_schedule_to_brief_to_deadline
        """
        ctx = setup_briefing_case(court_overrides={"code": "CASC"})
        brief = create_brief(ctx, "OPENING")
        assert_brief(brief)
        opening_before = find_deadline(list_case_deadlines(ctx), "OPENING_BRIEF")
        assert_instant_equal(brief["due_at"], ctx["schedule"]["opening_due_at"])
        assert_instant_equal(opening_before["final_due_at"], opening_before["provisional_due_at"])

        motion = create_motion(ctx, target="OPENING", requested_days=10)
        version = get_schedule_version(ctx)
        validate_success(grant_motion(motion, 10, version), 200)

        brief_after = validate_success(
            api.get_brief(brief["id"], attorney_headers(ctx["attorney"])), 200
        )
        expected = iso_utc(add_calendar_days(ctx["schedule"]["opening_due_at"], 10))
        assert_instant_equal(
            brief_after["due_at"], expected,
            "brief due_at must be re-derived from the shifted schedule",
        )

    def test_grant_recomputes_matching_deadline_final_due_at(self, api):
        """PRD §3.4: "Every brief whose `brief_type` matches the target or any
        cascaded target has its `due_at` re-derived from the shifted schedule,
        every deadline row of the matching kind has its `final_due_at` recomputed
        as its `provisional_due_at` plus the total granted days, and the
        schedule's `extensions_granted_count` increments by one."

        Design: Difficulty/transitive_cascade/extension_grant_cascade_depth3_motion_to_schedule_to_brief_to_deadline
        """
        ctx = setup_briefing_case(court_overrides={"code": "CAS2"})
        opening_before = find_deadline(list_case_deadlines(ctx), "OPENING_BRIEF")

        motion = create_motion(ctx, target="OPENING", requested_days=10)
        version = get_schedule_version(ctx)
        validate_success(grant_motion(motion, 10, version), 200)

        opening_after = find_deadline(list_case_deadlines(ctx), "OPENING_BRIEF")
        expected_final = iso_utc(add_calendar_days(opening_before["provisional_due_at"], 10))
        assert_instant_equal(
            opening_after["final_due_at"], expected_final,
            "OPENING_BRIEF final_due_at must equal provisional plus total granted days",
        )
        assert_instant_equal(
            opening_after["provisional_due_at"], opening_before["provisional_due_at"],
            "provisional must not move when an extension is granted",
        )
        schedule = validate_success(
            api.get_schedule(ctx["schedule"]["id"], attorney_headers(ctx["attorney"])), 200
        )
        assert schedule["extensions_granted_count"] == 1


class TestGrantValidation:
    def test_grant_with_zero_days_returns_grant_days_invalid(self, api):
        """PRD §3.4: "The grant payload must carry a `granted_days` that is at
        least one and no more than the motion's `requested_days` — anything
        outside that band is rejected with `ERR_GRANT_DAYS_INVALID` — and the
        schedule must still be `ACTIVE`."

        Design: Corner/validations/grant_extension_with_zero_days_returns_invalid
        """
        ctx = setup_briefing_case(court_overrides={"code": "V2"})
        motion = create_motion(ctx, target="OPENING", requested_days=7)
        version = get_schedule_version(ctx)
        res = grant_motion(motion, granted_days=0, expected_schedule_version=version)
        validate_error(res, ApiErrorId.ERR_GRANT_DAYS_INVALID.value, expected_status=422)

    def test_grant_above_requested_days_returns_grant_days_invalid(self, api):
        """PRD §3.4: "The grant payload must carry a `granted_days` that is at
        least one and no more than the motion's `requested_days` — anything
        outside that band is rejected with `ERR_GRANT_DAYS_INVALID` — and the
        schedule must still be `ACTIVE`."

        Design: Corner/validations/grant_extension_with_zero_days_returns_invalid
        """
        ctx = setup_briefing_case(court_overrides={"code": "V2B"})
        motion = create_motion(ctx, target="OPENING", requested_days=7)
        version = get_schedule_version(ctx)
        res = grant_motion(motion, granted_days=8, expected_schedule_version=version)
        validate_error(res, ApiErrorId.ERR_GRANT_DAYS_INVALID.value, expected_status=422)


class TestOptimisticConcurrency:
    def test_grant_with_stale_schedule_version_returns_stale_version(self, api):
        """PRD §2.6: "Granting an extension motion requires the request to carry
        `expected_schedule_version` holding the `version` of the governing
        briefing schedule as the caller last observed it; a mismatch with the
        schedule's current `version` is likewise rejected with
        `ERR_STALE_VERSION` (HTTP 412), because a previously granted motion may
        already have shifted the same target deadline and a second grant computed
        from a stale view would double-apply deltas."

        Design: Corner/errors/err_stale_version_triggered_by_occ_mismatch
        """
        ctx = setup_briefing_case(court_overrides={"code": "E1"})
        stale_version = get_schedule_version(ctx)
        motion_a = create_motion(ctx, target="OPENING", requested_days=7, reason="first")
        motion_b = create_motion(ctx, target="RESPONSE", requested_days=5, reason="second")
        validate_success(grant_motion(motion_a, 7, stale_version), 200)

        res = grant_motion(motion_b, 5, stale_version)
        validate_error(res, ApiErrorId.ERR_STALE_VERSION.value, expected_status=412)
        motion_b_after = validate_success(
            api.get_motion(motion_b["id"], attorney_headers(ctx["attorney"])), 200
        )
        assert motion_b_after["status"] == "PENDING", (
            "a grant rejected for staleness must leave the motion PENDING"
        )

    def test_grant_increments_schedule_version_by_one(self, api):
        """PRD §3.4: "Both the schedule and the motion increment their `version`."
        PRD §2.4: "The `version` is an integer that starts at 1 when the resource
        is created and increments by exactly 1 on every mutation of that
        resource, including system-driven mutations described in §3."

        Design: Corner/endpoints/extension_motion_grant_computes_case_version_bump
        """
        ctx = setup_briefing_case(court_overrides={"code": "EP1"})
        motion = create_motion(ctx, target="OPENING", requested_days=7)
        version_before = get_schedule_version(ctx)
        validate_success(grant_motion(motion, 7, version_before), 200)
        schedule = validate_success(
            api.get_schedule(ctx["schedule"]["id"], attorney_headers(ctx["attorney"])), 200
        )
        assert schedule["version"] == version_before + 1, (
            f"schedule version must increment by exactly 1 on grant: {version_before} -> {schedule['version']}"
        )

    def test_vacate_with_stale_case_version_returns_stale_version(self, api):
        """PRD §2.6: "Vacating a briefing schedule requires the request to carry
        `expected_case_version` holding the `version` of the parent case as the
        caller last observed it; if the case's current `version` has advanced
        beyond that observed value — for example because another writer filed a
        brief or a petition ruling reopened the case since the clerk's last read
        — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), because
        vacating would silently undo work the caller never saw."

        Design: Corner/cross_cutting_complexity_layers/occ_vacate_stale_case_version
        """
        reset_clock()
        court = create_court(code="CC-OCC")
        attorney = create_attorney(admitted_court_ids=[court["id"]])
        case = create_case(court, attorney)
        stale_version = case["version"]
        file_and_accept_notice(case, attorney)  # posture change bumps case version
        schedule = get_case_schedule(case["id"], attorney_headers(attorney))

        res = api.vacate_schedule(
            schedule["id"], {"expected_case_version": stale_version}, CLERK
        )
        validate_error(res, ApiErrorId.ERR_STALE_VERSION.value, expected_status=412)


class TestScheduleVacateInvariant:
    def test_vacate_returns_all_briefs_to_draft(self, api):
        """PRD §3.4: "Vacating from `ACTIVE` is allowed only while no brief under
        the schedule has reached `EFILED` or `ACCEPTED`; it returns every brief
        under the schedule to `DRAFT`, marks every brief-type deadline row
        unmet, and moves the schedule to `VACATED`."

        Design: Difficulty/compensating_invariant/schedule_vacate_restores_brief_state_invariant
        """
        ctx = setup_briefing_case(court_overrides={"code": "CI1"})
        brief_a = create_brief(ctx, "OPENING")
        brief_b = create_brief(ctx, "RESPONSE")
        submit_brief(brief_a, ctx["attorney"])
        walk_brief_to_ready(ctx, brief_b)  # IN_REVIEW -> READY via reviewer

        case_version = get_case_version(ctx)
        res = api.vacate_schedule(
            ctx["schedule"]["id"], {"expected_case_version": case_version}, CLERK
        )
        schedule = validate_success(res, 200)
        assert schedule["status"] == "VACATED"

        for brief, prior in ((brief_a, "IN_REVIEW"), (brief_b, "READY")):
            after = validate_success(
                api.get_brief(brief["id"], attorney_headers(ctx["attorney"])), 200
            )
            assert after["status"] == "DRAFT", (
                f"brief that was {prior} must return to DRAFT after vacate, got {after['status']}"
            )
        headers = attorney_headers(ctx["attorney"])
        briefs = get_success_data(api.list_schedule_briefs(ctx["schedule"]["id"], headers))
        briefs = briefs if isinstance(briefs, list) else [briefs]
        non_draft = [b for b in briefs if b.get("status") != "DRAFT"]
        assert non_draft == [], f"no brief on a vacated schedule may remain non-DRAFT: {non_draft}"

    def test_vacate_blocked_once_brief_efiled(self, api):
        """PRD §3.4: "Vacating from `ACTIVE` is allowed only while no brief under
        the schedule has reached `EFILED` or `ACCEPTED`; it returns every brief
        under the schedule to `DRAFT`, marks every brief-type deadline row
        unmet, and moves the schedule to `VACATED`."
        PRD §2.9: "5. **State validity** — the target resource is in a state from
        which the requested transition exists (for example, a brief may be
        submitted for review only while `DRAFT`); otherwise `ERR_INVALID_STATE`
        (HTTP 409). Applies to every state-transition endpoint."

        Design: Difficulty/compensating_invariant/schedule_vacate_restores_brief_state_invariant
        """
        ctx = setup_briefing_case(court_overrides={"code": "CI1B"})
        brief = create_brief(ctx, "OPENING")
        walk_brief_to_efiled(ctx, brief)

        case_version = get_case_version(ctx)
        res = api.vacate_schedule(
            ctx["schedule"]["id"], {"expected_case_version": case_version}, CLERK
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)
        schedule = validate_success(
            api.get_schedule(ctx["schedule"]["id"], attorney_headers(ctx["attorney"])), 200
        )
        assert schedule["status"] == "ACTIVE", "a blocked vacate must leave the schedule ACTIVE"
