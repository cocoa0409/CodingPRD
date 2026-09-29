"""Putting sessions on the calendar: the three independent resources, their
opposing interval conventions, and which refusal wins when two rules break."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_blackout,
    api_client,
    assign_lead_artist,
    create_cleared_artist,
    create_residency_for_school,
    create_school,
    create_session_payload,
    read_residency,
    read_school,
    read_session,
    schedule_session,
    set_clock_to_default,
    set_residency_status,
    setup_approved_residency,
    setup_second_artist,
    validate_error,
    validate_success,
)

RC = TEST_USERS["roster_coordinator_headers"]


def _attempt_session(
    residency_id: str,
    assigned_artist_id: str,
    expected_residency_version: int,
    session_date: str = "2026-09-15",
    start_time: str = "09:00",
    end_time: str = "10:00",
    **overrides,
):
    """Post a session creation and hand back the raw response for inspection."""
    payload = create_session_payload(
        residency_id,
        assigned_artist_id,
        expected_residency_version,
        session_date=session_date,
        start_time=start_time,
        end_time=end_time,
        **overrides,
    )
    return api_client.create_session(payload, RC)


# ==========================================================================
# Resource one: the artist, compared pairwise over half-open intervals
# ==========================================================================
def _residency_with_anchor_session() -> dict:
    """Approved residency at a two-room school with one PLANNED 09:00-10:00
    session already on the books for its lead artist."""
    set_clock_to_default()
    scenario = setup_approved_residency()
    scenario["anchor"] = schedule_session(
        scenario["residency"]["id"],
        scenario["artist"]["id"],
        session_date="2026-09-15",
        start_time="09:00",
        end_time="10:00",
    )
    return scenario


def test_overlapping_second_session_for_the_same_artist_is_refused(api):
    """PRD §3.6: "A session occupies the **half-open** local interval running
    from its `start_time` up to but not including its `end_time`, on its
    `session_date`."
    PRD §3.6: "Only sessions in `PLANNED`, `CONFIRMED`, or `DELIVERED` block
    anything; `VACATED` and cancelled sessions never block."
    PRD §3.6: "If the two half-open intervals overlap, the request is refused
    with `ERR_ARTIST_SCHEDULE_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/artist_half_open_pairwise_overlap_rejects_but_abutting_allowed
    """
    scenario = _residency_with_anchor_session()
    residency_id = scenario["residency"]["id"]
    assert scenario["anchor"]["status"] == "PLANNED"
    assert read_school(scenario["school"]["id"])["concurrent_session_capacity"] == 2, (
        "the school must have room to spare so the artist is the only "
        "binding resource"
    )

    version = read_residency(residency_id)["version"]
    res = _attempt_session(
        residency_id,
        scenario["artist"]["id"],
        version,
        session_date="2026-09-15",
        start_time="09:30",
        end_time="10:30",
    )
    validate_error(
        res, ApiErrorId.ERR_ARTIST_SCHEDULE_CONFLICT.value, expected_status=409
    )

    residency = read_residency(residency_id)
    assert residency["sessions_open_count"] == 1, (
        f"the refused request must not open a session, got "
        f"{residency['sessions_open_count']}"
    )
    assert residency["sessions_unscheduled_count"] == 9
    assert read_session(scenario["anchor"]["id"])["status"] == "PLANNED"


def test_abutting_second_session_for_the_same_artist_is_permitted(api):
    """PRD §3.6: "The gap is the non-negative distance between the two
    intervals, so two sessions that abut exactly — gap of zero — are permitted
    at the same school and rejected at different schools."
    PRD §3.6: "Either way `sessions_open_count` gains one,
    `projected_cost_cents` is recomputed, and the residency's `version`
    increments."
    PRD §3.6: "A new session is created in `PLANNED` status with
    `vacated_artist_id`, `payment_voucher_id`, `cancel_reason`, and every
    delivery and money field still null or zero, and with `is_substitute` false,
    `co_planning_completed` false, `makeup_eligible` false, and
    `makeup_consumed` false."

    Design: Difficulty/resource_temporal_overlap/artist_half_open_pairwise_overlap_rejects_but_abutting_allowed
    """
    scenario = _residency_with_anchor_session()
    residency_id = scenario["residency"]["id"]
    artist_id = scenario["artist"]["id"]

    # One read of the residency version serves both attempts: the refused
    # request leaves the residency untouched, so the version is still current.
    version = read_residency(residency_id)["version"]
    refused = _attempt_session(
        residency_id, artist_id, version, start_time="09:30", end_time="10:30"
    )
    validate_error(
        refused, ApiErrorId.ERR_ARTIST_SCHEDULE_CONFLICT.value, expected_status=409
    )

    accepted = validate_success(
        _attempt_session(
            residency_id, artist_id, version, start_time="10:00", end_time="11:00"
        ),
        expected_status=201,
    )
    assert accepted["status"] == "PLANNED", (
        f"an abutting session must be schedulable, got {accepted['status']}"
    )
    assert accepted["start_time"] == "10:00"
    assert accepted["encumbered_cents"] == 0, (
        f"a PLANNED session holds no money yet, got {accepted['encumbered_cents']}"
    )

    assert read_session(scenario["anchor"]["id"])["status"] == "PLANNED"
    residency = read_residency(residency_id)
    assert residency["sessions_open_count"] == 2, (
        f"expected both sessions open, got {residency['sessions_open_count']}"
    )
    assert residency["sessions_unscheduled_count"] == 8
    assert residency["encumbered_cents"] == 0


# ==========================================================================
# Resource two: the school, counted as an aggregate load per boundary instant
# ==========================================================================
def _one_room_school_with_two_residencies() -> dict:
    """A single-room school hosting two approved residencies led by two
    different artists, with one 09:00-10:00 session already booked."""
    set_clock_to_default()
    school = create_school(
        name="Northgate Arts Magnet",
        district_name="Northgate USD",
        concurrent_session_capacity=1,
        total_enrollment=400,
        frl_pct=0.55,
        ell_pct=0.20,
        iep_pct=0.12,
    )
    ana = create_cleared_artist()
    bo = setup_second_artist(grade_bands=["G3_5"])

    residency_a = create_residency_for_school(school["id"])
    assign_lead_artist(residency_a["id"], ana["id"])
    residency_a = set_residency_status(residency_a["id"], "APPROVED")

    residency_b = create_residency_for_school(
        school["id"],
        title="Rhythm Lab",
        collaboration_expectation="OBSERVE",
        co_planning_hours_required=0,
        materials_stipend_cents=0,
        enrolled_student_count=30,
    )
    assign_lead_artist(residency_b["id"], bo["id"])
    residency_b = set_residency_status(residency_b["id"], "APPROVED")

    anchor = schedule_session(
        residency_a["id"],
        ana["id"],
        session_date="2026-09-15",
        start_time="09:00",
        end_time="10:00",
    )
    return {
        "school": school,
        "ana": ana,
        "bo": bo,
        "residency_a": residency_a,
        "residency_b": residency_b,
        "anchor": anchor,
    }


def test_second_artist_overlapping_the_single_room_exceeds_school_capacity(api):
    """PRD §3.6: "Take the sorted set of all start and end instants of the
    candidate session together with every blocking session of the **same
    school** on that date."
    PRD §3.6: "At each such boundary instant, count how many of those intervals
    contain it, remembering that an interval ending exactly at that instant does
    not count."
    PRD §3.6: "If that count anywhere exceeds the school's
    `concurrent_session_capacity`, the request is refused with
    `ERR_SCHOOL_CAPACITY_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/school_aggregate_capacity_load_at_boundary_instant
    """
    scenario = _one_room_school_with_two_residencies()
    school = read_school(scenario["school"]["id"])
    assert school["concurrent_session_capacity"] == 1
    assert school["partnership_health"] == "HEALTHY", (
        f"both residencies are staffed, got {school['partnership_health']}"
    )

    version = read_residency(scenario["residency_b"]["id"])["version"]
    res = _attempt_session(
        scenario["residency_b"]["id"],
        scenario["bo"]["id"],
        version,
        session_date="2026-09-15",
        start_time="09:30",
        end_time="10:30",
    )
    validate_error(
        res, ApiErrorId.ERR_SCHOOL_CAPACITY_EXCEEDED.value, expected_status=409
    )

    assert read_session(scenario["anchor"]["id"])["status"] == "PLANNED"
    assert read_residency(scenario["residency_b"]["id"])["sessions_open_count"] == 0


def test_second_artist_abutting_the_single_room_keeps_every_load_within_capacity(api):
    """PRD §3.6: "At each such boundary instant, count how many of those
    intervals contain it, remembering that an interval ending exactly at that
    instant does not count."
    PRD §3.6: "A session occupies the **half-open** local interval running from
    its `start_time` up to but not including its `end_time`, on its
    `session_date`."
    PRD §3.6: "Either way `sessions_open_count` gains one,
    `projected_cost_cents` is recomputed, and the residency's `version`
    increments."

    Design: Difficulty/resource_temporal_overlap/school_aggregate_capacity_load_at_boundary_instant
    """
    scenario = _one_room_school_with_two_residencies()
    residency_b_id = scenario["residency_b"]["id"]

    version = read_residency(residency_b_id)["version"]
    refused = _attempt_session(
        residency_b_id,
        scenario["bo"]["id"],
        version,
        start_time="09:30",
        end_time="10:30",
    )
    validate_error(
        refused, ApiErrorId.ERR_SCHOOL_CAPACITY_EXCEEDED.value, expected_status=409
    )

    accepted = validate_success(
        _attempt_session(
            residency_b_id,
            scenario["bo"]["id"],
            version,
            start_time="10:00",
            end_time="11:00",
        ),
        expected_status=201,
    )
    assert accepted["status"] == "PLANNED", (
        "the 09:00-10:00 interval no longer contains 10:00, so the load stays "
        f"at one, got {accepted['status']}"
    )
    assert accepted["start_time"] == "10:00"

    assert read_session(scenario["anchor"]["id"])["status"] == "PLANNED"
    assert read_residency(scenario["residency_a"]["id"])["sessions_open_count"] == 1
    residency_b = read_residency(residency_b_id)
    assert residency_b["sessions_open_count"] == 1
    assert residency_b["sessions_unscheduled_count"] == 9


# ==========================================================================
# Resource three: the school calendar, a closed date interval
# ==========================================================================
def _residency_inside_a_testing_window() -> dict:
    """Approved residency at a school whose calendar is blacked out from
    2026-09-14 through 2026-09-18."""
    set_clock_to_default()
    scenario = setup_approved_residency()
    scenario["blackout"] = add_blackout(
        scenario["school"]["id"],
        blackout_type="TESTING_WINDOW",
        start_date="2026-09-14",
        end_date="2026-09-18",
        note="state assessment window",
    )
    return scenario


def test_session_dated_on_the_blackout_end_date_is_refused(api):
    """PRD §3.3: "Both dates are ISO 8601 calendar dates and the interval is
    **closed at both ends**: the end date is itself blacked out."
    PRD §3.6: "**The school calendar** is checked as a closed date interval: if
    any blackout window of the school has a `start_date` on or before the
    `session_date` and an `end_date` on or after it, the refusal is
    `ERR_CALENDAR_BLACKOUT`."

    Design: Difficulty/resource_temporal_overlap/calendar_blackout_closed_interval_includes_its_end_date
    """
    scenario = _residency_inside_a_testing_window()
    assert scenario["blackout"]["start_date"] == "2026-09-14"
    assert scenario["blackout"]["end_date"] == "2026-09-18"

    residency_id = scenario["residency"]["id"]
    version = read_residency(residency_id)["version"]
    res = _attempt_session(
        residency_id,
        scenario["artist"]["id"],
        version,
        session_date="2026-09-18",
        start_time="09:00",
        end_time="10:00",
    )
    validate_error(res, ApiErrorId.ERR_CALENDAR_BLACKOUT.value, expected_status=409)

    residency = read_residency(residency_id)
    assert residency["sessions_unscheduled_count"] == 10, (
        "the refused request must not draw allotment, got "
        f"{residency['sessions_unscheduled_count']}"
    )
    assert residency["sessions_open_count"] == 0


def test_session_dated_the_day_after_the_blackout_is_accepted(api):
    """PRD §3.6: "**The school calendar** is checked as a closed date interval:
    if any blackout window of the school has a `start_date` on or before the
    `session_date` and an `end_date` on or after it, the refusal is
    `ERR_CALENDAR_BLACKOUT`."
    PRD §3.3: "Adding a window never retroactively cancels sessions that are
    already on the books; it takes effect on the next session creation and on
    the next confirmation, both of which refuse a date inside any of the
    school's windows with `ERR_CALENDAR_BLACKOUT`."

    Design: Difficulty/resource_temporal_overlap/calendar_blackout_closed_interval_includes_its_end_date
    """
    scenario = _residency_inside_a_testing_window()
    residency_id = scenario["residency"]["id"]
    artist_id = scenario["artist"]["id"]

    version = read_residency(residency_id)["version"]
    refused = _attempt_session(
        residency_id, artist_id, version, session_date="2026-09-18"
    )
    validate_error(
        refused, ApiErrorId.ERR_CALENDAR_BLACKOUT.value, expected_status=409
    )

    accepted = validate_success(
        _attempt_session(residency_id, artist_id, version, session_date="2026-09-19"),
        expected_status=201,
    )
    assert accepted["session_date"] == "2026-09-19"
    assert accepted["status"] == "PLANNED", (
        f"the day after the window is clear, got {accepted['status']}"
    )

    residency = read_residency(residency_id)
    assert residency["sessions_open_count"] == 1
    assert residency["sessions_unscheduled_count"] == 9


# ==========================================================================
# When both a capability rule and the calendar are violated at once
# ==========================================================================
def _blackout_school_with_a_wrong_band_artist() -> dict:
    """Approved G3_5 residency at a blacked-out school, plus a cleared artist
    rostered only for K_2."""
    scenario = _residency_inside_a_testing_window()
    scenario["bo"] = setup_second_artist(grade_bands=["K_2"])
    return scenario


def test_capability_mismatch_outranks_the_calendar_blackout_on_creation(api):
    """PRD §2.9: "Checks are therefore evaluated in a fixed global order, and
    the **first** violated check decides the response."
    PRD §2.9: "17. Capability tagging match between residency and artist —
    `ERR_DISCIPLINE_MISMATCH`, `ERR_GRADE_BAND_MISMATCH`, or
    `ERR_LANGUAGE_CAPABILITY_MISSING`."
    PRD §2.9: "23. School calendar blackout — `ERR_CALENDAR_BLACKOUT`."
    PRD §3.6: "The artist must be capable of the residency's discipline, grade
    band, and instruction language, with the three capability codes of §3.4."

    Design: Difficulty/priority_pair_validation_conflict/business_constraint_precedes_business_temporal_on_session_open
    """
    scenario = _blackout_school_with_a_wrong_band_artist()
    residency_id = scenario["residency"]["id"]
    assert scenario["residency"]["grade_band"] == "G3_5"
    assert scenario["bo"]["grade_bands"] == ["K_2"], (
        f"expected a K_2-only artist, got {scenario['bo']['grade_bands']}"
    )

    version = read_residency(residency_id)["version"]
    res = _attempt_session(
        residency_id,
        scenario["bo"]["id"],
        version,
        session_date="2026-09-15",
        start_time="09:00",
        end_time="10:00",
    )
    validate_error(res, ApiErrorId.ERR_GRADE_BAND_MISMATCH.value, expected_status=422)

    residency = read_residency(residency_id)
    assert residency["sessions_unscheduled_count"] == 10
    assert residency["sessions_open_count"] == 0


def test_the_masked_calendar_violation_surfaces_once_the_artist_is_capable(api):
    """PRD §2.9: "A single request can violate many rules at once, and the
    response must be deterministic."
    PRD §2.9: "23. School calendar blackout — `ERR_CALENDAR_BLACKOUT`."
    PRD §3.6: "**The school calendar** is checked as a closed date interval: if
    any blackout window of the school has a `start_date` on or before the
    `session_date` and an `end_date` on or after it, the refusal is
    `ERR_CALENDAR_BLACKOUT`."

    Design: Difficulty/priority_pair_validation_conflict/business_constraint_precedes_business_temporal_on_session_open
    """
    scenario = _blackout_school_with_a_wrong_band_artist()
    residency_id = scenario["residency"]["id"]

    version = read_residency(residency_id)["version"]
    masked = _attempt_session(
        residency_id, scenario["bo"]["id"], version, session_date="2026-09-15"
    )
    validate_error(masked, ApiErrorId.ERR_GRADE_BAND_MISMATCH.value, expected_status=422)

    # Same school, same date, an artist who clears the capability check: the
    # lower-priority calendar violation was real all along.
    surfaced = _attempt_session(
        residency_id, scenario["artist"]["id"], version, session_date="2026-09-15"
    )
    validate_error(
        surfaced, ApiErrorId.ERR_CALENDAR_BLACKOUT.value, expected_status=409
    )

    residency = read_residency(residency_id)
    assert residency["sessions_unscheduled_count"] == 10
    assert residency["sessions_open_count"] == 0
