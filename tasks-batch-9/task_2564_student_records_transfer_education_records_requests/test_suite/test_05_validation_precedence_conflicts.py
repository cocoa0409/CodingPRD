"""Two rules violated by one call: only the earlier precedence band may speak.

Each scenario carries its own control call proving the later band was genuinely
available at that instant, so the assertion is about ordering rather than about
one rule simply not firing.
"""
from test_helpers import (
    CLERK,
    OFFICER_1,
    api_client,
    appointment_payload,
    assert_inspection_request,
    assert_review_appointment,
    assert_student,
    book_appointment,
    create_district,
    create_inspection_request,
    create_inspection_room,
    create_state_rule,
    create_student,
    directory_optout_payload,
    get_inspection_request,
    make_parent_headers,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

CA_RULE = dict(
    transfer_response_days=10,
    discipline_inclusion_mode="SUSPENSIONS_AND_EXPULSIONS",
    discipline_min_days_removed=10,
    include_pending_investigations=False,
    sped_requires_consent=True,
    amendment_hearing_days=30,
    destruction_min_age_years=5,
    directory_optout_grace_days=14,
    notification_wait_days=7,
)
OPTOUT_CATEGORIES = ["NAME", "PHOTO"]


def _get_student(student_id):
    return validate_success(api_client.get_student(student_id, CLERK))


def _adult_and_minor_past_the_window():
    """Two siblings created at the default clock share the deadline
    2026-08-15T00:00:00.000Z; the clock then runs five days past it. Jonah turns
    18 on 2026-08-01, so his parent no longer holds the family's rights."""
    create_state_rule("CA", **CA_RULE)
    district = create_district("SEND01", state_code="CA", name="Sending Unified")
    adult = create_student(
        district["id"],
        first_name="Jonah",
        last_name="Adeyemi",
        dob="2008-08-01",
        grade_level=12,
        has_iep=False,
        guardian_user_id="guardian-jonah",
        student_user_id="student-jonah",
    )
    minor = create_student(
        district["id"],
        first_name="Kira",
        last_name="Adeyemi",
        dob="2012-05-05",
        grade_level=8,
        has_iep=False,
        guardian_user_id="guardian-jonah",
    )
    set_clock("2026-08-20T00:00:00Z")
    return adult, minor, make_parent_headers("guardian-jonah")


class TestRightsTransferBeatsTheOptoutWindow:
    def test_the_authorization_band_answers_for_the_adult_student(self):
        """A parent filing an opt-out for their 18-year-old five days after the
        grace window closed breaks both the rights-holder rule and the window
        rule; only the 403 from the authorization band may surface.

        PRD: "When one request violates several rules at once, the response is determined by a total precedence ordering over nine bands, and the error returned is always the one from the earliest band."

        Design: Difficulty/priority_pair_validation_conflict/rights_transferred_beats_optout_window
        """
        adult, _minor, parent = _adult_and_minor_past_the_window()

        response = api_client.update_directory_optout(
            adult["id"], directory_optout_payload(OPTOUT_CATEGORIES), parent
        )

        error = validate_error(response, "ERR_RIGHTS_TRANSFERRED", 403)
        assert error["error_id"] != "ERR_OPTOUT_WINDOW_CLOSED", (
            "the business-rule band must not answer ahead of the authorization band"
        )

        blocked = _get_student(adult["id"])
        assert_student(blocked)
        assert blocked["is_eligible_student"] is True
        assert blocked["directory_optout_deadline_at"] == "2026-08-15T00:00:00.000Z"
        assert blocked["directory_optout_received_at"] is None
        assert blocked["directory_optout_effective"] is False

    def test_the_minor_control_call_proves_the_window_rule_was_live(self):
        """The identical payload for the sibling minor, at the identical instant
        and against the identical deadline, must reach the business-rule band and
        be refused with 422, which is the error the adult's call suppressed.

        PRD: "The boundary is inclusive to the millisecond: at exactly the deadline the opt-out takes effect, and one millisecond later the filing is refused with `ERR_OPTOUT_WINDOW_CLOSED` and `directory_optout_effective` remains false."

        Design: Difficulty/priority_pair_validation_conflict/rights_transferred_beats_optout_window
        """
        _adult, minor, parent = _adult_and_minor_past_the_window()

        response = api_client.update_directory_optout(
            minor["id"], directory_optout_payload(OPTOUT_CATEGORIES), parent
        )

        validate_error(response, "ERR_OPTOUT_WINDOW_CLOSED", 422)

        untouched = _get_student(minor["id"])
        assert untouched["is_eligible_student"] is False
        assert untouched["directory_optout_deadline_at"] == "2026-08-15T00:00:00.000Z"
        assert untouched["directory_optout_effective"] is False
        assert untouched["directory_optout_categories"] == []

    def test_rights_transfer_is_decided_by_the_birthday_alone(self):
        """The two siblings differ only in date of birth, and that difference is
        what routes one call into the authorization band and the other into the
        business-rule band.

        PRD: "`is_eligible_student` is true when that whole-year count is at least 18, so eligibility begins on the birthday itself: a student born on 2008-08-01 is eligible from the instant `2026-08-01T00:00:00.000Z` and is not eligible at `2026-07-31T23:59:59.999Z`."

        Design: Difficulty/priority_pair_validation_conflict/rights_transferred_beats_optout_window
        """
        adult, minor, parent = _adult_and_minor_past_the_window()

        adult_error = validate_error(
            api_client.update_directory_optout(
                adult["id"], directory_optout_payload(OPTOUT_CATEGORIES), parent
            ),
            "ERR_RIGHTS_TRANSFERRED",
            403,
        )
        minor_error = validate_error(
            api_client.update_directory_optout(
                minor["id"], directory_optout_payload(OPTOUT_CATEGORIES), parent
            ),
            "ERR_OPTOUT_WINDOW_CLOSED",
            422,
        )

        assert adult_error["error_id"] != minor_error["error_id"]
        assert _get_student(adult["id"])["is_eligible_student"] is True
        assert _get_student(minor["id"])["is_eligible_student"] is False


COLLIDING_START = "2026-08-10T10:15:00Z"
COLLIDING_END = "2026-08-10T11:00:00Z"


def _booked_room_with_a_stale_token():
    """One appointment already sits in ROOM-A from 09:00 to 10:00 on
    2026-08-10. `stale` is the inspection request version read before that
    booking, `current` the version after it."""
    create_state_rule("CA", **CA_RULE)
    district = create_district("SEND01", state_code="CA", name="Sending Unified")
    room = create_inspection_room(
        room_code="ROOM-A", seats=4, site_name="District Records Annex"
    )
    student = create_student(
        district["id"],
        first_name="Lena",
        last_name="Whitcombe",
        dob="2013-03-21",
        grade_level=7,
        has_iep=False,
        guardian_user_id="guardian-lena",
    )
    parent = make_parent_headers("guardian-lena")
    request = create_inspection_request(
        student["id"], parent, categories=["ACADEMIC"], copies_requested=False
    )
    stale = get_inspection_request(request["id"])["version"]
    first = book_appointment(
        request["id"],
        room["id"],
        "2026-08-10T09:00:00Z",
        "2026-08-10T10:00:00Z",
        expected_version=stale,
    )
    current = get_inspection_request(request["id"])["version"]
    assert current != stale, "booking the first appointment must move the request version"
    return room, request, first, stale, current


def _appointments_for(request_id):
    data, _meta = validate_paginated(
        api_client.list_review_appointments(
            OFFICER_1, params={"inspection_request_id": request_id}
        )
    )
    return data


class TestStaleTokenBeatsRoomDoubleBooking:
    def test_the_optimistic_lock_band_answers_before_the_temporal_band(self):
        """One body carries both a stale expected_inspection_request_version and
        an interval that lands inside the fifteen-minute turnover buffer of the
        existing appointment; only 412 may surface.

        PRD: "It is likewise non-optional, and a value that does not equal the request's current `version` is rejected with `ERR_STALE_INSPECTION_REQUEST_VERSION` (HTTP 412)."

        Design: Difficulty/priority_pair_validation_conflict/occ_stale_version_beats_room_double_booking
        """
        room, request, first, stale, _current = _booked_room_with_a_stale_token()

        response = api_client.create_review_appointment(
            request["id"],
            appointment_payload(room["id"], COLLIDING_START, COLLIDING_END, stale),
            OFFICER_1,
        )

        error = validate_error(response, "ERR_STALE_INSPECTION_REQUEST_VERSION", 412)
        assert error["error_id"] != "ERR_ROOM_DOUBLE_BOOKED", (
            "the temporal-conflict band must not answer ahead of the optimistic-lock band"
        )
        assert len(_appointments_for(request["id"])) == 1

    def test_the_current_token_exposes_the_room_collision(self):
        """Replaying the identical interval with the current token proves the
        409 was genuinely available: 10:15 is inside the padded edge of an
        appointment that ended at 10:00.

        PRD: "Touching the padded edge therefore collides, and the booking is refused with `ERR_ROOM_DOUBLE_BOOKED`."

        Design: Difficulty/priority_pair_validation_conflict/occ_stale_version_beats_room_double_booking
        """
        room, request, first, _stale, current = _booked_room_with_a_stale_token()

        response = api_client.create_review_appointment(
            request["id"],
            appointment_payload(room["id"], COLLIDING_START, COLLIDING_END, current),
            OFFICER_1,
        )

        validate_error(response, "ERR_ROOM_DOUBLE_BOOKED", 409)

        standing = validate_success(api_client.get_review_appointment(first["id"], OFFICER_1))
        assert_review_appointment(standing)
        assert standing["status"] == "SCHEDULED"
        assert standing["duration_minutes"] == 60

    def test_neither_refusal_books_a_second_appointment_or_moves_the_version(self):
        """Both rejected calls must leave the first appointment SCHEDULED, the
        inspection request in SCHEDULED at the version read after the accepted
        booking, and exactly one appointment row against the request.

        PRD: "Booking supersedes any appointment already scheduled against that inspection request, which is legitimate rescheduling; the token ensures the client is displacing the appointment it actually saw."

        Design: Difficulty/priority_pair_validation_conflict/occ_stale_version_beats_room_double_booking
        """
        room, request, first, stale, current = _booked_room_with_a_stale_token()

        validate_error(
            api_client.create_review_appointment(
                request["id"],
                appointment_payload(room["id"], COLLIDING_START, COLLIDING_END, stale),
                OFFICER_1,
            ),
            "ERR_STALE_INSPECTION_REQUEST_VERSION",
            412,
        )
        validate_error(
            api_client.create_review_appointment(
                request["id"],
                appointment_payload(room["id"], COLLIDING_START, COLLIDING_END, current),
                OFFICER_1,
            ),
            "ERR_ROOM_DOUBLE_BOOKED",
            409,
        )

        after = get_inspection_request(request["id"])
        assert_inspection_request(after)
        assert after["status"] == "SCHEDULED"
        assert after["version"] == current
        rows = _appointments_for(request["id"])
        assert len(rows) == 1, f"exactly one appointment must survive, got {len(rows)}"
        assert rows[0]["id"] == first["id"]
        assert rows[0]["status"] == "SCHEDULED"
