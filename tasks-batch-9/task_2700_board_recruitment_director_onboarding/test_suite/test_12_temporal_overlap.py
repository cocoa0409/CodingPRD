"""Two overlap resources with opposite interval conventions: the interviewer's
half-open calendar, and the closed-interval committee term plus the finite seat
count that a committee's occupancy defends.
"""
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.api_errors import (
    ERR_ASSIGNMENT_TERM_OVERLAP,
    ERR_COMMITTEE_SEATS_EXHAUSTED,
    ERR_INTERVIEWER_DOUBLE_BOOKED,
)
from test_helpers.assertions import (
    assert_committee_ledger,
    assert_fields_equal,
    assert_page,
    ids_of,
)
from test_helpers.test_users import SECRETARY, STAFF, make_committee_chair_headers

# The occupied window on interviewer X's calendar.
BUSY_START = "2026-03-02T10:00:00Z"
BUSY_END = "2026-03-02T11:00:00Z"

# Starts exactly when the busy window ends: legal under a half-open interval.
ABUTS_AFTER_START = "2026-03-02T11:00:00Z"
ABUTS_AFTER_END = "2026-03-02T12:00:00Z"

# Ends exactly when the busy window starts: the other endpoint of the same rule.
ABUTS_BEFORE_START = "2026-03-02T09:00:00Z"
ABUTS_BEFORE_END = "2026-03-02T10:00:00Z"

# Straddles the busy window by thirty minutes at each end: a genuine overlap.
STRADDLE_START = "2026-03-02T10:30:00Z"
STRADDLE_END = "2026-03-02T11:30:00Z"

# A closed term ending on this date shares its final day with a term starting on it.
TERM_A_START = "2026-01-01"
TERM_A_END = "2026-06-30"
TERM_SHARING_THE_END_DAY = "2026-06-30"
TERM_ONE_DAY_CLEAR = "2026-07-01"
TERM_END_OF_YEAR = "2026-12-31"

# The committee charters two seats and both are already occupied.
COMMITTEE_AUTHORIZED_SEATS = 2
COMMITTEE_MIN_SEATS = 1


def _calendar_with_one_busy_hour(client):
    """Interviewer X is booked 10:00-11:00; four screened candidates are ready to book."""
    X.adopt_policy(client, min_completed_interviews=1)
    chair = X.new_seated_director(
        client,
        full_name="Dana Chair",
        email="dana.chair@issuer.example",
        birth_date="1962-03-15",
        appointed_on="2019-05-01",
    )
    chair_headers = make_committee_chair_headers(chair["id"])
    interviewer_x = X.new_seated_director(
        client,
        full_name="Xena Interviewer",
        email="xena@issuer.example",
        birth_date="1966-07-07",
        appointed_on="2020-05-01",
    )
    interviewer_y = X.new_seated_director(
        client,
        full_name="Yuri Interviewer",
        email="yuri@issuer.example",
        birth_date="1967-08-08",
        appointed_on="2020-06-01",
    )

    candidates = {}
    for key, full_name, email, birth_date in [
        ("a", "Aida Alpha", "aida@cand.example", "1974-01-05"),
        ("f", "Fred Foxtrot", "fred@cand.example", "1975-02-06"),
        ("g", "Gita Golf", "gita@cand.example", "1976-03-07"),
        ("h", "Hana Hotel", "hana@cand.example", "1977-04-08"),
    ]:
        candidate = X.new_candidate(
            client,
            full_name=full_name,
            email=email,
            birth_date=birth_date,
            source_channel="SHAREHOLDER_PROPOSAL",
            shareholder_proponent_name="Cedar Ridge Capital",
        )
        X.advance_to_screen_passed(client, candidate["id"], chair_headers)
        candidates[key] = candidate

    session_a = X.schedule_interview(
        client, candidates["a"]["id"], interviewer_x["id"], BUSY_START, BUSY_END
    )
    return {
        "interviewer_x": interviewer_x,
        "interviewer_y": interviewer_y,
        "candidates": candidates,
        "session_a": session_a,
    }


def _committee_with_both_seats_occupied(client):
    """A two-seat RISK committee holding an ACTIVE chair term and an ACTIVE member term."""
    X.adopt_policy(client)
    director_one = X.new_seated_director(
        client,
        full_name="Dinah One",
        email="dinah@issuer.example",
        birth_date="1968-01-01",
        appointed_on="2021-01-01",
        is_independent=True,
    )
    director_two = X.new_seated_director(
        client,
        full_name="Devon Two",
        email="devon@issuer.example",
        birth_date="1969-02-02",
        appointed_on="2021-02-01",
        is_independent=True,
    )
    committee = X.new_committee(
        client,
        code="RISK",
        name="Risk Oversight Committee",
        authorized_seats=COMMITTEE_AUTHORIZED_SEATS,
        min_seats=COMMITTEE_MIN_SEATS,
    )
    chair_seat = X.seat_assignment(
        client,
        committee["id"],
        director_one["id"],
        seat_role="CHAIR",
        term_start_on=TERM_A_START,
        term_end_on=TERM_A_END,
    )
    member_seat = X.seat_assignment(
        client,
        committee["id"],
        director_two["id"],
        seat_role="MEMBER",
        term_start_on=TERM_A_START,
        term_end_on=TERM_END_OF_YEAR,
    )
    return {
        "committee": committee,
        "director_one": director_one,
        "director_two": director_two,
        "chair_seat": chair_seat,
        "member_seat": member_seat,
    }


def test_a_session_that_abuts_an_existing_window_is_not_a_double_booking(client):
    """Both endpoints of the half-open interval are pinned: 11:00-12:00 starts exactly when
    the busy hour ends and 09:00-10:00 ends exactly when it starts, and both are admitted.

    PRD: "Because the interval is half-open, a session whose `start_at` equals an existing session's `end_at` is permitted, and back-to-back interviews are therefore legal"

    Design: Difficulty/resource_temporal_overlap/interviewer_calendar_half_open_adjacency_allowed_but_overlap_rejected
    """
    built = _calendar_with_one_busy_hour(client)
    interviewer_x = built["interviewer_x"]["id"]

    after = validate_success(
        client.schedule_interview(
            F.interview_payload(
                built["candidates"]["f"]["id"],
                interviewer_x,
                start_at=ABUTS_AFTER_START,
                end_at=ABUTS_AFTER_END,
            ),
            STAFF,
        ),
        201,
    )
    before = validate_success(
        client.schedule_interview(
            F.interview_payload(
                built["candidates"]["h"]["id"],
                interviewer_x,
                start_at=ABUTS_BEFORE_START,
                end_at=ABUTS_BEFORE_END,
                modality="IN_PERSON",
            ),
            STAFF,
        ),
        201,
    )

    assert after["status"] == "SCHEDULED"
    assert before["status"] == "SCHEDULED"
    data, _ = assert_page(
        client.list_interviews(STAFF, params={"interviewer_director_id": interviewer_x}),
        expected_total=3,
    )
    assert [row["status"] for row in data] == ["SCHEDULED", "SCHEDULED", "SCHEDULED"]


def test_a_straddling_window_is_refused_on_the_same_interviewer(client):
    """A 10:30-11:30 request overlaps the interior of the 10:00-11:00 session already on
    interviewer X's calendar, so it is refused as a double booking.

    PRD: "it must not overlap any session of the same `interviewer_director_id` whose `status` is `SCHEDULED` or `COMPLETED`"

    Design: Difficulty/resource_temporal_overlap/interviewer_calendar_half_open_adjacency_allowed_but_overlap_rejected
    """
    built = _calendar_with_one_busy_hour(client)

    validate_error(
        client.schedule_interview(
            F.interview_payload(
                built["candidates"]["g"]["id"],
                built["interviewer_x"]["id"],
                start_at=STRADDLE_START,
                end_at=STRADDLE_END,
            ),
            STAFF,
        ),
        ERR_INTERVIEWER_DOUBLE_BOOKED,
        409,
    )

    assert_page(
        client.list_interviews(
            STAFF, params={"interviewer_director_id": built["interviewer_x"]["id"]}
        ),
        expected_total=1,
        expected_ids=[built["session_a"]["id"]],
    )


def test_the_same_straddling_window_is_free_on_another_interviewer(client):
    """The calendar is scoped per interviewer, so the identical 10:30-11:30 window that
    collided on X is admitted on Y and leaves X's own calendar untouched.

    PRD: "it must not overlap any session of the same `interviewer_director_id` whose `status` is `SCHEDULED` or `COMPLETED`"

    Design: Difficulty/resource_temporal_overlap/interviewer_calendar_half_open_adjacency_allowed_but_overlap_rejected
    """
    built = _calendar_with_one_busy_hour(client)

    validate_error(
        client.schedule_interview(
            F.interview_payload(
                built["candidates"]["g"]["id"],
                built["interviewer_x"]["id"],
                start_at=STRADDLE_START,
                end_at=STRADDLE_END,
            ),
            STAFF,
        ),
        ERR_INTERVIEWER_DOUBLE_BOOKED,
        409,
    )
    session_g = validate_success(
        client.schedule_interview(
            F.interview_payload(
                built["candidates"]["g"]["id"],
                built["interviewer_y"]["id"],
                start_at=STRADDLE_START,
                end_at=STRADDLE_END,
            ),
            STAFF,
        ),
        201,
    )

    assert_fields_equal(
        session_g,
        {
            "interviewer_director_id": built["interviewer_y"]["id"],
            "candidate_id": built["candidates"]["g"]["id"],
            "status": "SCHEDULED",
        },
    )
    assert_page(
        client.list_interviews(
            STAFF, params={"interviewer_director_id": built["interviewer_y"]["id"]}
        ),
        expected_total=1,
        expected_ids=[session_g["id"]],
    )


def test_the_refused_booking_leaves_no_phantom_session_or_round(client):
    """The rejected request created nothing, so the candidate's first round opens only when
    the retried booking lands on a free interviewer.

    PRD: "the session's `interview_round` is recorded as the candidate's `interview_round` plus 1 when the candidate was at `SCREEN_PASSED`"

    Design: Difficulty/resource_temporal_overlap/interviewer_calendar_half_open_adjacency_allowed_but_overlap_rejected
    """
    built = _calendar_with_one_busy_hour(client)
    candidate_g = built["candidates"]["g"]["id"]

    validate_error(
        client.schedule_interview(
            F.interview_payload(
                candidate_g,
                built["interviewer_x"]["id"],
                start_at=STRADDLE_START,
                end_at=STRADDLE_END,
            ),
            STAFF,
        ),
        ERR_INTERVIEWER_DOUBLE_BOOKED,
        409,
    )
    assert X.get_candidate(client, candidate_g)["status"] == "SCREEN_PASSED"

    session_g = X.schedule_interview(
        client, candidate_g, built["interviewer_y"]["id"], STRADDLE_START, STRADDLE_END
    )

    assert session_g["interview_round"] == 1
    assert_fields_equal(
        X.get_candidate(client, candidate_g),
        {"status": "INTERVIEWING", "interview_round": 1, "completed_interview_count": 0},
    )


def test_a_term_starting_on_the_day_a_prior_term_ends_overlaps(client):
    """Committee terms are closed at both ends, so a new term for the same director that
    begins on the chair term's final day shares that day and is refused.

    PRD: "the requested term may not overlap any assignment of the same committee-and-director pair whose `status` is `PROPOSED` or `ACTIVE`"

    Design: Difficulty/resource_temporal_overlap/committee_assignment_closed_term_overlap_then_seat_capacity_exhaustion
    """
    built = _committee_with_both_seats_occupied(client)
    committee_id = built["committee"]["id"]
    version_before = X.committee_version(client, committee_id)

    assert_committee_ledger(
        X.get_committee(client, committee_id), filled_seats=2, status="AT_STRENGTH"
    )

    validate_error(
        client.create_assignment(
            committee_id,
            F.assignment_payload(
                built["director_one"]["id"],
                version_before,
                seat_role="MEMBER",
                term_start_on=TERM_SHARING_THE_END_DAY,
                term_end_on=TERM_END_OF_YEAR,
            ),
            SECRETARY,
        ),
        ERR_ASSIGNMENT_TERM_OVERLAP,
        409,
    )

    assert X.committee_version(client, committee_id) == version_before
    assert_committee_ledger(
        X.get_committee(client, committee_id), filled_seats=2, status="AT_STRENGTH"
    )


def test_a_term_starting_one_day_clear_of_the_prior_term_is_admitted(client):
    """One day past the chair term's final day the closed intervals no longer touch, so the
    proposal is created and reuses the committee version the refused call left alone.

    PRD: "The assignment is created `PROPOSED` with `committee_id` from the path, `activated_at` null, `ended_at` null and `ended_reason_code` null"

    Design: Difficulty/resource_temporal_overlap/committee_assignment_closed_term_overlap_then_seat_capacity_exhaustion
    """
    built = _committee_with_both_seats_occupied(client)
    committee_id = built["committee"]["id"]
    version_before = X.committee_version(client, committee_id)

    validate_error(
        client.create_assignment(
            committee_id,
            F.assignment_payload(
                built["director_one"]["id"],
                version_before,
                seat_role="MEMBER",
                term_start_on=TERM_SHARING_THE_END_DAY,
                term_end_on=TERM_END_OF_YEAR,
            ),
            SECRETARY,
        ),
        ERR_ASSIGNMENT_TERM_OVERLAP,
        409,
    )
    third = validate_success(
        client.create_assignment(
            committee_id,
            F.assignment_payload(
                built["director_one"]["id"],
                version_before,
                seat_role="MEMBER",
                term_start_on=TERM_ONE_DAY_CLEAR,
                term_end_on=TERM_END_OF_YEAR,
            ),
            SECRETARY,
        ),
        201,
    )

    assert_fields_equal(
        third,
        {
            "committee_id": committee_id,
            "status": "PROPOSED",
            "term_start_on": TERM_ONE_DAY_CLEAR,
            "activated_at": None,
            "ended_at": None,
            "ended_reason_code": None,
        },
    )


def test_activating_a_third_seat_beyond_the_authorized_count_is_refused(client):
    """The admitted term overlaps nothing, but activating it would take filled_seats to
    three against two chartered seats, so the second overlap dimension refuses it.

    PRD: "Activation may not push `filled_seats` above the committee's `authorized_seats`, else `ERR_COMMITTEE_SEATS_EXHAUSTED`."

    Design: Difficulty/resource_temporal_overlap/committee_assignment_closed_term_overlap_then_seat_capacity_exhaustion
    """
    built = _committee_with_both_seats_occupied(client)
    committee_id = built["committee"]["id"]
    third = X.propose_assignment(
        client,
        committee_id,
        built["director_one"]["id"],
        seat_role="MEMBER",
        term_start_on=TERM_ONE_DAY_CLEAR,
        term_end_on=TERM_END_OF_YEAR,
    )

    validate_error(
        client.activate_assignment(third["id"], SECRETARY),
        ERR_COMMITTEE_SEATS_EXHAUSTED,
        422,
    )

    assert X.get_assignment(client, third["id"])["status"] == "PROPOSED"
    assert_committee_ledger(
        X.get_committee(client, committee_id), filled_seats=2, status="AT_STRENGTH"
    )
    active_rows, _ = assert_page(
        client.list_assignments(
            SECRETARY, params={"committee_id": committee_id, "status": "ACTIVE"}
        ),
        expected_total=2,
    )
    assert set(ids_of(active_rows)) == {
        built["chair_seat"]["id"],
        built["member_seat"]["id"],
    }
