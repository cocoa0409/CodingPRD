"""Interval arithmetic behind combine-week scheduling.

Covers the three conflict rules that decide whether a proposed booking may
hold its slot: the sanitation buffer that inflates a medical station request on
both sides, the aggregate overlap count that an interview room admits up to its
concurrent capacity, and the ten-minute travel allowance that keeps one
prospect's own itinerary physically walkable.
"""

from typing import Dict, List

from test_helpers import (
    ERR_PROSPECT_ITINERARY_CONFLICT,
    ERR_ROOM_CAPACITY_EXCEEDED,
    ERR_STATION_SLOT_CONFLICT,
    ADMIN,
    book,
    build_declaration_open,
    combine_booking_payload,
    create_room,
    create_station,
    declare_prospect,
    move_phase,
    read_booking,
    read_prospect,
    register_prospect,
    validate_error,
    validate_success,
)

# Prospect seeds used by the scheduling scenarios, in registration order.
PROSPECT_SEEDS: List[Dict] = [
    {
        "full_name": "Avery Lane",
        "position_group": "QB",
        "school_code": "NRT",
        "seasons_played": 4,
        "scouting_grade": 92.50,
        "position_group_scarcity_rank": 1,
    },
    {
        "full_name": "Brooks Hale",
        "position_group": "WR",
        "school_code": "STH",
        "seasons_played": 4,
        "scouting_grade": 88.00,
        "position_group_scarcity_rank": 3,
    },
    {
        "full_name": "Cade Rios",
        "position_group": "DL",
        "school_code": "EST",
        "seasons_played": 3,
        "scouting_grade": 85.00,
        "position_group_scarcity_rank": 2,
    },
    {
        "full_name": "Dane Cobb",
        "position_group": "OL",
        "school_code": "WST",
        "seasons_played": 4,
        "scouting_grade": 90.00,
        "position_group_scarcity_rank": 4,
    },
]

# Medical station day on 2027-02-23.
EXAM_START = "2027-02-23T09:00:00.000Z"
EXAM_END = "2027-02-23T09:45:00.000Z"
CLEAR_EXAM_START = "2027-02-23T10:00:00.000Z"
CLEAR_EXAM_END = "2027-02-23T10:45:00.000Z"
BUFFERED_EXAM_START = "2027-02-23T09:50:00.000Z"
BUFFERED_EXAM_END = "2027-02-23T10:30:00.000Z"

# Interview room day on 2027-02-24.
IV1_START = "2027-02-24T13:00:00.000Z"
IV1_END = "2027-02-24T13:30:00.000Z"
IV2_START = "2027-02-24T13:15:00.000Z"
IV2_END = "2027-02-24T13:45:00.000Z"
IV_TOUCHING_START = "2027-02-24T13:30:00.000Z"
IV_TOUCHING_END = "2027-02-24T14:00:00.000Z"
IV_THIRD_OVERLAP_START = "2027-02-24T13:20:00.000Z"
IV_THIRD_OVERLAP_END = "2027-02-24T13:50:00.000Z"

# Itinerary day on 2027-02-23.
TRAVEL_OK_INTERVIEW_START = "2027-02-23T09:55:00.000Z"
TRAVEL_OK_INTERVIEW_END = "2027-02-23T10:25:00.000Z"
FIELD_TEST_START = "2027-02-23T09:50:00.000Z"
FIELD_TEST_END = "2027-02-23T10:20:00.000Z"


# ---------------------------------------------------------------------------
# Local scenario compositions
# ---------------------------------------------------------------------------


def _combine_week_with_declared_prospects(api, count: int) -> Dict:
    """COMBINE_WEEK behind ``count`` registered, declared prospects."""
    state = build_declaration_open(api)
    prospects = []
    for seed in PROSPECT_SEEDS[:count]:
        prospect = register_prospect(api, state["cycle"]["id"], **seed)
        prospects.append(declare_prospect(api, prospect))
    state["prospects"] = prospects
    state["cycle"] = move_phase(api, state["cycle"]["id"], "COMBINE_WEEK")
    return state


def _station_week(api) -> Dict:
    """Three declared prospects and one ORTHO station with a 15-minute buffer."""
    state = _combine_week_with_declared_prospects(api, 3)
    state["station"] = create_station(
        api, "ST-ORTHO-1", "ORTHO", turnaround_buffer_minutes=15
    )
    return state


def _room_week(api) -> Dict:
    """Four declared prospects and one interview room holding two at a time."""
    state = _combine_week_with_declared_prospects(api, 4)
    state["room"] = create_room(api, "IR-1", concurrent_capacity=2)
    return state


def _itinerary_week(api) -> Dict:
    """One declared prospect already holding a 09:00-09:45 cardiac exam."""
    state = _combine_week_with_declared_prospects(api, 1)
    state["station"] = create_station(
        api, "ST-CARD-1", "CARDIAC", turnaround_buffer_minutes=15
    )
    state["room"] = create_room(api, "IR-2", concurrent_capacity=2)
    state["exam"] = book(
        api,
        state["prospects"][0],
        "MEDICAL_EXAM",
        EXAM_START,
        EXAM_END,
        medical_station_id=state["station"]["id"],
    )
    return state


def _try_booking(api, prospect: Dict, booking_type: str, starts_at, ends_at, **extra):
    """Attempt a booking without asserting the outcome."""
    return api.create_combine_booking(
        combine_booking_payload(
            prospect["id"], booking_type, starts_at, ends_at, **extra
        ),
        ADMIN,
    )


# ---------------------------------------------------------------------------
# Medical station sanitation buffer
# ---------------------------------------------------------------------------


class TestStationTurnaroundBuffer:
    def test_exam_inside_the_sanitation_window_conflicts(self, api):
        """A 09:50 start sits inside the buffered tail of the 09:00 exam.

        "A medical station admits one examination at a time, and the sanitation
        window counts: the proposed interval is widened by the station's
        `turnaround_buffer_minutes` at both ends, and if that widened interval
        overlaps the half-open interval of any booking already on that station
        in `SCHEDULED` or `CHECKED_IN`, the request is refused with
        `ERR_STATION_SLOT_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/station_turnaround_buffer_inflates_the_new_interval_on_both_sides
        """
        state = _station_week(api)
        station = state["station"]
        first, second, third = state["prospects"]

        book(
            api,
            first,
            "MEDICAL_EXAM",
            EXAM_START,
            EXAM_END,
            medical_station_id=station["id"],
        )
        book(
            api,
            second,
            "MEDICAL_EXAM",
            CLEAR_EXAM_START,
            CLEAR_EXAM_END,
            medical_station_id=station["id"],
        )

        response = _try_booking(
            api,
            third,
            "MEDICAL_EXAM",
            BUFFERED_EXAM_START,
            BUFFERED_EXAM_END,
            medical_station_id=station["id"],
        )

        validate_error(response, ERR_STATION_SLOT_CONFLICT)

    def test_exam_one_clear_buffer_after_the_previous_one_is_accepted(self, api):
        """A 10:00 start leaves the full quarter hour and is booked.

        "With the default buffer of a quarter of an hour, two examinations at
        the same station must therefore be separated by at least fifteen clear
        minutes."

        "The server computes `duration_minutes` as the whole number of minutes
        between `starts_at` and `ends_at`."

        Design: Difficulty/resource_temporal_overlap/station_turnaround_buffer_inflates_the_new_interval_on_both_sides
        """
        state = _station_week(api)
        station = state["station"]
        first, second, _third = state["prospects"]

        book(
            api,
            first,
            "MEDICAL_EXAM",
            EXAM_START,
            EXAM_END,
            medical_station_id=station["id"],
        )

        response = _try_booking(
            api,
            second,
            "MEDICAL_EXAM",
            CLEAR_EXAM_START,
            CLEAR_EXAM_END,
            medical_station_id=station["id"],
        )

        booking = validate_success(response, expected_status=201)
        assert booking["status"] == "SCHEDULED"
        assert booking["starts_at"] == CLEAR_EXAM_START
        assert booking["duration_minutes"] == 45

    def test_station_conflict_leaves_both_exams_holding_their_slots(self, api):
        """The refused request releases nothing already on the station.

        "A medical station admits one examination at a time, and the sanitation
        window counts: the proposed interval is widened by the station's
        `turnaround_buffer_minutes` at both ends, and if that widened interval
        overlaps the half-open interval of any booking already on that station
        in `SCHEDULED` or `CHECKED_IN`, the request is refused with
        `ERR_STATION_SLOT_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/station_turnaround_buffer_inflates_the_new_interval_on_both_sides
        """
        state = _station_week(api)
        station = state["station"]
        first, second, third = state["prospects"]

        early = book(
            api,
            first,
            "MEDICAL_EXAM",
            EXAM_START,
            EXAM_END,
            medical_station_id=station["id"],
        )
        late = book(
            api,
            second,
            "MEDICAL_EXAM",
            CLEAR_EXAM_START,
            CLEAR_EXAM_END,
            medical_station_id=station["id"],
        )

        _try_booking(
            api,
            third,
            "MEDICAL_EXAM",
            BUFFERED_EXAM_START,
            BUFFERED_EXAM_END,
            medical_station_id=station["id"],
        )

        early = read_booking(api, early["id"])
        assert early["status"] == "SCHEDULED"
        assert early["duration_minutes"] == 45

        late = read_booking(api, late["id"])
        assert late["status"] == "SCHEDULED"
        assert late["starts_at"] == CLEAR_EXAM_START

        blocked = read_prospect(api, third["id"])
        assert blocked["declaration_status"] == "DECLARED"


# ---------------------------------------------------------------------------
# Interview room concurrent capacity
# ---------------------------------------------------------------------------


class TestInterviewRoomCapacity:
    def test_request_overlapping_three_live_interviews_exceeds_capacity(self, api):
        """A 13:20-13:50 request overlaps three bookings in a room that holds two.

        "An interview room admits several clubs at once, but not without limit:
        the system counts the bookings on that room in `SCHEDULED` or
        `CHECKED_IN` whose half-open intervals overlap the proposed one, and
        that count must be strictly less than the room's `concurrent_capacity`,
        else `ERR_ROOM_CAPACITY_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/interview_room_capacity_counts_overlaps_but_not_adjacency
        """
        state = _room_week(api)
        room = state["room"]
        elm = state["clubs"]["ELM"]
        first, second, third, fourth = state["prospects"]

        for prospect, starts_at, ends_at in (
            (first, IV1_START, IV1_END),
            (second, IV2_START, IV2_END),
            (fourth, IV_TOUCHING_START, IV_TOUCHING_END),
        ):
            book(
                api,
                prospect,
                "CLUB_INTERVIEW",
                starts_at,
                ends_at,
                interview_room_id=room["id"],
                club_id=elm["id"],
            )

        response = _try_booking(
            api,
            third,
            "CLUB_INTERVIEW",
            IV_THIRD_OVERLAP_START,
            IV_THIRD_OVERLAP_END,
            interview_room_id=room["id"],
            club_id=elm["id"],
        )

        validate_error(response, ERR_ROOM_CAPACITY_EXCEEDED)

    def test_interview_touching_the_first_slot_counts_one_overlap(self, api):
        """A 13:30 start only overlaps the 13:15 booking, so the room admits it.

        "Two intervals that merely touch — one ending at the exact instant the
        next begins — do not overlap, so a zero gap is legal in a room."

        Design: Difficulty/resource_temporal_overlap/interview_room_capacity_counts_overlaps_but_not_adjacency
        """
        state = _room_week(api)
        room = state["room"]
        elm = state["clubs"]["ELM"]
        first, second, _third, fourth = state["prospects"]

        book(
            api,
            first,
            "CLUB_INTERVIEW",
            IV1_START,
            IV1_END,
            interview_room_id=room["id"],
            club_id=elm["id"],
        )
        book(
            api,
            second,
            "CLUB_INTERVIEW",
            IV2_START,
            IV2_END,
            interview_room_id=room["id"],
            club_id=elm["id"],
        )

        response = _try_booking(
            api,
            fourth,
            "CLUB_INTERVIEW",
            IV_TOUCHING_START,
            IV_TOUCHING_END,
            interview_room_id=room["id"],
            club_id=elm["id"],
        )

        booking = validate_success(response, expected_status=201)
        assert booking["status"] == "SCHEDULED"
        assert booking["starts_at"] == IV_TOUCHING_START
        assert booking["duration_minutes"] == 30

    def test_capacity_refusal_leaves_the_three_interviews_scheduled(self, api):
        """The over-capacity request changes nothing the room already holds.

        "An interview room admits several clubs at once, but not without limit:
        the system counts the bookings on that room in `SCHEDULED` or
        `CHECKED_IN` whose half-open intervals overlap the proposed one, and
        that count must be strictly less than the room's `concurrent_capacity`,
        else `ERR_ROOM_CAPACITY_EXCEEDED`."

        "A booking is created in `SCHEDULED` and is moved by the admin with a
        status `action`."

        Design: Difficulty/resource_temporal_overlap/interview_room_capacity_counts_overlaps_but_not_adjacency
        """
        state = _room_week(api)
        room = state["room"]
        elm = state["clubs"]["ELM"]
        first, second, third, fourth = state["prospects"]

        booked = [
            book(
                api,
                prospect,
                "CLUB_INTERVIEW",
                starts_at,
                ends_at,
                interview_room_id=room["id"],
                club_id=elm["id"],
            )
            for prospect, starts_at, ends_at in (
                (first, IV1_START, IV1_END),
                (second, IV2_START, IV2_END),
                (fourth, IV_TOUCHING_START, IV_TOUCHING_END),
            )
        ]

        _try_booking(
            api,
            third,
            "CLUB_INTERVIEW",
            IV_THIRD_OVERLAP_START,
            IV_THIRD_OVERLAP_END,
            interview_room_id=room["id"],
            club_id=elm["id"],
        )

        for booking in booked:
            assert read_booking(api, booking["id"])["status"] == "SCHEDULED"

        assert read_booking(api, booked[2]["id"])["duration_minutes"] == 30

        room_now = validate_success(api.get_interview_room(room["id"], ADMIN))
        assert room_now["concurrent_capacity"] == 2


# ---------------------------------------------------------------------------
# Prospect travel allowance
# ---------------------------------------------------------------------------


class TestProspectItineraryTravelGap:
    def test_field_test_inside_the_travel_gap_conflicts_on_the_prospect(self, api):
        """The widened field-test interval collides with the prospect's own exam.

        "Finally, the prospect must physically be able to make it: the proposed
        interval is widened by ten minutes of travel allowance at both ends, and
        if that widened interval overlaps any other booking of the same prospect
        in `SCHEDULED` or `CHECKED_IN`, the request is refused with
        `ERR_PROSPECT_ITINERARY_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/prospect_itinerary_travel_gap_blocks_a_second_resource_booking
        """
        state = _itinerary_week(api)
        prospect = state["prospects"][0]
        elm = state["clubs"]["ELM"]

        book(
            api,
            prospect,
            "CLUB_INTERVIEW",
            TRAVEL_OK_INTERVIEW_START,
            TRAVEL_OK_INTERVIEW_END,
            interview_room_id=state["room"]["id"],
            club_id=elm["id"],
        )

        response = _try_booking(
            api, prospect, "ON_FIELD_TEST", FIELD_TEST_START, FIELD_TEST_END
        )

        error = validate_error(response, ERR_PROSPECT_ITINERARY_CONFLICT)
        assert error["error_id"] != ERR_ROOM_CAPACITY_EXCEEDED

    def test_interview_exactly_ten_minutes_after_the_exam_is_accepted(self, api):
        """A 09:55 start leaves the exact travel allowance after a 09:45 finish.

        "Finally, the prospect must physically be able to make it: the proposed
        interval is widened by ten minutes of travel allowance at both ends, and
        if that widened interval overlaps any other booking of the same prospect
        in `SCHEDULED` or `CHECKED_IN`, the request is refused with
        `ERR_PROSPECT_ITINERARY_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/prospect_itinerary_travel_gap_blocks_a_second_resource_booking
        """
        state = _itinerary_week(api)
        prospect = state["prospects"][0]
        elm = state["clubs"]["ELM"]

        response = _try_booking(
            api,
            prospect,
            "CLUB_INTERVIEW",
            TRAVEL_OK_INTERVIEW_START,
            TRAVEL_OK_INTERVIEW_END,
            interview_room_id=state["room"]["id"],
            club_id=elm["id"],
        )

        booking = validate_success(response, expected_status=201)
        assert booking["status"] == "SCHEDULED"
        assert booking["starts_at"] == TRAVEL_OK_INTERVIEW_START
        assert booking["duration_minutes"] == 30

    def test_itinerary_refusal_leaves_the_exam_and_interview_scheduled(self, api):
        """Neither of the prospect's live bookings is released by the refusal.

        "Only bookings in `SCHEDULED` or `CHECKED_IN` occupy a resource; those
        in `COMPLETED`, `NO_SHOW` or `CANCELLED` have released their interval
        and never block anything."

        Design: Difficulty/resource_temporal_overlap/prospect_itinerary_travel_gap_blocks_a_second_resource_booking
        """
        state = _itinerary_week(api)
        prospect = state["prospects"][0]
        elm = state["clubs"]["ELM"]

        interview = book(
            api,
            prospect,
            "CLUB_INTERVIEW",
            TRAVEL_OK_INTERVIEW_START,
            TRAVEL_OK_INTERVIEW_END,
            interview_room_id=state["room"]["id"],
            club_id=elm["id"],
        )

        _try_booking(
            api, prospect, "ON_FIELD_TEST", FIELD_TEST_START, FIELD_TEST_END
        )

        exam = read_booking(api, state["exam"]["id"])
        assert exam["status"] == "SCHEDULED"

        interview = read_booking(api, interview["id"])
        assert interview["status"] == "SCHEDULED"
        assert interview["starts_at"] == TRAVEL_OK_INTERVIEW_START
        assert interview["duration_minutes"] == 30
