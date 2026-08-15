"""Return-case workflow: initiation template, abort, records gate, checklist
lifecycle (inspect/rectify/waive loops), the checklist gate into negotiation,
and the inspection booking gate."""
from test_helpers import (
    ApiErrorId,
    CHECKLIST_TEMPLATE,
    TEST_USERS,
    add_verified_document,
    advance_return_case,
    create_aircraft,
    create_inspector,
    create_lease_with_return_initiated,
    create_return_case_in_inspection,
    get_checklist_items,
    inspect_item,
    make_lessee_rep_headers,
    make_tech_inspector_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["lessor_admin_headers"]


class TestReturnInitiation:
    def test_new_return_case_initial_state_and_template(self, api):
        """PRD §3.5: "Initiation flips the lease `ACTIVE → RETURN_INITIATED`,
        creates the return case in `OPEN` with `round_count` and
        `reinspection_count` at zero, and generates four checklist items from
        the fixed return-condition template: `item_code` `AIRFRAME` with
        `severity` `CRITICAL`, `ENGINE` with `MAJOR`, and `INTERIOR` and
        `PAINT` with `MINOR`, all in `PENDING`, each item stamped with the
        case's `return_case_id`."

        Design: Corner/state_machines/new_return_case_initial_state_and_template
        """
        lease, _aircraft, _lessee, rc = create_lease_with_return_initiated()
        assert rc["status"] == "OPEN"
        assert rc["round_count"] == 0
        assert rc["reinspection_count"] == 0
        assert rc["current_proposal_cents"] is None

        items, _meta = validate_paginated(api.list_checklist_items(rc["id"], ADMIN))
        assert len(items) == 4
        assert [i["item_code"] for i in items] == [code for code, _ in CHECKLIST_TEMPLATE]
        for item, (code, severity) in zip(items, CHECKLIST_TEMPLATE):
            assert item["severity"] == severity
            assert item["status"] == "PENDING"
            assert item["return_case_id"] == rc["id"]

    def test_second_open_return_case_rejected(self, api):
        """PRD §3.5: "At most one non-terminal return case may exist per lease
        — if one is already open (not `SETTLED` and not `CANCELLED`), the
        initiation is `ERR_INVALID_STATE`."

        Design: Corner/state_machines/new_return_case_initial_state_and_template
        """
        lease, _aircraft, _lessee, _rc = create_lease_with_return_initiated()
        resp = api.initiate_return(lease["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


class TestAbortReturn:
    def test_abort_return_reverts_lease_and_cancels_case(self, api):
        """PRD §3.5: "Should the return be called off before any inspection
        has been booked — that is, while the open case is still `OPEN` or
        `RECORDS_VERIFIED` — aborting the return flips the lease back
        `RETURN_INITIATED → ACTIVE` and cascades the open case to
        `CANCELLED`; once the case has moved past `RECORDS_VERIFIED` the
        return can no longer be aborted (`ERR_INVALID_STATE`)."

        Design: Corner/state_machines/abort_return_reverts_lease_and_cancels_case
        """
        lease, _aircraft, _lessee, rc = create_lease_with_return_initiated()
        lease_now = validate_success(api.abort_return(lease["id"], ADMIN))
        assert lease_now["status"] == "ACTIVE"

        cases, _meta = validate_paginated(api.list_return_cases(lease["id"], ADMIN))
        assert cases[0]["status"] == "CANCELLED", (
            f"abort must cascade the open case to CANCELLED, got {cases[0]['status']!r}")

        # A second abort on the ACTIVE lease has no transition.
        resp = api.abort_return(lease["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


class TestRecordsGate:
    def test_three_of_four_verified_blocked_then_unblocked(self, api):
        """PRD §3.5: "From `OPEN` to `RECORDS_VERIFIED` the records gate
        applies: for every one of the four required `doc_type` values —
        `BIRTH_RECORD`, `AIRWORTHINESS_CERT`, `ENGINE_LOG`, `LLP_STATUS` —
        the aircraft must hold at least one `VERIFIED` document; all four are
        required, and three of four fails the gate with
        `ERR_RECORDS_INCOMPLETE`."

        Design: Corner/calculations/records_gate_three_of_four_blocked
        """
        # Aircraft with only 3 of the 4 required types verified.
        aircraft = create_aircraft(msn="MSN-CAL-1", model="A320-200",
                                   manufacture_date="2013-03-03")
        for dt in ("BIRTH_RECORD", "AIRWORTHINESS_CERT", "ENGINE_LOG"):
            add_verified_document(aircraft["id"], dt)
        lease, aircraft, _lessee, rc = create_lease_with_return_initiated(aircraft=aircraft)

        resp = api.advance_return_case(rc["id"], {"to": "RECORDS_VERIFIED"}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_RECORDS_INCOMPLETE, expected_status=409)

        add_verified_document(aircraft["id"], "LLP_STATUS")
        rc_now = validate_success(api.advance_return_case(rc["id"], {"to": "RECORDS_VERIFIED"}, ADMIN))
        assert rc_now["status"] == "RECORDS_VERIFIED"


class TestChecklistGate:
    def test_one_pending_item_blocks_negotiation(self, api):
        """PRD §3.6: "With the inspection complete, the case moves
        `INSPECTION → NEGOTIATION` — but only once the checklist gate passes:
        zero items of the case may remain in `PENDING` or `RECTIFIED`,
        otherwise the advance is refused with `ERR_CHECKLIST_INCOMPLETE`."

        Design: Difficulty/boundary_precision_check/begin_negotiation_zero_pending_gate
        """
        lease, _aircraft, _lessee, rc, inspector = create_return_case_in_inspection()
        items = get_checklist_items(rc["id"])
        for code in ("AIRFRAME", "ENGINE", "INTERIOR"):
            inspect_item(items[code]["id"], inspector["id"], "COMPLIANT")
        # PAINT left PENDING: exactly one outstanding item.
        resp = api.advance_return_case(rc["id"], {"to": "NEGOTIATION"}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_CHECKLIST_INCOMPLETE, expected_status=409)

    def test_zero_pending_items_allows_negotiation(self, api):
        """PRD §3.6: "With the inspection complete, the case moves
        `INSPECTION → NEGOTIATION` — but only once the checklist gate passes:
        zero items of the case may remain in `PENDING` or `RECTIFIED`,
        otherwise the advance is refused with `ERR_CHECKLIST_INCOMPLETE`."

        Design: Difficulty/boundary_precision_check/begin_negotiation_zero_pending_gate
        """
        lease, _aircraft, _lessee, rc, inspector = create_return_case_in_inspection()
        items = get_checklist_items(rc["id"])
        for code, item in items.items():
            inspect_item(item["id"], inspector["id"], "COMPLIANT")
        rc_now = advance_return_case(rc["id"], "NEGOTIATION")
        assert rc_now["status"] == "NEGOTIATION"


class TestChecklistItemLifecycle:
    def test_rectify_reinspect_loop_and_waive(self, api):
        """PRD §3.5: "marking the item rectified moves it `NON_COMPLIANT →
        RECTIFIED`, after which a booked inspector re-inspects it — a passing
        re-inspection moves it `RECTIFIED → COMPLIANT` and re-stamps
        `inspected_by_id`, while a failing one moves it back `RECTIFIED →
        NON_COMPLIANT`, overwrites `rectification_cost_estimate_cents` with
        the new positive estimate, and the rectify/inspect loop may repeat.
        Alternatively, a `LessorAdmin` may simply waive a `NON_COMPLIANT`
        item, optionally recording a `reason`, moving it to `WAIVED`;
        `COMPLIANT`, `WAIVED`, and `COMPENSATED` are the item's terminal
        states."

        Design: Corner/state_machines/checklist_item_rectify_reinspect_loop_and_waive
        """
        lease, _aircraft, lessee, rc, inspector = create_return_case_in_inspection()
        items = get_checklist_items(rc["id"])
        engine = inspect_item(items["ENGINE"]["id"], inspector["id"],
                              "NON_COMPLIANT", 80000)
        interior = inspect_item(items["INTERIOR"]["id"], inspector["id"],
                                "NON_COMPLIANT", 5000)

        rectified = validate_success(
            api.rectify_checklist_item(engine["id"], make_lessee_rep_headers(lessee["id"])))
        assert rectified["status"] == "RECTIFIED"

        # Failing re-inspection loops back to NON_COMPLIANT and overwrites
        # the estimate.
        relooped = validate_success(
            api.inspect_checklist_item(
                engine["id"],
                {"outcome": "NON_COMPLIANT", "rectification_cost_estimate_cents": 90000},
                make_tech_inspector_headers(inspector["id"])))
        assert relooped["status"] == "NON_COMPLIANT"
        assert relooped["rectification_cost_estimate_cents"] == 90000

        waived = validate_success(
            api.waive_checklist_item(interior["id"], {"reason": "cosmetic only"}, ADMIN))
        assert waived["status"] == "WAIVED"

    def test_non_compliant_without_positive_estimate_rejected(self, api):
        """PRD §3.5: "Recording `outcome` `NON_COMPLIANT` requires a
        `rectification_cost_estimate_cents` greater than zero — a
        non-compliant verdict without a positive estimate is
        `ERR_INVALID_REQUEST`"

        Design: Corner/state_machines/checklist_item_rectify_reinspect_loop_and_waive
        """
        lease, _aircraft, _lessee, rc, inspector = create_return_case_in_inspection()
        items = get_checklist_items(rc["id"])
        resp = api.inspect_checklist_item(
            items["ENGINE"]["id"], {"outcome": "NON_COMPLIANT"},
            make_tech_inspector_headers(inspector["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    def test_inspect_stamps_inspector_identity(self, api):
        """PRD §3.5: "Either way the item's `inspected_by_id` is stamped with
        the acting inspector's `X-User-ID` as an audit stamp."

        Design: Corner/state_machines/checklist_item_rectify_reinspect_loop_and_waive
        """
        lease, _aircraft, _lessee, rc, inspector = create_return_case_in_inspection()
        items = get_checklist_items(rc["id"])
        inspected = inspect_item(items["AIRFRAME"]["id"], inspector["id"], "COMPLIANT")
        assert inspected["inspected_by_id"] == inspector["id"]
        assert inspected["status"] == "COMPLIANT"


class TestBookingGate:
    def test_unbooked_inspector_rejected_booked_inspector_succeeds(self, api):
        """PRD §3.5: "recording an outcome on a checklist item requires the
        case to be in `INSPECTION`, the item to be in `PENDING` or
        `RECTIFIED`, and an existing booking whose `inspector_id` equals the
        acting `X-User-ID` and whose `booking_date` equals the logical
        clock's current date — with no such booking the inspection is refused
        with `ERR_BOOKING_REQUIRED` (HTTP 403)."

        Design: Corner/validations/booking_required_for_unbooked_inspector
        """
        lease, _aircraft, _lessee, rc, inspector_a = create_return_case_in_inspection()
        inspector_b = create_inspector()  # registered but never booked
        items = get_checklist_items(rc["id"])

        resp = api.inspect_checklist_item(
            items["AIRFRAME"]["id"], {"outcome": "COMPLIANT"},
            make_tech_inspector_headers(inspector_b["id"]))
        validate_error(resp, ApiErrorId.ERR_BOOKING_REQUIRED, expected_status=403)

        inspected = validate_success(
            api.inspect_checklist_item(
                items["AIRFRAME"]["id"], {"outcome": "COMPLIANT"},
                make_tech_inspector_headers(inspector_a["id"])))
        assert inspected["status"] == "COMPLIANT"


class TestBookingCapacity:
    def test_inspector_daily_capacity(self, api):
        """PRD §3.5: "capacity is one booking per inspector per calendar
        date, and a second booking for the same inspector on the same date is
        `ERR_INSPECTOR_DOUBLE_BOOKED`."

        Design: Difficulty/resource_temporal_overlap/inspector_daily_capacity
        """
        lease, _aircraft, _lessee, rc, inspector = create_return_case_in_inspection()

        # First booking already exists (fixture, 2026-08-01). Same date again:
        resp = api.create_inspection_booking(
            rc["id"], {"inspector_id": inspector["id"], "booking_date": "2026-08-01"},
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_INSPECTOR_DOUBLE_BOOKED, expected_status=409)

        # The next calendar date is fine: capacity is per discrete day.
        booking = validate_success(
            api.create_inspection_booking(
                rc["id"], {"inspector_id": inspector["id"], "booking_date": "2026-08-02"},
                ADMIN),
            expected_status=201)
        assert booking["booking_date"] == "2026-08-02"

    def test_capacity_is_per_inspector_not_per_case(self, api):
        """PRD §3.5: "capacity is one booking per inspector per calendar
        date, and a second booking for the same inspector on the same date is
        `ERR_INSPECTOR_DOUBLE_BOOKED`."

        Design: Difficulty/resource_temporal_overlap/inspector_daily_capacity
        """
        lease, _aircraft, _lessee, rc, inspector = create_return_case_in_inspection()
        other_inspector = create_inspector()

        # A different inspector on the same date does not trip the gate:
        # capacity binds (inspector, date), not the return case.
        booking = validate_success(
            api.create_inspection_booking(
                rc["id"], {"inspector_id": other_inspector["id"],
                           "booking_date": "2026-08-01"},
                ADMIN),
            expected_status=201)
        assert booking["inspector_id"] == other_inspector["id"]

        # The first inspector is still capped at one for that date.
        resp = api.create_inspection_booking(
            rc["id"], {"inspector_id": inspector["id"], "booking_date": "2026-08-01"},
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_INSPECTOR_DOUBLE_BOOKED, expected_status=409)


class TestInspectionBookingShape:
    def test_booking_carries_no_version(self, api):
        """PRD §2.5: "The single exception is the **inspection booking**,
        which is a scheduling record rather than a mutable resource: it
        carries `id` and `created_at` only, and both `updated_at` and
        `version` are absent from it."

        Design: Corner/entities/inspection_booking_immutable_no_version
        """
        lease, _aircraft, _lessee, rc, inspector = create_return_case_in_inspection()
        # The fixture already created one booking; create a second on a new
        # date and check its shape plus FK-reverse reachability.
        booking = validate_success(
            api.create_inspection_booking(
                rc["id"], {"inspector_id": inspector["id"], "booking_date": "2026-08-02"},
                ADMIN),
            expected_status=201)
        assert "id" in booking and "created_at" in booking
        assert "updated_at" not in booking and "version" not in booking

        bookings, _meta = validate_paginated(api.list_inspection_bookings(rc["id"], ADMIN))
        ids = [b["id"] for b in bookings]
        assert booking["id"] in ids, "booking must be discoverable from its return case"
