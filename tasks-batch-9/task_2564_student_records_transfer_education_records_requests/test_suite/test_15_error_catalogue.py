"""Each refusal names its own code rather than a generic one.

Eight not-found families, two uniqueness codes, the three withdrawal refusals,
the fee and terminal-state codes on an inspection, the amendment target rules,
the retention state codes, and the court seal that stops a release.
"""
from test_helpers import (
    ADMIN,
    CLERK,
    COMPLIANCE,
    LEGAL,
    NON_EXISTENT_UUID,
    OFFICER_1,
    amendment_request_payload,
    api_client,
    appointment_payload,
    assert_amendment_request,
    assert_cumulative_file,
    assert_error_envelope_shape,
    assert_file_component,
    assert_inspection_request,
    assert_records_request,
    assert_retention_schedule,
    assert_review_appointment,
    assert_student,
    assert_withdrawal,
    attendance_payload,
    book_appointment,
    certify_component,
    collect_component,
    complete_withdrawal,
    create_amendment,
    create_district,
    create_hearing_officer,
    create_inspection_request,
    create_inspection_room,
    create_records_request,
    create_state_rule,
    create_student,
    create_withdrawal,
    destruction_payload,
    district_payload,
    exclude_component,
    fee_transaction_payload,
    get_components,
    get_cumulative_file_id,
    get_disclosure_log,
    get_file,
    get_inspection_request,
    get_retention_schedules,
    hearing_schedule_payload,
    hold_payload,
    make_parent_headers,
    mark_ready_request,
    pay_fee,
    record_attendance,
    reinstate_component,
    release_payload,
    run_sweep,
    set_clock,
    state_rule_payload,
    validate_error,
    validate_paginated,
    validate_request,
    validate_success,
    withdrawal_payload,
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


def _sending_district():
    create_state_rule("CA", **CA_RULE)
    return create_district("SEND01", state_code="CA", name="Sending Unified")


def _unknown_id_reads():
    """One by-id read per entity family, each aimed at an id nothing owns."""
    return (
        ("ERR_WITHDRAWAL_NOT_FOUND", api_client.get_withdrawal(NON_EXISTENT_UUID, OFFICER_1)),
        (
            "ERR_DISCIPLINE_INCIDENT_NOT_FOUND",
            api_client.get_discipline_incident(NON_EXISTENT_UUID, OFFICER_1),
        ),
        (
            "ERR_RECORDS_REQUEST_NOT_FOUND",
            api_client.get_records_request(NON_EXISTENT_UUID, OFFICER_1),
        ),
        (
            "ERR_INSPECTION_REQUEST_NOT_FOUND",
            api_client.get_inspection_request(NON_EXISTENT_UUID, OFFICER_1),
        ),
        (
            "ERR_REVIEW_APPOINTMENT_NOT_FOUND",
            api_client.get_review_appointment(NON_EXISTENT_UUID, OFFICER_1),
        ),
        (
            "ERR_AMENDMENT_REQUEST_NOT_FOUND",
            api_client.get_amendment_request(NON_EXISTENT_UUID, OFFICER_1),
        ),
        ("ERR_LEGAL_DEMAND_NOT_FOUND", api_client.get_legal_demand(NON_EXISTENT_UUID, LEGAL)),
        (
            "ERR_RETENTION_SCHEDULE_NOT_FOUND",
            api_client.get_retention_schedule(NON_EXISTENT_UUID, COMPLIANCE),
        ),
    )


class TestNotFoundCodesPerEntityFamily:
    def test_eight_by_id_reads_return_eight_different_not_found_codes(self):
        """The same syntactically valid but unowned identifier produces a
        different code in each family, so no read falls back on a shared
        not-found code.

        PRD: "Each resource family has its own code: `ERR_DISTRICT_NOT_FOUND`, `ERR_STATE_RULE_NOT_FOUND`, `ERR_STUDENT_NOT_FOUND`, `ERR_WITHDRAWAL_NOT_FOUND`, `ERR_CUMULATIVE_FILE_NOT_FOUND`, `ERR_FILE_COMPONENT_NOT_FOUND`, `ERR_DISCIPLINE_INCIDENT_NOT_FOUND`, `ERR_RECORDS_REQUEST_NOT_FOUND`, `ERR_INSPECTION_ROOM_NOT_FOUND`, `ERR_INSPECTION_REQUEST_NOT_FOUND`, `ERR_REVIEW_APPOINTMENT_NOT_FOUND`, `ERR_HEARING_OFFICER_NOT_FOUND`, `ERR_AMENDMENT_REQUEST_NOT_FOUND`, `ERR_LEGAL_DEMAND_NOT_FOUND`, and `ERR_RETENTION_SCHEDULE_NOT_FOUND`."

        Design: Corner/errors/every_unknown_path_id_returns_its_own_not_found_code
        """
        reads = _unknown_id_reads()

        seen = []
        for expected_error_id, response in reads:
            body = validate_error(response, expected_error_id, 404)
            seen.append(body["error_id"])

        assert len(set(seen)) == 8, f"eight families, eight codes, got {sorted(set(seen))}"

    def test_every_not_found_body_is_a_well_formed_error_envelope(self):
        """Each of the eight refusals answers with the error envelope: the
        response type says error and the body carries a machine-readable code
        beside a human-readable message.

        PRD: "The `error_id` is a unique, machine-readable string that identifies the specific error."

        Design: Corner/errors/every_unknown_path_id_returns_its_own_not_found_code
        """
        for expected_error_id, response in _unknown_id_reads():
            assert response.status_code == 404, (
                f"{expected_error_id} is a 404, got {response.status_code}"
            )
            body = assert_error_envelope_shape(response)
            assert body["error_id"] == expected_error_id
            assert body["message"].strip()


class TestNaturalKeyUniquenessCodes:
    def test_re_posting_a_configured_state_leaves_the_stored_rule_untouched(self):
        """The natural key decides, not the payload: a second CA rule carrying a
        wholly different set of statutory parameters is refused, and the rule that
        was already there keeps every value it was configured with.

        PRD: "A **state records rule** is keyed by `state_code`, which is one of `CA`, `TX`, or `NY` and is unique across the table; a second registration for a state that already has one is refused with `ERR_DUPLICATE_STATE_RULE`."

        Design: Corner/errors/duplicate_state_rule_and_duplicate_district_code_codes
        """
        create_state_rule("CA", **CA_RULE)

        response = api_client.create_state_rule(
            state_rule_payload(
                "CA",
                transfer_response_days=45,
                discipline_inclusion_mode="ALL_INCIDENTS",
                discipline_min_days_removed=1,
                include_pending_investigations=True,
                sped_requires_consent=False,
                amendment_hearing_days=60,
                destruction_min_age_years=9,
                directory_optout_grace_days=30,
                notification_wait_days=1,
            ),
            ADMIN,
        )

        validate_error(response, "ERR_DUPLICATE_STATE_RULE", 409)

        stored = validate_success(api_client.get_state_rule("CA", ADMIN))
        assert stored["transfer_response_days"] == 10
        assert stored["amendment_hearing_days"] == 30
        assert stored["destruction_min_age_years"] == 5

    def test_re_using_a_district_code_under_another_name_is_refused(self):
        """The code is the district's unique key, so a second registration that
        differs only in its name is refused and the collection still holds the one
        district that took the code first.

        PRD: "The district code is globally unique — a duplicate is refused with `ERR_DUPLICATE_DISTRICT_CODE` — and must be between 2 and 12 characters of uppercase alphanumeric text."

        Design: Corner/errors/duplicate_state_rule_and_duplicate_district_code_codes
        """
        original = _sending_district()

        response = api_client.create_district(
            district_payload(
                name="Impostor Unified", district_code="SEND01", state_code="CA"
            ),
            ADMIN,
        )

        validate_error(response, "ERR_DUPLICATE_DISTRICT_CODE", 409)

        districts, meta = validate_paginated(api_client.list_districts(ADMIN))
        assert meta["total_count"] == 1
        assert districts[0]["id"] == original["id"]
        assert districts[0]["name"] == "Sending Unified"


def _yves_with_one_open_withdrawal():
    """Yves has a single withdrawal, effective 2026-08-14, sitting in CLEARED
    with no holds against it."""
    district = _sending_district()
    student = create_student(
        district["id"],
        first_name="Yves",
        last_name="Marchetti",
        dob="2012-11-23",
        grade_level=9,
        has_iep=False,
        guardian_user_id="guardian-yves",
    )
    withdrawal = create_withdrawal(
        student["id"],
        effective_date="2026-08-14",
        destination_district_code="TXD-9",
        withdrawal_reason="TRANSFER_OUT",
    )
    assert withdrawal["status"] == "CLEARED"
    return student, withdrawal


def _open_another_withdrawal(student_id, effective_date):
    return api_client.create_withdrawal(
        student_id,
        withdrawal_payload(
            effective_date=effective_date,
            destination_district_code="TXD-9",
            withdrawal_reason="MOVED",
        ),
        CLERK,
    )


class TestWithdrawalRefusalCodes:
    def test_a_second_withdrawal_while_one_is_open_is_the_uniqueness_refusal(self):
        """A WITHDRAWAL_PENDING student still passes the enrollment check, so the
        sharper uniqueness rule is what catches the second filing, and no extra
        row is left behind.

        PRD: "A student already in `WITHDRAWAL_PENDING` passes that first check and is then caught by the sharper uniqueness rule, which refuses a second withdrawal row with `ERR_OPEN_WITHDRAWAL_EXISTS` whenever the student already has one whose status is anything other than `COMPLETED`."

        Design: Corner/errors/withdrawal_uniqueness_enrollment_and_completion_codes
        """
        student, withdrawal = _yves_with_one_open_withdrawal()

        response = _open_another_withdrawal(student["id"], "2026-08-20")

        validate_error(response, "ERR_OPEN_WITHDRAWAL_EXISTS", 409)

        rows = validate_success(
            api_client.list_student_withdrawals(student["id"], CLERK)
        )
        assert len(rows) == 1
        assert rows[0]["id"] == withdrawal["id"]

    def test_a_departed_student_can_never_open_another_withdrawal(self):
        """Completion moves the student to WITHDRAWN and copies the effective date
        onto them; from there the enrollment guard, not the uniqueness rule, is
        what refuses a fresh filing.

        PRD: "The student must be in `ENROLLED` or `WITHDRAWAL_PENDING`; a `WITHDRAWN` or `TRANSFERRED_OUT` student can never open another withdrawal and is refused with `ERR_STUDENT_NOT_ENROLLED`."

        Design: Corner/errors/withdrawal_uniqueness_enrollment_and_completion_codes
        """
        student, withdrawal = _yves_with_one_open_withdrawal()

        completed = complete_withdrawal(withdrawal["id"])
        assert_withdrawal(completed)
        assert completed["status"] == "COMPLETED"
        assert completed["completed_at"] == "2026-08-01T00:00:00.000Z"

        departed = validate_success(api_client.get_student(student["id"], CLERK))
        assert_student(departed)
        assert departed["enrollment_status"] == "WITHDRAWN"
        assert departed["exit_effective_date"] == "2026-08-14"

        response = _open_another_withdrawal(student["id"], "2026-08-25")

        validate_error(response, "ERR_STUDENT_NOT_ENROLLED", 409)

    def test_a_completed_withdrawal_accepts_no_hold_release_or_completion(self):
        """All three operations on the row are closed once it is COMPLETED, and
        each of them says so with the same code while the hold set stays empty.

        PRD: "Once a withdrawal is `COMPLETED`, none of these three operations is available: placing a hold, releasing a hold, and completing are all refused with `ERR_WITHDRAWAL_ALREADY_COMPLETED`."

        Design: Corner/errors/withdrawal_uniqueness_enrollment_and_completion_codes
        """
        _student, withdrawal = _yves_with_one_open_withdrawal()
        complete_withdrawal(withdrawal["id"])

        placing = api_client.place_withdrawal_hold(
            withdrawal["id"], hold_payload("LIBRARY_FINE"), CLERK
        )
        validate_error(placing, "ERR_WITHDRAWAL_ALREADY_COMPLETED", 409)

        releasing = api_client.release_withdrawal_hold(
            withdrawal["id"], hold_payload("LIBRARY_FINE"), CLERK
        )
        validate_error(releasing, "ERR_WITHDRAWAL_ALREADY_COMPLETED", 409)

        completing = api_client.complete_withdrawal(withdrawal["id"], OFFICER_1)
        validate_error(completing, "ERR_WITHDRAWAL_ALREADY_COMPLETED", 409)

        final = validate_success(api_client.get_withdrawal(withdrawal["id"], OFFICER_1))
        assert final["status"] == "COMPLETED"
        assert final["hold_count"] == 0
        assert final["active_hold_types"] == []


def _wren_and_xan_with_one_priced_inspection():
    """Wren's forty-page ACADEMIC component is inspected with copies requested
    and an appointment already booked for 2026-08-05T09:00Z; Xan's request holds
    nothing, asks for no copies, and is never scheduled."""
    district = _sending_district()
    room = create_inspection_room("ROOM-A", 4)
    wren = create_student(
        district["id"],
        first_name="Wren",
        last_name="Baptiste",
        dob="2013-01-24",
        grade_level=6,
        has_iep=False,
        guardian_user_id="guardian-wren",
    )
    xan = create_student(
        district["id"],
        first_name="Xan",
        last_name="Oyelaran",
        dob="2013-02-25",
        grade_level=6,
        has_iep=False,
        guardian_user_id="guardian-xan",
    )
    wren_file = get_cumulative_file_id(wren["id"])
    collect_component(wren_file, get_components(wren_file)["ACADEMIC"]["id"], 40, 0)

    priced = create_inspection_request(
        wren["id"],
        make_parent_headers("guardian-wren"),
        categories=["ACADEMIC"],
        copies_requested=True,
    )
    unscheduled = create_inspection_request(
        xan["id"],
        make_parent_headers("guardian-xan"),
        categories=["ACADEMIC"],
        copies_requested=False,
    )
    appointment = book_appointment(
        priced["id"], room["id"], "2026-08-05T09:00:00Z", "2026-08-05T10:00:00Z"
    )
    return dict(
        room=room,
        wren=wren,
        xan=xan,
        priced=priced,
        unscheduled=unscheduled,
        appointment=appointment,
    )


class TestInspectionFeeAndTerminalStateCodes:
    def test_forty_chargeable_pages_are_priced_at_three_hundred_twenty_five_cents(self):
        """The per-page charge is rounded once and the surcharge once more, giving
        325 cents, which sits under the first certification floor so nothing rides
        on top; the request that asked for no copies is assessed nothing at all.

        PRD: "For each qualifying component, take its `page_count` minus its `redacted_page_count` as the chargeable page figure, multiply that by seven and a half cents per page, and round half up to a whole number of cents; then apply the 8.25 percent copy surcharge by multiplying that whole-cent figure by one plus the surcharge rate and rounding half up again to whole cents."

        Design: Corner/errors/inspection_fee_and_terminal_state_codes
        """
        scenario = _wren_and_xan_with_one_priced_inspection()

        priced = get_inspection_request(scenario["priced"]["id"])
        assert_inspection_request(priced)
        assert priced["base_copy_fee_cents"] == 325, "40 pages at 7.5c is 300c, plus 8.25%"
        assert priced["certification_fee_cents"] == 0
        assert priced["fee_assessed_cents"] == 325
        assert priced["fee_outstanding_cents"] == 325
        assert priced["status"] == "SCHEDULED"

        free = get_inspection_request(scenario["unscheduled"]["id"])
        assert_inspection_request(free)
        assert free["base_copy_fee_cents"] == 0
        assert free["fee_assessed_cents"] == 0
        assert free["fee_outstanding_cents"] == 0
        assert free["status"] == "SUBMITTED"

    def test_attendance_waits_for_the_balance_and_then_closes_the_inspection(self):
        """An outstanding balance on a copies-requested inspection blocks the
        attendance outright; once the 325 cents are paid the identical call moves
        the appointment to ATTENDED, bubbles the request to COMPLETED and logs the
        inspection once.

        PRD: "Where the inspection request had `copies_requested` true, its `fee_outstanding_cents` must be exactly 0 before attendance may be recorded; an outstanding balance is refused with `ERR_FEE_OUTSTANDING`."

        Design: Corner/errors/inspection_fee_and_terminal_state_codes
        """
        scenario = _wren_and_xan_with_one_priced_inspection()
        appointment_id = scenario["appointment"]["id"]
        set_clock("2026-08-05T09:30:00Z")

        too_early = api_client.record_attendance(
            appointment_id, attendance_payload(True), OFFICER_1
        )
        validate_error(too_early, "ERR_FEE_OUTSTANDING", 422)

        settled = validate_success(
            api_client.create_fee_transaction(
                scenario["priced"]["id"], fee_transaction_payload("PAYMENT", 325), CLERK
            )
        )
        assert settled["fee_collected_cents"] == 325
        assert settled["fee_outstanding_cents"] == 0

        attended = record_attendance(appointment_id, True)
        assert_review_appointment(attended)
        assert attended["status"] == "ATTENDED"
        assert attended["attended_at"] == "2026-08-05T09:30:00.000Z"

        completed = get_inspection_request(scenario["priced"]["id"])
        assert completed["status"] == "COMPLETED"
        assert completed["inspection_completed_at"] == "2026-08-05T09:30:00.000Z"

        entries = get_disclosure_log(scenario["wren"]["id"])
        assert [entry["disclosure_type"] for entry in entries] == ["PARENT_INSPECTION"]
        assert entries[0]["source_id"] == scenario["priced"]["id"]

    def test_the_three_terminal_refusals_each_name_their_own_state(self):
        """A completed inspection refuses a further booking, its attended
        appointment refuses a second attendance, and a swept-away request refuses
        booking for a different reason again — three states, three codes.

        PRD: "The inspection request must be in `SUBMITTED` or `SCHEDULED`; a `COMPLETED` one is refused with `ERR_INSPECTION_ALREADY_COMPLETED` and an `EXPIRED` one with `ERR_INSPECTION_EXPIRED`."

        Design: Corner/errors/inspection_fee_and_terminal_state_codes
        """
        scenario = _wren_and_xan_with_one_priced_inspection()
        room_id = scenario["room"]["id"]
        priced_id = scenario["priced"]["id"]
        set_clock("2026-08-05T09:30:00Z")
        pay_fee(priced_id, 325, "PAYMENT", headers=CLERK)
        record_attendance(scenario["appointment"]["id"], True)

        rebooking = api_client.create_review_appointment(
            priced_id,
            appointment_payload(
                room_id,
                "2026-08-06T09:00:00Z",
                "2026-08-06T10:00:00Z",
                get_inspection_request(priced_id)["version"],
            ),
            OFFICER_1,
        )
        validate_error(rebooking, "ERR_INSPECTION_ALREADY_COMPLETED", 409)

        re_attending = api_client.record_attendance(
            scenario["appointment"]["id"], attendance_payload(True), OFFICER_1
        )
        validate_error(re_attending, "ERR_APPOINTMENT_NOT_SCHEDULED", 409)

        set_clock("2026-09-16T00:00:00Z")
        run_sweep()
        expired = get_inspection_request(scenario["unscheduled"]["id"])
        assert expired["status"] == "EXPIRED"

        late_booking = api_client.create_review_appointment(
            scenario["unscheduled"]["id"],
            appointment_payload(
                room_id, "2026-09-17T09:00:00Z", "2026-09-17T10:00:00Z", expired["version"]
            ),
            OFFICER_1,
        )
        validate_error(late_booking, "ERR_INSPECTION_EXPIRED", 409)


def _two_students_and_one_submitted_challenge():
    """Yasmin has challenged Yara's ten-page ACADEMIC component and the challenge
    is still SUBMITTED; Yara's HEALTH component is excluded and Zora's daughter
    has an ACADEMIC component of her own."""
    district = _sending_district()
    officer = create_hearing_officer("Hannah Osei", "DISTRICT_DESIGNEE")
    yara = create_student(
        district["id"],
        first_name="Yara",
        last_name="Petrov",
        dob="2012-03-08",
        grade_level=8,
        has_iep=False,
        guardian_user_id="guardian-yasmin",
    )
    zola = create_student(
        district["id"],
        first_name="Zola",
        last_name="Quintero",
        dob="2012-04-09",
        grade_level=8,
        has_iep=False,
        guardian_user_id="guardian-zora",
    )
    yara_file = get_cumulative_file_id(yara["id"])
    yara_components = get_components(yara_file)
    collect_component(yara_file, yara_components["ACADEMIC"]["id"], 10, 0)
    collect_component(yara_file, yara_components["HEALTH"]["id"], 20, 0)
    excluded = exclude_component(
        yara_file, yara_components["HEALTH"]["id"], "OTHER_STUDENT_INFO"
    )
    assert excluded["status"] == "EXCLUDED"

    zola_file = get_cumulative_file_id(zola["id"])
    zola_components = get_components(zola_file)
    collect_component(zola_file, zola_components["ACADEMIC"]["id"], 30, 0)

    challenge = create_amendment(
        yara["id"],
        yara_components["ACADEMIC"]["id"],
        make_parent_headers("guardian-yasmin"),
    )
    assert challenge["status"] == "SUBMITTED"
    return dict(
        officer=officer,
        yara=yara,
        zola=zola,
        yara_file=yara_file,
        yara_components=yara_components,
        zola_components=zola_components,
        challenge=challenge,
    )


class TestHearingScheduleAndAmendmentTargetCodes:
    def test_a_hearing_cannot_be_booked_on_a_challenge_nobody_has_denied(self):
        """Scheduling is reachable only from the two hearing statuses, so a
        SUBMITTED challenge is turned away on the state check alone — before the
        officer or the window is ever consulted — and nothing about the hearing is
        recorded.

        PRD: "The challenge must be in `HEARING_REQUESTED` or `HEARING_SCHEDULED` — a call from a status outside that pair is refused with `ERR_HEARING_NOT_SCHEDULED` — so a second scheduling call is a legitimate reschedule rather than an error, and that self-loop on `HEARING_SCHEDULED` may run as often as the statutory window allows."

        Design: Corner/errors/hearing_schedule_and_amendment_target_codes
        """
        scenario = _two_students_and_one_submitted_challenge()

        response = api_client.create_hearing_schedule(
            scenario["challenge"]["id"],
            hearing_schedule_payload(
                scenario["officer"]["id"],
                "2026-08-10T14:00:00Z",
                "2026-08-10T15:00:00Z",
            ),
            OFFICER_1,
        )

        validate_error(response, "ERR_HEARING_NOT_SCHEDULED", 409)

        untouched = validate_success(
            api_client.get_amendment_request(scenario["challenge"]["id"], OFFICER_1)
        )
        assert_amendment_request(untouched)
        assert untouched["status"] == "SUBMITTED"
        assert untouched["hearing_officer_id"] is None
        assert untouched["hearing_due_at"] is None
        assert untouched["hearing_start_at"] is None
        assert untouched["hearing_duration_minutes"] is None

    def test_another_students_component_and_an_excluded_one_share_one_refusal(self):
        """The ownership test and the status test are the same rule, so pointing a
        challenge at a component of another student's file and pointing it at this
        student's own excluded component are refused identically.

        PRD: "The component must belong to the cumulative file of the student in question and must not be `EXCLUDED`; a component belonging to another student's file, or an excluded one, is refused with `ERR_COMPONENT_NOT_FOR_STUDENT`, while an identifier that resolves to nothing at all is refused earlier with `ERR_FILE_COMPONENT_NOT_FOUND`."

        Design: Corner/errors/hearing_schedule_and_amendment_target_codes
        """
        scenario = _two_students_and_one_submitted_challenge()
        yasmin = make_parent_headers("guardian-yasmin")

        wrong_file = api_client.create_amendment_request(
            scenario["yara"]["id"],
            amendment_request_payload(scenario["zola_components"]["ACADEMIC"]["id"]),
            yasmin,
        )
        validate_error(wrong_file, "ERR_COMPONENT_NOT_FOR_STUDENT", 422)

        own_excluded = api_client.create_amendment_request(
            scenario["yara"]["id"],
            amendment_request_payload(scenario["yara_components"]["HEALTH"]["id"]),
            yasmin,
        )
        validate_error(own_excluded, "ERR_COMPONENT_NOT_FOR_STUDENT", 422)

        unresolvable = api_client.create_amendment_request(
            scenario["yara"]["id"], amendment_request_payload(NON_EXISTENT_UUID), yasmin
        )
        validate_error(unresolvable, "ERR_FILE_COMPONENT_NOT_FOUND", 404)

        yara_rows, yara_meta = validate_paginated(
            api_client.list_amendment_requests(
                OFFICER_1, params={"student_id": scenario["yara"]["id"]}
            )
        )
        assert yara_meta["total_count"] == 1
        assert yara_rows[0]["id"] == scenario["challenge"]["id"]

        _zola_rows, zola_meta = validate_paginated(
            api_client.list_amendment_requests(
                OFFICER_1, params={"student_id": scenario["zola"]["id"]}
            )
        )
        assert zola_meta["total_count"] == 0

        file_read = get_file(scenario["yara_file"])
        assert_cumulative_file(file_read)
        assert file_read["total_page_count"] == 30
        assert file_read["included_page_count"] == 10
        assert file_read["excluded_page_count"] == 20


def _abel_with_a_schedule_and_forty_uncertified_pages():
    """A completed withdrawal effective 2026-08-14 mints the schedule; the forty
    ACADEMIC pages are collected only afterwards and are never certified, so the
    latest-activity instant stays on the exit anchor."""
    district = _sending_district()
    student = create_student(
        district["id"],
        first_name="Abel",
        last_name="Nwosu",
        dob="2012-05-11",
        grade_level=8,
        has_iep=False,
        guardian_user_id="guardian-abel",
    )
    file_id = get_cumulative_file_id(student["id"])
    withdrawal = create_withdrawal(
        student["id"],
        effective_date="2026-08-14",
        destination_district_code="TXD-9",
        withdrawal_reason="TRANSFER_OUT",
    )
    complete_withdrawal(withdrawal["id"])
    component_id = get_components(file_id)["ACADEMIC"]["id"]
    collect_component(file_id, component_id, 40, 0)

    schedules = get_retention_schedules(file_id)
    assert len(schedules) == 1, f"one schedule per exited file, got {len(schedules)}"
    return student, file_id, component_id, schedules[0]


class TestRetentionDestructionStateCodes:
    def test_destruction_before_the_sweep_promotes_the_schedule_is_refused(self):
        """The five-year projection off the exit anchor lands on
        2031-08-14T00:00:00.000Z, and until the sweep declares that date reached the
        schedule stays ACTIVE and refuses to be destroyed.

        PRD: "The schedule must be in `DESTRUCTION_ELIGIBLE`: one still in `ACTIVE` is refused with `ERR_RETENTION_NOT_ELIGIBLE` because the sweep has not promoted it, and one already in `DESTROYED` is refused with `ERR_ALREADY_DESTROYED`."

        Design: Corner/errors/retention_destruction_state_codes
        """
        student, _file_id, _component_id, schedule = (
            _abel_with_a_schedule_and_forty_uncertified_pages()
        )

        assert_retention_schedule(schedule)
        assert schedule["status"] == "ACTIVE"
        assert schedule["destruction_min_age_years"] == 5
        assert schedule["exit_anchor_at"] == "2026-08-14T00:00:00.000Z"
        assert schedule["last_activity_at"] == "2026-08-14T00:00:00.000Z"
        assert schedule["destruction_eligible_at"] == "2031-08-14T00:00:00.000Z"
        assert schedule["exit_anchored_eligible_at"] == "2031-08-14T00:00:00.000Z"

        mirrored = validate_success(api_client.get_student(student["id"], CLERK))
        assert mirrored["records_disposition_date"] == "2031-08-14T00:00:00.000Z"

        response = api_client.execute_destruction(
            schedule["id"], destruction_payload("CROSS_CUT_SHRED"), COMPLIANCE
        )

        validate_error(response, "ERR_RETENTION_NOT_ELIGIBLE", 409)

        still_active = validate_success(
            api_client.get_retention_schedule(schedule["id"], COMPLIANCE)
        )
        assert still_active["status"] == "ACTIVE"
        assert still_active["destroyed_at"] is None

    def test_destruction_zeroes_the_pages_once_and_refuses_a_second_pass(self):
        """At exactly the eligible instant the sweep promotes the schedule, the
        certified destruction empties every component of its pages, and the second
        attempt is refused on the already-destroyed state without touching the
        stored method.

        PRD: "Every component of the file then has its `page_count` and `redacted_page_count` set to 0, so the file's `total_page_count` becomes 0 and the page-custody identity holds trivially thereafter."

        Design: Corner/errors/retention_destruction_state_codes
        """
        student, file_id, component_id, schedule = (
            _abel_with_a_schedule_and_forty_uncertified_pages()
        )
        set_clock("2031-08-14T00:00:00Z")
        run_sweep()

        promoted = validate_success(
            api_client.get_retention_schedule(schedule["id"], COMPLIANCE)
        )
        assert promoted["status"] == "DESTRUCTION_ELIGIBLE"

        destroyed = validate_success(
            api_client.execute_destruction(
                schedule["id"], destruction_payload("CROSS_CUT_SHRED"), COMPLIANCE
            )
        )
        assert_retention_schedule(destroyed)
        assert destroyed["status"] == "DESTROYED"
        assert destroyed["destroyed_at"] == "2031-08-14T00:00:00.000Z"
        assert destroyed["destruction_method"] == "CROSS_CUT_SHRED"

        emptied = get_components(file_id)["ACADEMIC"]
        assert_file_component(emptied)
        assert emptied["id"] == component_id
        assert emptied["page_count"] == 0
        assert emptied["redacted_page_count"] == 0

        file_read = get_file(file_id)
        assert_cumulative_file(file_read)
        assert file_read["total_page_count"] == 0
        assert file_read["included_page_count"] == 0
        assert file_read["excluded_page_count"] == 0

        second = api_client.execute_destruction(
            schedule["id"], destruction_payload("INCINERATION"), COMPLIANCE
        )
        validate_error(second, "ERR_ALREADY_DESTROYED", 409)

        unchanged = validate_success(
            api_client.get_retention_schedule(schedule["id"], COMPLIANCE)
        )
        assert unchanged["destruction_method"] == "CROSS_CUT_SHRED"
        assert unchanged["destroyed_at"] == "2031-08-14T00:00:00.000Z"

        assert get_disclosure_log(student["id"]) == [], "destruction is not a disclosure"


def _bea_with_a_frozen_seventy_five_page_packet():
    """A has_iep false student whose four components are all certified at
    10 / 20 / 30 / 15 pages, over which one transfer request has been snapshotted."""
    create_state_rule("CA", **CA_RULE)
    create_state_rule("TX", **TX_RULE)
    responding = create_district("SEND01", state_code="CA", name="Sending Unified")
    requesting = create_district("RECV01", state_code="TX", name="Receiving Unified")
    student = create_student(
        responding["id"],
        first_name="Bea",
        last_name="Fontaine",
        dob="2012-06-12",
        grade_level=8,
        has_iep=False,
        guardian_user_id="guardian-bea",
    )
    file_id = get_cumulative_file_id(student["id"])
    components = get_components(file_id)
    for component_type, pages in (
        ("ACADEMIC", 10),
        ("HEALTH", 20),
        ("DISCIPLINE", 30),
        ("SPECIAL_EDUCATION", 15),
    ):
        component_id = components[component_type]["id"]
        collect_component(file_id, component_id, pages, 0)
        certify_component(file_id, component_id)

    request = create_records_request(
        student["id"],
        requesting["id"],
        responding["id"],
        authorization_reference="ENR-2026-7710",
    )
    validate_request(request["id"])
    ready = mark_ready_request(request["id"], file_id)
    assert ready["packet_page_count"] == 75
    return dict(
        student=student,
        file_id=file_id,
        components=components,
        request=request,
        ready=ready,
    )


class TestCourtSealedComponentBlocksRelease:
    def test_sealing_an_optional_component_leaves_the_file_and_packet_alone(self):
        """Only a required component's departure from CERTIFIED bubbles the file
        down, so sealing the special-education component of a student with no IEP
        leaves the file COMPLETE and the snapshot untouched.

        PRD: "Because a required component has left `CERTIFIED`, the parent file bubbles `COMPLETE → IN_ASSEMBLY`."

        Design: Corner/errors/court_sealed_component_blocks_release_until_reinstated
        """
        scenario = _bea_with_a_frozen_seventy_five_page_packet()
        file_id = scenario["file_id"]

        before = get_file(file_id)
        assert_cumulative_file(before)
        assert before["required_component_types"] == ["ACADEMIC", "HEALTH", "DISCIPLINE"]
        assert before["assembly_status"] == "COMPLETE"
        assert get_components(file_id)["SPECIAL_EDUCATION"]["is_required"] is False

        sealed = exclude_component(
            file_id, scenario["components"]["SPECIAL_EDUCATION"]["id"], "SEALED_BY_COURT"
        )
        assert_file_component(sealed)
        assert sealed["status"] == "EXCLUDED"
        assert sealed["exclusion_reason"] == "SEALED_BY_COURT"
        assert sealed["certified_at"] is None

        after = get_file(file_id)
        assert after["assembly_status"] == "COMPLETE"
        assert after["completeness_pct"] == 100.0
        assert after["certified_component_count"] == 3
        assert after["included_page_count"] == 60
        assert after["excluded_page_count"] == 15

        held = validate_success(
            api_client.get_records_request(scenario["request"]["id"], OFFICER_1)
        )
        assert_records_request(held)
        assert held["status"] == "READY_FOR_RELEASE"
        assert held["packet_status"] == "SNAPSHOT"
        assert held["reopen_count"] == 0
        assert held["packet_page_count"] == 75

    def test_the_seal_alone_stops_the_release_and_reinstatement_lifts_it(self):
        """With the request ready and the packet frozen, the sealed component is the
        only thing standing between the packet and the wire; reinstating it lets the
        identical release call through with the original page count.

        PRD: "Court-sealed material may not leave the district under a transfer request: when any component of the file is `EXCLUDED` with an `exclusion_reason` of `SEALED_BY_COURT` and the request's `denial_reason` was not set to `COURT_SEALED`, release is refused with `ERR_COURT_SEALED_COMPONENT`."

        Design: Corner/errors/court_sealed_component_blocks_release_until_reinstated
        """
        scenario = _bea_with_a_frozen_seventy_five_page_packet()
        request_id = scenario["request"]["id"]
        sped_id = scenario["components"]["SPECIAL_EDUCATION"]["id"]
        exclude_component(scenario["file_id"], sped_id, "SEALED_BY_COURT")

        blocked = api_client.release_records_request(
            request_id, release_payload("SECURE_PORTAL"), OFFICER_1
        )
        validate_error(blocked, "ERR_COURT_SEALED_COMPONENT", 409)

        unsealed = reinstate_component(scenario["file_id"], sped_id)
        assert unsealed["status"] == "COLLECTED"
        assert unsealed["exclusion_reason"] is None
        assert unsealed["page_count"] == 15

        released = validate_success(
            api_client.release_records_request(
                request_id, release_payload("SECURE_PORTAL"), OFFICER_1
            )
        )
        assert_records_request(released)
        assert released["status"] == "RELEASED"
        assert released["transmission_method"] == "SECURE_PORTAL"
        assert released["packet_page_count"] == 75
        assert released["released_at"] == "2026-08-01T00:00:00.000Z"

        entries = get_disclosure_log(scenario["student"]["id"])
        assert [entry["disclosure_type"] for entry in entries] == ["INTERDISTRICT_TRANSFER"]
        assert entries[0]["page_count"] == 75
        assert entries[0]["source_id"] == request_id
