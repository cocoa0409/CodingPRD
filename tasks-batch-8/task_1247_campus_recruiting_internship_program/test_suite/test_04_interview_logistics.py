"""Interview days, slot booking guards, evaluator governance, auto-flip."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    make_recruiter_headers, make_evaluator_headers,
    create_interview_day_payload, create_interview_slot_payload,
)
from test_helpers import fixtures as fx

RECRUITER = make_recruiter_headers()


class TestDayWindowContainment:
    def test_day_outside_season_interview_window(self, api):
        """PRD §3.5: "The day's window must be contained in the season's —
        `window_start_at` at or after the season's
        `interview_window_start_at`, and `window_end_at` at or before the
        season's `interview_window_end_at` — failing with
        `ERR_DAY_OUTSIDE_WINDOW` (HTTP 422) otherwise."

        Design: Corner/validations/day_outside_season_interview_window
        """
        season = fx.create_season()
        fx.create_school(season["id"])
        fx.advance_season(season["id"])  # OPEN
        fx.set_clock("2026-05-21T00:00:00Z")
        fx.advance_season(season["id"])  # SELECTION
        resp = api.create_interview_day(
            season["id"],
            create_interview_day_payload(
                window_start_at="2026-05-25T09:00:00Z",
                window_end_at="2026-05-25T17:00:00Z",
            ),
            RECRUITER,
        )
        validate_error(resp, ApiErrorId.ERR_DAY_OUTSIDE_WINDOW)

    def test_slot_outside_day_window_pure(self, api):
        """PRD §3.5: "the slot must be contained in the day's window, starting
        at or after `window_start_at` and ending at or before `window_end_at`
        (`ERR_SLOT_OUTSIDE_DAY_WINDOW`, HTTP 422)".

        Design: Corner/validations/slot_outside_day_window_pure
        """
        ctx = fx.setup_selection_with_day_and_evaluator()
        resp = api.book_interview_slot(
            ctx.day["id"],
            create_interview_slot_payload(
                application_id=ctx.application["id"],
                evaluator_id=ctx.evaluator["id"],
                start_at="2026-06-08T16:30:00Z", end_at="2026-06-08T17:30:00Z",
            ),
            RECRUITER,
        )
        validate_error(resp, ApiErrorId.ERR_SLOT_OUTSIDE_DAY_WINDOW)


class TestSlotConflictRules:
    def test_candidate_schedule_overlap(self, api):
        """PRD §3.5: "the candidate's own schedule first — the new slot's
        half-open interval must not intersect any existing `BOOKED` slot of
        the same application on any day, touching boundaries permitted, else
        `ERR_CANDIDATE_SCHEDULE_CONFLICT` (HTTP 409)".

        Design: Corner/validations/candidate_schedule_overlap
        """
        ctx = fx.setup_selection_with_day_and_evaluator()
        ev2 = fx.create_employee(
            ctx.season["id"], full_name="Olive", email="ol@co.com",
        )
        resp1 = api.book_interview_slot(
            ctx.day["id"],
            create_interview_slot_payload(
                application_id=ctx.application["id"],
                evaluator_id=ctx.evaluator["id"],
            ),
            RECRUITER,
        )
        assert resp1.status_code == 201
        resp = api.book_interview_slot(
            ctx.day["id"],
            create_interview_slot_payload(
                application_id=ctx.application["id"], evaluator_id=ev2["id"],
                start_at="2026-06-08T10:30:00Z", end_at="2026-06-08T11:30:00Z",
            ),
            RECRUITER,
        )
        validate_error(resp, ApiErrorId.ERR_CANDIDATE_SCHEDULE_CONFLICT)

    def test_evaluator_zero_gap_rejected(self, api):
        """PRD §3.5: "the evaluator's buffered schedule second: measured
        against the evaluator's `BOOKED` or `COMPLETED` slots on the same day,
        where the gap between two intervals is zero when they intersect and
        otherwise the time separating the earlier interval's end from the
        later interval's start, a gap of strictly less than 15 minutes rejects
        the booking with `ERR_EVALUATOR_SCHEDULE_CONFLICT` (HTTP 409), while a
        gap of exactly 15 minutes is allowed."

        Design: Difficulty/resource_temporal_overlap/evaluator_buffered_gap_fifteen_minutes
        """
        season = fx.create_season()
        school = fx.create_school(season["id"])
        fx.advance_season(season["id"])  # OPEN
        fx.set_clock("2026-05-15T00:00:00Z")
        c1 = fx.create_candidate(email="a@x.com", full_name="Candidate A")
        c2 = fx.create_candidate(email="b@x.com", full_name="Candidate B")
        app1 = fx.submit_application(season["id"], c1["id"], school["id"])
        app2 = fx.submit_application(season["id"], c2["id"], school["id"])
        fx.set_clock("2026-05-21T00:00:00Z")
        fx.advance_season(season["id"])  # SELECTION
        for app in (app1, app2):
            r = api.screen_application(app["id"], "SHORTLIST", RECRUITER)
            assert r.status_code == 200
        ev = fx.create_employee(season["id"])
        day = validate_success(api.create_interview_day(
            season["id"], create_interview_day_payload(), RECRUITER,
        ), expected_status=201)
        resp1 = api.book_interview_slot(
            day["id"],
            create_interview_slot_payload(
                application_id=app1["id"], evaluator_id=ev["id"],
            ),
            RECRUITER,
        )
        assert resp1.status_code == 201
        resp = api.book_interview_slot(
            day["id"],
            create_interview_slot_payload(
                application_id=app2["id"], evaluator_id=ev["id"],
                start_at="2026-06-08T11:00:00Z", end_at="2026-06-08T11:30:00Z",
            ),
            RECRUITER,
        )
        validate_error(resp, ApiErrorId.ERR_EVALUATOR_SCHEDULE_CONFLICT)

    def test_evaluator_exactly_fifteen_minute_gap_allowed(self, api):
        """PRD §3.5: "a gap of strictly less than 15 minutes rejects the
        booking with `ERR_EVALUATOR_SCHEDULE_CONFLICT` (HTTP 409), while a gap
        of exactly 15 minutes is allowed."

        Design: Difficulty/resource_temporal_overlap/evaluator_buffered_gap_fifteen_minutes
        """
        season = fx.create_season()
        school = fx.create_school(season["id"])
        fx.advance_season(season["id"])  # OPEN
        fx.set_clock("2026-05-15T00:00:00Z")
        c1 = fx.create_candidate(email="a@x.com", full_name="Candidate A")
        c2 = fx.create_candidate(email="b@x.com", full_name="Candidate B")
        app1 = fx.submit_application(season["id"], c1["id"], school["id"])
        app2 = fx.submit_application(season["id"], c2["id"], school["id"])
        fx.set_clock("2026-05-21T00:00:00Z")
        fx.advance_season(season["id"])  # SELECTION
        for app in (app1, app2):
            r = api.screen_application(app["id"], "SHORTLIST", RECRUITER)
            assert r.status_code == 200
        ev = fx.create_employee(season["id"])
        day = validate_success(api.create_interview_day(
            season["id"], create_interview_day_payload(), RECRUITER,
        ), expected_status=201)
        resp1 = api.book_interview_slot(
            day["id"],
            create_interview_slot_payload(
                application_id=app1["id"], evaluator_id=ev["id"],
            ),
            RECRUITER,
        )
        assert resp1.status_code == 201
        resp2 = api.book_interview_slot(
            day["id"],
            create_interview_slot_payload(
                application_id=app2["id"], evaluator_id=ev["id"],
                start_at="2026-06-08T11:15:00Z", end_at="2026-06-08T12:00:00Z",
            ),
            RECRUITER,
        )
        assert validate_success(resp2, expected_status=201)["status"] == "BOOKED"
        day_after = validate_success(api.get_interview_day(day["id"], RECRUITER))
        assert day_after["booked_count"] == 2


class TestSlotGovernance:
    def test_evaluator_coi_case_insensitive(self, api):
        """PRD §3.5: "the evaluator's `alma_mater_school_name` must not equal,
        case-insensitively, the applicant school's `school_name`
        (`ERR_EVALUATOR_CONFLICT_OF_INTEREST`, HTTP 422)".

        Design: Corner/validations/evaluator_coi_case_insensitive
        """
        ctx = fx.setup_selection_with_day_and_evaluator(
            employee_overrides={"alma_mater_school_name": "stateu"},
        )
        resp = api.book_interview_slot(
            ctx.day["id"],
            create_interview_slot_payload(
                application_id=ctx.application["id"],
                evaluator_id=ctx.evaluator["id"],
            ),
            RECRUITER,
        )
        validate_error(resp, ApiErrorId.ERR_EVALUATOR_CONFLICT_OF_INTEREST)

    def test_slot_book_safety_beats_temporal(self, api):
        """PRD §2.11: "(10) the business-safety rules — conflict of interest
        before calibration before segregation of duties before capability
        flags; (11) temporal window rules". PRD §2.11: "An earlier failure
        masks every later check: the response carries the error of the first
        failed rule only."

        Design: Difficulty/priority_pair_validation_conflict/slot_book_safety_beats_temporal
        """
        ctx = fx.setup_selection_with_day_and_evaluator(
            employee_overrides={"alma_mater_school_name": "StateU"},
        )
        # Slot outside the day window AND conflict-of-interest both fail; the
        # safety rule is earlier in the fixed order.
        resp = api.book_interview_slot(
            ctx.day["id"],
            create_interview_slot_payload(
                application_id=ctx.application["id"],
                evaluator_id=ctx.evaluator["id"],
                start_at="2026-06-08T18:00:00Z", end_at="2026-06-08T19:00:00Z",
            ),
            RECRUITER,
        )
        validate_error(resp, ApiErrorId.ERR_EVALUATOR_CONFLICT_OF_INTEREST)

    def test_slot_book_coi_also_when_inside_window(self, api):
        """PRD §3.5: "the evaluator's `alma_mater_school_name` must not equal,
        case-insensitively, the applicant school's `school_name`
        (`ERR_EVALUATOR_CONFLICT_OF_INTEREST`, HTTP 422)" — the check fires
        on its own when no other guard fails.

        Design: Difficulty/priority_pair_validation_conflict/slot_book_safety_beats_temporal
        """
        ctx = fx.setup_selection_with_day_and_evaluator(
            employee_overrides={"alma_mater_school_name": "StateU"},
        )
        resp = api.book_interview_slot(
            ctx.day["id"],
            create_interview_slot_payload(
                application_id=ctx.application["id"],
                evaluator_id=ctx.evaluator["id"],
            ),
            RECRUITER,
        )
        validate_error(resp, ApiErrorId.ERR_EVALUATOR_CONFLICT_OF_INTEREST)

    def test_calibration_gate_core_requires_calibrated(self, api):
        """PRD §3.5: "an applicant from a `CORE`-tier school may only be
        assigned to a `calibrated` evaluator
        (`ERR_EVALUATOR_NOT_CALIBRATED`, HTTP 422)".

        Design: Corner/validations/calibration_gate_core_requires_calibrated
        """
        season = fx.create_season()
        school = fx.create_school(
            season["id"], school_name="MetroU", tier="CORE",
            stipend_region="METRO",
        )
        fx.advance_season(season["id"])
        fx.set_clock("2026-05-15T00:00:00Z")
        cand = fx.create_candidate()
        app = fx.submit_application(season["id"], cand["id"], school["id"])
        fx.set_clock("2026-05-21T00:00:00Z")
        fx.advance_season(season["id"])
        r = api.screen_application(app["id"], "SHORTLIST", RECRUITER)
        assert r.status_code == 200
        ev = fx.create_employee(season["id"])  # calibrated defaults to false
        day = validate_success(api.create_interview_day(
            season["id"], create_interview_day_payload(), RECRUITER,
        ), expected_status=201)
        resp = api.book_interview_slot(
            day["id"],
            create_interview_slot_payload(
                application_id=app["id"], evaluator_id=ev["id"],
            ),
            RECRUITER,
        )
        validate_error(resp, ApiErrorId.ERR_EVALUATOR_NOT_CALIBRATED)

    def test_capability_missing_evaluator(self, api):
        """PRD §3.5: "the evaluator's `can_evaluate` flag must be set
        (`ERR_CAPABILITY_MISSING`, HTTP 422)".

        Design: Corner/validations/capability_missing_evaluator
        """
        ctx = fx.setup_selection_with_day_and_evaluator(
            employee_overrides={"can_evaluate": False},
        )
        resp = api.book_interview_slot(
            ctx.day["id"],
            create_interview_slot_payload(
                application_id=ctx.application["id"],
                evaluator_id=ctx.evaluator["id"],
            ),
            RECRUITER,
        )
        validate_error(resp, ApiErrorId.ERR_CAPABILITY_MISSING)


class TestCapacityRules:
    def test_day_capacity_boundary(self, api):
        """PRD §3.5: "Last come the two capacity checks, both reported as
        `ERR_DAY_AT_CAPACITY` (HTTP 422): the day's `booked_count` must still
        be below its `capacity`".

        Design: Corner/validations/day_capacity_boundary
        """
        season = fx.create_season()
        school = fx.create_school(season["id"])
        fx.advance_season(season["id"])
        fx.set_clock("2026-05-15T00:00:00Z")
        c1 = fx.create_candidate(email="a@x.com", full_name="Candidate A")
        c2 = fx.create_candidate(email="b@x.com", full_name="Candidate B")
        app1 = fx.submit_application(season["id"], c1["id"], school["id"])
        app2 = fx.submit_application(season["id"], c2["id"], school["id"])
        fx.set_clock("2026-05-21T00:00:00Z")
        fx.advance_season(season["id"])
        for app in (app1, app2):
            r = api.screen_application(app["id"], "SHORTLIST", RECRUITER)
            assert r.status_code == 200
        ev1 = fx.create_employee(season["id"])
        ev2 = fx.create_employee(
            season["id"], full_name="Olive", email="ol@co.com",
        )
        day = validate_success(api.create_interview_day(
            season["id"], create_interview_day_payload(capacity=1), RECRUITER,
        ), expected_status=201)
        resp1 = api.book_interview_slot(
            day["id"],
            create_interview_slot_payload(
                application_id=app1["id"], evaluator_id=ev1["id"],
            ),
            RECRUITER,
        )
        assert resp1.status_code == 201
        resp = api.book_interview_slot(
            day["id"],
            create_interview_slot_payload(
                application_id=app2["id"], evaluator_id=ev2["id"],
                start_at="2026-06-08T11:15:00Z", end_at="2026-06-08T12:00:00Z",
            ),
            RECRUITER,
        )
        validate_error(resp, ApiErrorId.ERR_DAY_AT_CAPACITY)

    def test_evaluator_daily_limit(self, api):
        """PRD §3.5: "the evaluator's load on that day — their `BOOKED` and
        `COMPLETED` slots — must still be below their `daily_slot_limit`"
        (reported as `ERR_DAY_AT_CAPACITY`, HTTP 422).

        Design: Corner/validations/evaluator_daily_limit
        """
        season = fx.create_season()
        school = fx.create_school(season["id"])
        fx.advance_season(season["id"])
        fx.set_clock("2026-05-15T00:00:00Z")
        c1 = fx.create_candidate(email="a@x.com", full_name="Candidate A")
        c2 = fx.create_candidate(email="b@x.com", full_name="Candidate B")
        app1 = fx.submit_application(season["id"], c1["id"], school["id"])
        app2 = fx.submit_application(season["id"], c2["id"], school["id"])
        fx.set_clock("2026-05-21T00:00:00Z")
        fx.advance_season(season["id"])
        for app in (app1, app2):
            r = api.screen_application(app["id"], "SHORTLIST", RECRUITER)
            assert r.status_code == 200
        ev = fx.create_employee(season["id"], daily_slot_limit=1)
        day = validate_success(api.create_interview_day(
            season["id"], create_interview_day_payload(capacity=5), RECRUITER,
        ), expected_status=201)
        resp1 = api.book_interview_slot(
            day["id"],
            create_interview_slot_payload(
                application_id=app1["id"], evaluator_id=ev["id"],
            ),
            RECRUITER,
        )
        assert resp1.status_code == 201
        resp = api.book_interview_slot(
            day["id"],
            create_interview_slot_payload(
                application_id=app2["id"], evaluator_id=ev["id"],
                start_at="2026-06-08T13:00:00Z", end_at="2026-06-08T14:00:00Z",
            ),
            RECRUITER,
        )
        validate_error(resp, ApiErrorId.ERR_DAY_AT_CAPACITY)


class TestDayLifecycleAndSlotOutcomes:
    def test_day_complete_rejected_when_open_or_slots_pending(self, api):
        """PRD §3.5: "Completing a day requires it to be `LOCKED` and every
        one of its slots terminal (`COMPLETED`, `CANCELLED`, or `NO_SHOW`);
        the move to `COMPLETED` is otherwise rejected with
        `ERR_DAY_STATE_FORBIDDEN`." Also: "no further bookings or
        cancellations are accepted once locked".

        Design: Corner/state_machines/day_complete_rejected_when_open_or_slots_pending
        """
        ctx = fx.setup_interview_scheduled()
        # day1 locked with a BOOKED slot still pending.
        resp = api.lock_interview_day(ctx.day["id"], RECRUITER)
        assert resp.status_code == 200
        # A second, OPEN day.
        day2 = validate_success(api.create_interview_day(
            ctx.season["id"],
            create_interview_day_payload(
                window_start_at="2026-06-09T09:00:00Z",
                window_end_at="2026-06-09T17:00:00Z",
            ),
            RECRUITER,
        ), expected_status=201)
        resp1 = api.complete_interview_day(day2["id"], RECRUITER)
        validate_error(resp1, ApiErrorId.ERR_DAY_STATE_FORBIDDEN)
        resp2 = api.complete_interview_day(ctx.day["id"], RECRUITER)
        validate_error(resp2, ApiErrorId.ERR_DAY_STATE_FORBIDDEN)
        resp3 = api.book_interview_slot(
            ctx.day["id"],
            create_interview_slot_payload(
                application_id=ctx.application["id"],
                evaluator_id=ctx.evaluator["id"],
                start_at="2026-06-08T13:00:00Z", end_at="2026-06-08T14:00:00Z",
            ),
            RECRUITER,
        )
        validate_error(resp3, ApiErrorId.ERR_DAY_STATE_FORBIDDEN)

    def test_slot_evaluation_completes_slot_and_bubbles_application(self, api):
        """PRD §3.5: "Submission moves the slot `BOOKED → COMPLETED` and
        re-evaluates the auto-flip rule" and "the application flips ... forward
        to `DECISION_PENDING` if at least one did [complete]". Also: "The
        evaluation records the slot as `interview_slot_id` (taken from the
        path) and denormalizes `evaluator_id` from the slot at submission".

        Design: Corner/state_machines/slot_evaluation_completes_slot_and_bubbles_application
        """
        ctx = fx.setup_interview_scheduled()
        resp = api.submit_evaluation(
            ctx.slot["id"], {"score": 5, "recommendation": "STRONG_HIRE"},
            make_evaluator_headers(ctx.evaluator["id"]),
        )
        evaluation = validate_success(resp, expected_status=201)
        assert evaluation["evaluator_id"] == ctx.evaluator["id"]
        slot = validate_success(api.get_interview_slot(ctx.slot["id"], RECRUITER))
        assert slot["status"] == "COMPLETED"
        app = validate_success(api.get_application(ctx.application["id"], RECRUITER))
        assert app["status"] == "DECISION_PENDING"

    def test_evaluation_on_cancelled_slot_rejected(self, api):
        """PRD §3.5: "both of them — like evaluation submission below —
        require the slot to still be `BOOKED`, failing with
        `ERR_SLOT_STATE_FORBIDDEN` (HTTP 409) once it has left that status."

        Design: Corner/state_machines/evaluation_on_cancelled_slot_rejected
        """
        ctx = fx.setup_interview_scheduled()
        resp = api.cancel_interview_slot(ctx.slot["id"], RECRUITER)
        assert resp.status_code == 200
        resp = api.submit_evaluation(
            ctx.slot["id"], {"score": 4, "recommendation": "HIRE"},
            make_evaluator_headers(ctx.evaluator["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SLOT_STATE_FORBIDDEN)


class TestApplicationInterviewCycle:
    def test_book_moves_shortlisted_to_interview_scheduled(self, api):
        """PRD §3.5: "the first slot booked for an application moves it
        `SHORTLISTED → INTERVIEW_SCHEDULED`."

        Design: Difficulty/non_linear_state_machine/application_shortlist_interview_cycle
        """
        ctx = fx.setup_selection_with_day_and_evaluator()
        resp = api.book_interview_slot(
            ctx.day["id"],
            create_interview_slot_payload(
                application_id=ctx.application["id"],
                evaluator_id=ctx.evaluator["id"],
            ),
            RECRUITER,
        )
        assert resp.status_code == 201
        app = validate_success(api.get_application(ctx.application["id"], RECRUITER))
        assert app["status"] == "INTERVIEW_SCHEDULED"

    def test_cancel_all_slots_flips_back_and_rebooking_closes_cycle(self, api):
        """PRD §3.5: "when the application is in `INTERVIEW_SCHEDULED` and
        every one of its slots has reached a terminal status (`COMPLETED`,
        `CANCELLED`, or `NO_SHOW`), the application flips back to
        `SHORTLISTED` if not a single slot completed"; "Booking followed by
        cancelling every slot therefore cycles an application `SHORTLISTED →
        INTERVIEW_SCHEDULED → SHORTLISTED` without recruiter intervention."

        Design: Difficulty/non_linear_state_machine/application_shortlist_interview_cycle
        """
        ctx = fx.setup_interview_scheduled()
        resp = api.cancel_interview_slot(ctx.slot["id"], RECRUITER)
        assert resp.status_code == 200
        app = validate_success(api.get_application(ctx.application["id"], RECRUITER))
        assert app["status"] == "SHORTLISTED"
        day = validate_success(api.get_interview_day(ctx.day["id"], RECRUITER))
        assert day["booked_count"] == 0
        resp = api.book_interview_slot(
            ctx.day["id"],
            create_interview_slot_payload(
                application_id=ctx.application["id"],
                evaluator_id=ctx.evaluator["id"],
                start_at="2026-06-08T13:00:00Z", end_at="2026-06-08T14:00:00Z",
            ),
            RECRUITER,
        )
        assert resp.status_code == 201
        app = validate_success(api.get_application(ctx.application["id"], RECRUITER))
        assert app["status"] == "INTERVIEW_SCHEDULED"
        day = validate_success(api.get_interview_day(ctx.day["id"], RECRUITER))
        assert day["booked_count"] == 1


class TestSeatCompensationInvariant:
    def test_book_then_cancel_leaves_booked_count_unchanged(self, api):
        """PRD §3.5: "Cancelling a slot — additionally permitted only while
        the season is in `SELECTION` and the day is `OPEN` — moves it `BOOKED
        → CANCELLED` and decrements the day's `booked_count` by one, the
        compensating action of the booking."

        Design: Difficulty/compensating_invariant/interview_day_seat_compensation
        """
        ctx = fx.setup_interview_scheduled()
        day = validate_success(api.get_interview_day(ctx.day["id"], RECRUITER))
        assert day["booked_count"] == 1
        resp = api.cancel_interview_slot(ctx.slot["id"], RECRUITER)
        assert resp.status_code == 200
        day = validate_success(api.get_interview_day(ctx.day["id"], RECRUITER))
        assert day["booked_count"] == 0

    def test_no_show_keeps_seat_consumed(self, api):
        """PRD §3.5: "Marking a no-show — permitted while the season is in
        `SELECTION` and the day is `OPEN` or `LOCKED` — moves it `BOOKED →
        NO_SHOW` and leaves `booked_count` unchanged: a no-show consumes the
        seat."

        Design: Difficulty/compensating_invariant/interview_day_seat_compensation
        """
        ctx = fx.setup_interview_scheduled()
        # Book+cancel pair: net zero.
        resp = api.cancel_interview_slot(ctx.slot["id"], RECRUITER)
        assert resp.status_code == 200
        day = validate_success(api.get_interview_day(ctx.day["id"], RECRUITER))
        assert day["booked_count"] == 0
        # Re-book and mark no-show: seat stays consumed.
        resp = api.book_interview_slot(
            ctx.day["id"],
            create_interview_slot_payload(
                application_id=ctx.application["id"],
                evaluator_id=ctx.evaluator["id"],
                start_at="2026-06-08T13:00:00Z", end_at="2026-06-08T14:00:00Z",
            ),
            RECRUITER,
        )
        slot2 = validate_success(resp, expected_status=201)
        resp = api.no_show_interview_slot(slot2["id"], RECRUITER)
        assert validate_success(resp)["status"] == "NO_SHOW"
        day = validate_success(api.get_interview_day(ctx.day["id"], RECRUITER))
        assert day["booked_count"] == 1
