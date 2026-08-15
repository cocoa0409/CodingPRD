"""Booking creation: computed windows, temporal gates, room overlap, capacity."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    advance_clock,
    assert_booking,
    assert_instants_equal,
    create_booking,
    create_booking_payload,
    create_colono_type,
    create_egd_type,
    create_patient,
    create_provider,
    create_room,
    create_scope,
    make_registry,
    setup_capacity_room_scenario,
    run_procedure_to_complete,
    confirm_prep,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

ADMIN = TEST_USERS["unit_admin_headers"]
SCHED = TEST_USERS["scheduler_headers"]
QO = TEST_USERS["quality_officer_headers"]


class TestBookingBirth:
    def test_booking_created_in_scheduled_prep_pending(self, api):
        """PRD §3.2: "A booking that passes everything is born with its booking
        axis in `SCHEDULED` and its prep axis in `PREP_PENDING` — two parallel
        status dimensions that live on the same record and evolve independently".
        PRD §3.2: "Every outcome and timing field on a fresh booking —
        `actual_start`, `actual_end`, `actual_duration_minutes`, `cecum_intubated`,
        `withdrawal_time_seconds`, `adenomas_detected`, `rescheduled_from_id`, and
        `cancel_reason` — begins null, `notification_flag` begins false, and the
        three BBPS segment fields stay null until the assessment of §3.5."

        Design: Corner/state_machines/booking_created_in_scheduled_prep_pending
        """
        reg = make_registry(mrn="MRN-INIT", serial="SC-INIT")
        data = validate_success(api.create_booking(
            create_booking_payload(reg["patient"]["id"], reg["provider"]["id"],
                                   reg["ptype"]["id"], reg["room"]["id"],
                                   scheduled_start="2026-08-03T09:00:00Z"),
            SCHED), 201)
        assert_booking(data)
        assert data["status"] == "SCHEDULED"
        assert data["prep_status"] == "PREP_PENDING"
        assert data["rescheduled_from_id"] is None
        assert data["notification_flag"] is False
        assert data["bbps_left"] is None and data["bbps_right"] is None
        assert data["bbps_transverse"] is None
        assert data["actual_start"] is None and data["actual_end"] is None
        assert data["cancel_reason"] is None

    def test_booking_create_missing_required_returns_invalid_request(self, api):
        """
        PRD §2.6: "4. **Request schema** — required fields present, types valid,
        enum values in range, integer ranges honored (BBPS segment scores between 0
        and 3 inclusive, `container_count` at least 1, `base_duration_minutes`
        greater than 0, `withdrawal_time_seconds` and `adenomas_detected` at least
        0, a POSITIVE culture accompanied by its organism and colony count):
        `ERR_INVALID_REQUEST`."

        Design: Corner/entities/booking_create_missing_required_returns_invalid_request
        """
        reg = make_registry(mrn="MRN-REQ", serial="SC-REQ", with_scope=False)
        payload = create_booking_payload(
            reg["patient"]["id"], reg["provider"]["id"], reg["ptype"]["id"],
            reg["room"]["id"], scheduled_start="2026-08-03T09:00:00Z")
        del payload["room_id"]
        resp = api.create_booking(payload, SCHED)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_booking_system_and_computed_field_input_ignored(self, api):
        """
        PRD §2.5: "**`id`** (string): a server-minted UUID with no type prefix,
        uniquely addressing the resource."

        PRD §2.5: "**`version`** (integer): starts at 1 when the resource is created
        and increments by exactly 1 on every mutation, including mutations driven by
        cascades originating on other entities."

        PRD §3.2: "From these inputs the system computes the booking's time window."

        Design: Corner/entities/booking_system_and_computed_field_input_ignored
        """
        reg = make_registry(mrn="MRN-SYS", serial="SC-SYS")
        payload = create_booking_payload(
            reg["patient"]["id"], reg["provider"]["id"], reg["ptype"]["id"],
            reg["room"]["id"], scheduled_start="2026-08-03T09:00:00Z")
        payload.update({"id": "11111111-1111-1111-1111-111111111111",
                        "version": 99, "status": "COMPLETED",
                        "procedure_minutes": 999})
        data = validate_success(api.create_booking(payload, SCHED), 201)
        assert data["id"] != "11111111-1111-1111-1111-111111111111"
        assert data["version"] == 1
        assert data["status"] == "SCHEDULED"
        assert data["procedure_minutes"] == 40, "server-computed window wins"

    def test_booking_not_found_returns_404(self, api):
        """
        PRD §2.6: "Each unresolved reference maps to its own error:
        `ERR_PATIENT_NOT_FOUND`, `ERR_PROVIDER_NOT_FOUND`,
        `ERR_PROCEDURE_TYPE_NOT_FOUND`, `ERR_ROOM_NOT_FOUND` (also raised for an
        unresolvable `new_room_id`), `ERR_ANESTHESIA_PROVIDER_NOT_FOUND`,
        `ERR_SCOPE_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`, `ERR_SCOPE_USAGE_NOT_FOUND`,
        `ERR_REPROCESSING_CYCLE_NOT_FOUND`, `ERR_CULTURE_TEST_NOT_FOUND`,
        `ERR_QUARANTINE_CASE_NOT_FOUND`, `ERR_SPECIMEN_NOT_FOUND`,
        `ERR_QUALITY_REPORT_NOT_FOUND`, and `ERR_ANESTHESIA_ASSIGNMENT_NOT_FOUND`,
        all HTTP 404."

        Design: Corner/entities/booking_not_found_returns_404
        """
        resp = api.get_booking(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_BOOKING_NOT_FOUND)


class TestTemporalGates:
    def test_scheduled_start_in_past_rejected(self, api):
        """PRD §3.2: "First, `scheduled_start` must lie strictly in the future; a
        start at or before the current logical time is refused with
        `ERR_SCHEDULED_START_IN_PAST`."
        PRD §2.4: "At server startup the logical clock reads exactly
        `2026-08-01T00:00:00Z`; before it has ever been set, the clock continues
        to report this default and never falls back to wall-clock time."

        Design: Corner/validations/scheduled_start_in_past_rejected
        """
        patient = create_patient(mrn="MRN-PS")
        provider = create_provider("Dr Ps")
        t_egd = create_egd_type(prep_protocol="NONE")
        room = create_room(name="R-PS")
        payload = create_booking_payload(
            patient["id"], provider["id"], t_egd["id"], room["id"],
            scheduled_start="2026-08-01T00:00:00Z", indication="DIAGNOSTIC",
            anesthesia_type="NONE")
        resp = api.create_booking(payload, SCHED)
        validate_error(resp, ApiErrorId.ERR_SCHEDULED_START_IN_PAST)

    def test_lead_time_exactly_24h_accepted(self, api):
        """PRD §3.2: "Second, the chosen procedure type's `prep_protocol` imposes
        a minimum lead time: a `SPLIT_DOSE` prep requires the start to be at least
        24 hours away, `CLEAR_LIQUIDS` requires at least 8 hours, and `NONE`
        imposes no lead at all. A start inside the lead window is refused with
        `ERR_PREP_LEAD_TIME_INSUFFICIENT`."

        Design: Corner/validations/lead_time_exactly_24h_accepted
        """
        patient = create_patient(mrn="MRN-LT")
        provider = create_provider("Dr Lt")
        t_col = create_colono_type()
        r1 = create_room(name="R1")
        r2 = create_room(name="R2")
        advance_clock("2026-08-01T09:00:00Z")

        ok = validate_success(api.create_booking(
            create_booking_payload(patient["id"], provider["id"], t_col["id"],
                                   r1["id"], scheduled_start="2026-08-02T09:00:00Z"),
            SCHED), 201)
        assert_booking(ok)

        resp = api.create_booking(
            create_booking_payload(patient["id"], provider["id"], t_col["id"],
                                   r2["id"], scheduled_start="2026-08-02T08:59:59Z"),
            SCHED)
        validate_error(resp, ApiErrorId.ERR_PREP_LEAD_TIME_INSUFFICIENT)

    def test_booking_create_room_out_of_service_rejected(self, api):
        """PRD §3.2: "Credential and room gates complete creation: the named
        provider must be `ACTIVE` (`ERR_PROVIDER_SUSPENDED` otherwise) and the
        room must be `ACTIVE` (`ERR_ROOM_NOT_IN_SERVICE` otherwise)."

        Design: Corner/validations/booking_create_room_out_of_service_rejected
        """
        reg = make_registry(mrn="MRN-OS", serial="SC-OS", with_scope=False)
        validate_success(api.patch_room(reg["room"]["id"],
                                        {"status": "OUT_OF_SERVICE"}, ADMIN), 200)
        resp = api.create_booking(
            create_booking_payload(reg["patient"]["id"], reg["provider"]["id"],
                                   reg["ptype"]["id"], reg["room"]["id"],
                                   scheduled_start="2026-08-03T09:00:00Z"), SCHED)
        validate_error(resp, ApiErrorId.ERR_ROOM_NOT_IN_SERVICE)


class TestWindowFormula:
    def test_age_addon_exact_birthday_boundary(self, api):
        """PRD §3.2: "The planned `procedure_minutes` is the procedure type's
        `base_duration_minutes`, plus an anesthesia add-on of 0 minutes for
        `NONE`, 10 for `MAC`, or 15 for `GENERAL`, plus a further 5 minutes when
        the patient is at least 65 years old at the scheduled start."
        PRD §3.2: "Age here means full calendar years between the patient's
        `date_of_birth` and `scheduled_start` in UTC, and a patient whose birthday
        falls on the scheduled date counts as having already turned that age."

        Design: Corner/calculations/age_addon_exact_birthday_boundary
        """
        p65 = create_patient(mrn="MRN-65", date_of_birth="1961-08-03")
        p64 = create_patient(mrn="MRN-64", date_of_birth="1961-08-04")
        provider = create_provider("Dr Age")
        t_col = create_colono_type()
        r1 = create_room(name="R1")
        r2 = create_room(name="R2")
        b65 = validate_success(api.create_booking(
            create_booking_payload(p65["id"], provider["id"], t_col["id"], r1["id"],
                                   scheduled_start="2026-08-03T09:00:00Z",
                                   anesthesia_type="MAC"), SCHED), 201)
        b64 = validate_success(api.create_booking(
            create_booking_payload(p64["id"], provider["id"], t_col["id"], r2["id"],
                                   scheduled_start="2026-08-03T09:00:00Z",
                                   anesthesia_type="MAC"), SCHED), 201)
        assert b65["procedure_minutes"] == 55, "65th birthday on the date counts"
        assert b64["procedure_minutes"] == 50, "still 64: no age add-on"

    def test_multi_input_formula_age_birthday_mac_standard_room(self, api):
        """PRD §3.2: "The planned `procedure_minutes` is the procedure type's
        `base_duration_minutes`, plus an anesthesia add-on of 0 minutes for
        `NONE`, 10 for `MAC`, or 15 for `GENERAL`, plus a further 5 minutes when
        the patient is at least 65 years old at the scheduled start."
        PRD §3.2: "The `scheduled_end` is then `scheduled_start` advanced by
        `procedure_minutes`, and the `room_block_end` adds a turnover buffer on
        top of `scheduled_end` — 15 minutes for a `STANDARD` room, 25 for an
        `ERCP_CAPABLE` one."

        Design: Difficulty/combinatorial_formula/scheduled_window_multi_input_formula_mode_a
        """
        p_old = create_patient(mrn="M3001", full_name="Pat Old",
                               date_of_birth="1961-08-02")
        provider = create_provider("Dr One")
        t_col = create_colono_type()
        r_std = create_room(name="R-STD", room_class="STANDARD")
        b1 = validate_success(api.create_booking(
            create_booking_payload(p_old["id"], provider["id"], t_col["id"],
                                   r_std["id"], scheduled_start="2026-08-02T09:00:00Z",
                                   anesthesia_type="MAC"), SCHED), 201)
        assert b1["procedure_minutes"] == 55, "40 base + 10 MAC + 5 age (65th birthday)"
        assert_instants_equal(b1["scheduled_end"], "2026-08-02T09:55:00Z",
                              "scheduled_end")
        assert_instants_equal(b1["room_block_end"], "2026-08-02T10:10:00Z",
                              "STANDARD turnover 15")

    def test_multi_input_formula_general_ercp_room_branch(self, api):
        """PRD §3.2: "The planned `procedure_minutes` is the procedure type's
        `base_duration_minutes`, plus an anesthesia add-on of 0 minutes for
        `NONE`, 10 for `MAC`, or 15 for `GENERAL`, plus a further 5 minutes when
        the patient is at least 65 years old at the scheduled start."
        PRD §3.2: "The `scheduled_end` is then `scheduled_start` advanced by
        `procedure_minutes`, and the `room_block_end` adds a turnover buffer on
        top of `scheduled_end` — 15 minutes for a `STANDARD` room, 25 for an
        `ERCP_CAPABLE` one."

        Design: Difficulty/combinatorial_formula/scheduled_window_multi_input_formula_mode_a
        """
        p_yng = create_patient(mrn="M3002", full_name="Pat Young",
                               date_of_birth="1990-05-05")
        provider = create_provider("Dr One")
        t_col = create_colono_type()
        r_ercp = create_room(name="R-ERCP", room_class="ERCP_CAPABLE")
        b2 = validate_success(api.create_booking(
            create_booking_payload(p_yng["id"], provider["id"], t_col["id"],
                                   r_ercp["id"], scheduled_start="2026-08-02T09:00:00Z",
                                   indication="DIAGNOSTIC", anesthesia_type="GENERAL"),
            SCHED), 201)
        assert b2["procedure_minutes"] == 55, "40 base + 15 GENERAL + 0 age"
        assert_instants_equal(b2["scheduled_end"], "2026-08-02T09:55:00Z",
                              "scheduled_end")
        assert_instants_equal(b2["room_block_end"], "2026-08-02T10:20:00Z",
                              "ERCP_CAPABLE turnover 25")


class TestValidationPriorityPairs:
    def test_existence_beats_business_temporal_on_booking_create(self, api):
        """
        PRD §2.6: "When a single request violates several rules, exactly one error
        surfaces, chosen by the following ladder — earlier rungs win over later
        ones:"

        PRD §2.6: "3. **Existence** — path and body reference resolution, as above;
        the 404 family."

        PRD §2.6: "9. **Temporal gates** — `ERR_SCHEDULED_START_IN_PAST`,
        `ERR_PREP_LEAD_TIME_INSUFFICIENT`, `ERR_CHECKIN_WINDOW_CLOSED`,
        `ERR_NO_SHOW_WINDOW_NOT_REACHED`, `ERR_INVALID_PERIOD`,
        `ERR_CLOCK_REGRESSION`."

        Design: Difficulty/priority_pair_validation_conflict/existence_beats_business_temporal_on_booking_create
        """
        reg = make_registry(mrn="M5101", serial="SC-5101", with_scope=False)
        resp = api.create_booking(
            create_booking_payload(reg["patient"]["id"], reg["provider"]["id"],
                                   reg["ptype"]["id"], NON_EXISTENT_UUID,
                                   scheduled_start="2026-08-01T00:00:00Z"), SCHED)
        validate_error(resp, ApiErrorId.ERR_ROOM_NOT_FOUND)
        assert resp.status_code == 404

    def test_existence_priority_control_temporal_gate_is_live(self, api):
        """
        PRD §3.2: "First, `scheduled_start` must lie strictly in the future; a start
        at or before the current logical time is refused with
        `ERR_SCHEDULED_START_IN_PAST`. Second, the chosen procedure type's
        `prep_protocol` imposes a minimum lead time: a `SPLIT_DOSE` prep requires
        the start to be at least 24 hours away, `CLEAR_LIQUIDS` requires at least 8
        hours, and `NONE` imposes no lead at all. A start inside the lead window is
        refused with `ERR_PREP_LEAD_TIME_INSUFFICIENT`."

        Control: with the room reference resolving, the same request shape fails on
        the temporal rung (HTTP 422), proving that rung was live when the 404 pre-
        empted it.

        Design: Difficulty/priority_pair_validation_conflict/existence_beats_business_temporal_on_booking_create
        """
        reg = make_registry(mrn="M5102", serial="SC-5102", with_scope=False)
        resp = api.create_booking(
            create_booking_payload(reg["patient"]["id"], reg["provider"]["id"],
                                   reg["ptype"]["id"], reg["room"]["id"],
                                   scheduled_start="2026-08-01T00:00:00Z"), SCHED)
        actual = validate_error_is_one_of(resp, [
            ApiErrorId.ERR_SCHEDULED_START_IN_PAST,
            ApiErrorId.ERR_PREP_LEAD_TIME_INSUFFICIENT,
        ])
        assert resp.status_code == 422, f"temporal rung answers 422, got {actual}"

    def test_business_temporal_beats_business_constraint_on_booking_create(self, api):
        """
        PRD §2.6: "When a single request violates several rules, exactly one error
        surfaces, chosen by the following ladder — earlier rungs win over later
        ones:"

        PRD §2.6: "9. **Temporal gates** — `ERR_SCHEDULED_START_IN_PAST`,
        `ERR_PREP_LEAD_TIME_INSUFFICIENT`, `ERR_CHECKIN_WINDOW_CLOSED`,
        `ERR_NO_SHOW_WINDOW_NOT_REACHED`, `ERR_INVALID_PERIOD`,
        `ERR_CLOCK_REGRESSION`."

        PRD §2.6: "10. **Capacity and uniqueness** — `ERR_ROOM_TIME_CONFLICT`,
        `ERR_ROOM_DAY_CAPACITY_EXCEEDED`, `ERR_ANESTHESIA_TIME_CONFLICT`,
        `ERR_ROOM_NOT_IN_SERVICE`, `ERR_ANESTHESIA_TYPE_NONE`,
        `ERR_NO_COMPATIBLE_SCOPE`, `ERR_PATIENT_MRN_EXISTS`,
        `ERR_SERIAL_NUMBER_EXISTS`, `ERR_PROCEDURE_TYPE_CODE_EXISTS`."

        Design: Difficulty/priority_pair_validation_conflict/business_temporal_beats_business_constraint_on_booking_create
        """
        reg = make_registry(mrn="M5201", serial="SC-5201", with_scope=False)
        create_booking(reg["patient"]["id"], reg["provider"]["id"], reg["ptype"]["id"],
                       reg["room"]["id"], scheduled_start="2026-08-02T09:00:00Z")
        advance_clock("2026-08-01T13:00:00Z")
        # 09:30 next day is only 20.5h ahead (SPLIT_DOSE needs 24h) AND falls
        # inside the existing booking's block [09:00, 09:55).
        resp = api.create_booking(
            create_booking_payload(reg["patient"]["id"], reg["provider"]["id"],
                                   reg["ptype"]["id"], reg["room"]["id"],
                                   scheduled_start="2026-08-02T09:30:00Z"), SCHED)
        validate_error(resp, ApiErrorId.ERR_PREP_LEAD_TIME_INSUFFICIENT)
        assert resp.status_code == 422

    def test_temporal_priority_control_overlap_is_live(self, api):
        """
        PRD §3.2: "A conflict exists exactly when the new booking's
        `scheduled_start` falls strictly before a candidate's `room_block_end` and
        the new booking's `room_block_end` falls strictly after that candidate's
        `scheduled_start`; because the intervals are half-open, exact adjacency — a
        new start landing precisely on the prior booking's `room_block_end` — is
        permitted. An overlapping request is refused with `ERR_ROOM_TIME_CONFLICT`."

        Control: with the lead time satisfied (default clock), the same 09:30 start
        fails on the overlap rung, proving the constraint was live.

        Design: Difficulty/priority_pair_validation_conflict/business_temporal_beats_business_constraint_on_booking_create
        """
        reg = make_registry(mrn="M5202", serial="SC-5202", with_scope=False)
        create_booking(reg["patient"]["id"], reg["provider"]["id"], reg["ptype"]["id"],
                       reg["room"]["id"], scheduled_start="2026-08-02T09:00:00Z")
        resp = api.create_booking(
            create_booking_payload(reg["patient"]["id"], reg["provider"]["id"],
                                   reg["ptype"]["id"], reg["room"]["id"],
                                   scheduled_start="2026-08-02T09:30:00Z"), SCHED)
        validate_error(resp, ApiErrorId.ERR_ROOM_TIME_CONFLICT)


class TestRoomOverlap:
    def test_room_conflict_inside_turnover_buffer_rejected(self, api):
        """PRD §3.2: "A conflict exists exactly when the new booking's
        `scheduled_start` falls strictly before a candidate's `room_block_end`
        and the new booking's `room_block_end` falls strictly after that
        candidate's `scheduled_start`; because the intervals are half-open, exact
        adjacency — a new start landing precisely on the prior booking's
        `room_block_end` — is permitted. An overlapping request is refused with
        `ERR_ROOM_TIME_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/room_conflict_half_open_with_turnover_buffer
        """
        p_old = create_patient(mrn="M8001", date_of_birth="1961-08-02")
        p_yng = create_patient(mrn="M8002", date_of_birth="1990-05-05")
        provider = create_provider("Dr R")
        t_col = create_colono_type()
        room = create_room(name="R-STD")
        b1 = create_booking(p_old["id"], provider["id"], t_col["id"], room["id"],
                            scheduled_start="2026-08-02T09:00:00Z",
                            anesthesia_type="MAC")
        assert_instants_equal(b1["room_block_end"], "2026-08-02T10:10:00Z",
                              "09:55 end + 15 turnover")
        resp = api.create_booking(
            create_booking_payload(p_yng["id"], provider["id"], t_col["id"],
                                   room["id"], scheduled_start="2026-08-02T10:05:00Z"),
            SCHED)
        validate_error(resp, ApiErrorId.ERR_ROOM_TIME_CONFLICT)

    def test_room_exact_adjacency_at_block_end_permitted(self, api):
        """PRD §3.2: "because the intervals are half-open, exact adjacency — a new
        start landing precisely on the prior booking's `room_block_end` — is
        permitted."

        Design: Difficulty/resource_temporal_overlap/room_conflict_half_open_with_turnover_buffer
        """
        p_old = create_patient(mrn="M8003", date_of_birth="1961-08-02")
        p_yng = create_patient(mrn="M8004", date_of_birth="1990-05-05")
        provider = create_provider("Dr R")
        t_col = create_colono_type()
        room = create_room(name="R-STD")
        create_booking(p_old["id"], provider["id"], t_col["id"], room["id"],
                       scheduled_start="2026-08-02T09:00:00Z", anesthesia_type="MAC")
        b3 = validate_success(api.create_booking(
            create_booking_payload(p_yng["id"], provider["id"], t_col["id"],
                                   room["id"], scheduled_start="2026-08-02T10:10:00Z"),
            SCHED), 201)
        assert_instants_equal(b3["scheduled_start"], "2026-08-02T10:10:00Z")
        assert_instants_equal(b3["room_block_end"], "2026-08-02T11:05:00Z",
                              "40 NONE + 15 turnover")


class TestRoomDayCapacity:
    def test_room_day_capacity_aggregate_limit_rejected(self, api):
        """PRD §3.2: "For capacity, the same candidate set restricted to the UTC
        calendar date of `scheduled_start` contributes its block minutes — the
        minutes from each booking's `scheduled_start` to its `room_block_end` —
        and the running total plus the new booking's own block must not exceed 480
        minutes of committed room time in a day. A request that would breach the
        cap is refused with `ERR_ROOM_DAY_CAPACITY_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/room_day_capacity_aggregate_limit
        """
        fx = setup_capacity_room_scenario()
        resp = api.create_booking(
            create_booking_payload(fx["patient"]["id"], fx["provider"]["id"],
                                   fx["ptype"]["id"], fx["room"]["id"],
                                   scheduled_start="2026-08-04T15:00:00Z",
                                   anesthesia_type="MAC"), SCHED)
        validate_error(resp, ApiErrorId.ERR_ROOM_DAY_CAPACITY_EXCEEDED)

    def test_room_day_capacity_rejection_contributes_nothing(self, api):
        """PRD §3.9: "For every Room regardless of `status`, the occupied minutes
        are the sum of block minutes — `scheduled_start` to `room_block_end` —
        over bookings whose `scheduled_start` falls on that UTC date and whose
        booking axis is `SCHEDULED`, `CHECKED_IN`, `IN_PROGRESS`, `COMPLETED`, or
        `ABORTED_PREP_INADEQUATE`; `CANCELLED`, `NO_SHOW`, and `RESCHEDULED`
        bookings are excluded."

        Design: Difficulty/resource_temporal_overlap/room_day_capacity_aggregate_limit
        """
        fx = setup_capacity_room_scenario()
        resp = api.create_booking(
            create_booking_payload(fx["patient"]["id"], fx["provider"]["id"],
                                   fx["ptype"]["id"], fx["room"]["id"],
                                   scheduled_start="2026-08-04T15:00:00Z",
                                   anesthesia_type="MAC"), SCHED)
        validate_error(resp, ApiErrorId.ERR_ROOM_DAY_CAPACITY_EXCEEDED)

        report = validate_success(api.get_room_utilization(QO, "2026-08-04"), 200)
        room_row = [r for r in report["rooms"] if r.get("room_id") == fx["room"]["id"]]
        assert len(room_row) == 1
        assert room_row[0]["occupied_minutes"] == 420, "six 70-minute blocks only"
        assert room_row[0]["utilization_pct"] == 87.5


class TestBookingListing:
    def test_bookings_list_filters_provider_and_status(self, api):
        """PRD §3.2: "The booking list supports a broad filter set for day-to-day
        coordination: `patient_id`, `provider_id`, `room_id`, `procedure_type_id`,
        `rescheduled_from_id` (to trace a replacement chain), `status`,
        `prep_status`, and a `date` filter narrowing results to a UTC calendar
        day, in addition to pagination."

        Design: Corner/endpoints/bookings_list_filters_provider_and_status
        """
        patient = create_patient(mrn="MRN-FL")
        dra = create_provider("Dr A")
        drb = create_provider("Dr B", specialty="COLORECTAL_SURGERY")
        t_col = create_colono_type()
        r1 = create_room(name="R1")
        r2 = create_room(name="R2")
        scope = create_scope(serial_number="SC-FL")
        b1 = create_booking(patient["id"], dra["id"], t_col["id"], r1["id"],
                            scheduled_start="2026-08-03T09:00:00Z")
        b2 = create_booking(patient["id"], dra["id"], t_col["id"], r2["id"],
                            scheduled_start="2026-08-04T09:00:00Z")
        create_booking(patient["id"], drb["id"], t_col["id"], r2["id"],
                       scheduled_start="2026-08-05T09:00:00Z")
        confirm_prep(b1["id"])
        run_procedure_to_complete(b1["id"], dra["id"], scope["id"],
                                  "2026-08-03T09:00:00Z", "2026-08-03T09:00:00Z")

        data, meta = validate_paginated(api.list_bookings(
            ADMIN, params={"provider_id": dra["id"], "status": "COMPLETED"}))
        assert [row["id"] for row in data] == [b1["id"]]
        assert meta["total_count"] == 1

        data2, meta2 = validate_paginated(api.list_bookings(
            ADMIN, params={"provider_id": dra["id"], "status": "NO_SHOW"}))
        assert data2 == [], "empty match set is a 200 with an empty array"
        assert meta2["total_count"] == 0 and meta2["has_more"] is False
