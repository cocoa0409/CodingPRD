"""Testimony scheduling: interval rule, clock gate, overlap regimes, fees, terminal lockdown."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    assert_testimony_schedule, ApiErrorId,
    create_venue, create_schedule, confirm_schedule, create_confirmed_schedule,
    create_report, submit_report, finalize_report,
    setup_active_engagement, set_clock,
    TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]
CM = TEST_USERS["case_manager_headers"]


class TestIntervalRule:

    def test_end_equal_start_rejected(self, api):
        """PRD §3.6: "The interval must be sensible: `end_at` strictly after `start_at`,
        else `ERR_INVALID_INTERVAL`."

        Design: Corner/validations/schedule_end_before_start_rejected
        """
        sc = setup_active_engagement()
        res = api.create_testimony_schedule(
            sc["engagement"]["id"],
            {"kind": "DEPOSITION", "start_at": "2026-06-15T12:00:00Z",
             "end_at": "2026-06-15T12:00:00Z", "estimated_hours": 1},
            CM)
        validate_error(res, ApiErrorId.ERR_INVALID_INTERVAL)


class TestScheduleInPast:

    def test_default_clock_rejects_past_start_and_allows_future(self, api):
        """PRD §2.5: "At server startup, before any administrative call, the logical clock
        reads exactly `2026-05-01T00:00:00Z`; it never falls back to wall-clock time."
        PRD §3.6: "the session must start strictly after the current logical clock, with a
        start at or before the present rejected as `ERR_SCHEDULE_IN_PAST`".

        Design: Corner/validations/schedule_in_past_rejected_at_default_clock
        """
        sc = setup_active_engagement()
        gid = sc["engagement"]["id"]

        res = api.create_testimony_schedule(
            gid, {"kind": "DEPOSITION", "start_at": "2026-04-30T10:00:00Z",
                  "end_at": "2026-04-30T12:00:00Z", "estimated_hours": 2}, CM)
        validate_error(res, ApiErrorId.ERR_SCHEDULE_IN_PAST)

        ok = validate_success(api.create_testimony_schedule(
            gid, {"kind": "DEPOSITION", "start_at": "2026-05-01T00:00:01Z",
                  "end_at": "2026-05-01T02:00:00Z", "estimated_hours": 2}, CM), 201)
        assert_testimony_schedule(ok)
        assert ok["status"] == "PROPOSED", "one second after the default clock is valid"


class TestExpertCalendarOverlap:
    """Half-open expert calendar: adjacency legal, one second of true overlap conflicts."""

    def test_adjacency_at_prior_end_allowed(self, api):
        """PRD §2.10: "Because the intervals are half-open, adjacency is allowed: a new
        session starting at exactly the instant an existing session ends does not conflict."

        Design: Difficulty/resource_temporal_overlap/expert_calendar_half_open_adjacency
        """
        sc = setup_active_engagement()
        gid = sc["engagement"]["id"]
        create_schedule(gid, start_at="2026-06-15T10:00:00Z", end_at="2026-06-15T12:00:00Z")

        adjacent = validate_success(api.create_testimony_schedule(
            gid, {"kind": "DEPOSITION", "start_at": "2026-06-15T12:00:00Z",
                  "end_at": "2026-06-15T14:00:00Z", "estimated_hours": 2}, CM), 201)
        assert adjacent["status"] == "PROPOSED", "start == prior end: half-open adjacency allowed"

    def test_one_second_overlap_conflicts(self, api):
        """PRD §2.10: "A new session conflicts with an existing session of the same expert
        whenever the existing session starts before the new session ends and the new session
        starts before the existing session ends." and "A violation is rejected with
        `ERR_SCHEDULE_CONFLICT` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/expert_calendar_half_open_adjacency
        """
        sc = setup_active_engagement()
        gid = sc["engagement"]["id"]
        create_schedule(gid, start_at="2026-06-15T10:00:00Z", end_at="2026-06-15T12:00:00Z")

        res = api.create_testimony_schedule(
            gid, {"kind": "DEPOSITION", "start_at": "2026-06-15T11:59:59Z",
                  "end_at": "2026-06-15T13:00:00Z", "estimated_hours": 1}, CM)
        validate_error(res, ApiErrorId.ERR_SCHEDULE_CONFLICT)


class TestVenueBuffer:
    """Closed venue intervals with a 30-minute turnover buffer."""

    def _setup_venue_with_session(self, api):
        sc = setup_active_engagement()
        venue = create_venue(name="Suite 4A", location="NYC")
        create_schedule(sc["engagement"]["id"],
                        start_at="2026-06-15T10:00:00Z", end_at="2026-06-15T12:00:00Z",
                        venue_id=venue["id"])
        return sc, venue

    def test_start_exactly_thirty_minutes_after_end_conflicts(self, api):
        """PRD §2.10: "When a session names a `venue_id`, the session is treated as
        occupying that room from thirty minutes before its `start_at` until thirty minutes
        after its `end_at`, with both boundary instants included. Two buffered windows for
        the same venue conflict whenever each starts at or before the other's buffered end —
        which means touching still conflicts: a new session starting exactly thirty minutes
        after an existing session's end violates the buffer. A violation is rejected with
        `ERR_VENUE_CONFLICT` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/venue_closed_interval_turnover_buffer
        """
        sc, venue = self._setup_venue_with_session(api)
        res = api.create_testimony_schedule(
            sc["engagement"]["id"],
            {"kind": "DEPOSITION", "start_at": "2026-06-15T13:00:00Z",
             "end_at": "2026-06-15T15:00:00Z", "estimated_hours": 2, "venue_id": venue["id"]},
            CM)
        validate_error(res, ApiErrorId.ERR_VENUE_CONFLICT)

    def test_one_second_past_buffer_is_free(self, api):
        """PRD §2.10: "the session is treated as occupying that room from thirty minutes
        before its `start_at` until thirty minutes after its `end_at`, with both boundary
        instants included" — so a buffered start one second past the prior buffered end does
        not touch and is allowed.

        Design: Difficulty/resource_temporal_overlap/venue_closed_interval_turnover_buffer
        """
        sc, venue = self._setup_venue_with_session(api)
        free = validate_success(api.create_testimony_schedule(
            sc["engagement"]["id"],
            {"kind": "DEPOSITION", "start_at": "2026-06-15T13:00:01Z",
             "end_at": "2026-06-15T15:00:00Z", "estimated_hours": 2, "venue_id": venue["id"]},
            CM), 201)
        assert free["status"] == "PROPOSED"


class TestTrialConfirmGate:

    def _setup_trial_with_draft_report(self, api):
        sc = setup_active_engagement()
        gid = sc["engagement"]["id"]
        schedule = create_schedule(gid, kind="TRIAL",
                                   start_at="2026-08-10T09:00:00Z", end_at="2026-08-10T17:00:00Z",
                                   estimated_hours=8)
        report = create_report(gid, title="Liability", report_type="LIABILITY")
        return sc, schedule, report

    def test_trial_confirm_blocked_without_finalized_report(self, api):
        """PRD §3.6: "for a session of kind `TRIAL` the engagement must additionally hold a
        report in `FINALIZED` or `DISCLOSED`, else `ERR_REPORT_NOT_FINALIZED`."

        Design: Difficulty/cross_entity_state_dependency/trial_confirm_requires_report_finalized
        """
        sc, schedule, report = self._setup_trial_with_draft_report(api)
        assert report["status"] == "DRAFT"

        res = api.confirm_schedule(schedule["id"], CM)
        validate_error(res, ApiErrorId.ERR_REPORT_NOT_FINALIZED)

    def test_trial_confirm_succeeds_after_finalize(self, api):
        """PRD §3.6: "for a session of kind `TRIAL` the engagement must additionally hold a
        report in `FINALIZED` or `DISCLOSED`, else `ERR_REPORT_NOT_FINALIZED`."
        PRD §3.5: "a `decision` of `FINALIZE` moves it `IN_REVIEW` → `FINALIZED`."

        Design: Difficulty/cross_entity_state_dependency/trial_confirm_requires_report_finalized
        """
        sc, schedule, report = self._setup_trial_with_draft_report(api)

        res = api.confirm_schedule(schedule["id"], CM)
        validate_error(res, ApiErrorId.ERR_REPORT_NOT_FINALIZED)

        submit_report(report["id"], sc["expert"]["id"])
        finalize_report(report["id"])

        confirmed = validate_success(api.confirm_schedule(schedule["id"], CM), 200)
        assert_testimony_schedule(confirmed)
        assert confirmed["status"] == "CONFIRMED"


class TestCancellationFee:

    def test_late_cancel_draws_fee_from_retainer(self, api):
        """PRD §3.6: "Cancelling a `CONFIRMED` session inside the late window draws a fee
        from the retainer: when the logical clock has passed the instant seventy-two hours
        before the session's `start_at`, the `cancellation_fee_cents` is fifty percent of
        the estimated testimony value — the `estimated_hours` multiplied by the engagement's
        `hourly_rate_cents` and by one and a quarter — rounded half-up to the nearest cent;
        the draw is the lesser of that fee and the remaining retainer, and is added to
        `retainer_drawn_cents`."

        Design: Corner/calculations/cancellation_fee_within_72h
        """
        sc = setup_active_engagement(engagement_overrides={"retainer_cents": 100_000})
        gid = sc["engagement"]["id"]
        schedule = create_confirmed_schedule(
            gid, kind="DEPOSITION", start_at="2026-06-15T10:00:00Z",
            end_at="2026-06-15T12:00:00Z", estimated_hours=4)

        set_clock("2026-06-14T12:00:00Z")  # 22h before start: inside the 72h window
        cancelled = validate_success(api.cancel_schedule(
            schedule["id"], {"reason": "client settled late"}, CM), 200)
        assert cancelled["status"] == "CANCELLED"
        # 0.50 * 4 * 40000 * 1.25 = 100000
        assert cancelled["cancellation_fee_cents"] == 100_000

        engagement = validate_success(api.get_engagement(gid, CM), 200)
        assert engagement["retainer_drawn_cents"] == 100_000, "fee drawn from retainer (capped by remaining)"
        assert engagement["retainer_remaining_cents"] == 0


class TestTerminalLockdown:

    def test_confirm_after_cancel_rejected(self, api):
        """PRD §3.6: "A `CaseManager` confirms a `PROPOSED` session — moving it `PROPOSED` →
        `CONFIRMED`" and "Cancellation distinguishes posture and always lands the session in
        `CANCELLED`."
        PRD §2.11: "then the target entity's state preconditions for the requested
        transition are checked, with violations yielding `ERR_INVALID_STATE` (HTTP 409)".

        Design: Corner/state_machines/cancelled_schedule_confirm_rejected
        """
        sc = setup_active_engagement()
        schedule = create_schedule(sc["engagement"]["id"])
        cancelled = validate_success(api.cancel_schedule(
            schedule["id"], {"reason": "settled"}, CM), 200)
        assert cancelled["status"] == "CANCELLED"

        res = api.confirm_schedule(schedule["id"], CM)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
