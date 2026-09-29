"""One request, four hops, no clock movement: the consistency model promises that a
disputed evidence axis has already denied an enrolment, released its seat, promoted the
waitlist behind it and rebalanced every derived counter by the time the response is
read back.
"""
from test_helpers import (
    api_client,
    confirm_seat,
    evidence_payload,
    get_success_data,
    hold_seat,
    mint_determination,
    new_active_rule,
    new_course,
    new_student,
    read_section,
    setup_open_section,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import (
    make_assessment_staff_headers,
    make_registrar_headers,
)


def _read_registration(registration_id):
    return get_success_data(
        api_client.get_registration(registration_id, make_registrar_headers())
    )


def _read_determination(determination_id):
    return get_success_data(
        api_client.get_placement_determination(
            determination_id, make_assessment_staff_headers()
        )
    )


# --------------------------------------------------------------------------- #
# a_disputed_evidence_axis_denies_promotes_and_rebalances_before_the_response_returns
# --------------------------------------------------------------------------- #


def _setup_one_seat_one_enrolment_and_one_waitlisted_student():
    """A single-seat section of a course two students are placed into: the first takes
    the seat, the second waits behind them.

    The logical clock is never moved anywhere in this setup or in the tests that use it,
    so nothing here can be attributed to time passing.
    """
    course = new_course(
        course_code="MATH-050",
        title="Pre-Algebra",
        subject_area="MATH",
        level_rank=50,
        units=5.0,
    )
    new_active_rule(
        course["id"],
        subject_area="MATH",
        measure_type="TRANSCRIPT_GPA",
        min_hs_gpa=2.00,
        priority_rank=10,
        effective_from="2026-07-01T00:00:00Z",
        version_label="V1",
    )
    section = setup_open_section(
        course["id"],
        term_code="2026FA",
        room_code="R797",
        meets_start_at="2026-09-02T10:00:00Z",
        meets_end_at="2026-09-02T11:00:00Z",
        seat_capacity=1,
    )

    students = {}
    determinations = {}
    registrations = {}
    for label, number, code in (("first", "SC1", "WHITE"), ("second", "SC2", "HISPANIC")):
        students[label] = new_student(
            student_number=number,
            full_name=f"Student C {label.title()}",
            race_ethnicity_code=code,
            hs_gpa=2.50,
            hs_transcript_status="VERIFIED",
            transcript_recorded_at="2025-06-01T00:00:00Z",
        )
        determinations[label] = mint_determination(
            students[label]["id"], subject_area="MATH"
        )
        assert determinations[label]["placed_course_id"] == course["id"]
        registrations[label] = confirm_seat(
            hold_seat(students[label]["id"], section["id"])["id"]
        )

    assert registrations["first"]["state"] == "ENROLLED"
    assert registrations["second"]["state"] == "WAITLISTED"

    before = read_section(section["id"])
    assert before["seats_taken"] == 1
    assert before["seats_held"] == 0
    assert before["waitlist_count"] == 1
    assert before["available_seats"] == 0

    return {
        "course": course,
        "section": section,
        "students": students,
        "determinations": determinations,
        "registrations": registrations,
    }


def _dispute(determination_id):
    return validate_success(
        api_client.set_determination_evidence(
            determination_id,
            evidence_payload(
                "DISPUTED",
                note="Transcript authenticity challenged by the receiving college.",
            ),
            make_assessment_staff_headers(),
        )
    )


def test_the_dispute_denies_the_enrolment_and_promotes_the_waitlist_in_one_request():
    """"Landing on `DISPUTED` -- by direct action or by cascade -- has consequences for
    enrolment. Every registration in state `PENDING`, `ENROLLED` or `WAITLISTED` whose
    section belongs to the determination's `placed_course_id` or its `coreq_course_id`
    moves to `DENIED` with `denial_reason` set to `EVIDENCE_DISPUTED`; the seats those rows
    held are released; any override those rows had consumed returns from `CONSUMED` to
    `ISSUED`; and each affected section then promotes its waitlist in `created_at`
    ascending order."  And "Consistency is immediate: a single request completes all of its
    downstream effects before it returns, and there is no deferred reconciliation", so
    every one of those effects is readable next, with the clock exactly where it was.

    Design: Corner/Consistency Model/a_disputed_evidence_axis_denies_promotes_and_rebalances_before_the_response_returns
    """
    setup = _setup_one_seat_one_enrolment_and_one_waitlisted_student()

    disputed = _dispute(setup["determinations"]["first"]["id"])
    assert disputed["evidence_state"] == "DISPUTED"
    # "The finalize action touches only the first; the evidence action touches only the
    # second."
    assert disputed["placement_state"] == "PROVISIONAL"

    denied = _read_registration(setup["registrations"]["first"]["id"])
    assert denied["state"] == "DENIED"
    assert denied["denial_reason"] == "EVIDENCE_DISPUTED"

    promoted = _read_registration(setup["registrations"]["second"]["id"])
    assert promoted["state"] == "ENROLLED"

    # The promoted student's own placement was never in question.
    untouched = _read_determination(setup["determinations"]["second"]["id"])
    assert untouched["evidence_state"] == "UNVERIFIED"
    assert untouched["placement_state"] == "PROVISIONAL"


def test_the_freed_seat_is_reoccupied_without_the_ledger_showing_an_intermediate_state():
    """"For any section, the sum of `seats_taken`, `seats_held` and `waitlist_count` plus
    the number of its registrations in state `DENIED` or `DROPPED` equals the total number
    of registrations attached to that section."  Because the denial and the promotion are
    hops of one request, the released seat is already re-occupied when the ledger is next
    read: `seats_taken` never dips to zero for any observer, and "`seats_taken` always
    equals the number of that section's registrations in state `ENROLLED` or `COMPLETED`".

    Design: Corner/Consistency Model/a_disputed_evidence_axis_denies_promotes_and_rebalances_before_the_response_returns
    """
    setup = _setup_one_seat_one_enrolment_and_one_waitlisted_student()
    section_id = setup["section"]["id"]

    _dispute(setup["determinations"]["first"]["id"])

    after = read_section(section_id)
    assert after["seats_taken"] == 1
    assert after["seats_held"] == 0
    assert after["waitlist_count"] == 0
    assert after["available_seats"] == 0

    rows, meta = validate_paginated(
        api_client.list_section_registrations(section_id, make_registrar_headers())
    )
    assert meta["total_count"] == 2
    states = {row["id"]: row["state"] for row in rows}
    assert states[setup["registrations"]["first"]["id"]] == "DENIED"
    assert states[setup["registrations"]["second"]["id"]] == "ENROLLED"

    ledger = (
        after["seats_taken"]
        + after["seats_held"]
        + after["waitlist_count"]
        + sum(1 for row in rows if row["state"] in {"DENIED", "DROPPED"})
    )
    assert ledger == meta["total_count"]
    assert after["seats_taken"] == sum(
        1 for row in rows if row["state"] in {"ENROLLED", "COMPLETED"}
    )
