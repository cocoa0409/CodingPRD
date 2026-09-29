"""Inclusive boundaries checked at the exact endpoint.

Three different quantities on three different endpoints: an instant to the
millisecond on the directory opt-out, summed minutes per officer per UTC date on
hearing scheduling, and integer instructional days against the discipline
threshold at packet snapshot.
"""
from test_helpers import (
    CLERK,
    OFFICER_1,
    api_client,
    assert_discipline_incident,
    assert_incident_counts_partition,
    assert_records_request,
    assert_student,
    certify_component,
    collect_component,
    create_amendment,
    create_district,
    create_hearing_officer,
    create_incident,
    create_records_request,
    create_state_rule,
    create_student,
    decide_amendment,
    directory_optout_payload,
    get_components,
    get_cumulative_file_id,
    hearing_schedule_payload,
    make_parent_headers,
    mark_ready_request,
    request_hearing,
    schedule_hearing,
    set_clock,
    validate_error,
    validate_request,
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
TX_RULE = dict(
    transfer_response_days=30,
    discipline_inclusion_mode="ALL_INCIDENTS",
    discipline_min_days_removed=10,
    include_pending_investigations=True,
    sped_requires_consent=False,
    amendment_hearing_days=45,
    destruction_min_age_years=7,
    directory_optout_grace_days=10,
    notification_wait_days=3,
)
DEADLINE = "2026-08-15T00:00:00.000Z"
ONE_MS_LATE = "2026-08-15T00:00:00.001Z"
OPTOUT_CATEGORIES = ["ADDRESS", "PHONE"]


def _get_student(student_id):
    return validate_success(api_client.get_student(student_id, CLERK))


def _two_students_sharing_one_deadline():
    """Both minors are created at the default clock under a fourteen-day grace
    window, so both carry directory_optout_deadline_at 2026-08-15T00:00:00.000Z."""
    create_state_rule("CA", **CA_RULE)
    district = create_district("SEND01", state_code="CA", name="Sending Unified")
    on_time = create_student(
        district["id"],
        first_name="Mira",
        last_name="Okonkwo",
        dob="2013-09-09",
        grade_level=6,
        has_iep=False,
        guardian_user_id="guardian-mira",
    )
    late = create_student(
        district["id"],
        first_name="Noor",
        last_name="Okonkwo",
        dob="2011-10-10",
        grade_level=9,
        has_iep=False,
        guardian_user_id="guardian-noor",
    )
    assert on_time["directory_optout_deadline_at"] == DEADLINE
    assert late["directory_optout_deadline_at"] == DEADLINE
    return on_time, late


class TestDirectoryOptoutDeadlineToTheMillisecond:
    def test_an_optout_filed_at_exactly_the_deadline_takes_effect(self):
        """Parked on the deadline instant itself, the filing is accepted, the
        received instant is that same instant, and the opt-out becomes
        effective with its categories stored in the fixed directory order.

        PRD: "The boundary is inclusive to the millisecond: at exactly the deadline the opt-out takes effect, and one millisecond later the filing is refused with `ERR_OPTOUT_WINDOW_CLOSED` and `directory_optout_effective` remains false."

        Design: Difficulty/boundary_precision_check/directory_optout_deadline_inclusive_millisecond
        """
        on_time, _late = _two_students_sharing_one_deadline()
        set_clock(DEADLINE)

        updated = validate_success(
            api_client.update_directory_optout(
                on_time["id"],
                directory_optout_payload(OPTOUT_CATEGORIES),
                make_parent_headers("guardian-mira"),
            )
        )

        assert_student(updated)
        assert updated["directory_optout_deadline_at"] == DEADLINE
        assert updated["directory_optout_received_at"] == DEADLINE
        assert updated["directory_optout_effective"] is True
        assert updated["directory_optout_categories"] == OPTOUT_CATEGORIES

        reread = _get_student(on_time["id"])
        assert reread["directory_optout_effective"] is True
        assert reread["directory_optout_categories"] == OPTOUT_CATEGORIES

    def test_the_same_payload_one_millisecond_later_is_refused(self):
        """One millisecond past the identical deadline the identical payload from
        the identical role is refused, and nothing is recorded on the student.

        PRD: "The rights-holder supplies `directory_optout_categories`, a non-empty list drawn from `NAME`, `ADDRESS`, `PHONE`, `PHOTO`, `HONORS`, and `SPORTS_PARTICIPATION`; the server stores it in that fixed order regardless of the order supplied, sets `directory_optout_received_at` to the current logical clock instant, and sets `directory_optout_effective` true exactly when that instant is at or before `directory_optout_deadline_at`."

        Design: Difficulty/boundary_precision_check/directory_optout_deadline_inclusive_millisecond
        """
        on_time, late = _two_students_sharing_one_deadline()
        set_clock(DEADLINE)
        validate_success(
            api_client.update_directory_optout(
                on_time["id"],
                directory_optout_payload(OPTOUT_CATEGORIES),
                make_parent_headers("guardian-mira"),
            )
        )
        set_clock(ONE_MS_LATE)

        response = api_client.update_directory_optout(
            late["id"],
            directory_optout_payload(OPTOUT_CATEGORIES),
            make_parent_headers("guardian-noor"),
        )

        validate_error(response, "ERR_OPTOUT_WINDOW_CLOSED", 422)

        refused = _get_student(late["id"])
        assert refused["directory_optout_effective"] is False
        assert refused["directory_optout_received_at"] is None
        assert refused["directory_optout_categories"] == []
        assert _get_student(on_time["id"])["directory_optout_effective"] is True


def _officer_day_at_exactly_the_cap():
    """One officer holds 180 minutes on amendment A and 60 on amendment B on
    2026-10-06, so their day sums to exactly the four-hour cap."""
    create_state_rule("CA", **CA_RULE)
    district = create_district("SEND01", state_code="CA", name="Sending Unified")
    officer = create_hearing_officer(
        full_name="Hon. Priya Raman", credential="ADMINISTRATIVE_LAW_JUDGE"
    )
    student = create_student(
        district["id"],
        first_name="Omar",
        last_name="Fontaine",
        dob="2010-01-15",
        grade_level=11,
        has_iep=False,
        guardian_user_id="guardian-omar",
    )
    parent = make_parent_headers("guardian-omar")
    file_id = get_cumulative_file_id(student["id"])
    components = get_components(file_id)
    for component_type, pages in (("ACADEMIC", 40), ("HEALTH", 12)):
        collect_component(file_id, components[component_type]["id"], pages, 0)
        certify_component(file_id, components[component_type]["id"])

    set_clock("2026-09-15T00:00:00Z")
    amendment_a = create_amendment(
        student["id"],
        components["ACADEMIC"]["id"],
        parent,
        contested_field="attendance_total_absences",
        requested_change="Reduce recorded absences from 30 to 12",
        rationale="Doctor notes were submitted for 18 days",
    )
    amendment_b = create_amendment(
        student["id"],
        components["HEALTH"]["id"],
        parent,
        contested_field="immunization_exemption_status",
        requested_change="Record the religious exemption on file",
        rationale="Exemption form was filed in 2024",
    )
    decide_amendment(amendment_a["id"], "DENY", OFFICER_1, decision_note="Attendance ledger is accurate")
    decide_amendment(amendment_b["id"], "DENY", OFFICER_1, decision_note="No exemption form located")
    request_hearing(amendment_a["id"], parent)
    request_hearing(amendment_b["id"], parent)

    scheduled_a = schedule_hearing(
        amendment_a["id"], officer["id"], "2026-10-06T09:00:00Z", "2026-10-06T12:00:00Z"
    )
    scheduled_b = schedule_hearing(
        amendment_b["id"], officer["id"], "2026-10-06T13:00:00Z", "2026-10-06T14:00:00Z"
    )
    return officer, amendment_a, amendment_b, scheduled_a, scheduled_b


def _get_amendment(amendment_request_id):
    return validate_success(
        api_client.get_amendment_request(amendment_request_id, OFFICER_1)
    )


class TestHearingOfficerDailyMinuteCap:
    def test_exactly_two_hundred_and_forty_minutes_in_one_officer_day_is_accepted(self):
        """180 plus 60 on the same UTC date is exactly the cap, so both hearings
        stand scheduled with their derived durations.

        PRD: "Next the officer's daily load: the sum of `hearing_duration_minutes` for that officer across one UTC calendar date, including the window being booked, may not exceed 240 minutes — four hours; exactly 240 is accepted and 241 is refused with `ERR_OFFICER_DAILY_CAP_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/officer_daily_minute_cap_exact_240
        """
        _officer, amendment_a, amendment_b, scheduled_a, scheduled_b = (
            _officer_day_at_exactly_the_cap()
        )

        assert scheduled_a["hearing_duration_minutes"] == 180
        assert scheduled_b["hearing_duration_minutes"] == 60
        assert scheduled_a["status"] == "HEARING_SCHEDULED"
        assert scheduled_b["status"] == "HEARING_SCHEDULED"
        assert _get_amendment(amendment_a["id"])["hearing_duration_minutes"] == 180
        assert _get_amendment(amendment_b["id"])["hearing_duration_minutes"] == 60

    def test_a_reschedule_that_would_make_two_hundred_and_forty_one_is_refused(self):
        """Rebooking B one minute longer takes the officer's day to 241 with the
        replaced window excluded from the sum, so the cap is the discriminator
        rather than double counting, and B keeps its 14:00 end.

        PRD: "On a reschedule, the window being replaced is excluded from that sum, and the previously reserved interval is released before the new interval is tested, so rescheduling onto the identical slot with the identical officer is always allowed."

        Design: Difficulty/boundary_precision_check/officer_daily_minute_cap_exact_240
        """
        officer, amendment_a, amendment_b, _a, _b = _officer_day_at_exactly_the_cap()

        response = api_client.create_hearing_schedule(
            amendment_b["id"],
            hearing_schedule_payload(
                officer["id"], "2026-10-06T13:00:00Z", "2026-10-06T14:01:00Z"
            ),
            OFFICER_1,
        )

        validate_error(response, "ERR_OFFICER_DAILY_CAP_EXCEEDED", 409)

        kept_a = _get_amendment(amendment_a["id"])
        kept_b = _get_amendment(amendment_b["id"])
        assert kept_a["hearing_duration_minutes"] == 180
        assert kept_b["hearing_duration_minutes"] == 60
        assert kept_b["hearing_end_at"] == "2026-10-06T14:00:00.000Z"
        assert kept_a["status"] == "HEARING_SCHEDULED"
        assert kept_b["status"] == "HEARING_SCHEDULED"


THREE_SUSPENSIONS = (
    dict(
        incident_date="2026-02-02",
        action_type="SUSPENSION",
        days_removed=9,
        incident_status="SUSTAINED",
        adjudicated_by_court=False,
        description="Nine day removal",
    ),
    dict(
        incident_date="2026-02-09",
        action_type="SUSPENSION",
        days_removed=10,
        incident_status="SUSTAINED",
        adjudicated_by_court=False,
        description="Ten day removal",
    ),
    dict(
        incident_date="2026-02-16",
        action_type="SUSPENSION",
        days_removed=11,
        incident_status="SUSTAINED",
        adjudicated_by_court=False,
        description="Eleven day removal",
    ),
)


def _three_suspensions_straddling_the_threshold():
    """A CA responding district with a ten-day threshold answers a TX request
    for a student holding suspensions of 9, 10 and 11 instructional days, over a
    twenty-page packet."""
    create_state_rule("CA", **CA_RULE)
    create_state_rule("TX", **TX_RULE)
    sending = create_district("SEND01", state_code="CA", name="Sending Unified")
    receiving = create_district("RECV01", state_code="TX", name="Receiving Unified")
    student = create_student(
        sending["id"],
        first_name="Pia",
        last_name="Strand",
        dob="2011-11-11",
        grade_level=9,
        has_iep=False,
        guardian_user_id="guardian-pia",
    )
    file_id = get_cumulative_file_id(student["id"])
    components = get_components(file_id)
    for component_type, pages in (("ACADEMIC", 10), ("HEALTH", 4), ("DISCIPLINE", 6)):
        collect_component(file_id, components[component_type]["id"], pages, 0)
        certify_component(file_id, components[component_type]["id"])

    incidents = [create_incident(student["id"], **spec) for spec in THREE_SUSPENSIONS]
    request = create_records_request(
        student["id"],
        receiving["id"],
        sending["id"],
        authorization_reference="ENR-2026-0020",
    )
    validate_request(request["id"])
    return student, file_id, request, incidents


def _get_incident(incident_id):
    return validate_success(api_client.get_discipline_incident(incident_id, CLERK))


class TestDisciplineThresholdIsInclusive:
    def test_the_ten_day_suspension_meets_the_threshold_and_the_nine_day_one_does_not(self):
        """With discipline_min_days_removed at 10 the comparison is greater than
        or equal, so the ten-day and eleven-day suspensions leave the state and
        only the nine-day one is withheld.

        PRD: "Under `SUSPENSIONS_AND_EXPULSIONS` an `EXPULSION` always transfers, a `SUSPENSION` transfers exactly when its `days_removed` is greater than or equal to the rule's `discipline_min_days_removed` — a ten-day threshold means a ten-day suspension does transfer and a nine-day one does not — and a `DETENTION` or `BEHAVIOR_PLAN` does not transfer."

        Design: Difficulty/boundary_precision_check/discipline_min_days_removed_inclusive
        """
        _student, file_id, request, incidents = (
            _three_suspensions_straddling_the_threshold()
        )
        nine, ten, eleven = incidents

        mark_ready_request(request["id"], file_id)

        stamped_nine = _get_incident(nine["id"])
        stamped_ten = _get_incident(ten["id"])
        stamped_eleven = _get_incident(eleven["id"])
        for stamped in (stamped_nine, stamped_ten, stamped_eleven):
            assert_discipline_incident(stamped)
        assert stamped_nine["transfer_inclusion_state"] == "WITHHELD"
        assert stamped_ten["transfer_inclusion_state"] == "INCLUDED", (
            "a ten-day suspension meets a ten-day threshold"
        )
        assert stamped_eleven["transfer_inclusion_state"] == "INCLUDED"

    def test_the_snapshot_counts_two_included_one_withheld_and_three_for_the_receiver(self):
        """The governing CA pass counts two of the three incidents while the
        advisory TX pass counts all three, and the twenty-page packet is frozen
        ready for release.

        PRD: "Under `ALL_INCIDENTS` every surviving incident transfers."

        Design: Difficulty/boundary_precision_check/discipline_min_days_removed_inclusive
        """
        _student, file_id, request, _incidents = (
            _three_suspensions_straddling_the_threshold()
        )

        ready = mark_ready_request(request["id"], file_id)

        assert_records_request(ready)
        assert ready["included_incident_count"] == 2
        assert ready["withheld_incident_count"] == 1
        assert_incident_counts_partition(ready, 3)
        assert ready["receiving_state_inclusion_count"] == 3
        assert ready["packet_page_count"] == 20
        assert ready["status"] == "READY_FOR_RELEASE"
