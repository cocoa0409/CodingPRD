"""Three shared resources under three different interval conventions: the exam room
with a mandatory thirty-minute buffer on both sides, the corequisite meeting block
with no buffer at all, and the proctor as a per-day minute budget.
"""
from test_helpers import (
    ApiErrorId,
    administration_status_payload,
    api_client,
    create_test_administration_payload,
    get_success_data,
    new_administration,
    new_course,
    new_requisite,
    new_section,
    new_support_course,
    pair_section_payload,
    pair_sections,
    read_section,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import (
    DIRECTOR_1,
    make_assessment_director_headers,
    make_assessment_staff_headers,
    make_registrar_headers,
)

# --------------------------------------------------------------------------- #
# exam_room_turnaround_buffer_of_exactly_thirty_minutes_is_allowed
# --------------------------------------------------------------------------- #


def _schedule(room_code, proctor_user_id, starts_at, ends_at):
    return api_client.create_test_administration(
        create_test_administration_payload(
            proctor_user_id,
            room_code=room_code,
            subject_area="MATH",
            starts_at=starts_at,
            ends_at=ends_at,
            seat_capacity=5,
        ),
        make_assessment_staff_headers(),
    )


def _setup_room_incumbent():
    """One scheduled session holding room T05 from 09:00 to 11:00.  Every candidate
    below names a different proctor, so the daily aggregate never participates."""
    incumbent = new_administration(
        "proctor-4",
        room_code="T05",
        subject_area="MATH",
        starts_at="2026-08-20T09:00:00Z",
        ends_at="2026-08-20T11:00:00Z",
        seat_capacity=5,
    )
    return {"incumbent": incumbent}


def test_a_gap_of_twenty_nine_minutes_after_the_incumbent_conflicts():
    """"Two sessions sharing a `room_code`, both in status `SCHEDULED`, `OPEN` or
    `CLOSED`, conflict when the first one's `starts_at` falls strictly before the
    second one's `ends_at` advanced by thirty minutes *and* the second one's
    `starts_at` falls strictly before the first one's `ends_at` advanced by thirty
    minutes.  A gap of exactly thirty minutes between them is therefore permitted; a
    gap of twenty-nine is not."

    Design: Difficulty/resource_temporal_overlap/exam_room_turnaround_buffer_of_exactly_thirty_minutes_is_allowed
    """
    setup = _setup_room_incumbent()
    assert setup["incumbent"]["duration_minutes"] == 120

    validate_error(
        _schedule("T05", "proctor-5", "2026-08-20T11:29:00Z", "2026-08-20T13:29:00Z"),
        ApiErrorId.ERR_ROOM_TIME_CONFLICT,
        409,
    )

    accepted = validate_success(
        _schedule("T05", "proctor-5", "2026-08-20T11:30:00Z", "2026-08-20T13:30:00Z"),
        201,
    )
    assert accepted["status"] == "SCHEDULED"


def test_the_turnaround_buffer_is_symmetric_on_the_earlier_side():
    """The same rule reads in both directions, so a candidate that *ends* twenty-nine
    minutes before the incumbent begins conflicts too: 09:00 falls strictly before
    08:59 advanced by thirty minutes.  A candidate ending exactly thirty minutes
    earlier is accepted, because 09:00 does not fall strictly before 08:30 advanced
    by thirty minutes.

    Design: Difficulty/resource_temporal_overlap/exam_room_turnaround_buffer_of_exactly_thirty_minutes_is_allowed
    """
    _setup_room_incumbent()

    validate_error(
        _schedule("T05", "proctor-6", "2026-08-20T08:29:00Z", "2026-08-20T08:59:00Z"),
        ApiErrorId.ERR_ROOM_TIME_CONFLICT,
        409,
    )

    accepted = validate_success(
        _schedule("T05", "proctor-6", "2026-08-20T08:00:00Z", "2026-08-20T08:30:00Z"),
        201,
    )
    assert accepted["duration_minutes"] == 30


def test_cancelling_the_incumbent_frees_its_exact_window():
    """"Sessions already in status `CANCELLED` never conflict with anything."  The
    conflict set is filtered by status rather than by geometry alone, so a candidate
    occupying the cancelled session's exact window is admitted, and neither rejected
    candidate was ever persisted.

    Design: Difficulty/resource_temporal_overlap/exam_room_turnaround_buffer_of_exactly_thirty_minutes_is_allowed
    """
    setup = _setup_room_incumbent()
    validate_success(
        _schedule("T05", "proctor-5", "2026-08-20T11:30:00Z", "2026-08-20T13:30:00Z"),
        201,
    )
    validate_success(
        _schedule("T05", "proctor-6", "2026-08-20T08:00:00Z", "2026-08-20T08:30:00Z"),
        201,
    )

    cancelled = validate_success(
        api_client.set_test_administration_status(
            setup["incumbent"]["id"],
            administration_status_payload("CANCELLED"),
            make_assessment_director_headers(DIRECTOR_1),
        )
    )
    assert cancelled["status"] == "CANCELLED"

    reused = validate_success(
        _schedule("T05", "proctor-7", "2026-08-20T09:00:00Z", "2026-08-20T11:00:00Z"),
        201,
    )
    assert reused["status"] == "SCHEDULED"

    rows, meta = validate_paginated(
        api_client.list_test_administrations(
            make_assessment_staff_headers(), params={"room_code": "T05"}
        )
    )
    assert meta["total_count"] == 4
    assert len(rows) == 4


# --------------------------------------------------------------------------- #
# paired_section_meeting_blocks_may_be_exactly_adjacent
# --------------------------------------------------------------------------- #


def _setup_pairing_candidates():
    """One primary section and three pairing candidates: a second primary section
    that is both the wrong kind of course and time-overlapping, a support section
    overlapping by one minute, and a support section exactly adjacent."""
    primary_course = new_course(
        course_code="MATH-100",
        title="College Algebra",
        subject_area="MATH",
        level_rank=100,
        units=4.0,
        transfer_level=True,
    )
    support_course = new_support_course(
        course_code="MATH-100S",
        title="Algebra Support",
        subject_area="MATH",
        level_rank=100,
        units=2.0,
    )
    coreq_edge = new_requisite(
        primary_course["id"],
        support_course["id"],
        requisite_type="COREQUISITE",
    )
    primary = new_section(
        primary_course["id"],
        term_code="2026FA",
        room_code="R801",
        meets_start_at="2026-09-01T17:00:00Z",
        meets_end_at="2026-09-01T18:00:00Z",
        seat_capacity=20,
    )
    wrong_kind = new_section(
        primary_course["id"],
        term_code="2026FA",
        room_code="R804",
        meets_start_at="2026-09-01T17:59:00Z",
        meets_end_at="2026-09-01T18:59:00Z",
        seat_capacity=20,
    )
    overlapping = new_section(
        support_course["id"],
        term_code="2026FA",
        room_code="R802",
        meets_start_at="2026-09-01T17:59:00Z",
        meets_end_at="2026-09-01T18:59:00Z",
        seat_capacity=20,
    )
    adjacent = new_section(
        support_course["id"],
        term_code="2026FA",
        room_code="R803",
        meets_start_at="2026-09-01T18:00:00Z",
        meets_end_at="2026-09-01T19:00:00Z",
        seat_capacity=20,
    )
    return {
        "coreq_edge": coreq_edge,
        "primary": primary,
        "wrong_kind": wrong_kind,
        "overlapping": overlapping,
        "adjacent": adjacent,
    }


def _pair(primary_id, support_id):
    return api_client.pair_section(
        primary_id, pair_section_payload(support_id), make_registrar_headers()
    )


def test_pairing_integrity_is_checked_before_the_meeting_geometry():
    """"The pairing integrity check requires that the primary section's course have
    `is_support_course` false, that the support section's course have
    `is_support_course` true ... any failure is refused with
    `ERR_COREQ_SECTION_MISMATCH`" and "Only after that check passes is the meeting
    geometry examined".  A candidate that breaks both rules therefore reports the
    referential failure, never the temporal one.

    Design: Difficulty/resource_temporal_overlap/paired_section_meeting_blocks_may_be_exactly_adjacent
    """
    setup = _setup_pairing_candidates()
    assert setup["coreq_edge"]["status"] == "ACTIVE"
    assert setup["primary"]["pairing_state"] == "UNPAIRED"
    assert setup["primary"]["role_in_pair"] == "NONE"

    body = validate_error(
        _pair(setup["primary"]["id"], setup["wrong_kind"]["id"]),
        ApiErrorId.ERR_COREQ_SECTION_MISMATCH,
        422,
    )
    assert body["error_id"] != ApiErrorId.ERR_COREQ_TIME_CONFLICT


def test_one_minute_of_overlap_between_meeting_blocks_is_fatal():
    """"the two meeting blocks must not overlap under half-open, **zero-buffer**
    semantics, meaning they conflict exactly when the primary's `meets_start_at`
    falls strictly before the support's `meets_end_at` and the support's
    `meets_start_at` falls strictly before the primary's `meets_end_at`."  The
    rejected pair writes no half-link.

    Design: Difficulty/resource_temporal_overlap/paired_section_meeting_blocks_may_be_exactly_adjacent
    """
    setup = _setup_pairing_candidates()

    validate_error(
        _pair(setup["primary"]["id"], setup["overlapping"]["id"]),
        ApiErrorId.ERR_COREQ_TIME_CONFLICT,
        409,
    )

    unchanged = read_section(setup["primary"]["id"])
    assert unchanged["pairing_state"] == "UNPAIRED"
    assert unchanged["linked_section_id"] is None


def test_exactly_adjacent_meeting_blocks_pair_and_link_both_halves():
    """"Exact adjacency -- one block ending at the very instant the other begins --
    is allowed, since a student can walk between rooms; unlike test sessions,
    corequisite meetings get no turnaround buffer at all."  17:00 is strictly before
    19:00, but 18:00 is not strictly before 18:00, so there is no conflict.

    Design: Difficulty/resource_temporal_overlap/paired_section_meeting_blocks_may_be_exactly_adjacent
    """
    setup = _setup_pairing_candidates()

    paired = pair_sections(setup["primary"]["id"], setup["adjacent"]["id"])
    assert paired["pairing_state"] == "PAIRED"
    assert paired["role_in_pair"] == "PRIMARY"
    assert paired["linked_section_id"] == setup["adjacent"]["id"]
    assert paired["available_seats"] == 20

    support = read_section(setup["adjacent"]["id"])
    assert support["pairing_state"] == "PAIRED"
    assert support["role_in_pair"] == "SUPPORT"
    assert support["linked_section_id"] == setup["primary"]["id"]


# --------------------------------------------------------------------------- #
# proctor_daily_minutes_clipped_at_each_utc_midnight
# --------------------------------------------------------------------------- #


def _setup_midnight_spanning_session():
    """A single 240-minute sitting from 22:00 to 02:00, which the daily aggregate
    must split as 120 minutes on each of the two UTC days it touches."""
    session = new_administration(
        "proctor-8",
        room_code="T07",
        subject_area="MATH",
        starts_at="2026-08-25T22:00:00Z",
        ends_at="2026-08-26T02:00:00Z",
        seat_capacity=5,
    )
    return {"session": session}


def test_the_earlier_day_carries_only_the_minutes_before_midnight():
    """"for the named `proctor_user_id`, the office sums the minutes of every session
    in status `SCHEDULED`, `OPEN` or `CLOSED`, plus the proposed session, *clipped to
    each UTC calendar day* so that a sitting spanning midnight contributes its own
    minutes to each of the two days it touches."  An eight-hour candidate on the
    earlier day would reach 600 minutes and is refused; a six-hour candidate reaches
    exactly 480 and is accepted.

    Design: Difficulty/resource_temporal_overlap/proctor_daily_minutes_clipped_at_each_utc_midnight
    """
    setup = _setup_midnight_spanning_session()
    assert setup["session"]["duration_minutes"] == 240
    assert setup["session"]["status"] == "SCHEDULED"

    validate_error(
        _schedule("T08", "proctor-8", "2026-08-25T09:00:00Z", "2026-08-25T17:00:00Z"),
        ApiErrorId.ERR_PROCTOR_DAILY_CAP_EXCEEDED,
        409,
    )

    accepted = validate_success(
        _schedule("T08", "proctor-8", "2026-08-25T09:00:00Z", "2026-08-25T15:00:00Z"),
        201,
    )
    assert accepted["duration_minutes"] == 360


def test_the_later_day_already_carries_the_minutes_after_midnight():
    """"If that sum exceeds eight hours on any single UTC calendar day, the request is
    refused with `ERR_PROCTOR_DAILY_CAP_EXCEEDED`."  The later day already holds 120
    minutes from a sitting that *started* on the earlier day, so only 360 remain, and
    one further minute is refused.

    Design: Difficulty/resource_temporal_overlap/proctor_daily_minutes_clipped_at_each_utc_midnight
    """
    _setup_midnight_spanning_session()

    accepted = validate_success(
        _schedule("T09", "proctor-8", "2026-08-26T09:00:00Z", "2026-08-26T15:00:00Z"),
        201,
    )
    assert accepted["duration_minutes"] == 360

    validate_error(
        _schedule("T10", "proctor-8", "2026-08-26T16:00:00Z", "2026-08-26T16:01:00Z"),
        ApiErrorId.ERR_PROCTOR_DAILY_CAP_EXCEEDED,
        409,
    )


def test_the_daily_cap_is_charged_per_proctor_and_rejections_persist_nothing():
    """The aggregate is taken "for the named `proctor_user_id`", so the identical
    window is accepted for a different person, and only the accepted sessions of the
    saturated proctor survive.

    Design: Difficulty/resource_temporal_overlap/proctor_daily_minutes_clipped_at_each_utc_midnight
    """
    _setup_midnight_spanning_session()
    validate_success(
        _schedule("T08", "proctor-8", "2026-08-25T09:00:00Z", "2026-08-25T15:00:00Z"),
        201,
    )
    validate_success(
        _schedule("T09", "proctor-8", "2026-08-26T09:00:00Z", "2026-08-26T15:00:00Z"),
        201,
    )
    validate_error(
        _schedule("T10", "proctor-8", "2026-08-26T16:00:00Z", "2026-08-26T16:01:00Z"),
        ApiErrorId.ERR_PROCTOR_DAILY_CAP_EXCEEDED,
        409,
    )

    other = validate_success(
        _schedule("T11", "proctor-12", "2026-08-26T16:00:00Z", "2026-08-26T16:01:00Z"),
        201,
    )
    assert other["duration_minutes"] == 1

    staff = make_assessment_staff_headers()
    rows, meta = validate_paginated(
        api_client.list_test_administrations(
            staff, params={"proctor_user_id": "proctor-8"}
        )
    )
    assert meta["total_count"] == 3
    assert sorted(row["room_code"] for row in rows) == ["T07", "T08", "T09"]

    persisted = get_success_data(
        api_client.get_test_administration(other["id"], staff)
    )
    assert persisted["room_code"] == "T11"
