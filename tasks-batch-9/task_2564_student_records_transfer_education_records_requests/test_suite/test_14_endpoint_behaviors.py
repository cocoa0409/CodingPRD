"""Endpoint surfaces read back exactly what the contract says they store.

Room registration with its paged and filtered listing, the two legal-demand
action endpoints and every guard on them, the sorted hold set of a withdrawal,
the release gate and its ex parte hold, the compliance sweep's reach, and the
three link rules on an inter-district filing.
"""
from test_helpers import (
    ADMIN,
    CLERK,
    COMPLIANCE,
    LEGAL,
    OFFICER_1,
    api_client,
    assert_disclosure_log_entry,
    assert_inspection_room,
    assert_legal_demand,
    assert_records_request,
    assert_review_appointment,
    assert_withdrawal,
    book_appointment,
    certify_component,
    collect_component,
    create_district,
    create_inspection_request,
    create_inspection_room,
    create_legal_demand,
    create_records_request,
    create_state_rule,
    create_student,
    create_withdrawal,
    deny_request,
    get_components,
    get_cumulative_file_id,
    get_disclosure_log,
    get_inspection_request,
    inspection_room_payload,
    legal_demand_payload,
    make_parent_headers,
    make_receiving_registrar_headers,
    mark_ready_request,
    notification_payload,
    notify_demand,
    place_hold,
    produce_demand,
    production_payload,
    records_request_payload,
    release_hold,
    release_payload,
    run_sweep,
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


def _sending_district():
    """The CA rule plus the SEND01 district that holds the record."""
    create_state_rule("CA", **CA_RULE)
    return create_district("SEND01", state_code="CA", name="Sending Unified")


def _two_districts():
    """SEND01 (CA) responds and RECV01 (TX) requests."""
    create_state_rule("CA", **CA_RULE)
    create_state_rule("TX", **TX_RULE)
    sending = create_district("SEND01", state_code="CA", name="Sending Unified")
    receiving = create_district("RECV01", state_code="TX", name="Receiving Unified")
    return sending, receiving


def _rooms(headers=None, params=None):
    return validate_success(
        api_client.list_inspection_rooms(headers or CLERK, params=params)
    )


def _room_page(params, headers=None):
    return validate_paginated(api_client.list_inspection_rooms(headers or CLERK, params=params))


def _get_demand(demand_id):
    return validate_success(api_client.get_legal_demand(demand_id, LEGAL))


def _get_withdrawal(withdrawal_id):
    return validate_success(api_client.get_withdrawal(withdrawal_id, OFFICER_1))


def _withdrawals_of(student_id, params=None):
    return validate_success(
        api_client.list_student_withdrawals(student_id, CLERK, params=params)
    )


def _get_request(request_id):
    return validate_success(api_client.get_records_request(request_id, OFFICER_1))


def _get_district(district_id):
    return validate_success(api_client.get_district(district_id, ADMIN))


def _certify_three(file_id, pages=(("ACADEMIC", 10), ("HEALTH", 20), ("DISCIPLINE", 30))):
    """Collect and certify the three required components at the given page
    counts, leaving the file COMPLETE."""
    components = get_components(file_id)
    for component_type, page_count in pages:
        component_id = components[component_type]["id"]
        collect_component(file_id, component_id, page_count)
        certify_component(file_id, component_id)
    return components


def _three_rooms():
    """ROOM-A (4 seats), ROOM-B (2) and ROOM-C (8), registered in that order."""
    room_a = create_inspection_room("ROOM-A", 4, site_name="District Office")
    room_b = create_inspection_room("ROOM-B", 2, site_name="North Annex")
    room_c = create_inspection_room("ROOM-C", 8, site_name="Records Center")
    for room in (room_a, room_b, room_c):
        assert_inspection_room(room)
        assert room["status"] == "ACTIVE", "a new room begins ACTIVE"
    return room_a, room_b, room_c


class TestInspectionRoomSurface:
    def test_the_by_id_read_echoes_the_row_and_the_listing_pages_it(self):
        """Each room comes back with the code, site and capacity it was
        registered with and a status nobody supplied, and the three of them page
        two-then-one with total_count reporting the whole match either way.

        PRD: "Both are echoed back in the `meta` object of the envelope alongside `total_count`, the number of items matching the query before pagination, and `has_more`, which is true whenever items remain beyond the current page."

        Design: Corner/endpoints/inspection_room_crud_and_status_filtered_pagination
        """
        room_a, _room_b, _room_c = _three_rooms()

        one = validate_success(api_client.get_inspection_room(room_a["id"], OFFICER_1))
        assert_inspection_room(one)
        assert one["id"] == room_a["id"]
        assert one["room_code"] == "ROOM-A"
        assert one["seats"] == 4
        assert one["site_name"] == "District Office"
        assert one["created_at"] == room_a["created_at"]
        assert one["status"] == "ACTIVE"

        first_page, first_meta = _room_page({"limit": 2, "offset": 0})
        assert len(first_page) == 2
        assert first_meta["total_count"] == 3
        assert first_meta["limit"] == 2
        assert first_meta["offset"] == 0
        assert first_meta["has_more"] is True

        last_page, last_meta = _room_page({"limit": 2, "offset": 2})
        assert len(last_page) == 1
        assert last_meta["total_count"] == 3
        assert last_meta["offset"] == 2
        assert last_meta["has_more"] is False

    def test_closing_one_room_narrows_the_status_filter_while_its_code_stays_taken(self):
        """A room closed by the admin drops out of ?status=ACTIVE without leaving
        the collection, and its code is still spoken for, so a fresh registration
        reusing ROOM-A is refused.

        PRD: "An **inspection room** carries a `room_code` that is globally unique across rooms — a duplicate is refused with `ERR_DUPLICATE_ROOM_CODE` — and between 2 and 12 characters long, a `site_name` naming the building or office, a `seats` capacity of at least 1 and at most 40, and a `status` of `ACTIVE` or `CLOSED` that begins as `ACTIVE`."

        Design: Corner/endpoints/inspection_room_crud_and_status_filtered_pagination
        """
        room_a, room_b, room_c = _three_rooms()

        closed = validate_success(
            api_client.update_inspection_room(room_b["id"], {"status": "CLOSED"}, ADMIN)
        )
        assert_inspection_room(closed)
        assert closed["id"] == room_b["id"]
        assert closed["status"] == "CLOSED"

        active = _rooms(params={"status": "ACTIVE"}, headers=COMPLIANCE)
        assert sorted(room["id"] for room in active) == sorted(
            [room_a["id"], room_c["id"]]
        )

        duplicate = api_client.create_inspection_room(
            inspection_room_payload(
                room_code="ROOM-A", site_name="Duplicate Site", seats=1
            ),
            ADMIN,
        )

        validate_error(duplicate, "ERR_DUPLICATE_ROOM_CODE", 409)

        _unfiltered, meta = _room_page({})
        assert meta["total_count"] == 3, "the closed room is still a room"


def _one_waived_and_one_unwaived_demand():
    """Pilar's file carries a JUDICIAL_SUBPOENA that still owes a notification
    and a LAW_ENFORCEMENT_REQUEST whose notification is waived."""
    district = _sending_district()
    student = create_student(
        district["id"],
        first_name="Pilar",
        last_name="Quiroga",
        dob="2012-05-17",
        grade_level=8,
        has_iep=False,
        guardian_user_id="guardian-pilar",
    )
    unwaived = create_legal_demand(
        student["id"],
        demand_type="JUDICIAL_SUBPOENA",
        issuing_authority="Superior Court of CA",
        case_reference="CV-2026-4411",
        production_scope=["ACADEMIC"],
    )
    waived = create_legal_demand(
        student["id"],
        demand_type="LAW_ENFORCEMENT_REQUEST",
        issuing_authority="City Police Department",
        case_reference="LE-2026-0087",
        production_scope=["DISCIPLINE"],
        notification_waived=True,
        waiver_basis="LAW_ENFORCEMENT_DIRECTIVE",
    )
    assert_legal_demand(unwaived)
    assert unwaived["notification_waived"] is False
    assert unwaived["status"] == "RECEIVED"
    assert unwaived["received_at"] == "2026-08-01T00:00:00.000Z"
    assert unwaived["notified_party"] is None
    assert unwaived["notification_sent_at"] is None
    assert unwaived["production_allowed_at"] is None
    assert unwaived["produced_at"] is None
    assert unwaived["produced_page_count"] is None
    return student, unwaived, waived


class TestLegalDemandActionGuards:
    def test_the_notification_duty_is_owed_once_and_only_by_an_unwaived_demand(self):
        """Producing before notifying is refused on the unwaived demand, notifying
        is refused on the waived one, and the notification that does land moves the
        demand out of RECEIVED so a second one has nothing to discharge.

        PRD: "The demand must be in `RECEIVED` — a `NOTIFIED` demand is refused with `ERR_DEMAND_NOT_RECEIVED` and a `PRODUCED` one with `ERR_DEMAND_ALREADY_PRODUCED` — and its `notification_waived` must be false, since notifying under a waived instrument is refused with `ERR_NOTIFICATION_WAIVED`."

        Design: Corner/endpoints/legal_demand_notification_and_production_action_guards
        """
        _student, unwaived, waived = _one_waived_and_one_unwaived_demand()

        too_early = api_client.create_demand_production(
            unwaived["id"], production_payload(40), LEGAL
        )
        validate_error(too_early, "ERR_NOTIFICATION_REQUIRED", 422)

        pointless = api_client.create_demand_notification(
            waived["id"], notification_payload("PARENT"), LEGAL
        )
        validate_error(pointless, "ERR_NOTIFICATION_WAIVED", 409)

        notified = validate_success(
            api_client.create_demand_notification(
                unwaived["id"], notification_payload("PARENT"), LEGAL
            )
        )
        assert_legal_demand(notified)
        assert notified["status"] == "NOTIFIED"
        assert notified["notified_party"] == "PARENT"
        assert notified["notification_sent_at"] == "2026-08-01T00:00:00.000Z"
        assert notified["production_allowed_at"] == "2026-08-08T00:00:00.000Z", (
            "seven notification_wait_days at the identical time of day"
        )

        again = api_client.create_demand_notification(
            unwaived["id"], notification_payload("PARENT"), LEGAL
        )
        validate_error(again, "ERR_DEMAND_NOT_RECEIVED", 409)

        assert _get_demand(waived["id"])["status"] == "RECEIVED"

    def test_the_waiting_period_is_inclusive_and_production_happens_exactly_once(self):
        """One millisecond short of production_allowed_at the demand is still
        frozen; at the instant itself it produces, logs the disclosure, and refuses
        every further production.

        PRD: "On the **notified branch**, the demand is in `NOTIFIED` and the current logical clock instant must be at or after `production_allowed_at`; the boundary is inclusive, so production at exactly that instant succeeds while production one millisecond earlier is refused with `ERR_NOTIFICATION_WAIT_NOT_ELAPSED`."

        Design: Corner/endpoints/legal_demand_notification_and_production_action_guards
        """
        student, unwaived, _waived = _one_waived_and_one_unwaived_demand()
        notify_demand(unwaived["id"], notified_party="PARENT")

        set_clock("2026-08-07T23:59:59.999Z")
        one_ms_short = api_client.create_demand_production(
            unwaived["id"], production_payload(40), LEGAL
        )
        validate_error(one_ms_short, "ERR_NOTIFICATION_WAIT_NOT_ELAPSED", 409)
        assert _get_demand(unwaived["id"])["status"] == "NOTIFIED"

        set_clock("2026-08-08T00:00:00Z")
        produced = validate_success(
            api_client.create_demand_production(
                unwaived["id"], production_payload(40), LEGAL
            )
        )
        assert_legal_demand(produced)
        assert produced["status"] == "PRODUCED"
        assert produced["produced_at"] == "2026-08-08T00:00:00.000Z"
        assert produced["produced_page_count"] == 40

        repeat = api_client.create_demand_production(
            unwaived["id"], production_payload(40), LEGAL
        )
        validate_error(repeat, "ERR_DEMAND_ALREADY_PRODUCED", 409)

        log = get_disclosure_log(student["id"])
        assert len(log) == 1, f"exactly one disclosure was made, got {len(log)}"
        assert_disclosure_log_entry(log[0])
        assert log[0]["disclosure_type"] == "LEGAL_DEMAND"
        assert log[0]["source_type"] == "LEGAL_DEMAND"
        assert log[0]["source_id"] == unwaived["id"]
        assert log[0]["page_count"] == 40

    def test_a_waived_docket_entry_with_no_basis_never_reaches_the_docket(self):
        """The waiver pairing is a payload condition, so a waived demand that
        names no basis is refused at the door and the student's docket still holds
        only the two demands that were properly paired.

        PRD: "The pairing rules are strict and are checked as payload conditions: a waived demand must carry a `waiver_basis`, a non-waived demand must leave it absent or null, `GRAND_JURY_ORDER` is accepted only alongside a `GRAND_JURY_SUBPOENA`, and `EX_PARTE_COURT_ORDER` only alongside an `EX_PARTE_ORDER`."

        Design: Corner/endpoints/legal_demand_notification_and_production_action_guards
        """
        student, _unwaived, _waived = _one_waived_and_one_unwaived_demand()

        response = api_client.create_legal_demand(
            student["id"],
            legal_demand_payload(
                demand_type="GRAND_JURY_SUBPOENA",
                issuing_authority="County Grand Jury",
                case_reference="GJ-2026-0002",
                production_scope=["DISCIPLINE"],
                notification_waived=True,
            ),
            LEGAL,
        )

        validate_error(response, "ERR_WAIVER_BASIS_REQUIRED", 400)

        docket = validate_success(
            api_client.list_student_legal_demands(student["id"], LEGAL)
        )
        assert len(docket) == 2, f"the refused demand was never docketed, got {len(docket)}"


def _quinn_with_three_holds():
    """Quinn's withdrawal to TXD-9 collects holds in the order MEAL_ACCOUNT,
    LIBRARY_FINE, UNRETURNED_PROPERTY."""
    district = _sending_district()
    student = create_student(
        district["id"],
        first_name="Quinn",
        last_name="Adeyemi",
        dob="2012-06-18",
        grade_level=9,
        has_iep=False,
        guardian_user_id="guardian-quinn",
    )
    withdrawal = create_withdrawal(
        student["id"],
        effective_date="2026-08-14",
        destination_district_code="TXD-9",
        withdrawal_reason="MOVED",
    )
    assert_withdrawal(withdrawal)
    assert withdrawal["status"] == "CLEARED"
    assert withdrawal["hold_count"] == 0
    assert withdrawal["active_hold_types"] == []
    assert withdrawal["destination_district_code"] == "TXD-9"
    assert withdrawal["completed_at"] is None
    for hold_type in ("MEAL_ACCOUNT", "LIBRARY_FINE", "UNRETURNED_PROPERTY"):
        place_hold(withdrawal["id"], hold_type)
    return student, withdrawal


class TestWithdrawalHoldSet:
    def test_the_hold_list_reads_back_sorted_rather_than_in_call_order(self):
        """The three holds were placed meal-first, but the stored list is ordered
        by enum name, and the count follows the list rather than the number of
        calls that were made.

        PRD: "The type is appended to `active_hold_types`, which is kept sorted ascending by enum name, `hold_count` is set to the number of entries in that list, and the withdrawal moves `CLEARED → HOLD`."

        Design: Corner/endpoints/withdrawal_hold_set_is_a_computed_sorted_read
        """
        student, withdrawal = _quinn_with_three_holds()

        held = _get_withdrawal(withdrawal["id"])

        assert_withdrawal(held)
        assert held["active_hold_types"] == [
            "LIBRARY_FINE",
            "MEAL_ACCOUNT",
            "UNRETURNED_PROPERTY",
        ]
        assert held["hold_count"] == 3
        assert held["status"] == "HOLD"

        exiting = validate_success(api_client.get_student(student["id"], CLERK))
        assert exiting["enrollment_status"] == "WITHDRAWAL_PENDING"

    def test_releasing_the_middle_entry_leaves_the_other_two_in_order(self):
        """Releasing MEAL_ACCOUNT removes that one entry and nothing else: two
        holds remain, the withdrawal stays in HOLD, and the status filter finds it
        there rather than among the cleared.

        PRD: "A release while two or more holds are active removes that one entry and is another `HOLD → HOLD` transition, leaving `hold_count` at one or more; the final release — the one taken while `hold_count` is exactly 1 — empties `active_hold_types`, returns `hold_count` to 0, and moves the withdrawal `HOLD → CLEARED`."

        Design: Corner/endpoints/withdrawal_hold_set_is_a_computed_sorted_read
        """
        student, withdrawal = _quinn_with_three_holds()

        release_hold(withdrawal["id"], "MEAL_ACCOUNT")

        remaining = _get_withdrawal(withdrawal["id"])
        assert_withdrawal(remaining)
        assert remaining["active_hold_types"] == ["LIBRARY_FINE", "UNRETURNED_PROPERTY"]
        assert remaining["hold_count"] == 2
        assert remaining["status"] == "HOLD"

        on_hold = _withdrawals_of(student["id"], params={"status": "HOLD"})
        assert len(on_hold) == 1
        assert on_hold[0]["id"] == withdrawal["id"]

        cleared = _withdrawals_of(student["id"], params={"status": "CLEARED"})
        assert cleared == [], "the only withdrawal is still holding"


def _rafa_with_an_ex_parte_order_over_a_validated_request():
    """Rafa's file is COMPLETE at 60 pages, an EX_PARTE_ORDER sits unexecuted on
    the student, and RECV01's request has been validated into ASSEMBLING."""
    sending, receiving = _two_districts()
    student = create_student(
        sending["id"],
        first_name="Rafa",
        last_name="Solano",
        dob="2012-07-19",
        grade_level=9,
        has_iep=False,
        guardian_user_id="guardian-rafa",
    )
    file_id = get_cumulative_file_id(student["id"])
    _certify_three(file_id)
    order = create_legal_demand(
        student["id"],
        demand_type="EX_PARTE_ORDER",
        issuing_authority="Superior Court of CA",
        case_reference="EX-2026-0001",
        production_scope=["ACADEMIC", "HEALTH", "DISCIPLINE"],
        notification_waived=True,
        waiver_basis="EX_PARTE_COURT_ORDER",
    )
    request = create_records_request(
        student["id"],
        receiving["id"],
        sending["id"],
        authorization_reference="ENR-2026-9050",
    )
    validated = validate_request(request["id"])
    assert validated["status"] == "ASSEMBLING", (
        "the file is already COMPLETE, so VALIDATED bubbles on immediately"
    )
    return sending, student, file_id, order, request


class TestReleaseGate:
    def test_release_before_the_packet_is_frozen_is_refused(self):
        """Nothing has been snapshotted while the request sits in ASSEMBLING, so
        release is refused there; only the mark-ready call freezes the sixty-page
        packet that release exists to transmit.

        PRD: "The request must be in `READY_FOR_RELEASE` — a request reopened to `ASSEMBLING` by a component change is refused with `ERR_REQUEST_NOT_READY` — and its `packet_status` must be `SNAPSHOT`."

        Design: Corner/endpoints/release_is_conditional_on_ready_state_and_ex_parte_clearance
        """
        _sending, _student, file_id, _order, request = (
            _rafa_with_an_ex_parte_order_over_a_validated_request()
        )

        premature = api_client.release_records_request(
            request["id"], release_payload("SECURE_PORTAL"), OFFICER_1
        )
        validate_error(premature, "ERR_REQUEST_NOT_READY", 409)

        ready = mark_ready_request(request["id"], file_id)
        assert_records_request(ready)
        assert ready["status"] == "READY_FOR_RELEASE"
        assert ready["packet_status"] == "SNAPSHOT"
        assert ready["packet_page_count"] == 60

    def test_the_ex_parte_hold_lifts_only_once_that_order_is_produced(self):
        """A frozen packet is still not releasable while the ex parte order sits in
        RECEIVED; producing the order clears the block, and the release then logs
        the transfer beside the demand's own disclosure.

        PRD: "An unexecuted ex parte order freezes the file against outbound transfer: while the student has any legal demand whose `demand_type` is `EX_PARTE_ORDER` and whose status is `RECEIVED` or `NOTIFIED`, release is refused with `ERR_EX_PARTE_HOLD_ACTIVE`, and producing that demand clears the block."

        Design: Corner/endpoints/release_is_conditional_on_ready_state_and_ex_parte_clearance
        """
        sending, student, file_id, order, request = (
            _rafa_with_an_ex_parte_order_over_a_validated_request()
        )
        mark_ready_request(request["id"], file_id)

        blocked = api_client.release_records_request(
            request["id"], release_payload("SECURE_PORTAL"), OFFICER_1
        )
        validate_error(blocked, "ERR_EX_PARTE_HOLD_ACTIVE", 409)
        assert _get_request(request["id"])["status"] == "READY_FOR_RELEASE"

        executed = produce_demand(order["id"], 60)
        assert executed["status"] == "PRODUCED"

        released = validate_success(
            api_client.release_records_request(
                request["id"], release_payload("SECURE_PORTAL"), OFFICER_1
            )
        )
        assert_records_request(released)
        assert released["status"] == "RELEASED"
        assert released["transmission_method"] == "SECURE_PORTAL"
        assert released["released_at"] == "2026-08-01T00:00:00.000Z"

        assert _get_district(sending["id"])["open_request_count"] == 0

        log = get_disclosure_log(student["id"])
        assert len(log) == 2, f"one demand production and one transfer, got {len(log)}"
        by_type = {entry["disclosure_type"]: entry for entry in log}
        assert set(by_type) == {"LEGAL_DEMAND", "INTERDISTRICT_TRANSFER"}
        assert by_type["LEGAL_DEMAND"]["source_id"] == order["id"]
        assert by_type["LEGAL_DEMAND"]["page_count"] == 60
        assert by_type["INTERDISTRICT_TRANSFER"]["source_type"] == "RECORDS_REQUEST"
        assert by_type["INTERDISTRICT_TRANSFER"]["source_id"] == request["id"]
        assert by_type["INTERDISTRICT_TRANSFER"]["page_count"] == 60


def _two_inspections_and_one_transfer_at_the_default_clock():
    """Tess's inspection is booked into ROOM-A for 2026-08-05 and Ulf's is left
    unscheduled; a transfer request for Tess is filed the same instant."""
    sending, receiving = _two_districts()
    room = create_inspection_room("ROOM-A", 4, site_name="District Office")
    tess = create_student(
        sending["id"],
        first_name="Tess",
        last_name="Novak",
        dob="2012-08-20",
        grade_level=9,
        has_iep=False,
        guardian_user_id="guardian-tess",
    )
    ulf = create_student(
        sending["id"],
        first_name="Ulf",
        last_name="Sorensen",
        dob="2012-09-21",
        grade_level=9,
        has_iep=False,
        guardian_user_id="guardian-ulf",
    )
    scheduled = create_inspection_request(
        tess["id"], make_parent_headers("guardian-tess"), categories=["ACADEMIC"]
    )
    submitted = create_inspection_request(
        ulf["id"], make_parent_headers("guardian-ulf"), categories=["ACADEMIC"]
    )
    assert submitted["statutory_inspection_due_at"] == "2026-09-15T00:00:00.000Z"
    appointment = book_appointment(
        scheduled["id"],
        room["id"],
        "2026-08-05T09:00:00Z",
        "2026-08-05T10:00:00Z",
        expected_version=scheduled["version"],
    )
    assert_review_appointment(appointment)
    assert appointment["status"] == "SCHEDULED"
    request = create_records_request(
        tess["id"],
        receiving["id"],
        sending["id"],
        authorization_reference="ENR-2026-9060",
    )
    return scheduled, submitted, appointment, request


def _appointment(appointment_id):
    return validate_success(
        api_client.get_review_appointment(appointment_id, COMPLIANCE)
    )


class TestComplianceSweepReach:
    def test_one_sweep_flags_the_overdue_transfer_and_expires_the_lapsed_appointment(self):
        """At 2026-08-15 the request's window has closed and the appointment's hour
        has passed, so the sweep sets one flag and expires one appointment while
        leaving both inspection requests exactly where they stand.

        PRD: "The sweep sets `is_overdue` true on every request whose status is `RECEIVED`, `VALIDATED`, `ASSEMBLING`, or `READY_FOR_RELEASE` and whose `statutory_due_at` is strictly earlier than the current logical clock instant — at exactly the due instant the request is not yet overdue."

        Design: Corner/endpoints/compliance_sweep_touches_four_families_and_is_idempotent
        """
        scheduled, submitted, appointment, request = (
            _two_inspections_and_one_transfer_at_the_default_clock()
        )

        filed = _get_request(request["id"])
        assert_records_request(filed)
        assert filed["received_at"] == "2026-08-01T00:00:00.000Z"
        assert filed["statutory_days_allowed"] == 10
        assert filed["statutory_due_at"] == "2026-08-14T23:59:59.999Z"
        assert filed["is_overdue"] is False

        set_clock("2026-08-15T00:00:00Z")
        run_sweep()

        swept = _get_request(request["id"])
        assert swept["is_overdue"] is True
        assert swept["status"] == "RECEIVED", "the sweep never moves the routing status"
        assert _appointment(appointment["id"])["status"] == "EXPIRED"
        assert get_inspection_request(scheduled["id"])["status"] == "SCHEDULED"
        assert get_inspection_request(submitted["id"])["status"] == "SUBMITTED"

    def test_a_second_sweep_changes_nothing_and_a_scheduled_request_never_expires(self):
        """Run again at the same instant the sweep finds nothing left to do, and
        when the clock passes the inspection deadline only the request still in
        SUBMITTED expires — the scheduled one is outside the sweep's input set.

        PRD: "A `ComplianceOfficer` runs a compliance sweep, which takes no payload and is idempotent with respect to the logical clock: run twice at the same instant, the second run finds nothing left to change."

        Design: Corner/endpoints/compliance_sweep_touches_four_families_and_is_idempotent
        """
        scheduled, submitted, appointment, request = (
            _two_inspections_and_one_transfer_at_the_default_clock()
        )
        set_clock("2026-08-15T00:00:00Z")
        run_sweep()

        validate_success(api_client.run_compliance_sweep(COMPLIANCE))

        assert _get_request(request["id"])["is_overdue"] is True
        assert _appointment(appointment["id"])["status"] == "EXPIRED"
        assert get_inspection_request(submitted["id"])["status"] == "SUBMITTED"

        set_clock("2026-09-16T00:00:00Z")
        run_sweep()

        assert get_inspection_request(submitted["id"])["status"] == "EXPIRED"
        assert get_inspection_request(scheduled["id"])["status"] == "SCHEDULED"

        expired = validate_success(
            api_client.list_review_appointments(COMPLIANCE, params={"status": "EXPIRED"})
        )
        assert len(expired) == 1
        assert expired[0]["id"] == appointment["id"]


def _vera_and_two_receiving_districts():
    """One student in SEND01 (CA) and two TX districts, RECV01 and RECV02, that
    might both want her record."""
    create_state_rule("CA", **CA_RULE)
    create_state_rule("TX", **TX_RULE)
    sending = create_district("SEND01", state_code="CA", name="Sending Unified")
    recv_one = create_district("RECV01", state_code="TX", name="Receiving One")
    recv_two = create_district("RECV02", state_code="TX", name="Receiving Two")
    student = create_student(
        sending["id"],
        first_name="Vera",
        last_name="Lindqvist",
        dob="2012-10-22",
        grade_level=9,
        has_iep=False,
        guardian_user_id="guardian-vera",
    )
    return sending, recv_one, recv_two, student


def _file_as(student, requesting, responding, acting_district, reference):
    """File a request naming `requesting` while acting as `acting_district`'s
    registrar, returning the raw response."""
    return api_client.create_records_request(
        records_request_payload(
            student["id"],
            requesting["id"],
            responding["id"],
            authorization_reference=reference,
        ),
        make_receiving_registrar_headers(acting_district["id"]),
    )


class TestRecordsRequestLinks:
    def test_a_registrar_may_only_file_in_their_own_district_s_name(self):
        """RECV02's registrar naming RECV01 as the requesting district is refused
        on ownership, and the identical filing from RECV01's own registrar is
        accepted with every optional fact at its default.

        PRD: "When the caller acts as `ReceivingRegistrar`, the `requesting_district_id` must equal the acting `X-User-ID`, because a registrar may only file in the name of their own district; a mismatch is refused with `ERR_DISTRICT_MISMATCH`."

        Design: Corner/endpoints/records_request_links_student_and_two_districts
        """
        sending, recv_one, recv_two, student = _vera_and_two_receiving_districts()

        impostor = _file_as(student, recv_one, sending, recv_two, "ENR-2026-9070")
        validate_error(impostor, "ERR_DISTRICT_MISMATCH", 403)

        owned = validate_success(
            _file_as(student, recv_one, sending, recv_one, "ENR-2026-9070"), 201
        )
        assert_records_request(owned)
        assert owned["status"] == "RECEIVED"
        assert owned["requesting_district_id"] == recv_one["id"]
        assert owned["responding_district_id"] == sending["id"]
        assert owned["request_priority"] == "STANDARD"
        assert owned["includes_special_education"] is False
        assert owned["sped_consent_on_file"] is False
        assert owned["authorization_verified"] is False

    def test_the_open_pair_blocks_a_refiling_until_the_first_request_is_denied(self):
        """The uniqueness rule binds the student to the requesting district, so
        RECV01 cannot file twice while its first request is open, RECV02 can file
        at once, and RECV01 becomes free again the moment its request is denied.

        PRD: "One request per district pair is allowed at a time: a student may not carry two requests from the same `requesting_district_id` while one of them is in `RECEIVED`, `VALIDATED`, `ASSEMBLING`, or `READY_FOR_RELEASE`, and a second filing is refused with `ERR_DUPLICATE_ACTIVE_REQUEST`."

        Design: Corner/endpoints/records_request_links_student_and_two_districts
        """
        sending, recv_one, recv_two, student = _vera_and_two_receiving_districts()
        first = validate_success(
            _file_as(student, recv_one, sending, recv_one, "ENR-2026-9070"), 201
        )

        duplicate = _file_as(student, recv_one, sending, recv_one, "ENR-2026-9071")
        validate_error(duplicate, "ERR_DUPLICATE_ACTIVE_REQUEST", 409)

        other_district = validate_success(
            _file_as(student, recv_two, sending, recv_two, "ENR-2026-9072"), 201
        )
        assert other_district["requesting_district_id"] == recv_two["id"]

        denied = deny_request(first["id"], "DUPLICATE_REQUEST")
        assert denied["status"] == "DENIED"
        assert denied["denial_reason"] == "DUPLICATE_REQUEST"

        afresh = validate_success(
            _file_as(student, recv_one, sending, recv_one, "ENR-2026-9073"), 201
        )
        assert afresh["id"] not in (first["id"], other_district["id"])

        for_student = validate_success(
            api_client.list_records_requests(OFFICER_1, params={"student_id": student["id"]})
        )
        assert len(for_student) == 3, f"three filings survive, got {len(for_student)}"

        assert _get_district(sending["id"])["open_request_count"] == 2, (
            "the denied request drops out of the open set"
        )
