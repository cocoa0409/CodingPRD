"""Recruiting the roster: the two lifecycle axes, the portfolio threshold,
the standing clearance gate, and the failed-screening cascade."""

from test_helpers import (
    ApiErrorId,
    PANELIST_1_USER_ID,
    PANELIST_2_USER_ID,
    TEST_USERS,
    api_client,
    confirm_session_as_liaison,
    create_artist_applicant,
    create_cleared_artist,
    create_vetting_payload,
    read_artist,
    read_residency,
    read_school,
    read_session,
    record_failed_screening,
    record_portfolio_review,
    schedule_session,
    set_clock_to_default,
    set_roster_status,
    setup_active_residency,
    validate_error,
    validate_success,
)

RC = TEST_USERS["roster_coordinator_headers"]
PD = TEST_USERS["program_director_headers"]


# ==========================================================================
# The two independent lifecycle axes of a teaching artist
# ==========================================================================
def test_roster_axis_walks_active_suspended_active_while_vetting_stays_cleared(api):
    """PRD §3.1: "Reaching `CLEARED` on the recruitment axis fires an automatic
    transition on the roster axis, moving `roster_status` from `NOT_LISTED` to
    `ACTIVE`, and recomputes `roster_tier_effective`."
    PRD §3.2: "The reachable moves are `ACTIVE → PROBATION`, `PROBATION →
    ACTIVE`, `ACTIVE → SUSPENDED`, `PROBATION → SUSPENDED`, `SUSPENDED →
    ACTIVE`, and retirement from `ACTIVE`, `PROBATION`, or `SUSPENDED`."
    PRD §3.2: "Reinstatement out of `SUSPENDED` requires two things: clearance
    must hold, or the refusal is `ERR_ARTIST_NOT_CLEARED`; and the recruitment
    axis must itself read `CLEARED`, or the refusal is
    `ERR_INVALID_STATE_TRANSITION`."

    Design: Difficulty/non_linear_state_machine/artist_vetting_and_roster_axes_evolve_independently
    """
    set_clock_to_default()
    artist = create_cleared_artist()
    assert artist["vetting_status"] == "CLEARED"
    assert artist["roster_status"] == "ACTIVE", (
        f"reaching CLEARED must auto-list the artist, got {artist['roster_status']}"
    )

    suspended = set_roster_status(
        artist["id"], "SUSPENDED", reason="documentation audit"
    )
    assert suspended["roster_status"] == "SUSPENDED"
    assert suspended["vetting_status"] == "CLEARED", (
        "the roster axis must not rewrite the recruitment axis, got "
        f"{suspended['vetting_status']}"
    )

    reinstated = set_roster_status(artist["id"], "ACTIVE", reason="audit cleared")
    assert reinstated["roster_status"] == "ACTIVE"
    assert reinstated["vetting_status"] == "CLEARED", (
        "the recruitment axis must still read CLEARED after reinstatement, got "
        f"{reinstated['vetting_status']}"
    )


def test_clearance_window_and_effective_tier_survive_the_suspension_round_trip(api):
    """PRD §3.1: "Otherwise `clearance_expires_on` is the **earliest**
    `expires_on` among those three latest rows, and `clearance_status` is
    `CLEARED` when that date is on or after the current logical-clock date and
    `EXPIRED` when it is earlier."
    PRD §3.2: "Failing both of those, the effective tier is simply the assigned
    tier."

    Design: Difficulty/non_linear_state_machine/artist_vetting_and_roster_axes_evolve_independently
    """
    set_clock_to_default()
    artist = create_cleared_artist(roster_tier_assigned="APPRENTICE")
    set_roster_status(artist["id"], "SUSPENDED", reason="documentation audit")
    set_roster_status(artist["id"], "ACTIVE", reason="audit cleared")

    final = read_artist(artist["id"])
    assert final["clearance_status"] == "CLEARED", (
        f"clearance must still hold, got {final['clearance_status']}"
    )
    assert final["clearance_expires_on"] == "2027-06-30", (
        "clearance_expires_on must be the earliest expiry of the three latest "
        f"screenings, got {final['clearance_expires_on']}"
    )
    assert final["roster_tier_effective"] == "APPRENTICE", (
        "an artist off probation with fewer than 25 deliveries keeps the "
        f"assigned tier, got {final['roster_tier_effective']}"
    )


# ==========================================================================
# The portfolio mean at the advance threshold
# ==========================================================================
def _artist_in_portfolio_review(full_name: str, email: str) -> dict:
    artist = create_artist_applicant(
        full_name=full_name,
        email=email,
        primary_discipline="VISUAL_ARTS",
        secondary_disciplines=[],
        grade_bands=["G3_5"],
        languages=["en"],
        roster_tier_assigned="APPRENTICE",
    )
    validate_success(
        api_client.advance_vetting(
            artist["id"], create_vetting_payload("PORTFOLIO_REVIEW"), RC
        )
    )
    return artist


def test_portfolio_mean_of_exactly_the_advance_threshold_schedules_the_demo(api):
    """PRD §3.1: "The panel weights artistic quality at forty percent (a factor
    of 0.40), pedagogical clarity at thirty-five percent (0.35), and cultural
    responsiveness at twenty-five percent (0.25): the review's `composite_score`
    is the sum of each score multiplied by its weight, rounded half up to two
    decimal places."
    PRD §3.1: "The rounded `portfolio_mean_composite` must be at least 3.50 — a
    mean of exactly 3.50 passes — or the refusal is
    `ERR_PORTFOLIO_THRESHOLD_NOT_MET`."
    PRD §3.1: "Entering `DEMO_SCHEDULED` adds one to `demo_attempt_count`."

    Design: Difficulty/boundary_precision_check/portfolio_mean_at_advance_threshold_versus_one_cent_below
    """
    set_clock_to_default()
    nia = _artist_in_portfolio_review("Nia Cole", "nia.cole@arts.org")
    first = record_portfolio_review(nia["id"], PANELIST_1_USER_ID, 3.4, 3.4, 3.4)
    second = record_portfolio_review(nia["id"], PANELIST_2_USER_ID, 3.5, 4.0, 3.2)
    assert first["composite_score"] == 3.40, (
        f"expected composite 3.40, got {first['composite_score']}"
    )
    assert second["composite_score"] == 3.60, (
        f"expected composite 3.60, got {second['composite_score']}"
    )
    assert read_artist(nia["id"])["portfolio_mean_composite"] == 3.50

    advanced = validate_success(
        api_client.advance_vetting(
            nia["id"], create_vetting_payload("DEMO_SCHEDULED"), RC
        )
    )
    assert advanced["vetting_status"] == "DEMO_SCHEDULED", (
        f"a mean of exactly 3.50 must pass, got {advanced['vetting_status']}"
    )
    assert advanced["demo_attempt_count"] == 1, (
        f"entering DEMO_SCHEDULED consumes one attempt, got "
        f"{advanced['demo_attempt_count']}"
    )


def test_portfolio_mean_one_hundredth_below_threshold_is_refused(api):
    """PRD §3.1: "The rounded `portfolio_mean_composite` must be at least 3.50 —
    a mean of exactly 3.50 passes — or the refusal is
    `ERR_PORTFOLIO_THRESHOLD_NOT_MET`."
    PRD §3.1: "Entering `DEMO_SCHEDULED` adds one to `demo_attempt_count`."

    Design: Difficulty/boundary_precision_check/portfolio_mean_at_advance_threshold_versus_one_cent_below
    """
    set_clock_to_default()
    owen = _artist_in_portfolio_review("Owen Frye", "owen.frye@arts.org")
    first = record_portfolio_review(owen["id"], PANELIST_1_USER_ID, 3.4, 3.4, 3.4)
    second = record_portfolio_review(owen["id"], PANELIST_2_USER_ID, 4.0, 3.5, 3.0)
    assert first["composite_score"] == 3.40
    assert second["composite_score"] == 3.58, (
        f"3.575 must round half up to 3.58, got {second['composite_score']}"
    )
    assert read_artist(owen["id"])["portfolio_mean_composite"] == 3.49

    res = api_client.advance_vetting(
        owen["id"], create_vetting_payload("DEMO_SCHEDULED"), RC
    )
    validate_error(
        res, ApiErrorId.ERR_PORTFOLIO_THRESHOLD_NOT_MET.value, expected_status=409
    )

    unchanged = read_artist(owen["id"])
    assert unchanged["vetting_status"] == "PORTFOLIO_REVIEW", (
        f"the refused hop must not move the axis, got {unchanged['vetting_status']}"
    )
    assert unchanged["demo_attempt_count"] == 0, (
        f"a refused hop consumes no attempt, got {unchanged['demo_attempt_count']}"
    )


# ==========================================================================
# The clearance expiry date is itself schedulable
# ==========================================================================
def test_session_dated_on_the_clearance_expiry_date_is_accepted(api):
    """PRD §2.10: "Four operations additionally require that the artist's
    clearance still cover the session's own date, inclusive of the expiry date
    itself: session creation, session confirmation, session reassignment, and
    session delivery."
    PRD §3.1: "When present, `expires_on` must fall strictly after
    `effective_on`, and it is treated as inclusive: the expiry date itself is
    still covered."

    Design: Difficulty/boundary_precision_check/clearance_expiry_date_itself_is_schedulable_but_next_day_is_not
    """
    set_clock_to_default()
    scenario = setup_active_residency(clearance_expires_on="2026-09-15")
    artist = read_artist(scenario["artist"]["id"])
    assert artist["clearance_expires_on"] == "2026-09-15"
    assert artist["clearance_status"] == "CLEARED"

    session = schedule_session(
        scenario["residency"]["id"],
        artist["id"],
        session_date="2026-09-15",
        lesson_plan_id=scenario["lesson_plan"]["id"],
    )
    assert session["status"] == "PLANNED", (
        f"a session on the expiry date must be schedulable, got {session['status']}"
    )

    residency = read_residency(scenario["residency"]["id"])
    assert residency["sessions_unscheduled_count"] == 9
    assert residency["sessions_open_count"] == 1


def test_session_dated_one_day_after_clearance_lapses_is_refused(api):
    """PRD §2.10: "A session dated after the clearance lapses is rejected with
    `ERR_CLEARANCE_EXPIRED` at HTTP 409, even though the artist may be cleared
    as of today."
    PRD §3.6: "The assigned artist must be vetted and cleared
    (`ERR_ARTIST_NOT_CLEARED`), must still be covered on the session's own date
    (`ERR_CLEARANCE_EXPIRED`), and must have a `roster_status` of `ACTIVE`
    (`ERR_ARTIST_NOT_ON_ACTIVE_ROSTER`)."

    Design: Difficulty/boundary_precision_check/clearance_expiry_date_itself_is_schedulable_but_next_day_is_not
    """
    set_clock_to_default()
    scenario = setup_active_residency(clearance_expires_on="2026-09-15")
    residency_id = scenario["residency"]["id"]
    artist_id = scenario["artist"]["id"]

    schedule_session(
        residency_id,
        artist_id,
        session_date="2026-09-15",
        lesson_plan_id=scenario["lesson_plan"]["id"],
    )

    from test_helpers import create_session_payload

    version = read_residency(residency_id)["version"]
    payload = create_session_payload(
        residency_id,
        artist_id,
        version,
        session_date="2026-09-16",
        start_time="09:00",
        end_time="10:00",
        lesson_plan_id=scenario["lesson_plan"]["id"],
    )
    res = api_client.create_session(payload, RC)
    validate_error(res, ApiErrorId.ERR_CLEARANCE_EXPIRED.value, expected_status=409)

    residency = read_residency(residency_id)
    assert residency["sessions_unscheduled_count"] == 9, (
        "the refused creation must not draw allotment, got "
        f"{residency['sessions_unscheduled_count']}"
    )
    assert residency["sessions_open_count"] == 1


# ==========================================================================
# The failed-screening cascade
# ==========================================================================
def test_failed_screening_forces_screen_failed_and_suspension_and_clears_window(api):
    """PRD §3.1: "Recording an outcome of `FAILED` drives the recruitment axis to
    `SCREEN_FAILED` from either `SCREENING_PENDING` or `CLEARED`, and in both
    cases the first link of Cascade A fires immediately: the roster axis is
    forced to `SUSPENDED`."
    PRD §3.1: "When the failure arrives on an artist who was already `CLEARED`,
    the server additionally resets `clearance_status` to `NONE` and
    `clearance_expires_on` to null."

    Design: Difficulty/transitive_cascade/failed_screening_cascade_artist_sessions_residency_school
    """
    set_clock_to_default()
    scenario = setup_active_residency()
    artist_id = scenario["artist"]["id"]
    session = schedule_session(
        scenario["residency"]["id"],
        artist_id,
        session_date="2026-09-15",
        lesson_plan_id=scenario["lesson_plan"]["id"],
    )
    confirmed = confirm_session_as_liaison(session["id"], scenario["school"]["id"])
    assert confirmed["encumbered_cents"] == 13974, (
        f"expected the full-length fee held, got {confirmed['encumbered_cents']}"
    )
    assert read_school(scenario["school"]["id"])["partnership_health"] == "HEALTHY"
    assert read_residency(scenario["residency"]["id"])["staffing_status"] == "STAFFED"

    record_failed_screening(
        artist_id, "CHILD_ABUSE_REGISTRY", effective_on="2026-09-01"
    )

    artist = read_artist(artist_id)
    assert artist["vetting_status"] == "SCREEN_FAILED", (
        f"expected SCREEN_FAILED, got {artist['vetting_status']}"
    )
    assert artist["roster_status"] == "SUSPENDED", (
        f"expected the roster axis forced to SUSPENDED, got {artist['roster_status']}"
    )
    assert artist["clearance_status"] == "NONE", (
        f"expected clearance_status reset to NONE, got {artist['clearance_status']}"
    )
    assert artist["clearance_expires_on"] is None, (
        f"expected clearance_expires_on null, got {artist['clearance_expires_on']}"
    )


def test_failed_screening_vacates_the_session_and_reprices_residency_and_school(api):
    """PRD §3.2: "Link two: every session of this artist whose status is
    `PLANNED` or `CONFIRMED` moves to `VACATED`, with the artist's identifier
    copied from `assigned_artist_id` into `vacated_artist_id` and
    `assigned_artist_id` set to null; each session that was `CONFIRMED` also
    releases its held amount, subtracting the session's held cents from the
    residency's `encumbered_cents`, zeroing the session's own held amount, and
    recomputing `available_cents`."
    PRD §3.2: "Link three: for every residency touched by link two,
    `vacated_session_count` gains one and `staffing_status` is recomputed, and if
    the suspended artist was that residency's `lead_artist_id`, the lead
    reference is cleared to null so the residency reads `LEAD_VACANT`."
    PRD §3.3: "Otherwise, if any residency in that set has a `staffing_status` of
    `AT_RISK` or `LEAD_VACANT`, health reads `WATCH`."

    Design: Difficulty/transitive_cascade/failed_screening_cascade_artist_sessions_residency_school
    """
    set_clock_to_default()
    scenario = setup_active_residency()
    artist_id = scenario["artist"]["id"]
    session = schedule_session(
        scenario["residency"]["id"],
        artist_id,
        session_date="2026-09-15",
        lesson_plan_id=scenario["lesson_plan"]["id"],
    )
    confirm_session_as_liaison(session["id"], scenario["school"]["id"])

    record_failed_screening(
        artist_id, "CHILD_ABUSE_REGISTRY", effective_on="2026-09-01"
    )

    vacated = read_session(session["id"])
    assert vacated["status"] == "VACATED", (
        f"expected the confirmed session vacated, got {vacated['status']}"
    )
    assert vacated["assigned_artist_id"] is None
    assert vacated["vacated_artist_id"] == artist_id
    assert vacated["encumbered_cents"] == 0, (
        f"the vacated session must release its held amount, got "
        f"{vacated['encumbered_cents']}"
    )

    residency = read_residency(scenario["residency"]["id"])
    assert residency["encumbered_cents"] == 0
    assert residency["available_cents"] == 200000
    assert residency["vacated_session_count"] == 1
    assert residency["lead_artist_id"] is None, (
        "the suspended lead reference must be cleared, got "
        f"{residency['lead_artist_id']}"
    )
    assert residency["staffing_status"] == "LEAD_VACANT"

    school = read_school(scenario["school"]["id"])
    assert school["partnership_health"] == "WATCH", (
        f"expected the school on WATCH, got {school['partnership_health']}"
    )
