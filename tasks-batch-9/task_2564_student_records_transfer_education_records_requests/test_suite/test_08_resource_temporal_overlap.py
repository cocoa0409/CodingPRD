"""Two shared resources with deliberately opposite interval semantics.

Inspection rooms are closed and padded by fifteen minutes of turnover on both
sides; hearing officers are half-open with no buffer at all. The same clock
arithmetic therefore produces opposite verdicts on the two resources.
"""
from test_helpers import (
    OFFICER_1,
    api_client,
    appointment_payload,
    assert_amendment_request,
    assert_review_appointment,
    certify_component,
    collect_component,
    create_amendment,
    create_district,
    create_hearing_officer,
    create_inspection_request,
    create_inspection_room,
    create_state_rule,
    create_student,
    decide_amendment,
    get_components,
    get_cumulative_file_id,
    get_inspection_request,
    hearing_schedule_payload,
    make_parent_headers,
    request_hearing,
    schedule_hearing,
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


def _room_booked_from_nine_to_ten():
    """One room, two students with their own inspection requests, and a
    SCHEDULED appointment occupying 09:00-10:00 on 2026-08-10."""
    create_state_rule("CA", **CA_RULE)
    district = create_district("SEND01", state_code="CA", name="Sending Unified")
    room = create_inspection_room(
        room_code="ROOM-A", seats=6, site_name="District Records Annex"
    )
    student_a = create_student(
        district["id"],
        first_name="Sana",
        last_name="Verhoeven",
        dob="2012-08-08",
        grade_level=8,
        has_iep=False,
        guardian_user_id="guardian-sana",
    )
    student_b = create_student(
        district["id"],
        first_name="Tomas",
        last_name="Iversen",
        dob="2011-04-04",
        grade_level=9,
        has_iep=False,
        guardian_user_id="guardian-tomas",
    )
    request_a = create_inspection_request(
        student_a["id"],
        make_parent_headers("guardian-sana"),
        categories=["ACADEMIC"],
        copies_requested=False,
    )
    request_b = create_inspection_request(
        student_b["id"],
        make_parent_headers("guardian-tomas"),
        categories=["ACADEMIC", "HEALTH"],
        copies_requested=False,
    )
    appointment_a = validate_success(
        api_client.create_review_appointment(
            request_a["id"],
            appointment_payload(
                room["id"],
                "2026-08-10T09:00:00Z",
                "2026-08-10T10:00:00Z",
                request_a["version"],
            ),
            OFFICER_1,
        ),
        201,
    )
    return room, request_a, request_b, appointment_a


def _book_into_room(request, room, start_at, end_at):
    return api_client.create_review_appointment(
        request["id"],
        appointment_payload(room["id"], start_at, end_at, request["version"]),
        OFFICER_1,
    )


class TestInspectionRoomClosedPaddedInterval:
    def test_a_booking_exactly_fifteen_minutes_after_the_previous_end_collides(self):
        """10:15 against a window that ended at 10:00 touches the padded edge of
        the turnover buffer, so the room is still considered occupied.

        PRD: "Room occupancy is then checked with **closed, buffer-padded** semantics: the new interval and every existing `SCHEDULED` or `ATTENDED` appointment in the same room are each padded by fifteen minutes of turnover on both sides, and a collision exists whenever the new start is at or before the existing end plus fifteen minutes and the new end is at or after the existing start minus fifteen minutes."

        Design: Difficulty/resource_temporal_overlap/inspection_room_closed_interval_with_buffer
        """
        room, _request_a, request_b, appointment_a = _room_booked_from_nine_to_ten()

        response = _book_into_room(
            request_b, room, "2026-08-10T10:15:00Z", "2026-08-10T11:00:00Z"
        )

        validate_error(response, "ERR_ROOM_DOUBLE_BOOKED", 409)
        assert get_inspection_request(request_b["id"])["status"] == "SUBMITTED"
        standing = validate_success(
            api_client.get_review_appointment(appointment_a["id"], OFFICER_1)
        )
        assert standing["status"] == "SCHEDULED"

    def test_one_minute_past_the_padded_edge_clears_the_room(self):
        """10:16 is the first instant outside the buffer, so the booking is
        accepted with a forty-four minute window and the room then holds exactly
        two appointments.

        PRD: "The end instant must be strictly after the start instant — equality is rejected as a payload error — and the resulting `duration_minutes` is the whole number of minutes between them."

        Design: Difficulty/resource_temporal_overlap/inspection_room_closed_interval_with_buffer
        """
        room, _request_a, request_b, appointment_a = _room_booked_from_nine_to_ten()
        validate_error(
            _book_into_room(request_b, room, "2026-08-10T10:15:00Z", "2026-08-10T11:00:00Z"),
            "ERR_ROOM_DOUBLE_BOOKED",
            409,
        )

        appointment_b = validate_success(
            _book_into_room(request_b, room, "2026-08-10T10:16:00Z", "2026-08-10T11:00:00Z"),
            201,
        )

        assert_review_appointment(appointment_b)
        assert appointment_b["start_at"] == "2026-08-10T10:16:00.000Z"
        assert appointment_b["duration_minutes"] == 44
        assert appointment_b["status"] == "SCHEDULED"
        assert get_inspection_request(request_b["id"])["status"] == "SCHEDULED"

        standing = validate_success(
            api_client.get_review_appointment(appointment_a["id"], OFFICER_1)
        )
        assert standing["status"] == "SCHEDULED"

        rows, _meta = validate_paginated(
            api_client.list_review_appointments(OFFICER_1, params={"room_id": room["id"]})
        )
        assert len(rows) == 2, f"the room must hold exactly two appointments, got {len(rows)}"


AMENDMENT_SPECS = (
    (
        "ACADEMIC",
        dict(
            contested_field="transcript_credit_total",
            requested_change="Credit total should be 24, not 22",
            rationale="Two summer-school credits are missing",
        ),
        "Credit ledger matches the registrar record",
    ),
    (
        "HEALTH",
        dict(
            contested_field="vision_screening_result",
            requested_change="Remove the failed screening entry",
            rationale="The screening was repeated with a passing result",
        ),
        "Both screenings remain part of the health record",
    ),
    (
        "DISCIPLINE",
        dict(
            contested_field="incident_narrative_2026_03",
            requested_change="Correct the narrative to name the other participant only by initials",
            rationale="The narrative identifies another student",
        ),
        "Narrative is already redacted in the packet",
    ),
)


def _officer_with_two_adjacent_hearings():
    """One hearing officer holds 13:00-14:00 and 14:00-15:00 on 2026-10-07, and a
    third challenge is waiting in HEARING_REQUESTED."""
    create_state_rule("CA", **CA_RULE)
    district = create_district("SEND01", state_code="CA", name="Sending Unified")
    officer = create_hearing_officer(
        full_name="Hon. Lucia Berger", credential="EXTERNAL_CONTRACTOR"
    )
    student = create_student(
        district["id"],
        first_name="Uma",
        last_name="Castellanos",
        dob="2010-10-10",
        grade_level=11,
        has_iep=True,
        guardian_user_id="guardian-uma",
    )
    parent = make_parent_headers("guardian-uma")
    file_id = get_cumulative_file_id(student["id"])
    components = get_components(file_id)
    for component_type, pages in (("ACADEMIC", 60), ("HEALTH", 20), ("DISCIPLINE", 14)):
        collect_component(file_id, components[component_type]["id"], pages, 0)
        certify_component(file_id, components[component_type]["id"])

    set_clock("2026-09-15T00:00:00Z")
    amendments = []
    for component_type, fields, note in AMENDMENT_SPECS:
        amendment = create_amendment(
            student["id"], components[component_type]["id"], parent, **fields
        )
        decide_amendment(amendment["id"], "DENY", OFFICER_1, decision_note=note)
        request_hearing(amendment["id"], parent)
        amendments.append(amendment)

    first, second, third = amendments
    scheduled_first = schedule_hearing(
        first["id"], officer["id"], "2026-10-07T13:00:00Z", "2026-10-07T14:00:00Z"
    )
    scheduled_second = schedule_hearing(
        second["id"], officer["id"], "2026-10-07T14:00:00Z", "2026-10-07T15:00:00Z"
    )
    return officer, first, second, third, scheduled_first, scheduled_second


def _get_amendment(amendment_request_id):
    return validate_success(
        api_client.get_amendment_request(amendment_request_id, OFFICER_1)
    )


class TestHearingOfficerHalfOpenInterval:
    def test_a_hearing_starting_exactly_when_another_ends_is_accepted(self):
        """The officer's windows are half-open and unpadded, so 14:00 against a
        window that ends at 14:00 is not a conflict and both hearings stand.

        PRD: "Officer occupancy is checked with **half-open** semantics and no buffer at all: the new window conflicts with another `HEARING_SCHEDULED` window for the same officer only when the two intervals overlap treating each as including its start instant and excluding its end instant, so a hearing that starts exactly when another ends is accepted."

        Design: Difficulty/resource_temporal_overlap/hearing_officer_half_open_adjacency_allowed
        """
        _officer, first, second, _third, scheduled_first, scheduled_second = (
            _officer_with_two_adjacent_hearings()
        )

        assert_amendment_request(scheduled_second)
        assert scheduled_second["hearing_start_at"] == "2026-10-07T14:00:00.000Z"
        assert scheduled_second["hearing_duration_minutes"] == 60
        assert scheduled_second["status"] == "HEARING_SCHEDULED"
        assert scheduled_first["hearing_duration_minutes"] == 60
        assert _get_amendment(first["id"])["status"] == "HEARING_SCHEDULED"
        assert _get_amendment(second["id"])["status"] == "HEARING_SCHEDULED"

    def test_a_window_starting_one_minute_earlier_overlaps_and_is_refused(self):
        """13:59-14:30 genuinely overlaps both standing windows, and with the
        officer's day at 60 + 60 + 31 minutes the daily cap cannot be the reason,
        so the overlap rule alone must answer.

        PRD: "A conflict is refused with `ERR_OFFICER_DOUBLE_BOOKED`."

        Design: Difficulty/resource_temporal_overlap/hearing_officer_half_open_adjacency_allowed
        """
        officer, first, second, third, _sf, _ss = _officer_with_two_adjacent_hearings()

        response = api_client.create_hearing_schedule(
            third["id"],
            hearing_schedule_payload(
                officer["id"], "2026-10-07T13:59:00Z", "2026-10-07T14:30:00Z"
            ),
            OFFICER_1,
        )

        error = validate_error(response, "ERR_OFFICER_DOUBLE_BOOKED", 409)
        assert error["error_id"] != "ERR_OFFICER_DAILY_CAP_EXCEEDED", (
            "151 booked minutes are far below the 240-minute cap"
        )

        untouched = _get_amendment(third["id"])
        assert untouched["status"] == "HEARING_REQUESTED"
        assert untouched["hearing_officer_id"] is None
        assert untouched["hearing_start_at"] is None

        kept = _get_amendment(second["id"])
        assert kept["status"] == "HEARING_SCHEDULED"
        assert kept["hearing_start_at"] == "2026-10-07T14:00:00.000Z"
        assert kept["hearing_duration_minutes"] == 60
        assert _get_amendment(first["id"])["hearing_duration_minutes"] == 60
