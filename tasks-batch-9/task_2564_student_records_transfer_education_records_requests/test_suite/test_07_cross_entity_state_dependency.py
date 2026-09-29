"""Refusals owed entirely to the state of a different entity.

In each scenario the target resource is in the right state and the payload is
sound; what blocks the call is another row — an incomplete cumulative file, or a
records request that is still open — and curing only that other row flips the
identical call to success.
"""
from test_helpers import (
    CLERK,
    COMPLIANCE,
    OFFICER_1,
    api_client,
    assert_cumulative_file,
    assert_file_component,
    assert_page_custody_identity,
    assert_records_request,
    assert_retention_schedule,
    certify_component,
    collect_component,
    complete_withdrawal,
    create_district,
    create_records_request,
    create_state_rule,
    create_student,
    create_withdrawal,
    deny_request,
    destruction_payload,
    get_components,
    get_cumulative_file_id,
    get_disclosure_log,
    get_file,
    get_retention_schedules,
    mark_ready_payload,
    mark_ready_request,
    run_sweep,
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
PAGES = (("ACADEMIC", 120, 0), ("HEALTH", 34, 4), ("DISCIPLINE", 18, 2))


def _two_districts():
    create_state_rule("CA", **CA_RULE)
    create_state_rule("TX", **TX_RULE)
    sending = create_district("SEND01", state_code="CA", name="Sending Unified")
    receiving = create_district("RECV01", state_code="TX", name="Receiving Unified")
    return sending, receiving


def _get_request(request_id):
    return validate_success(api_client.get_records_request(request_id, OFFICER_1))


def _file_and_certified_components(student_id, certify_all=True):
    """Collect all three required components and certify either all of them or
    only the first two, leaving DISCIPLINE merely COLLECTED."""
    file_id = get_cumulative_file_id(student_id)
    components = get_components(file_id)
    for component_type, pages, redactions in PAGES:
        component_id = components[component_type]["id"]
        collect_component(file_id, component_id, pages, redactions)
        if certify_all or component_type != "DISCIPLINE":
            certify_component(file_id, component_id)
    return file_id, components


def _request_assembling_over_an_incomplete_file():
    """The request is legitimately in ASSEMBLING and the token is current; only
    the file lags, with two of three required components certified."""
    sending, receiving = _two_districts()
    student = create_student(
        sending["id"],
        first_name="Quinn",
        last_name="Delacroix",
        dob="2012-02-29",
        grade_level=8,
        has_iep=False,
        guardian_user_id="guardian-quinn",
    )
    file_id, components = _file_and_certified_components(student["id"], certify_all=False)
    request = create_records_request(
        student["id"],
        receiving["id"],
        sending["id"],
        authorization_reference="ENR-2026-0030",
    )
    validate_request(request["id"])
    assert _get_request(request["id"])["status"] == "ASSEMBLING"
    return student, file_id, components, request


class TestMarkReadyDependsOnTheCumulativeFile:
    def test_mark_ready_is_refused_while_the_file_is_still_in_assembly(self):
        """Nothing about the request is wrong — it is ASSEMBLING and the token is
        the file's current version — yet the snapshot is refused because the
        other entity holds only two of its three required certifications.

        PRD: "Then the cross-entity condition: the student's cumulative file must be in `COMPLETE`, meaning every required component is `CERTIFIED`, and a file in `IN_ASSEMBLY` is refused with `ERR_FILE_NOT_COMPLETE`."

        Design: Difficulty/cross_entity_state_dependency/mark_ready_requires_complete_cumulative_file
        """
        _student, file_id, _components, request = (
            _request_assembling_over_an_incomplete_file()
        )
        before = get_file(file_id)
        assert before["assembly_status"] == "IN_ASSEMBLY"

        response = api_client.mark_ready_records_request(
            request["id"], mark_ready_payload(before["version"]), OFFICER_1
        )

        validate_error(response, "ERR_FILE_NOT_COMPLETE")

        refused = _get_request(request["id"])
        assert_records_request(refused)
        assert refused["status"] == "ASSEMBLING"
        assert refused["packet_status"] == "NONE"

        blocking = get_file(file_id)
        assert_cumulative_file(blocking)
        assert blocking["certified_component_count"] == 2
        assert blocking["completeness_pct"] == 66.7

    def test_certifying_the_third_component_flips_the_identical_call_to_success(self):
        """Certifying DISCIPLINE changes only the file, taking it to 100.0 and
        COMPLETE; the same mark-ready call then freezes a 166-page packet on a
        request that never left ASSEMBLING in between.

        PRD: "Its `completeness_pct` is 100 multiplied by that certified count, divided by the number of required component types, rounded half up to one decimal place — so a file with four required types and three certified reads 75.0, a three-type file with one certified reads 33.3, and the same file with two certified reads 66.7."

        Design: Difficulty/cross_entity_state_dependency/mark_ready_requires_complete_cumulative_file
        """
        _student, file_id, components, request = (
            _request_assembling_over_an_incomplete_file()
        )
        validate_error(
            api_client.mark_ready_records_request(
                request["id"], mark_ready_payload(get_file(file_id)["version"]), OFFICER_1
            ),
            "ERR_FILE_NOT_COMPLETE",
        )

        certify_component(file_id, components["DISCIPLINE"]["id"])
        completed = get_file(file_id)
        assert completed["assembly_status"] == "COMPLETE"
        assert completed["completeness_pct"] == 100.0
        assert completed["certified_component_count"] == 3

        ready = mark_ready_request(request["id"], file_id)

        assert_records_request(ready)
        assert ready["status"] == "READY_FOR_RELEASE"
        assert ready["packet_status"] == "SNAPSHOT"
        assert ready["packet_page_count"] == 166
        assert ready["reopen_count"] == 0


DESTRUCTION_NOTE = "Destroyed under the 5-year schedule, witnessed by two staff"


def _eligible_schedule_with_one_open_request():
    """The schedule is genuinely DESTRUCTION_ELIGIBLE by date at
    2031-08-16T00:00:00Z, while one records request still sits in RECEIVED."""
    sending, receiving = _two_districts()
    student = create_student(
        sending["id"],
        first_name="Rhea",
        last_name="Bettencourt",
        dob="2010-06-06",
        grade_level=11,
        has_iep=False,
        guardian_user_id="guardian-rhea",
    )
    file_id = get_cumulative_file_id(student["id"])
    withdrawal = create_withdrawal(
        student["id"],
        effective_date="2026-08-14",
        destination_district_code="RECV01",
        withdrawal_reason="TRANSFER_OUT",
    )
    set_clock("2026-08-15T12:00:00Z")
    complete_withdrawal(withdrawal["id"])
    schedules = get_retention_schedules(file_id, headers=COMPLIANCE)
    assert len(schedules) == 1
    schedule = schedules[0]

    set_clock("2026-08-16T00:00:00Z")
    components = get_components(file_id)
    for component_type, pages, redactions in PAGES:
        component_id = components[component_type]["id"]
        collect_component(file_id, component_id, pages, redactions)
        certify_component(file_id, component_id)

    request = create_records_request(
        student["id"],
        receiving["id"],
        sending["id"],
        authorization_reference="ENR-2026-0040",
    )
    assert _get_request(request["id"])["status"] == "RECEIVED"

    set_clock("2031-08-16T00:00:00Z")
    run_sweep()
    promoted = _get_schedule(schedule["id"])
    assert promoted["status"] == "DESTRUCTION_ELIGIBLE"
    return student, file_id, components, request, promoted


def _get_schedule(schedule_id):
    return validate_success(api_client.get_retention_schedule(schedule_id, COMPLIANCE))


class TestDestructionDependsOnTheOpenRequest:
    def test_a_records_request_in_received_blocks_a_date_eligible_schedule(self):
        """The schedule has reached its governing eligibility date and the sweep
        has promoted it, yet destruction is refused because a different entity —
        one open records request — still claims the file.

        PRD: "Eligibility by date is necessary but never sufficient — destruction is additionally refused with `ERR_DESTRUCTION_HOLD_ACTIVE` while the student has any records request in `RECEIVED`, `VALIDATED`, `ASSEMBLING`, or `READY_FOR_RELEASE`, or any legal demand in `RECEIVED` or `NOTIFIED`, the latter being the litigation hold."

        Design: Difficulty/cross_entity_state_dependency/destruction_blocked_by_open_records_request
        """
        _student, file_id, _components, _request, schedule = (
            _eligible_schedule_with_one_open_request()
        )

        response = api_client.execute_destruction(
            schedule["id"],
            destruction_payload("CROSS_CUT_SHRED", certification_note=DESTRUCTION_NOTE),
            COMPLIANCE,
        )

        validate_error(response, "ERR_DESTRUCTION_HOLD_ACTIVE", 409)

        held = _get_schedule(schedule["id"])
        assert_retention_schedule(held)
        assert held["status"] == "DESTRUCTION_ELIGIBLE"
        assert held["destroyed_at"] is None
        assert held["destruction_eligible_at"] == "2031-08-16T00:00:00.000Z"
        assert held["exit_anchored_eligible_at"] == "2031-08-14T00:00:00.000Z"

        intact = get_file(file_id)
        assert intact["total_page_count"] == 172
        assert_page_custody_identity(intact)

    def test_denying_the_request_lets_the_identical_destruction_call_succeed(self):
        """Denying the request touches nothing on the schedule, yet the same
        destruction call now certifies the destruction and zeroes every page
        counter on the file without logging a disclosure.

        PRD: "Every component of the file then has its `page_count` and `redacted_page_count` set to 0, so the file's `total_page_count` becomes 0 and the page-custody identity holds trivially thereafter."

        Design: Difficulty/cross_entity_state_dependency/destruction_blocked_by_open_records_request
        """
        student, file_id, components, request, schedule = (
            _eligible_schedule_with_one_open_request()
        )
        validate_error(
            api_client.execute_destruction(
                schedule["id"],
                destruction_payload("CROSS_CUT_SHRED", certification_note=DESTRUCTION_NOTE),
                COMPLIANCE,
            ),
            "ERR_DESTRUCTION_HOLD_ACTIVE",
            409,
        )

        denied = deny_request(request["id"], "STUDENT_NOT_IN_DISTRICT")
        assert denied["status"] == "DENIED"

        destroyed = validate_success(
            api_client.execute_destruction(
                schedule["id"],
                destruction_payload("CROSS_CUT_SHRED", certification_note=DESTRUCTION_NOTE),
                COMPLIANCE,
            )
        )

        assert_retention_schedule(destroyed)
        assert destroyed["status"] == "DESTROYED"
        assert destroyed["destroyed_at"] == "2031-08-16T00:00:00.000Z"
        assert destroyed["destruction_method"] == "CROSS_CUT_SHRED"

        emptied = get_file(file_id)
        assert emptied["total_page_count"] == 0
        assert emptied["included_page_count"] == 0
        assert emptied["disclosable_page_count"] == 0
        assert_page_custody_identity(emptied)

        academic = get_components(file_id)["ACADEMIC"]
        assert_file_component(academic)
        assert academic["page_count"] == 0
        assert academic["redacted_page_count"] == 0

        assert get_disclosure_log(student["id"], headers=CLERK) == [], (
            "destruction is not a disclosure and appends no log entry"
        )
