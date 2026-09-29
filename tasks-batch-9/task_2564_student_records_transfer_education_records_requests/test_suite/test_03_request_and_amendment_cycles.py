"""Cycles and self-loops in the two lifecycles that are not linear.

A records request may traverse ASSEMBLING -> READY_FOR_RELEASE -> ASSEMBLING as
often as components move, and an amendment challenge may reschedule its hearing
on a HEARING_SCHEDULED self-loop before running on to the terminal state that
annotates the record.
"""
from test_helpers import (
    api_client,
    assert_amendment_request,
    assert_cumulative_file,
    assert_file_component,
    assert_page_custody_identity,
    assert_records_request,
    certify_component,
    create_amendment,
    create_district,
    create_hearing_officer,
    create_state_rule,
    create_student,
    collect_component,
    decide_amendment,
    exclude_component,
    file_statement,
    get_components,
    get_cumulative_file_id,
    get_file,
    make_parent_headers,
    make_records_clerk_headers,
    make_records_officer_headers,
    mark_ready_request,
    reinstate_component,
    request_hearing,
    schedule_hearing,
    set_clock,
    setup_transfer_scenario,
    validate_success,
)

CLERK = make_records_clerk_headers()
OFFICER_1 = make_records_officer_headers("officer-1")
OFFICER_2 = make_records_officer_headers("officer-2")

THREE_COMPONENT_PAGES = {"ACADEMIC": 120, "HEALTH": 34, "DISCIPLINE": 18}
THREE_COMPONENT_REDACTIONS = {"HEALTH": 4, "DISCIPLINE": 2}


def _request_ready_once():
    """Take the first packet snapshot on a three-component file worth 166
    disclosable certified pages."""
    scenario = setup_transfer_scenario(
        responding_state="CA",
        requesting_state="TX",
        student_overrides={
            "first_name": "Fatima",
            "last_name": "Rowe",
            "dob": "2011-02-14",
            "grade_level": 9,
            "guardian_user_id": "guardian-fatima",
        },
        pages=THREE_COMPONENT_PAGES,
        redactions=THREE_COMPONENT_REDACTIONS,
        certify=("ACADEMIC", "HEALTH", "DISCIPLINE"),
        request_overrides={"authorization_reference": "ENR-2026-0010"},
        validate=True,
    )
    scenario["request"] = mark_ready_request(
        scenario["request"]["id"], scenario["file_id"]
    )
    return scenario


def _cycle_once(scenario, exclusion_reason):
    """Exclude the certified DISCIPLINE component, reinstate it, re-certify it,
    and take a fresh snapshot against the file's new version."""
    file_id = scenario["file_id"]
    discipline_id = scenario["components"]["DISCIPLINE"]["id"]
    exclude_component(file_id, discipline_id, exclusion_reason)
    reinstate_component(file_id, discipline_id, CLERK)
    certify_component(file_id, discipline_id)
    scenario["request"] = mark_ready_request(scenario["request"]["id"], file_id)
    return scenario


class TestRecordsRequestReopenCycle:
    def test_exclusion_reopens_the_request_and_voids_the_packet(self):
        """Excluding the certified DISCIPLINE component drops the file out of
        COMPLETE, which pushes the request back to ASSEMBLING, raises
        reopen_count to 1 and nulls every packet counter.

        PRD: "Whenever the student's cumulative file leaves `COMPLETE` — by exclusion of a required component, by reinstatement that leaves a required type uncertified, or by an amendment that decertifies one — every records request for that student in `READY_FOR_RELEASE` moves `READY_FOR_RELEASE → ASSEMBLING`, its `reopen_count` grows by one, its `packet_status` becomes `VOID`, its `packet_page_count`, `included_incident_count`, `withheld_incident_count`, and `receiving_state_inclusion_count` are all nulled, and every discipline incident of the student returns to `NOT_EVALUATED`."

        Design: Difficulty/non_linear_state_machine/records_request_reopen_cycle
        """
        scenario = _request_ready_once()
        assert scenario["request"]["packet_status"] == "SNAPSHOT"
        assert scenario["request"]["packet_page_count"] == 166

        exclude_component(
            scenario["file_id"],
            scenario["components"]["DISCIPLINE"]["id"],
            "OTHER_STUDENT_INFO",
        )

        data = validate_success(
            api_client.get_records_request(scenario["request"]["id"], OFFICER_1)
        )
        assert_records_request(data)
        assert data["status"] == "ASSEMBLING"
        assert data["reopen_count"] == 1
        assert data["packet_status"] == "VOID"
        assert data["packet_page_count"] is None
        assert data["included_incident_count"] is None
        assert data["withheld_incident_count"] is None
        assert data["receiving_state_inclusion_count"] is None

    def test_two_full_cycles_leave_reopen_count_at_exactly_two(self):
        """The request enters ASSEMBLING three times and READY_FOR_RELEASE three
        times; each fresh snapshot supersedes the void one and restores the same
        166-page packet.

        PRD: "The cycle `ASSEMBLING → READY_FOR_RELEASE → ASSEMBLING` may run any number of times, and each fresh snapshot supersedes the void one."

        Design: Difficulty/non_linear_state_machine/records_request_reopen_cycle
        """
        scenario = _request_ready_once()
        _cycle_once(scenario, "OTHER_STUDENT_INFO")
        assert scenario["request"]["reopen_count"] == 1
        _cycle_once(scenario, "DUPLICATE_OF_TRANSCRIPT")

        data = validate_success(
            api_client.get_records_request(scenario["request"]["id"], OFFICER_1)
        )
        assert data["status"] == "READY_FOR_RELEASE"
        assert data["reopen_count"] == 2
        assert data["packet_status"] == "SNAPSHOT"
        assert data["packet_page_count"] == 166

    def test_reinstated_component_returns_to_certified_with_no_reason(self):
        """After two exclusion/reinstatement rounds the component is CERTIFIED
        again with its exclusion_reason cleared, and the file is back at 100.0.

        PRD: "Targeting `COLLECTED` against an `EXCLUDED` component moves it `EXCLUDED → COLLECTED`, clears `exclusion_reason` back to null, and leaves `page_count` and `redacted_page_count` unchanged unless the caller supplies replacements; on the parent, the component's pages move back out of `excluded_page_count` and into `included_page_count`, restoring the page-custody identity to precisely the figures it held before the exclusion."

        Design: Difficulty/non_linear_state_machine/records_request_reopen_cycle
        """
        scenario = _request_ready_once()
        _cycle_once(scenario, "OTHER_STUDENT_INFO")
        _cycle_once(scenario, "DUPLICATE_OF_TRANSCRIPT")

        components = get_components(scenario["file_id"])
        discipline = components["DISCIPLINE"]
        assert_file_component(discipline)
        assert discipline["status"] == "CERTIFIED"
        assert discipline["exclusion_reason"] is None
        assert discipline["page_count"] == 18
        assert discipline["redacted_page_count"] == 2

        data = get_file(scenario["file_id"])
        assert_cumulative_file(data)
        assert data["assembly_status"] == "COMPLETE"
        assert data["completeness_pct"] == 100.0
        assert_page_custody_identity(data)


def _denied_amendment_with_two_officers():
    """Deny an amendment against the certified ACADEMIC component at
    2026-09-15T00:00:00Z, so the thirty-day hearing window closes on 2026-10-15,
    and register two ACTIVE hearing officers to reschedule between."""
    create_state_rule("CA")
    sending = create_district("SEND01", "CA", name="Sending Unified")
    officer_a = create_hearing_officer(
        full_name="Hon. Marta Vale", credential="ADMINISTRATIVE_LAW_JUDGE"
    )
    officer_b = create_hearing_officer(
        full_name="Dr. Owen Pratt", credential="DISTRICT_DESIGNEE"
    )
    student = create_student(
        sending["id"],
        first_name="Gus",
        last_name="Halloran",
        dob="2010-04-30",
        grade_level=10,
        has_iep=False,
        guardian_user_id="guardian-gus",
    )
    parent_headers = make_parent_headers("guardian-gus")
    file_id = get_cumulative_file_id(student["id"])
    components = get_components(file_id)
    for ctype, page_count, redacted in (
        ("ACADEMIC", 120, 0),
        ("HEALTH", 34, 4),
        ("DISCIPLINE", 18, 2),
    ):
        collect_component(file_id, components[ctype]["id"], page_count, redacted)
        certify_component(file_id, components[ctype]["id"])

    set_clock("2026-09-15T00:00:00Z")
    amendment = create_amendment(
        student["id"],
        components["ACADEMIC"]["id"],
        parent_headers,
        contested_field="grade_grade_9_algebra",
        requested_change="Change the recorded grade from F to Incomplete",
        rationale="The course was dropped before the withdrawal deadline",
    )
    amendment = decide_amendment(
        amendment["id"],
        "DENY",
        OFFICER_1,
        decision_note="Grade is accurate per teacher gradebook",
    )
    request_hearing(amendment["id"], parent_headers)
    return {
        "student": student,
        "file_id": file_id,
        "components": components,
        "amendment": amendment,
        "parent_headers": parent_headers,
        "officer_a": officer_a,
        "officer_b": officer_b,
    }


class TestAmendmentHearingBranchAndReschedule:
    def test_denial_fork_pins_the_thirty_calendar_day_hearing_window(self):
        """DENY out of SUBMITTED stamps denied_at and derives hearing_due_at from
        the governing state rule's thirty calendar days at the identical time of
        day, rather than ending the challenge at AMENDED.

        PRD: "A denial moves the challenge `SUBMITTED → DENIED`, sets `denied_at` to the current logical clock instant, and computes `hearing_due_at` as that instant advanced by the `amendment_hearing_days` of the state rule governing the **student's** district, at the identical time of day."

        Design: Difficulty/non_linear_state_machine/amendment_hearing_branch_and_reschedule
        """
        scenario = _denied_amendment_with_two_officers()

        data = validate_success(
            api_client.get_amendment_request(scenario["amendment"]["id"], OFFICER_1)
        )
        assert_amendment_request(data)
        assert data["status"] == "HEARING_REQUESTED"
        assert data["denied_at"] == "2026-09-15T00:00:00.000Z"
        assert data["hearing_due_at"] == "2026-10-15T00:00:00.000Z"
        assert data["initial_decided_by_user_id"] == "officer-1"

    def test_rescheduling_is_a_self_loop_that_recomputes_the_duration(self):
        """A second scheduling call from HEARING_SCHEDULED replaces both the
        officer and the window, moving hearing_duration_minutes from 60 to 90
        without leaving the state.

        PRD: "The challenge must be in `HEARING_REQUESTED` or `HEARING_SCHEDULED` — a call from a status outside that pair is refused with `ERR_HEARING_NOT_SCHEDULED` — so a second scheduling call is a legitimate reschedule rather than an error, and that self-loop on `HEARING_SCHEDULED` may run as often as the statutory window allows."

        Design: Difficulty/non_linear_state_machine/amendment_hearing_branch_and_reschedule
        """
        scenario = _denied_amendment_with_two_officers()
        amendment_id = scenario["amendment"]["id"]

        first = schedule_hearing(
            amendment_id,
            scenario["officer_a"]["id"],
            "2026-10-01T14:00:00Z",
            "2026-10-01T15:00:00Z",
        )
        assert first["status"] == "HEARING_SCHEDULED"
        assert first["hearing_officer_id"] == scenario["officer_a"]["id"]
        assert first["hearing_duration_minutes"] == 60

        second = schedule_hearing(
            amendment_id,
            scenario["officer_b"]["id"],
            "2026-10-05T09:00:00Z",
            "2026-10-05T10:30:00Z",
        )
        assert second["status"] == "HEARING_SCHEDULED"
        assert second["hearing_officer_id"] == scenario["officer_b"]["id"]
        assert second["hearing_start_at"] == "2026-10-05T09:00:00.000Z"
        assert second["hearing_duration_minutes"] == 90

    def test_statement_of_disagreement_terminal_state_repaginates_the_component(self):
        """After the hearing is decided by the second officer the challenge is
        UPHELD, and the statement filing adds exactly one page to the contested
        component and re-derives the parent file.

        PRD: "On success the text is stored, `statement_filed_at` is set to the current logical clock instant, and the challenge moves `UPHELD → STATEMENT_FILED`, which is terminal."

        Design: Difficulty/non_linear_state_machine/amendment_hearing_branch_and_reschedule
        """
        scenario = _denied_amendment_with_two_officers()
        amendment_id = scenario["amendment"]["id"]
        schedule_hearing(
            amendment_id,
            scenario["officer_a"]["id"],
            "2026-10-01T14:00:00Z",
            "2026-10-01T15:00:00Z",
        )
        schedule_hearing(
            amendment_id,
            scenario["officer_b"]["id"],
            "2026-10-05T09:00:00Z",
            "2026-10-05T10:30:00Z",
        )
        set_clock("2026-10-05T10:30:00Z")
        upheld = decide_amendment(
            amendment_id, "DENY", OFFICER_2, decision_note="Hearing held; record upheld"
        )
        assert upheld["status"] == "UPHELD"
        assert upheld["hearing_decided_by_user_id"] == "officer-2"

        data = file_statement(
            amendment_id,
            scenario["parent_headers"],
            statement_text=(
                "The family disagrees with the algebra grade and the district's "
                "refusal to amend it."
            ),
        )
        assert data["status"] == "STATEMENT_FILED"
        assert data["statement_filed_at"] == "2026-10-05T10:30:00.000Z"

        academic = get_components(scenario["file_id"])["ACADEMIC"]
        assert academic["statement_of_disagreement_present"] is True
        assert academic["page_count"] == 121
        assert academic["status"] == "CERTIFIED"

        file_data = get_file(scenario["file_id"])
        assert file_data["total_page_count"] == 173
        assert file_data["disclosable_page_count"] == 167
        assert file_data["completeness_pct"] == 100.0
