"""Team meetings: the ratification cascade, meeting counters, and lifecycle
gates on ratify (PRD §3.7)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_second_window_screening,
    close_window,
    committed_minutes,
    convene_meeting,
    create_screening_window,
    create_team_meeting,
    define_cut_point,
    enroll_student,
    first_proposed_movement,
    get_plan,
    get_student,
    propose_movement,
    ratify_movement,
    record_score,
    score_window,
    set_clock,
    setup_active_plan,
    setup_district_school,
    setup_students_with_ratified_tiers,
    validate_error,
    validate_success,
)

COORD = TEST_USERS["district_coordinator_headers"]
LEAD = TEST_USERS["team_lead_headers"]


class TestRatificationCascade:
    def test_ratify_cascades_mismatched_plan_to_exit_moved(self, api):
        """PRD §3.7: "The movement transitions to `RATIFIED` and its
        `decided_at_meeting_id` is set to the meeting that decided it. The
        student's `current_tier` becomes the movement's `to_tier`, and when that
        target is `TIER_1` the student's `weeks_at_tier3_unresponsive` resets to
        zero. Any `ACTIVE` plan whose `tier_at_start` no longer matches the
        student's new tier cascades to `EXIT_MOVED`, releasing its
        `weekly_minute_cost` from the interventionist's
        `committed_minutes_per_week`."
        PRD §3.7: "The meeting's `minuted_movement_count` — initialized at 0 when
        the meeting is scheduled — increments by one, and the student's `version`
        increments by one."

        The cascade here originates from the ratify endpoint: the TIER_2 plan
        (90 committed minutes) ends as EXIT_MOVED once the student is ratified
        to TIER_3.

        Design: Difficulty/transitive_cascade/tier_ratify_cascades_to_plan_exit_and_supersede
        """
        ctx = setup_active_plan(api, tier="TIER_2", session_minutes=30,
                                sessions_per_week=3)
        d_id, s_id = ctx["district"]["id"], ctx["school"]["id"]
        st_id, plan_id = ctx["student"]["id"], ctx["plan"]["id"]
        assert committed_minutes(api, ctx) == 90

        add_second_window_screening(api, ctx, raw_score=60)
        movement = propose_movement(api, d_id, s_id, st_id, "TIER_3",
                                    rationale="WINTER screening shows TIER_3")
        meeting = create_team_meeting(api, d_id, s_id, scheduled_on="2026-12-20")
        convene_meeting(api, d_id, s_id, meeting["id"])

        before = get_student(api, d_id, s_id, st_id)
        ratified = ratify_movement(api, d_id, s_id, meeting["id"],
                                   movement["id"], st_id)
        assert ratified["status"] == "RATIFIED"
        assert ratified["decided_at_meeting_id"] == meeting["id"]

        student = get_student(api, d_id, s_id, st_id)
        assert student["current_tier"] == "TIER_3"
        assert student["version"] == before["version"] + 1, (
            "ratification increments the student's version by one")

        plan = get_plan(api, d_id, s_id, st_id, plan_id)
        assert plan["status"] == "EXIT_MOVED", (
            "tier_at_start TIER_2 mismatches the new tier TIER_3")
        assert committed_minutes(api, ctx) == 0, (
            "the cascade releases the plan's weekly_minute_cost")

    def test_ratify_sets_meeting_fields_and_counts(self, api):
        """PRD §3.7: "The movement transitions to `RATIFIED` and its
        `decided_at_meeting_id` is set to the meeting that decided it."
        PRD §3.7: "The meeting's `minuted_movement_count` — initialized at 0 when
        the meeting is scheduled — increments by one, and the student's `version`
        increments by one."

        Two students are auto-proposed by the same scored window and both are
        ratified at one convened meeting.

        Design: Difficulty/transitive_cascade/tier_ratify_cascades_to_plan_exit_and_supersede
        """
        ctx = setup_students_with_ratified_tiers(api, raw_scores=[80, 82])
        d_id, s_id = ctx["district"]["id"], ctx["school"]["id"]
        meeting = validate_success(api.get_team_meeting(
            d_id, s_id, ctx["meeting"]["id"], LEAD))
        assert meeting["minuted_movement_count"] == 2, (
            "each ratification increments minuted_movement_count by one")
        for student, movement in zip(ctx["students"], ctx["movements"]):
            refreshed = validate_success(api.get_tier_movement(
                d_id, s_id, student["id"], movement["id"], LEAD))
            assert refreshed["status"] == "RATIFIED"
            assert refreshed["decided_at_meeting_id"] == ctx["meeting"]["id"]


class TestRatifyMeetingStateGate:
    def _setup_student_with_pending_movement(self, api):
        """A scored window leaves one auto-PROPOSED movement for the student."""
        district, school = setup_district_school(api)
        d_id, s_id = district["id"], school["id"]
        define_cut_point(api, d_id, s_id, window_kind="FALL", grade_level=3,
                         subject="READING", tier2_max_score=100,
                         tier3_max_score=70)
        window = create_screening_window(api, d_id, s_id, window_kind="FALL")
        set_clock(api, "2026-08-05T00:00:00Z")
        student = enroll_student(api, d_id, s_id, full_name="L", grade_level=3)
        record_score(api, d_id, s_id, window["id"], student["id"], raw_score=80)
        close_window(api, d_id, s_id, window["id"])
        # Scoring auto-proposes a TIER_1 -> TIER_2 movement (PRD §3.3).
        score_window(api, d_id, s_id, window["id"])
        movement = first_proposed_movement(api, d_id, s_id, student["id"])
        return district, school, student, movement

    def test_ratify_rejected_once_meeting_minuted(self, api):
        """PRD §3.7: "Three preconditions guard the act, and their failure is
        rejected as `ERR_INVALID_STATE` (HTTP 409): the meeting must be
        `CONVENED`, the movement must still be `PROPOSED`, and no other
        `PROPOSED` movement for the same student may have been created later than
        this one — a later proposal supersedes earlier ones, so only the freshest
        proposal for a student is ever ratifiable."
        PRD §3.7: "Once every movement submitted to a meeting has been resolved
        one way or the other — no `PROPOSED` rows remain before it — the
        `TeamLead` marks the meeting `MINUTED`, closing it; attempting to minute
        a meeting with proposals still pending is rejected with
        `ERR_INVALID_STATE`."

        The movement is ratified first so no PROPOSED rows remain before the
        meeting (the minute gate above), the meeting is minuted, and the
        follow-up ratify attempt trips the state preconditions: the meeting is
        no longer CONVENED and the movement no longer PROPOSED.

        Design: Corner/state_machines/team_meeting_terminal_lockdown
        """
        district, school, student, movement = (
            self._setup_student_with_pending_movement(api))
        meeting = create_team_meeting(api, district["id"], school["id"])
        convene_meeting(api, district["id"], school["id"], meeting["id"])
        # Resolve the pending movement so the meeting can be minuted.
        ratify_movement(api, district["id"], school["id"], meeting["id"],
                        movement["id"], student["id"])
        minuted = validate_success(api.minute_team_meeting(
            district["id"], school["id"], meeting["id"], LEAD))
        assert minuted["status"] == "MINUTED"

        student = get_student(api, district["id"], school["id"], student["id"])
        resp = api.ratify_movement(
            district["id"], school["id"], meeting["id"],
            {"movement_id": movement["id"],
             "expected_student_version": student["version"]},
            LEAD)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

    def test_ratify_rejected_while_meeting_scheduled(self, api):
        """PRD §3.7: "Three preconditions guard the act, and their failure is
        rejected as `ERR_INVALID_STATE` (HTTP 409): the meeting must be
        `CONVENED`, the movement must still be `PROPOSED`, and no other
        `PROPOSED` movement for the same student may have been created later than
        this one — a later proposal supersedes earlier ones, so only the freshest
        proposal for a student is ever ratifiable."

        Design: Corner/state_machines/ratify_on_scheduled_meeting_rejected
        """
        district, school, student, movement = (
            self._setup_student_with_pending_movement(api))
        meeting = create_team_meeting(api, district["id"], school["id"])
        # The meeting is never convened.
        student = get_student(api, district["id"], school["id"], student["id"])
        resp = api.ratify_movement(
            district["id"], school["id"], meeting["id"],
            {"movement_id": movement["id"],
             "expected_student_version": student["version"]},
            LEAD)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
