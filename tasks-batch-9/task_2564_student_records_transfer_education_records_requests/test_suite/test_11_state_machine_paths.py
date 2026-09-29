"""Declared transitions walked forward, and the illegal ones refused.

Each scenario drives one entity along a path the contract names — hold cycles,
initial states, automatic bubbles, terminal statuses, supersession, sweep
expiry — and reads back both the moved row and the rows the move was supposed
to drag with it.
"""
from test_helpers import (
    CLERK,
    COMPLIANCE,
    LEGAL,
    OFFICER_1,
    OFFICER_2,
    api_client,
    assert_amendment_request,
    assert_cumulative_file,
    assert_disclosure_log_entry,
    assert_file_component,
    assert_inspection_request,
    assert_legal_demand,
    assert_page_custody_identity,
    assert_records_request,
    assert_retention_schedule,
    assert_review_appointment,
    assert_withdrawal,
    book_appointment,
    certify_component,
    collect_component,
    complete_withdrawal,
    create_amendment,
    create_district,
    create_hearing_officer,
    create_inspection_request,
    create_inspection_room,
    create_legal_demand,
    create_records_request,
    create_state_rule,
    create_student,
    create_withdrawal,
    decide_amendment,
    deny_payload,
    file_statement,
    get_components,
    get_cumulative_file_id,
    get_disclosure_log,
    get_file,
    get_inspection_request,
    get_retention_schedules,
    hold_payload,
    make_parent_headers,
    mark_ready_payload,
    mark_ready_request,
    notify_demand,
    place_hold,
    produce_demand,
    release_hold,
    release_payload,
    release_request,
    request_hearing,
    run_sweep,
    schedule_hearing,
    set_clock,
    validate_error,
    validate_paginated,
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


def _ca_district():
    create_state_rule("CA", **CA_RULE)
    return create_district("SEND01", state_code="CA", name="Sending Unified")


def _two_districts():
    create_state_rule("CA", **CA_RULE)
    create_state_rule("TX", **TX_RULE)
    sending = create_district("SEND01", state_code="CA", name="Sending Unified")
    receiving = create_district("RECV01", state_code="TX", name="Receiving Unified")
    return sending, receiving


def _get_student(student_id):
    return validate_success(api_client.get_student(student_id, CLERK))


def _get_request(request_id):
    return validate_success(api_client.get_records_request(request_id, OFFICER_1))


def _get_withdrawal(withdrawal_id):
    return validate_success(api_client.get_withdrawal(withdrawal_id, CLERK))


def _get_appointment(appointment_id):
    return validate_success(api_client.get_review_appointment(appointment_id, OFFICER_1))


def _get_demand(demand_id):
    return validate_success(api_client.get_legal_demand(demand_id, LEGAL))


def _get_amendment(amendment_request_id):
    return validate_success(api_client.get_amendment_request(amendment_request_id, OFFICER_1))


def _withdrawal_with_two_holds():
    """One withdrawal carrying MEAL_ACCOUNT and LIBRARY_FINE, placed in that
    order so the stored list cannot merely be echoing the insertion order."""
    district = _ca_district()
    student = create_student(
        district["id"],
        first_name="Mika",
        last_name="Rosen",
        dob="2011-04-04",
        grade_level=9,
        has_iep=False,
        guardian_user_id="guardian-mika",
    )
    withdrawal = create_withdrawal(
        student["id"], effective_date="2026-08-14", withdrawal_reason="MOVED"
    )
    assert withdrawal["status"] == "CLEARED"
    assert withdrawal["hold_count"] == 0
    first = place_hold(withdrawal["id"], "MEAL_ACCOUNT")
    second = place_hold(withdrawal["id"], "LIBRARY_FINE")
    return student, withdrawal, first, second


class TestWithdrawalHoldCycle:
    def test_a_second_different_hold_grows_the_sorted_list_without_moving_the_status(self):
        """The first hold takes the withdrawal to HOLD, and the second — placed
        later but sorting earlier — is a self-transition that leaves the status
        alone while the list comes back in ascending enum order.

        PRD: "The type is appended to `active_hold_types`, which is kept sorted ascending by enum name, `hold_count` is set to the number of entries in that list, and the withdrawal moves `CLEARED → HOLD`."

        Design: Corner/state_machines/withdrawal_hold_then_final_release_returns_to_cleared
        """
        _student, _withdrawal, first, second = _withdrawal_with_two_holds()

        assert_withdrawal(first)
        assert first["status"] == "HOLD"
        assert first["hold_count"] == 1
        assert first["active_hold_types"] == ["MEAL_ACCOUNT"]

        assert_withdrawal(second)
        assert second["status"] == "HOLD"
        assert second["hold_count"] == 2
        assert second["active_hold_types"] == ["LIBRARY_FINE", "MEAL_ACCOUNT"]
        assert second["completed_at"] is None

    def test_only_the_final_release_returns_the_withdrawal_to_cleared(self):
        """Releasing the first of two holds keeps the withdrawal in HOLD with one
        entry left; releasing the last one empties the list, zeroes the count and
        returns the row to CLEARED with the student still merely pending.

        PRD: "A release while two or more holds are active removes that one entry and is another `HOLD → HOLD` transition, leaving `hold_count` at one or more; the final release — the one taken while `hold_count` is exactly 1 — empties `active_hold_types`, returns `hold_count` to 0, and moves the withdrawal `HOLD → CLEARED`."

        Design: Corner/state_machines/withdrawal_hold_then_final_release_returns_to_cleared
        """
        student, withdrawal, _first, _second = _withdrawal_with_two_holds()

        partial = release_hold(withdrawal["id"], "LIBRARY_FINE")
        assert partial["status"] == "HOLD"
        assert partial["hold_count"] == 1
        assert partial["active_hold_types"] == ["MEAL_ACCOUNT"]

        cleared = release_hold(withdrawal["id"], "MEAL_ACCOUNT")

        assert_withdrawal(cleared)
        assert cleared["status"] == "CLEARED"
        assert cleared["hold_count"] == 0
        assert cleared["active_hold_types"] == []
        assert cleared["completed_at"] is None

        reread = _get_withdrawal(withdrawal["id"])
        assert reread["status"] == "CLEARED"
        assert reread["hold_count"] == 0
        assert _get_student(student["id"])["enrollment_status"] == "WITHDRAWAL_PENDING"


class TestHoldTypeUniqueness:
    def test_a_repeated_type_and_an_absent_type_are_each_refused_on_their_own_code(self):
        """LIBRARY_FINE is already active, so placing it again is refused; and
        MEAL_ACCOUNT was never placed, so releasing it is refused with the
        opposite code, leaving the single standing hold untouched.

        PRD: "A hold type already present in `active_hold_types` is refused with `ERR_HOLD_ALREADY_ACTIVE`."

        Design: Corner/state_machines/duplicate_hold_type_cannot_be_placed_twice
        """
        district = _ca_district()
        student = create_student(
            district["id"],
            first_name="Quinn",
            last_name="Alvarez",
            dob="2010-12-01",
            grade_level=10,
            has_iep=False,
            guardian_user_id="guardian-quinn",
        )
        withdrawal = create_withdrawal(
            student["id"], effective_date="2026-08-14", withdrawal_reason="TRANSFER_OUT"
        )
        place_hold(withdrawal["id"], "LIBRARY_FINE")

        duplicate = api_client.place_withdrawal_hold(
            withdrawal["id"], hold_payload("LIBRARY_FINE"), CLERK
        )
        validate_error(duplicate, "ERR_HOLD_ALREADY_ACTIVE", 409)

        absent = api_client.release_withdrawal_hold(
            withdrawal["id"], hold_payload("MEAL_ACCOUNT"), CLERK
        )
        validate_error(absent, "ERR_HOLD_NOT_ACTIVE", 409)

        standing = _get_withdrawal(withdrawal["id"])
        assert_withdrawal(standing)
        assert standing["status"] == "HOLD"
        assert standing["hold_count"] == 1
        assert standing["active_hold_types"] == ["LIBRARY_FINE"]


class TestCompletionRequiresEveryHoldReleased:
    def test_a_single_outstanding_hold_stops_the_whole_exit_cascade(self):
        """The withdrawal is otherwise ready to complete, yet one SPED_EXIT_MEETING
        hold refuses the call and none of the five downstream effects fire: no
        completion instant, no exit date, no assembly, no retention schedule.

        PRD: "It requires the withdrawal to be `CLEARED` with `hold_count` at 0 and the student still in `WITHDRAWAL_PENDING`; a single outstanding hold blocks the student's exit even though the withdrawal row is otherwise ready, and either failure is refused with `ERR_WITHDRAWAL_NOT_CLEARED`."

        Design: Corner/state_machines/complete_withdrawal_while_hold_active_cannot_proceed
        """
        district = _ca_district()
        student = create_student(
            district["id"],
            first_name="Rui",
            last_name="Tanaka",
            dob="2009-07-19",
            grade_level=11,
            has_iep=True,
            guardian_user_id="guardian-rui",
        )
        file_id = get_cumulative_file_id(student["id"])
        withdrawal = create_withdrawal(
            student["id"], effective_date="2026-08-14", withdrawal_reason="TRANSFER_OUT"
        )
        place_hold(withdrawal["id"], "SPED_EXIT_MEETING")

        response = api_client.complete_withdrawal(withdrawal["id"], OFFICER_1)

        validate_error(response, "ERR_WITHDRAWAL_NOT_CLEARED", 409)

        blocked = _get_withdrawal(withdrawal["id"])
        assert_withdrawal(blocked)
        assert blocked["status"] == "HOLD"
        assert blocked["completed_at"] is None

        stalled = _get_student(student["id"])
        assert stalled["enrollment_status"] == "WITHDRAWAL_PENDING"
        assert stalled["exit_effective_date"] is None
        assert stalled["records_disposition_date"] is None

        untouched = get_file(file_id)
        assert_cumulative_file(untouched)
        assert untouched["assembly_status"] == "NOT_STARTED"
        assert get_retention_schedules(file_id, headers=COMPLIANCE) == [], (
            "no retention schedule is minted while the exit is blocked"
        )


class TestRequestsBeginInTheirDeclaredInitialState:
    def test_a_filed_records_request_lands_in_received_with_every_outcome_field_null(self):
        """Filing alone decides nothing: the request sits in RECEIVED, stamped at
        the clock it arrived on, with authorization unverified and every release
        and denial field still empty.

        PRD: "An accepted filing lands in `RECEIVED` with `received_at` set to the current logical clock instant — the instant from which the statutory window is measured — `authorization_verified` false, `reopen_count` 0, `packet_status` `NONE`, `is_overdue` false, and `packet_page_count`, `included_incident_count`, `withheld_incident_count`, `receiving_state_inclusion_count`, `denial_reason`, `transmission_method`, and `released_at` all null."

        Design: Corner/state_machines/records_and_inspection_requests_start_in_initial_state
        """
        sending, receiving = _two_districts()
        student = create_student(
            sending["id"],
            first_name="Nadia",
            last_name="Farouk",
            dob="2011-02-02",
            grade_level=9,
            has_iep=False,
            guardian_user_id="guardian-nadia",
        )

        request = create_records_request(
            student["id"],
            receiving["id"],
            sending["id"],
            authorization_reference="ENR-2026-9010",
        )

        assert_records_request(request)
        assert request["status"] == "RECEIVED"
        assert request["received_at"] == "2026-08-01T00:00:00.000Z"
        assert request["authorization_verified"] is False
        assert request["reopen_count"] == 0
        assert request["packet_status"] == "NONE"
        assert request["is_overdue"] is False
        assert request["packet_page_count"] is None
        assert request["included_incident_count"] is None
        assert request["withheld_incident_count"] is None
        assert request["receiving_state_inclusion_count"] is None
        assert request["denial_reason"] is None
        assert request["transmission_method"] is None
        assert request["released_at"] is None

    def test_a_filed_inspection_request_begins_in_submitted_with_a_45_day_deadline(self):
        """The parent's own identity is copied onto the row, the request opens in
        SUBMITTED, and the statutory deadline lands 45 calendar days after the
        filing instant at the same time of day.

        PRD: "The request begins in `SUBMITTED` with `inspection_completed_at` null, and its `statutory_inspection_due_at` is pinned to its `created_at` advanced by 45 calendar days at the identical time of day."

        Design: Corner/state_machines/records_and_inspection_requests_start_in_initial_state
        """
        district = _ca_district()
        student = create_student(
            district["id"],
            first_name="Nadia",
            last_name="Farouk",
            dob="2011-02-02",
            grade_level=9,
            has_iep=False,
            guardian_user_id="guardian-nadia",
        )

        inspection = create_inspection_request(
            student["id"],
            make_parent_headers("guardian-nadia"),
            categories=["ACADEMIC"],
            copies_requested=False,
        )

        assert_inspection_request(inspection)
        assert inspection["status"] == "SUBMITTED"
        assert inspection["requester_role"] == "PARENT"
        assert inspection["requester_user_id"] == "guardian-nadia"
        assert inspection["created_at"] == "2026-08-01T00:00:00.000Z"
        assert inspection["statutory_inspection_due_at"] == "2026-09-15T00:00:00.000Z"
        assert inspection["inspection_completed_at"] is None
        assert inspection["fee_assessed_cents"] == 0
        assert inspection["fee_outstanding_cents"] == 0

        reread = get_inspection_request(inspection["id"])
        assert reread["status"] == "SUBMITTED"
        assert reread["statutory_inspection_due_at"] == "2026-09-15T00:00:00.000Z"


class TestSnapshotRequiresTheAssemblingStatus:
    def test_mark_ready_straight_out_of_received_is_refused_on_status(self):
        """The expected-version token matches the file exactly, so the only thing
        wrong with the call is that the request was never validated — and the
        status guard answers rather than the token or the file's completeness.

        PRD: "Next the request's own status must be `ASSEMBLING`; anything else — including a request still parked in `VALIDATED` because the student's file has not started assembling — is refused with `ERR_REQUEST_NOT_ASSEMBLING`, and a `RELEASED` or `DENIED` request is refused with `ERR_REQUEST_TERMINAL`."

        Design: Corner/state_machines/mark_ready_from_received_returns_4xx
        """
        sending, receiving = _two_districts()
        student = create_student(
            sending["id"],
            first_name="Omar",
            last_name="Reyes",
            dob="2010-05-05",
            grade_level=10,
            has_iep=False,
            guardian_user_id="guardian-omar",
        )
        file_id = get_cumulative_file_id(student["id"])
        request = create_records_request(
            student["id"],
            receiving["id"],
            sending["id"],
            authorization_reference="ENR-2026-9011",
        )
        assert _get_request(request["id"])["status"] == "RECEIVED"

        response = api_client.mark_ready_records_request(
            request["id"], mark_ready_payload(get_file(file_id)["version"]), OFFICER_1
        )

        validate_error(response, "ERR_REQUEST_NOT_ASSEMBLING", 409)

        refused = _get_request(request["id"])
        assert_records_request(refused)
        assert refused["status"] == "RECEIVED"
        assert refused["packet_status"] == "NONE"
        assert refused["packet_page_count"] is None
        assert get_file(file_id)["last_packet_snapshot_at"] is None


PIA_PAGES = (("ACADEMIC", 40), ("HEALTH", 20), ("DISCIPLINE", 10), ("SPECIAL_EDUCATION", 30))


def _released_request():
    """A hundred-page packet released over a secure portal, so the request is
    parked in the terminal RELEASED status."""
    sending, receiving = _two_districts()
    student = create_student(
        sending["id"],
        first_name="Pia",
        last_name="Novak",
        dob="2010-09-09",
        grade_level=10,
        has_iep=False,
        guardian_user_id="guardian-pia",
    )
    file_id = get_cumulative_file_id(student["id"])
    components = get_components(file_id)
    for component_type, pages in PIA_PAGES:
        collect_component(file_id, components[component_type]["id"], pages, 0)
        certify_component(file_id, components[component_type]["id"])

    request = create_records_request(
        student["id"],
        receiving["id"],
        sending["id"],
        authorization_reference="ENR-2026-9012",
    )
    validate_request(request["id"])
    mark_ready_request(request["id"], file_id)
    released = release_request(request["id"], "SECURE_PORTAL")
    assert released["status"] == "RELEASED"
    return student, request, released


class TestReleasedRequestIsTerminal:
    def test_neither_a_denial_nor_a_second_release_can_touch_a_released_request(self):
        """Denial is available from three earlier statuses but not from this one,
        and re-releasing is refused on the identical code, so the released row
        keeps its method, its page count and its single disclosure entry.

        PRD: "`RELEASED` and `DENIED` are both terminal: every further action against such a request is refused with `ERR_REQUEST_TERMINAL`."

        Design: Corner/state_machines/deny_after_release_returns_4xx
        """
        student, request, released = _released_request()

        late_denial = api_client.deny_records_request(
            request["id"], deny_payload("DUPLICATE_REQUEST"), OFFICER_1
        )
        validate_error(late_denial, "ERR_REQUEST_TERMINAL", 409)

        second_release = api_client.release_records_request(
            request["id"], release_payload("SECURE_PORTAL"), OFFICER_1
        )
        validate_error(second_release, "ERR_REQUEST_TERMINAL", 409)

        final = _get_request(request["id"])
        assert_records_request(final)
        assert final["status"] == "RELEASED"
        assert final["denial_reason"] is None
        assert final["transmission_method"] == "SECURE_PORTAL"
        assert final["packet_page_count"] == 100
        assert final["released_at"] == released["released_at"]

        entries = get_disclosure_log(student["id"], headers=CLERK)
        assert len(entries) == 1, (
            f"the refused calls must not append a second disclosure, got {len(entries)}"
        )
        assert_disclosure_log_entry(entries[0])
        assert entries[0]["disclosure_type"] == "INTERDISTRICT_TRANSFER"


class TestFileBubblesUpOnTheLastRequiredCertification:
    def test_certifying_the_third_of_three_required_components_pins_the_file_complete(self):
        """Each certification recomputes the percentage — 33.3, then 66.7 — and
        the third one, the last required type, carries the file to COMPLETE at
        100.0 while the optional component is left pending and uncounted.

        PRD: "And the pair `IN_ASSEMBLY → COMPLETE` and `COMPLETE → IN_ASSEMBLY` forms a cycle the file may traverse repeatedly: certifying the last required component bubbles it up to `COMPLETE` and pins `completeness_pct` at 100.0, while excluding, reinstating, or amending any required component bubbles it straight back down and recomputes the percentage."

        Design: Corner/state_machines/last_required_certification_bubbles_file_to_complete
        """
        district = _ca_district()
        student = create_student(
            district["id"],
            first_name="Sana",
            last_name="Iqbal",
            dob="2011-06-06",
            grade_level=9,
            has_iep=False,
            guardian_user_id="guardian-sana",
        )
        file_id = get_cumulative_file_id(student["id"])
        components = get_components(file_id)
        for component_type, pages in (("ACADEMIC", 10), ("HEALTH", 20), ("DISCIPLINE", 30)):
            collect_component(file_id, components[component_type]["id"], pages, 0)

        opened = get_file(file_id)
        assert opened["assembly_status"] == "IN_ASSEMBLY"
        assert len(opened["required_component_types"]) == 3

        expected = ((33.3, "IN_ASSEMBLY"), (66.7, "IN_ASSEMBLY"), (100.0, "COMPLETE"))
        for (component_type, _pages), (pct, status) in zip(
            (("ACADEMIC", 10), ("HEALTH", 20), ("DISCIPLINE", 30)), expected
        ):
            certify_component(file_id, components[component_type]["id"])
            stepped = get_file(file_id)
            assert stepped["completeness_pct"] == pct
            assert stepped["assembly_status"] == status

        complete = get_file(file_id)
        assert_cumulative_file(complete)
        assert complete["certified_component_count"] == 3
        assert complete["total_page_count"] == 60
        assert complete["included_page_count"] == 60
        assert complete["excluded_page_count"] == 0
        assert_page_custody_identity(complete)

        optional = get_components(file_id)["SPECIAL_EDUCATION"]
        assert_file_component(optional)
        assert optional["status"] == "PENDING"
        assert optional["is_required"] is False
        assert optional["page_count"] == 0


def _packet_released_for_a_withdrawn_student():
    """Tomas exits on 2026-08-14, his file is assembled and certified after the
    exit, and the sixty-page packet is released on 2026-08-20 at 10:00."""
    sending, receiving = _two_districts()
    student = create_student(
        sending["id"],
        first_name="Tomas",
        last_name="Weber",
        dob="2010-03-03",
        grade_level=11,
        has_iep=False,
        guardian_user_id="guardian-tomas",
    )
    file_id = get_cumulative_file_id(student["id"])
    withdrawal = create_withdrawal(
        student["id"], effective_date="2026-08-14", withdrawal_reason="TRANSFER_OUT"
    )
    set_clock("2026-08-15T08:00:00Z")
    complete_withdrawal(withdrawal["id"])
    assert _get_student(student["id"])["enrollment_status"] == "WITHDRAWN"

    components = get_components(file_id)
    for component_type, pages in (("ACADEMIC", 10), ("HEALTH", 20), ("DISCIPLINE", 30)):
        collect_component(file_id, components[component_type]["id"], pages, 0)
        certify_component(file_id, components[component_type]["id"])

    request = create_records_request(
        student["id"],
        receiving["id"],
        sending["id"],
        authorization_reference="ENR-2026-9013",
    )
    validate_request(request["id"])
    mark_ready_request(request["id"], file_id)

    set_clock("2026-08-20T10:00:00Z")
    released = release_request(request["id"], "SECURE_PORTAL")
    return student, file_id, request, released


class TestReleaseCompletesTheExit:
    def test_a_withdrawn_student_advances_to_the_terminal_enrollment_state(self):
        """The release itself is unremarkable — 60 pages over a secure portal — but
        because the student was already WITHDRAWN it carries them to
        TRANSFERRED_OUT with the exit date copied from the withdrawal.

        PRD: "A student who is in `WITHDRAWN` at that moment advances `WITHDRAWN → TRANSFERRED_OUT`, the terminal enrollment state; releasing a packet for a student who is still `ENROLLED` is perfectly legal and leaves `enrollment_status` untouched."

        Design: Corner/state_machines/release_for_withdrawn_student_advances_to_transferred_out
        """
        student, _file_id, _request, released = _packet_released_for_a_withdrawn_student()

        assert_records_request(released)
        assert released["status"] == "RELEASED"
        assert released["released_at"] == "2026-08-20T10:00:00.000Z"
        assert released["packet_page_count"] == 60
        assert released["transmission_method"] == "SECURE_PORTAL"

        moved = _get_student(student["id"])
        assert moved["enrollment_status"] == "TRANSFERRED_OUT"
        assert moved["exit_effective_date"] == "2026-08-14"

    def test_the_transfer_disclosure_pushes_the_retention_dates_forward(self):
        """One INTERDISTRICT_TRANSFER entry of exactly sixty pages is logged, and
        the schedule's activity instant becomes that entry's instant while the
        exit-anchored date stays pinned to the 14th.

        PRD: "Because a new disclosure entry now exists, the student's retention schedule has its `last_activity_at` set to that entry's `disclosed_at`, its `destruction_eligible_at` recomputed, and the student's `records_disposition_date` re-mirrored from it."

        Design: Corner/state_machines/release_for_withdrawn_student_advances_to_transferred_out
        """
        student, file_id, _request, _released = _packet_released_for_a_withdrawn_student()

        entries = get_disclosure_log(
            student["id"], headers=CLERK, params={"disclosure_type": "INTERDISTRICT_TRANSFER"}
        )
        assert len(entries) == 1, f"exactly one transfer disclosure, got {len(entries)}"
        assert_disclosure_log_entry(entries[0])
        assert entries[0]["page_count"] == 60
        assert entries[0]["disclosed_at"] == "2026-08-20T10:00:00.000Z"

        schedules = get_retention_schedules(file_id, headers=COMPLIANCE)
        assert len(schedules) == 1
        schedule = schedules[0]
        assert_retention_schedule(schedule)
        assert schedule["last_activity_at"] == "2026-08-20T10:00:00.000Z"
        assert schedule["destruction_eligible_at"] == "2031-08-20T10:00:00.000Z"
        assert schedule["exit_anchor_at"] == "2026-08-14T00:00:00.000Z"
        assert schedule["exit_anchored_eligible_at"] == "2031-08-14T00:00:00.000Z"
        assert schedule["destruction_min_age_years"] == 5

        assert _get_student(student["id"])["records_disposition_date"] == (
            "2031-08-20T10:00:00.000Z"
        )


def _two_demands_for_one_student():
    """A grand-jury subpoena with the notification duty waived, and a judicial
    subpoena that still owes one."""
    district = _ca_district()
    student = create_student(
        district["id"],
        first_name="Ulla",
        last_name="Lindgren",
        dob="2009-11-11",
        grade_level=12,
        has_iep=False,
        guardian_user_id="guardian-ulla",
    )
    waived = create_legal_demand(
        student["id"],
        demand_type="GRAND_JURY_SUBPOENA",
        issuing_authority="County Grand Jury",
        case_reference="GJ-2026-77",
        production_scope=["ACADEMIC", "DISCIPLINE"],
        notification_waived=True,
        waiver_basis="GRAND_JURY_ORDER",
    )
    notifiable = create_legal_demand(
        student["id"],
        demand_type="JUDICIAL_SUBPOENA",
        issuing_authority="Superior Court of CA",
        case_reference="SC-2026-88",
        production_scope=["ACADEMIC"],
    )
    assert waived["status"] == "RECEIVED"
    assert notifiable["status"] == "RECEIVED"
    return student, waived, notifiable


class TestLegalDemandProductionBranches:
    def test_the_waived_branch_produces_at_once_and_leaves_both_instants_null(self):
        """No notification was ever sent, so production is immediate and the two
        notification fields stay null on the produced row, which still logs its
        twelve disclosed pages.

        PRD: "On the **waived branch**, the demand is still in `RECEIVED` with `notification_waived` true and a non-null `waiver_basis`, and it may be produced immediately with no waiting period at all; this branch never sets `notification_sent_at` or `production_allowed_at`, both of which remain null on the produced row."

        Design: Corner/state_machines/legal_demand_waived_branch_skips_notification_fields
        """
        student, waived, notifiable = _two_demands_for_one_student()

        produced = produce_demand(waived["id"], 12)

        assert_legal_demand(produced)
        assert produced["status"] == "PRODUCED"
        assert produced["produced_at"] == "2026-08-01T00:00:00.000Z"
        assert produced["produced_page_count"] == 12
        assert produced["notification_sent_at"] is None
        assert produced["production_allowed_at"] is None
        assert produced["notified_party"] is None

        assert _get_demand(notifiable["id"])["status"] == "RECEIVED"

        entries = get_disclosure_log(
            student["id"], headers=CLERK, params={"disclosure_type": "LEGAL_DEMAND"}
        )
        assert len(entries) == 1, f"only the produced demand is logged, got {len(entries)}"
        assert_disclosure_log_entry(entries[0])
        assert entries[0]["source_type"] == "LEGAL_DEMAND"
        assert entries[0]["source_id"] == waived["id"]
        assert entries[0]["page_count"] == 12

    def test_the_notified_sibling_earns_a_waiting_period_instead(self):
        """The judicial subpoena owes a notification, and discharging it stamps
        the send instant and pushes production seven days out under the governing
        state rule.

        PRD: "On success the party is recorded, `notification_sent_at` is set to the current logical clock instant, `production_allowed_at` is computed as that instant advanced by the `notification_wait_days` of the state rule governing the student's district at the identical time of day, and the demand moves `RECEIVED → NOTIFIED`."

        Design: Corner/state_machines/legal_demand_waived_branch_skips_notification_fields
        """
        _student, waived, notifiable = _two_demands_for_one_student()

        notified = notify_demand(notifiable["id"], notified_party="PARENT")

        assert_legal_demand(notified)
        assert notified["status"] == "NOTIFIED"
        assert notified["notified_party"] == "PARENT"
        assert notified["notification_sent_at"] == "2026-08-01T00:00:00.000Z"
        assert notified["production_allowed_at"] == "2026-08-08T00:00:00.000Z"
        assert notified["produced_at"] is None
        assert notified["produced_page_count"] is None

        assert _get_demand(waived["id"])["notification_sent_at"] is None


class TestRebookingSupersedesTheStandingAppointment:
    def test_the_second_booking_stands_and_the_first_is_marked_superseded(self):
        """Booking again with a fresh version token is the supported reschedule:
        the earlier appointment moves to SUPERSEDED unattended, the new one holds
        the slot, and the request's own version has moved twice.

        PRD: "Any appointment of that same request already in `SCHEDULED` moves `SCHEDULED → SUPERSEDED` and releases its room interval, so the superseded interval no longer participates in overlap detection."

        Design: Corner/state_machines/second_appointment_supersedes_prior_scheduled_appointment
        """
        district = _ca_district()
        room = create_inspection_room(
            room_code="RM-201", seats=4, site_name="District Office"
        )
        student = create_student(
            district["id"],
            first_name="Vero",
            last_name="Castillo",
            dob="2010-08-08",
            grade_level=10,
            has_iep=False,
            guardian_user_id="guardian-vero",
        )
        request = create_inspection_request(
            student["id"],
            make_parent_headers("guardian-vero"),
            categories=["ACADEMIC"],
            copies_requested=False,
        )
        assert request["version"] == 1

        first = book_appointment(
            request["id"], room["id"], "2026-08-05T09:00:00Z", "2026-08-05T10:00:00Z", 1
        )
        assert first["status"] == "SCHEDULED"
        assert get_inspection_request(request["id"])["version"] == 2

        second = book_appointment(
            request["id"], room["id"], "2026-08-06T09:00:00Z", "2026-08-06T10:00:00Z", 2
        )

        assert_review_appointment(second)
        assert second["status"] == "SCHEDULED"
        assert second["duration_minutes"] == 60
        assert second["attended_at"] is None

        superseded = _get_appointment(first["id"])
        assert superseded["status"] == "SUPERSEDED"
        assert superseded["attended_at"] is None

        rescheduled = get_inspection_request(request["id"])
        assert rescheduled["status"] == "SCHEDULED"
        assert rescheduled["version"] == 3

        both, _meta = validate_paginated(
            api_client.list_review_appointments(
                OFFICER_1, params={"inspection_request_id": request["id"]}
            )
        )
        assert len(both) == 2, f"both appointments remain readable, got {len(both)}"

        still_standing, _meta = validate_paginated(
            api_client.list_review_appointments(
                OFFICER_1,
                params={"inspection_request_id": request["id"], "status": "SCHEDULED"},
            )
        )
        assert len(still_standing) == 1
        assert still_standing[0]["id"] == second["id"]


class TestSweepExpiresInspectionRequestsStrictlyAfterTheDeadline:
    def test_the_deadline_instant_itself_survives_the_sweep_and_one_millisecond_later_does_not(self):
        """Parked exactly on statutory_inspection_due_at the sweep leaves the
        request in SUBMITTED, because the deadline must be strictly earlier than
        the clock; one millisecond later the identical sweep expires it.

        PRD: "A request left unscheduled past that deadline is expired by the compliance sweep: any request still in `SUBMITTED` whose `statutory_inspection_due_at` is strictly earlier than the current logical clock instant moves `SUBMITTED → EXPIRED`."

        Design: Corner/state_machines/sweep_expires_inspection_request_only_strictly_after_due_instant
        """
        district = _ca_district()
        student = create_student(
            district["id"],
            first_name="Wren",
            last_name="Abara",
            dob="2011-01-01",
            grade_level=9,
            has_iep=False,
            guardian_user_id="guardian-wren",
        )
        request = create_inspection_request(
            student["id"],
            make_parent_headers("guardian-wren"),
            categories=["ACADEMIC", "HEALTH"],
            copies_requested=False,
        )
        assert request["statutory_inspection_due_at"] == "2026-09-15T00:00:00.000Z"

        set_clock("2026-09-15T00:00:00Z")
        run_sweep()

        on_the_boundary = get_inspection_request(request["id"])
        assert_inspection_request(on_the_boundary)
        assert on_the_boundary["status"] == "SUBMITTED"
        assert on_the_boundary["inspection_completed_at"] is None

        set_clock("2026-09-15T00:00:00.001Z")
        run_sweep()

        expired = get_inspection_request(request["id"])
        assert expired["status"] == "EXPIRED"
        assert expired["inspection_completed_at"] is None

        appointments, _meta = validate_paginated(
            api_client.list_review_appointments(
                OFFICER_1, params={"inspection_request_id": request["id"]}
            )
        )
        assert appointments == [], "an expired request never held an appointment"


def _upheld_challenge_over_a_fifty_page_component():
    """A certified fifty-page ACADEMIC component, challenged, denied by one
    officer, heard, and upheld by a second officer at 2026-08-10T10:00Z."""
    district = _ca_district()
    officer = create_hearing_officer(
        full_name="Hollis Vance", credential="DISTRICT_DESIGNEE"
    )
    student = create_student(
        district["id"],
        first_name="Xan",
        last_name="Oyelaran",
        dob="2009-04-04",
        grade_level=12,
        has_iep=False,
        guardian_user_id="guardian-xan",
    )
    parent = make_parent_headers("guardian-xan")
    file_id = get_cumulative_file_id(student["id"])
    academic = get_components(file_id)["ACADEMIC"]
    collect_component(file_id, academic["id"], 50, 0)
    certify_component(file_id, academic["id"])

    amendment = create_amendment(
        student["id"],
        academic["id"],
        parent,
        contested_field="final_grade_math_8",
        requested_change="Change the recorded D to a C",
        rationale="The re-graded final exam was never entered",
    )
    decide_amendment(amendment["id"], "DENY", OFFICER_1, decision_note="Grade matches the gradebook")
    request_hearing(amendment["id"], parent)
    schedule_hearing(
        amendment["id"], officer["id"], "2026-08-10T09:00:00Z", "2026-08-10T10:00:00Z"
    )
    set_clock("2026-08-10T10:00:00Z")
    upheld = decide_amendment(
        amendment["id"], "DENY", OFFICER_2, decision_note="The hearing confirms the record"
    )
    assert upheld["status"] == "UPHELD"
    return student, file_id, academic, amendment, parent


class TestStatementOfDisagreementJoinsTheRecord:
    def test_filing_the_statement_adds_exactly_one_page_to_the_contested_component(self):
        """The upheld record cannot change, but the annotation is stored, the flag
        is raised, and the component grows from fifty pages to fifty-one while
        staying certified and unamended.

        PRD: "The statement then becomes part of the record: the contested component's `statement_of_disagreement_present` is set true and its `page_count` grows by exactly one page, the statement's own page."

        Design: Corner/state_machines/statement_of_disagreement_syncs_component_and_file_pages
        """
        _student, file_id, academic, amendment, parent = (
            _upheld_challenge_over_a_fifty_page_component()
        )

        filed = file_statement(
            amendment["id"], parent, statement_text="The re-graded exam is still missing."
        )

        assert_amendment_request(filed)
        assert filed["status"] == "STATEMENT_FILED"
        assert filed["statement_filed_at"] == "2026-08-10T10:00:00.000Z"
        assert filed["initial_decided_by_user_id"] == "officer-1"
        assert filed["hearing_decided_by_user_id"] == "officer-2"
        assert filed["hearing_due_at"] == "2026-08-31T00:00:00.000Z"
        assert filed["hearing_duration_minutes"] == 60

        annotated = get_components(file_id)["ACADEMIC"]
        assert_file_component(annotated)
        assert annotated["id"] == academic["id"]
        assert annotated["statement_of_disagreement_present"] is True
        assert annotated["page_count"] == 51
        assert annotated["status"] == "CERTIFIED"
        assert annotated["amendment_count"] == 0

    def test_the_parent_file_recounts_its_pages_and_moves_its_version(self):
        """Because a child page count changed, the file's three page counters all
        land on 51 and its version moves on, invalidating any expected-version
        token an officer was holding.

        PRD: "Because the component's page count changed, the parent cumulative file's `total_page_count`, `included_page_count`, and `disclosable_page_count` are recomputed and the file's `version` is incremented by one — so a statement filed after a packet snapshot invalidates the expected-version token any officer was holding."

        Design: Corner/state_machines/statement_of_disagreement_syncs_component_and_file_pages
        """
        _student, file_id, _academic, amendment, parent = (
            _upheld_challenge_over_a_fifty_page_component()
        )
        before = get_file(file_id)
        assert before["total_page_count"] == 50

        file_statement(
            amendment["id"], parent, statement_text="The re-graded exam is still missing."
        )

        after = get_file(file_id)
        assert_cumulative_file(after)
        assert after["total_page_count"] == 51
        assert after["included_page_count"] == 51
        assert after["disclosable_page_count"] == 51
        assert after["excluded_page_count"] == 0
        assert_page_custody_identity(after)
        assert after["version"] == before["version"] + 1
        assert after["certified_component_count"] == 1
        assert after["completeness_pct"] == 33.3
