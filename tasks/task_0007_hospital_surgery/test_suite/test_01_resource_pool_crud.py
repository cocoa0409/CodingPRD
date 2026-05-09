"""CRUD and input validation for the three resource pools:
operating rooms, staff, and instrument sets."""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_operating_room,
    assert_staff_member,
    assert_instrument_set,
    create_operating_room_payload,
    create_staff_payload,
    create_instrument_set_payload,
    create_surgical_case_payload,
)


SCHED = TEST_USERS["scheduler_headers"]
ANY_H = TEST_USERS["any_headers"]
COORD = TEST_USERS["surgical_coordinator_headers"]


class TestOperatingRoomCrud:

    def test_create_operating_room(self, api):
        """PRD §3.1: 'A `Scheduler` registers a new operating room by supplying its
        hospital-internal label `room_number` ... its `room_type` ... an `equipment_list`
        of equipment identifiers present in the room ... the `specialty_required` it serves
        ... and the `hourly_rate` charged in currency units per hour'."""
        payload = create_operating_room_payload(
            room_type="GENERAL_OR",
            specialty_required="GENERAL",
            hourly_rate=500.00,
        )
        room = validate_success(api.create_operating_room(payload, SCHED), 201)
        assert_operating_room(room)
        assert room["room_type"] == "GENERAL_OR"
        assert room["specialty_required"] == "GENERAL"
        assert room["hourly_rate"] == 500.00

    def test_room_turnover_buffer_default_30(self, api):
        """PRD §3.1: 'this is the number of minutes that must elapse after one case
        ends before another may begin in the same room, and it defaults to 30 when
        not supplied at creation'."""
        payload = create_operating_room_payload()
        payload.pop("turnover_buffer_minutes", None)
        room = validate_success(api.create_operating_room(payload, SCHED), 201)
        assert room["turnover_buffer_minutes"] == 30

    def test_get_room_not_found(self, api):
        """PRD §2.6: 'The first miss returns the specific not-found error for that
        resource: ... `ERR_ROOM_NOT_FOUND` ...'."""
        validate_error(api.get_operating_room(NON_EXISTENT_UUID, SCHED), "ERR_ROOM_NOT_FOUND")

    def test_list_rooms_paginated(self, api):
        """PRD §2.3: 'List endpoints accept the optional query parameters `limit` and
        `offset`'."""
        for i in range(3):
            api.create_operating_room(create_operating_room_payload(), SCHED)
        data, meta = validate_paginated(api.list_operating_rooms(SCHED, params={"limit": 2}))
        assert len(data) <= 2
        assert "total_count" in meta
        assert "has_more" in meta

    def test_create_room_requires_scheduler_role(self, api):
        """PRD §2.1 + §4 endpoint table: POST /operating-rooms is restricted to Scheduler.
        PRD §2.1: 'If the role-bearing headers are present but the role is not on the
        authorized list for the requested operation, the server rejects the call with
        `ERR_INSUFFICIENT_PERMISSIONS` and HTTP status 403'."""
        validate_error(
            api.create_operating_room(create_operating_room_payload(), COORD),
            "ERR_INSUFFICIENT_PERMISSIONS",
        )


class TestStaffCrud:

    def test_create_staff(self, api):
        """PRD §3.1: 'A `Scheduler` registers a clinician by supplying `staff_name`,
        `staff_role` ... `qualifications` ... `hourly_rate`, and the inclusive
        shift-window start `shift_start_minute` and the exclusive end `shift_end_minute`'."""
        payload = create_staff_payload(staff_name="Dr. Test", staff_role="ANESTHESIOLOGIST")
        staff = validate_success(api.create_staff(payload, SCHED), 201)
        assert_staff_member(staff)
        assert staff["staff_role"] == "ANESTHESIOLOGIST"

    def test_staff_on_call_default_false(self, api):
        """PRD §3.1: 'The optional `on_call` flag is `false` when omitted'."""
        payload = create_staff_payload()
        payload.pop("on_call", None)
        staff = validate_success(api.create_staff(payload, SCHED), 201)
        assert staff["on_call"] is False

    def test_staff_shift_end_must_exceed_start(self, api):
        """PRD §3.1: '... the inclusive shift-window start `shift_start_minute` and
        the exclusive end `shift_end_minute` (which must be strictly greater than
        `shift_start_minute`)'.
        PRD §2.6: '`ERR_INVALID_TIME_PARAMETERS` for time-invariant violations such as ...
        `shift_end_minute` not being strictly greater than `shift_start_minute`'."""
        payload = create_staff_payload(shift_start_minute=100, shift_end_minute=100)
        validate_error(api.create_staff(payload, SCHED), "ERR_INVALID_TIME_PARAMETERS")

    def test_get_staff_not_found(self, api):
        """PRD §2.6 not-found chain: 'ERR_STAFF_NOT_FOUND'."""
        validate_error(api.get_staff(NON_EXISTENT_UUID, SCHED), "ERR_STAFF_NOT_FOUND")

    def test_get_staff_includes_workload_totals(self, api):
        """PRD §3.1: 'A staff member's read response also includes two computed workload
        totals, `planned_workload_minutes` and `actual_workload_minutes`, defined in §3.6'."""
        staff = validate_success(api.create_staff(create_staff_payload(), SCHED), 201)
        retrieved = validate_success(api.get_staff(staff["id"], SCHED), 200)
        assert "planned_workload_minutes" in retrieved
        assert "actual_workload_minutes" in retrieved


class TestInstrumentSetCrud:

    def test_create_instrument_set_initial_state_soiled(self, api):
        """PRD §3.1: 'On creation the tray's `sterilization_status` is set to `SOILED`,
        its `last_sterilized_at_minute` is `null` until the first sterilization completes,
        its `current_case_id` is `null`, and its `cycle_count` is 0'."""
        payload = create_instrument_set_payload()
        inst = validate_success(api.create_instrument_set(payload, SCHED), 201)
        assert_instrument_set(inst)
        assert inst["sterilization_status"] == "SOILED"
        assert inst["last_sterilized_at_minute"] is None
        assert inst["current_case_id"] is None
        assert inst["cycle_count"] == 0

    def test_get_instrument_set_not_found(self, api):
        """PRD §2.6: 'ERR_INSTRUMENT_SET_NOT_FOUND'."""
        validate_error(
            api.get_instrument_set(NON_EXISTENT_UUID, SCHED),
            "ERR_INSTRUMENT_SET_NOT_FOUND",
        )


class TestSurgicalCaseCrud:

    def test_create_surgical_case_initial_state_requested(self, api):
        """PRD §3.2: 'A successful creation initialises the case's `status` to `REQUESTED`'."""
        case = validate_success(api.create_surgical_case(create_surgical_case_payload(), COORD), 201)
        assert case["status"] == "REQUESTED"

    def test_create_case_priority_defaults_to_routine(self, api):
        """PRD §3.2: '`priority` defaults to `ROUTINE` when omitted'."""
        payload = create_surgical_case_payload()
        payload.pop("priority", None)
        case = validate_success(api.create_surgical_case(payload, COORD), 201)
        assert case["priority"] == "ROUTINE"

    def test_create_case_pre_op_default_false(self, api):
        """PRD §3.2: '`pre_op_assessment_attached` defaults to `false`'."""
        payload = create_surgical_case_payload()
        payload.pop("pre_op_assessment_attached", None)
        case = validate_success(api.create_surgical_case(payload, COORD), 201)
        assert case["pre_op_assessment_attached"] is False

    def test_create_case_consent_default_false(self, api):
        """PRD §3.2: '`informed_consent_verified` defaults to `false`'."""
        payload = create_surgical_case_payload()
        payload.pop("informed_consent_verified", None)
        case = validate_success(api.create_surgical_case(payload, COORD), 201)
        assert case["informed_consent_verified"] is False

    def test_create_case_implant_estimate_default_zero(self, api):
        """PRD §3.2: 'An optional `implant_cost_estimate` carries the projected implant
        component of the eventual bill — it defaults to `0.0` when omitted'."""
        payload = create_surgical_case_payload()
        payload.pop("implant_cost_estimate", None)
        case = validate_success(api.create_surgical_case(payload, COORD), 201)
        assert case["implant_cost_estimate"] == 0.0

    def test_get_case_not_found(self, api):
        """PRD §2.6: 'ERR_CASE_NOT_FOUND'."""
        validate_error(api.get_surgical_case(NON_EXISTENT_UUID, SCHED), "ERR_CASE_NOT_FOUND")

    def test_create_case_requires_surgical_coordinator(self, api):
        """PRD §4 + §2.1: POST /surgical-cases is restricted to SurgicalCoordinator;
        non-coordinator role yields 'ERR_INSUFFICIENT_PERMISSIONS'."""
        validate_error(
            api.create_surgical_case(create_surgical_case_payload(), SCHED),
            "ERR_INSUFFICIENT_PERMISSIONS",
        )
