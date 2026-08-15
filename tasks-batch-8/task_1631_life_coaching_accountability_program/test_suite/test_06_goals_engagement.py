"""Goals, habit check-ins, the engagement score, and session forfeiture."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    book_session,
    complete_session,
    create_goal,
    file_check_in,
    get_client,
    get_enrollment,
    get_session,
    make_client_headers,
    make_coach_headers,
    set_clock,
    setup_active_enrollment,
    validate_error,
    validate_success,
)

PM = TEST_USERS["practice_manager_headers"]


def _setup_engagement_scenario(api):
    """ACTIVE enrollment with 2 COMPLETED sessions (2026-08-04, 2026-08-05)
    and 7 completed check-ins dated 2026-08-03..2026-08-09; the clock ends at
    2026-08-10 (the window anchored on the 2026-08-03 activation runs
    2026-08-03 through 2026-08-10 inclusive — a length of 8 days)."""
    ctx = setup_active_enrollment()
    client = ctx["client"]
    coach_a = ctx["coach_a"]
    enrollment = ctx["enrollment"]
    goal = create_goal(enrollment["id"], client, title="Morning pages",
                       target_count=10)
    for i, day in enumerate((4, 5)):
        sess = book_session(
            enrollment["id"], client,
            scheduled_start=f"2026-08-{day:02d}T10:00:00Z")
        set_clock(f"2026-08-{day:02d}T12:00:00Z")
        complete_session(sess["id"], coach_a)
    for day in range(3, 10):
        file_check_in(goal["id"], client, f"2026-08-{day:02d}", completed=True)
    set_clock("2026-08-10T09:00:00Z")
    return ctx, goal


def test_engagement_score_provisional_variant_mid_window(api):
    """PRD §3.6: "the query parameter `score_variant` set to `provisional`
    substitutes the in-progress variant."
    PRD §3.6: "its length is the number of days from the anchor through today
    inclusive, capped at twenty-eight"
    PRD §3.6: "the session expectation becomes the eight-session expectation
    prorated by the elapsed fraction of twenty-eight days, rounded down to a
    whole number yet never less than one, and the habit denominator becomes
    the number of elapsed days."

    Design: Difficulty/dual_variant_calc/engagement_score_provisional_vs_final
    """
    ctx, _goal = _setup_engagement_scenario(api)
    client = ctx["client"]
    data = get_client(client["id"], params={"score_variant": "provisional"})
    # Anchor 2026-08-03 through today 2026-08-10 inclusive = 8 days.
    # sessions_expected = floor(8 * 8/28) = 2; habit denominator = 8.
    # 100 * (0.6 * 2/2 + 0.4 * 7/8) = 95.
    assert data["engagement_score"] == 95


def test_engagement_score_final_variant_stored_on_client(api):
    """PRD §3.6: "The stored, final variant looks at the trailing
    twenty-eight-day window ending on the current UTC date, both end dates
    included, so the window opens twenty-seven days back."
    PRD §3.6: "The score is one hundred times a weighted sum: six-tenths of
    the session count divided by the eight sessions expected in a full
    window, plus four-tenths of the habit count divided by the window's
    twenty-eight days; the figure is rounded half-up to the nearest integer
    and clamped to the inclusive range from 0 to 100."

    Design: Difficulty/dual_variant_calc/engagement_score_provisional_vs_final
    """
    ctx, _goal = _setup_engagement_scenario(api)
    client = ctx["client"]
    data = get_client(client["id"])
    # 100 * (0.6 * 2/8 + 0.4 * 7/28) = 25.
    assert data["engagement_score"] == 25


def test_goal_auto_achieved_at_exact_target_count(api):
    """PRD §3.6: "The goal's `achieved_count` recomputes as the number of its
    check-ins whose `completed` flag is true, and the moment that count
    reaches `target_count` — exactly reaching it suffices — the goal becomes
    `ACHIEVED`."

    Design: Corner/state_machines/goal_auto_achieved_at_exact_target_count
    """
    ctx = setup_active_enrollment()
    client = ctx["client"]
    enrollment = ctx["enrollment"]
    goal = create_goal(enrollment["id"], client, title="Two-day streak",
                       target_count=2)
    file_check_in(goal["id"], client, "2026-08-03", completed=True)
    resp = api.get_goal(goal["id"], make_client_headers(client["id"]))
    data = validate_success(resp)
    assert data["achieved_count"] == 1
    assert data["goal_status"] == "OPEN", "one below target stays OPEN"
    file_check_in(goal["id"], client, "2026-08-04", completed=True)
    resp = api.get_goal(goal["id"], make_client_headers(client["id"]))
    data = validate_success(resp)
    assert data["achieved_count"] == 2
    assert data["goal_status"] == "ACHIEVED", \
        "reaching target_count exactly flips the goal to ACHIEVED"


def test_engagement_score_excludes_no_show_and_incomplete_checkins(api):
    """PRD §3.6: "the session count covers sessions of the client's
    enrollments that stand `COMPLETED` with a `scheduled_start` date inside
    the window — `NO_SHOW` sessions never count — and the habit count covers
    check-ins with `completed` true whose `check_in_date` sits inside the
    window."

    Design: Corner/calculations/engagement_score_excludes_no_show_and_incomplete_checkins
    """
    ctx = setup_active_enrollment()
    client = ctx["client"]
    coach_a = ctx["coach_a"]
    enrollment = ctx["enrollment"]
    goal = create_goal(enrollment["id"], client, title="Filter goal",
                       target_count=10)
    sess_ok = book_session(
        enrollment["id"], client, scheduled_start="2026-08-04T10:00:00Z")
    sess_ns = book_session(
        enrollment["id"], client, scheduled_start="2026-08-05T10:00:00Z")
    set_clock("2026-08-04T11:00:00Z")
    complete_session(sess_ok["id"], coach_a)
    set_clock("2026-08-05T11:00:00Z")
    validate_success(
        api.mark_session_no_show(sess_ns["id"], make_coach_headers(coach_a["id"])))
    file_check_in(goal["id"], client, "2026-08-04", completed=True)
    file_check_in(goal["id"], client, "2026-08-05", completed=False)
    set_clock("2026-08-10T09:00:00Z")
    file_check_in(goal["id"], client, "2026-08-06", completed=False)
    data = get_client(client["id"])
    # 100 * (0.6 * 1/8 + 0.4 * 1/28) = 8.928 -> round half up = 9.
    assert data["engagement_score"] == 9, (
        "NO_SHOW sessions and completed=false check-ins contribute nothing; "
        "expected 9, got "
        f"{data['engagement_score']}"
    )


def test_derived_engagement_recomputed_after_new_checkin(api):
    """PRD §3.6: "Every check-in creation, and every terminal session
    transition — completion or no-show — recomputes the owning client's
    `engagement_score`, an integer from 0 to 100."

    Design: Corner/cross_cutting_layers/derived_engagement_recomputed_after_new_checkin
    """
    ctx = setup_active_enrollment()
    client = ctx["client"]
    enrollment = ctx["enrollment"]
    goal = create_goal(enrollment["id"], client, title="Recompute goal",
                       target_count=30)
    set_clock("2026-08-10T09:00:00Z")
    assert get_client(client["id"])["engagement_score"] == 0
    file_check_in(goal["id"], client, "2026-08-09", completed=True)
    data = get_client(client["id"])
    # 100 * (0.6 * 0/8 + 0.4 * 1/28) = 1.428 -> round half up = 1.
    assert data["engagement_score"] == 1


def test_session_forfeited_when_program_window_expires(api):
    """PRD §3.4: "any session still `SCHEDULED` when the current time reaches
    the end of the program window becomes `FORFEITED` with its `version`
    advancing, reducing `sessions_remaining` without counting as consumed."

    Design: Corner/state_machines/session_forfeited_when_program_window_expires
    """
    ctx = setup_active_enrollment(
        tier_overrides={
            "tier_type": "SINGLE", "session_count": 1, "price_cents": 15000,
            "duration_days": 30, "installment_count_allowed": 1,
            "reschedule_cap": 0,
        }
    )
    client = ctx["client"]
    enrollment = ctx["enrollment"]  # ACTIVE 2026-08-03; window ends 2026-09-02
    sess = book_session(
        enrollment["id"], client, scheduled_start="2026-09-01T10:00:00Z")
    set_clock("2026-09-03T00:00:01Z")
    assert get_session(sess["id"])["session_status"] == "FORFEITED"
    data = get_enrollment(enrollment["id"])
    assert data["sessions_remaining"] == 0
    assert data["sessions_consumed"] == 0


def test_checkin_on_abandoned_goal_returns_invalid_state(api):
    """PRD §3.6: "The client may instead abandon an `OPEN` goal belonging to
    their own enrollment, moving `goal_status` to `ABANDONED`; an abandoned
    goal accepts no further check-ins." PRD §2.11: "a habit check-in requires
    its goal to be `OPEN` — else `ERR_INVALID_STATE`".

    Design: Corner/consistency_model/checkin_on_abandoned_goal_returns_invalid_state
    """
    ctx = setup_active_enrollment()
    client = ctx["client"]
    enrollment = ctx["enrollment"]
    goal = create_goal(enrollment["id"], client, title="Abandoned goal",
                       target_count=5)
    resp = api.abandon_goal(goal["id"], make_client_headers(client["id"]))
    data = validate_success(resp)
    assert data["goal_status"] == "ABANDONED"
    resp = api.create_check_in(
        goal["id"], {"check_in_date": "2026-08-04", "completed": True},
        make_client_headers(client["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_duplicate_checkin_same_date_rejected(api):
    """PRD §3.6: "a goal accepts at most one check-in per calendar date — a
    second filing for the same (`goal_id`, `check_in_date`) pair is
    `ERR_DUPLICATE_RESOURCE`."

    Design: Corner/validations/duplicate_checkin_same_date_rejected
    """
    ctx = setup_active_enrollment()
    client = ctx["client"]
    enrollment = ctx["enrollment"]
    goal = create_goal(enrollment["id"], client, title="Daily journal",
                       target_count=20)
    file_check_in(goal["id"], client, "2026-08-04", completed=True)
    resp = api.create_check_in(
        goal["id"], {"check_in_date": "2026-08-04", "completed": False},
        make_client_headers(client["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_RESOURCE)
