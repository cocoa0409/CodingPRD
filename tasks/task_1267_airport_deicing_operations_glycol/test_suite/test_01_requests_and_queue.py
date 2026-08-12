"""Tests for request intake, queue management, pad assignment, and window overlap."""
import pytest

from test_helpers import (

    ApiErrorId,
    TEST_USERS,
    assign_request_payload,
    create_airline,
    create_and_activate_weather_event,
    create_deice_request_payload,
    create_fluid_tank,
    create_pad,
    create_pad_payload,
    create_reserved_request,
    create_station,
    create_station_with_permit,
    get_operation_for_request,
    get_success_data,
    make_airline_rep_headers,
    setup_operational_base,
    setup_request_assigned,
    validate_error,
    validate_success,
)


class TestRequestDefaultsAndReservation:
    def test_request_defaults_and_computed_estimate_applied(self, api):
        """PRD §3.3: "A `priority` of `EMERGENCY`, `SCHEDULED`, or `FLEXIBLE` may
        be supplied; it defaults to `SCHEDULED`. From the `size_class`, the system
        derives `estimated_liters`: 200 for a `SMALL` aircraft, 500 for `MEDIUM`,
        and 1200 for `LARGE`."

        Design: Corner/entities/request_defaults_and_computed_estimate_applied
        """
        station = create_station()
        tank = create_fluid_tank(
            station["id"],
            fluid_type="TYPE_I",
            capacity_liters=10000,
            on_hand_liters=5000,
            reorder_threshold_liters=300,
        )
        airline = create_airline()

        payload = create_deice_request_payload(
            airline["id"], station["id"], size_class="MEDIUM"
        )
        resp = api.create_deice_request(
            payload, make_airline_rep_headers(airline["id"])
        )
        data = validate_success(resp, expected_status=201)

        assert data["priority"] == "SCHEDULED"
        assert data["estimated_liters"] == 500
        assert data["status"] == "QUEUED"
        assert data["fluid_reservation_status"] == "RESERVED"
        assert data["assigned_tank_id"] == tank["id"]


class TestDeferRequeueCycle:
    def test_defer_requeue_cycle_status_and_counters(self, api):
        """PRD §3.4: "Deferring a `QUEUED` request moves it to `DEFERRED`,
        increments its `defer_count`, and bumps its `version`. Requeueing returns
        a `DEFERRED` request to `QUEUED` — an intentional `QUEUED → DEFERRED →
        QUEUED` cycle — incrementing the version again."

        Design: Difficulty/non_linear_state_machine/request_defer_requeue_cycle
        """
        station = create_station()
        tank = create_fluid_tank(
            station["id"],
            fluid_type="TYPE_I",
            capacity_liters=10000,
            on_hand_liters=5000,
            reorder_threshold_liters=300,
        )
        airline = create_airline()
        request = create_reserved_request(airline, station, tank, size_class="MEDIUM")

        resp = api.defer_deice_request(
            request["id"], TEST_USERS["pad_operator_headers"]
        )
        deferred = validate_success(resp)
        assert deferred["status"] == "DEFERRED"
        assert deferred["defer_count"] == 1

        resp = api.requeue_deice_request(
            request["id"], TEST_USERS["pad_operator_headers"]
        )
        requeued = validate_success(resp)
        assert requeued["status"] == "QUEUED"
        assert requeued["defer_count"] == 1
        assert requeued["epochs_in_queue"] == 0
        assert requeued["fluid_reservation_status"] == "RESERVED"

    def test_defer_requeue_reservation_retained(self, api):
        """PRD §3.4: "Aborting releases the request's fluid reservation — the
        request leaves the reservation input set of §2.7 — and the tank and
        station derived fields are recomputed." By contrast, defer/requeue does
        not release the reservation.

        Design: Difficulty/non_linear_state_machine/request_defer_requeue_cycle
        """
        station = create_station()
        tank = create_fluid_tank(
            station["id"],
            fluid_type="TYPE_I",
            capacity_liters=10000,
            on_hand_liters=5000,
            reorder_threshold_liters=300,
        )
        airline = create_airline()
        request = create_reserved_request(airline, station, tank, size_class="MEDIUM")

        # Defer and requeue; reservation must remain intact.
        api.defer_deice_request(request["id"], TEST_USERS["pad_operator_headers"])
        api.requeue_deice_request(request["id"], TEST_USERS["pad_operator_headers"])

        resp = api.get_fluid_tank(
            tank["id"], TEST_USERS["pad_operator_headers"]
        )
        tank_after = validate_success(resp)
        assert tank_after["reserved_liters"] == 500
        assert tank_after["available_liters"] == 4500


class TestAssignSideEffects:
    def test_assign_creates_planned_operation_and_marks_pad(self, api):
        """PRD §3.4: "A successful assignment moves the request from `QUEUED` to
        `ASSIGNED`, records the `assigned_pad_id`, and creates the corresponding
        **DeiceOperation** in `PLANNED` status. The operation inherits the
        request's `request_id`, `station_id`, `pad_id`, and `estimated_liters`,
        copies its `tank_id` from the request's `assigned_tank_id`, takes its
        occupancy window from the assignment payload, and carries a null
        `parent_operation_id`. Notably, the pad itself remains `AVAILABLE` at
        this point — physical occupancy begins only at spray start."

        Design: Corner/state_machines/assign_creates_planned_operation_and_marks_pad
        """
        station, permit, tank, pad, airline = setup_operational_base()
        request = create_reserved_request(airline, station, tank, size_class="MEDIUM")

        payload = assign_request_payload(pad["id"])
        resp = api.assign_deice_request(
            request["id"], payload, TEST_USERS["pad_operator_headers"]
        )
        assigned = validate_success(resp)
        assert assigned["status"] == "ASSIGNED"
        assert assigned["assigned_pad_id"] == pad["id"]

        operation = get_operation_for_request(request["id"])
        assert operation["status"] == "PLANNED"
        assert operation["tank_id"] == tank["id"]
        assert operation["estimated_liters"] == 500
        assert operation["parent_operation_id"] is None

        # Pad remains AVAILABLE until spray start.
        resp = api.get_pad(pad["id"], TEST_USERS["pad_operator_headers"])
        pad_after = validate_success(resp)
        assert pad_after["status"] == "AVAILABLE"

    def test_assign_response_immediately_reflects_mutation(self, api):
        """PRD §2: "The system maintains a chain of derived quantities that are
        recomputed eagerly whenever any input changes, so readers always observe
        a consistent position." The assign response body itself carries the
        mutated fields.

        Design: Corner/consistency_model/assign_response_immediately_reflects_mutation
        """
        station, permit, tank, pad, airline = setup_operational_base()
        request = create_reserved_request(airline, station, tank, size_class="MEDIUM")

        payload = assign_request_payload(pad["id"])
        resp = api.assign_deice_request(
            request["id"], payload, TEST_USERS["pad_operator_headers"]
        )
        data = validate_success(resp)
        assert data["status"] == "ASSIGNED"
        assert data["assigned_pad_id"] == pad["id"]


class TestPadGuards:
    def test_out_of_service_pad_rejects_assignment(self, api):
        """PRD §3.4: "The named pad must exist at the same station and currently
        be `AVAILABLE`, else `ERR_PAD_NOT_AVAILABLE`."

        Design: Corner/state_machines/out_of_service_pad_rejects_assignment
        """
        station, permit, tank, pad, airline = setup_operational_base()
        # Take the pad out of service before any request is assigned.
        resp = api.take_pad_out_of_service(
            pad["id"], TEST_USERS["station_admin_headers"]
        )
        validate_success(resp)

        request = create_reserved_request(airline, station, tank, size_class="MEDIUM")
        payload = assign_request_payload(pad["id"])
        resp = api.assign_deice_request(
            request["id"], payload, TEST_USERS["pad_operator_headers"]
        )
        validate_error(resp, ApiErrorId.ERR_PAD_NOT_AVAILABLE)

        resp = api.get_deice_request(
            request["id"], TEST_USERS["pad_operator_headers"]
        )
        assert validate_success(resp)["status"] == "QUEUED"

    def test_small_pad_rejects_large_request(self, api):
        """PRD §3.4: "The pad's `max_size_class` must cover the request's
        `size_class` — a pad serves any size class at or below its maximum,
        where `SMALL` is the smallest and `LARGE` the largest — else
        `ERR_PAD_INCOMPATIBLE`."

        Design: Corner/errors/small_pad_rejects_large_request
        """
        station, permit, tank, pad, airline = setup_operational_base(
            pad_overrides={"max_size_class": "SMALL"}
        )
        request = create_reserved_request(airline, station, tank, size_class="LARGE")
        payload = assign_request_payload(pad["id"])
        resp = api.assign_deice_request(
            request["id"], payload, TEST_USERS["pad_operator_headers"]
        )
        validate_error(resp, ApiErrorId.ERR_PAD_INCOMPATIBLE)

        resp = api.get_deice_request(
            request["id"], TEST_USERS["pad_operator_headers"]
        )
        assert validate_success(resp)["status"] == "QUEUED"


class TestPadWindowOverlap:
    def test_pad_window_half_open_adjacency(self, api):
        """PRD §3.4: "Because windows are half-open, back-to-back bookings where
        one ends exactly when the next begins are permitted; a true collision
        rejects with `ERR_PAD_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/pad_window_half_open_adjacency
        """
        station, permit, tank, pad, airline = setup_operational_base(
            tank_overrides={
                "capacity_liters": 50000,
                "on_hand_liters": 20000,
                "reorder_threshold_liters": 300,
            }
        )
        # R1 assigned [10:00, 10:30) and fully cleared.
        r1 = create_reserved_request(
            airline, station, tank, size_class="SMALL",
            flight_number="AA1", scheduled_departure="2026-05-01T12:00:00Z"
        )
        assign_request_to_pad = assign_request_payload(
            pad["id"],
            window_start="2026-05-01T10:00:00Z",
            window_end="2026-05-01T10:30:00Z",
        )
        resp = api.assign_deice_request(
            r1["id"], assign_request_to_pad, TEST_USERS["pad_operator_headers"]
        )
        validate_success(resp)
        op1 = get_operation_for_request(r1["id"])

        from test_helpers import (
            record_acceptance_inspection,
            record_post_treatment_inspection,
            start_operation,
            complete_operation,
        )
        record_acceptance_inspection(op1["id"], inspector_id="insp-1")
        start_operation(op1["id"], oat_celsius=0)
        complete_operation(op1["id"], actual_liters=10, collected_liters=6)
        record_post_treatment_inspection(op1["id"], result="PASS", inspector_id="insp-2")

        # R2 adjacent [10:30, 11:00) — allowed.
        r2 = create_reserved_request(
            airline, station, tank, size_class="SMALL",
            flight_number="AA2", scheduled_departure="2026-05-01T13:00:00Z"
        )
        payload = assign_request_payload(
            pad["id"],
            window_start="2026-05-01T10:30:00Z",
            window_end="2026-05-01T11:00:00Z",
        )
        resp = api.assign_deice_request(
            r2["id"], payload, TEST_USERS["pad_operator_headers"]
        )
        assert validate_success(resp)["status"] == "ASSIGNED"

        # R3 overlapping [10:45, 11:15) — rejected.
        r3 = create_reserved_request(
            airline, station, tank, size_class="SMALL",
            flight_number="AA3", scheduled_departure="2026-05-01T14:00:00Z"
        )
        payload = assign_request_payload(
            pad["id"],
            window_start="2026-05-01T10:45:00Z",
            window_end="2026-05-01T11:15:00Z",
        )
        resp = api.assign_deice_request(
            r3["id"], payload, TEST_USERS["pad_operator_headers"]
        )
        validate_error(resp, ApiErrorId.ERR_PAD_WINDOW_OVERLAP)

        # R3 retried adjacent [11:00, 11:30) — allowed.
        payload = assign_request_payload(
            pad["id"],
            window_start="2026-05-01T11:00:00Z",
            window_end="2026-05-01T11:30:00Z",
        )
        resp = api.assign_deice_request(
            r3["id"], payload, TEST_USERS["pad_operator_headers"]
        )
        assert validate_success(resp)["status"] == "ASSIGNED"

    def test_pad_window_overlap_rejected_and_adjacent_allowed(self, api):
        """PRD §3.4: "the planned window must not collide with any other booking
        on the same pad: overlap exists precisely when the new window starts
        before an existing operation's `window_end` and that operation's
        `window_start` starts before the new `window_end`, considering only
        operations that have not reached a terminal state (`REWORK_REQUIRED`,
        `CANCELLED`, or `VOIDED`). Because windows are half-open, back-to-back
        bookings where one ends exactly when the next begins are permitted."

        Design: Difficulty/resource_temporal_overlap/pad_window_half_open_adjacency
        """
        station, permit, tank, pad, airline = setup_operational_base(
            tank_overrides={
                "capacity_liters": 50000,
                "on_hand_liters": 20000,
                "reorder_threshold_liters": 300,
            }
        )
        r1 = create_reserved_request(
            airline, station, tank, size_class="SMALL",
            flight_number="AA1", scheduled_departure="2026-05-01T12:00:00Z"
        )
        payload = assign_request_payload(
            pad["id"],
            window_start="2026-05-01T10:00:00Z",
            window_end="2026-05-01T10:30:00Z",
        )
        resp = api.assign_deice_request(
            r1["id"], payload, TEST_USERS["pad_operator_headers"]
        )
        validate_success(resp)

        # Overlapping window rejected.
        r2 = create_reserved_request(
            airline, station, tank, size_class="SMALL",
            flight_number="AA2", scheduled_departure="2026-05-01T13:00:00Z"
        )
        payload = assign_request_payload(
            pad["id"],
            window_start="2026-05-01T10:15:00Z",
            window_end="2026-05-01T10:45:00Z",
        )
        resp = api.assign_deice_request(
            r2["id"], payload, TEST_USERS["pad_operator_headers"]
        )
        validate_error(resp, ApiErrorId.ERR_PAD_WINDOW_OVERLAP)

        # Adjacent window allowed.
        payload = assign_request_payload(
            pad["id"],
            window_start="2026-05-01T10:30:00Z",
            window_end="2026-05-01T11:00:00Z",
        )
        resp = api.assign_deice_request(
            r2["id"], payload, TEST_USERS["pad_operator_headers"]
        )
        assert validate_success(resp)["status"] == "ASSIGNED"


class TestRequestExpiration:
    def test_queued_request_expires_after_two_ops_epochs(self, api):
        """PRD §3.4: "It then walks every request of the station still in
        `QUEUED` or `DEFERRED`, in queue order, adding one to each request's
        `epochs_in_queue`; any request that reaches two or more epochs is moved
        to `EXPIRED` and its fluid reservation released."

        Design: Corner/state_machines/queued_request_expires_after_two_ops_epochs
        """
        station, permit, tank, pad, airline = setup_operational_base(
            tank_overrides={
                "capacity_liters": 10000,
                "on_hand_liters": 5000,
                "reorder_threshold_liters": 300,
            }
        )
        request = create_reserved_request(airline, station, tank, size_class="MEDIUM")

        # Checkpoint 1: request survives with epochs_in_queue == 1.
        resp = api.run_ops_checkpoint(
            station["id"], TEST_USERS["station_admin_headers"]
        )
        station_after_1 = validate_success(resp)
        assert station_after_1["ops_epoch_index"] == 1

        resp = api.get_deice_request(
            request["id"], TEST_USERS["pad_operator_headers"]
        )
        req_after_1 = validate_success(resp)
        assert req_after_1["status"] == "QUEUED"
        assert req_after_1["epochs_in_queue"] == 1

        # Checkpoint 2: request expires.
        resp = api.run_ops_checkpoint(
            station["id"], TEST_USERS["station_admin_headers"]
        )
        station_after_2 = validate_success(resp)
        assert station_after_2["ops_epoch_index"] == 2

        resp = api.get_deice_request(
            request["id"], TEST_USERS["pad_operator_headers"]
        )
        req_after_2 = validate_success(resp)
        assert req_after_2["status"] == "EXPIRED"

        # Reservation released.
        resp = api.get_fluid_tank(
            tank["id"], TEST_USERS["pad_operator_headers"]
        )
        tank_after = validate_success(resp)
        assert tank_after["reserved_liters"] == 0
        assert tank_after["available_liters"] == 5000


class TestAbortTerminalLockdown:
    def test_completed_request_is_terminal_for_abort(self, api):
        """PRD §3.4: "Aborting is available from `QUEUED`, `ASSIGNED`, or
        `DEFERRED` and moves the request to `ABORTED`, terminal." COMPLETED is
        not in the abortable set.

        Design: Corner/state_machines/completed_request_is_terminal_for_abort
        """
        from test_helpers import setup_operation_cleared

        station, permit, tank, pad, airline, request, operation = (
            setup_operation_cleared(actual_liters=300, collected_liters=200)
        )
        assert request["status"] == "COMPLETED"

        resp = api.abort_deice_request(
            request["id"], TEST_USERS["pad_operator_headers"]
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        resp = api.get_deice_request(
            request["id"], TEST_USERS["pad_operator_headers"]
        )
        assert validate_success(resp)["status"] == "COMPLETED"


class TestAssignBlockedByPosture:
    def test_assign_blocked_when_station_permit_suspended(self, api):
        """PRD §3.4: "The station's posture must not be `PERMIT_SUSPENDED`,
        which rejects with `ERR_PERMIT_SUSPENDED`, and must not be
        `FLUID_CONSTRAINED`, which rejects with `ERR_FLUID_CONSTRAINED`."
        PRD §3.7: "An `EnvironmentalOfficer` may suspend an `ACTIVE` permit,
        moving it to `SUSPENDED`, and may reinstate a `SUSPENDED` permit back
        to `ACTIVE`; both actions recompute the station's posture."

        Design: Difficulty/cross_entity_state_dependency/assign_blocked_when_station_permit_suspended
        """
        station, permit, tank, pad, airline = setup_operational_base()
        request = create_reserved_request(airline, station, tank, size_class="MEDIUM")

        # Suspend the permit.
        api.suspend_discharge_permit(
            permit["id"], TEST_USERS["environmental_officer_headers"]
        )

        # Assign blocked.
        payload = assign_request_payload(pad["id"])
        resp = api.assign_deice_request(
            request["id"], payload, TEST_USERS["pad_operator_headers"]
        )
        validate_error(resp, ApiErrorId.ERR_PERMIT_SUSPENDED)

        resp = api.get_deice_request(
            request["id"], TEST_USERS["pad_operator_headers"]
        )
        assert validate_success(resp)["status"] == "QUEUED"

        # Reinstate and assign succeeds.
        api.reinstate_discharge_permit(
            permit["id"], TEST_USERS["environmental_officer_headers"]
        )
        resp = api.assign_deice_request(
            request["id"], payload, TEST_USERS["pad_operator_headers"]
        )
        assert validate_success(resp)["status"] == "ASSIGNED"


class TestAbortReleasesReservation:
    def test_reserved_liters_reconciled_on_abort(self, api):
        """PRD §3.4: "Aborting releases the request's fluid reservation — the
        request leaves the reservation input set of §2.7 — and the tank and
        station derived fields are recomputed."

        Design: Corner/calculations/reserved_liters_reconciled_on_abort
        """
        station = create_station()
        tank = create_fluid_tank(
            station["id"],
            fluid_type="TYPE_I",
            capacity_liters=10000,
            on_hand_liters=5000,
            reorder_threshold_liters=300,
        )
        airline = create_airline()
        request = create_reserved_request(airline, station, tank, size_class="MEDIUM")

        resp = api.get_fluid_tank(
            tank["id"], TEST_USERS["pad_operator_headers"]
        )
        assert validate_success(resp)["reserved_liters"] == 500

        resp = api.abort_deice_request(
            request["id"], make_airline_rep_headers(airline["id"])
        )
        assert validate_success(resp)["status"] == "ABORTED"

        resp = api.get_fluid_tank(
            tank["id"], TEST_USERS["pad_operator_headers"]
        )
        tank_after = validate_success(resp)
        assert tank_after["reserved_liters"] == 0
        assert tank_after["available_liters"] == 5000


class TestReplenish:
    def test_replenish_beyond_tank_capacity_rejected(self, api):
        """PRD §3.1: "When a delivery arrives, a `StationAdmin` replenishes a
        tank with a payload carrying `liters`; if the addition would push
        `on_hand_liters` above the tank's `capacity_liters`, the request is
        rejected with `ERR_TANK_CAPACITY_EXCEEDED`."

        Design: Corner/errors/replenish_beyond_tank_capacity_rejected
        """
        station = create_station()
        tank = create_fluid_tank(
            station["id"],
            fluid_type="TYPE_I",
            capacity_liters=1000,
            on_hand_liters=900,
            reorder_threshold_liters=300,
        )

        # 200 L would exceed capacity.
        resp = api.replenish_fluid_tank(
            tank["id"], {"liters": 200}, TEST_USERS["station_admin_headers"]
        )
        validate_error(resp, ApiErrorId.ERR_TANK_CAPACITY_EXCEEDED)

        # 100 L lands exactly at capacity: allowed.
        resp = api.replenish_fluid_tank(
            tank["id"], {"liters": 100}, TEST_USERS["station_admin_headers"]
        )
        data = validate_success(resp)
        assert data["on_hand_liters"] == 1000

    def test_replenish_retries_unreserved_request_via_selector(self, api):
        """PRD §3.1: "A successful replenish adds the delivered volume,
        recomputes the tank's status and the station's posture and supply
        alert, and then retries fluid reservations: every `UNRESERVED` request
        of that station whose requested `fluid_type` matches the replenished
        tank is reconsidered in queue order — `EMERGENCY` priority first, then
        `SCHEDULED`, then `FLEXIBLE`, with ties broken by earlier
        `scheduled_departure` and then by earlier `created_at` — and each is
        reserved while eligibility continues to hold."
        PRD §3.3: "When no tank qualifies, the request is still created, but
        with `assigned_tank_id` null and `fluid_reservation_status` set to
        `UNRESERVED`; this is a deferred outcome, not an error."

        Design: Corner/calculations/replenish_retries_unreserved_request_via_selector
        """
        station = create_station()
        # Tank starts EMPTY.
        tank = create_fluid_tank(
            station["id"],
            fluid_type="TYPE_I",
            capacity_liters=10000,
            on_hand_liters=0,
            reorder_threshold_liters=300,
        )
        airline = create_airline()

        # Request created UNRESERVED because tank is EMPTY.
        payload = create_deice_request_payload(
            airline["id"], station["id"], size_class="SMALL", fluid_type="TYPE_I"
        )
        resp = api.create_deice_request(
            payload, make_airline_rep_headers(airline["id"])
        )
        request = validate_success(resp, expected_status=201)
        assert request["fluid_reservation_status"] == "UNRESERVED"
        assert request["assigned_tank_id"] is None

        # Replenish the tank.
        resp = api.replenish_fluid_tank(
            tank["id"], {"liters": 1000}, TEST_USERS["station_admin_headers"]
        )
        tank_after = validate_success(resp)
        assert tank_after["status"] == "OK"

        # Request is now RESERVED via the selector retry.
        resp = api.get_deice_request(
            request["id"], TEST_USERS["pad_operator_headers"]
        )
        request_after = validate_success(resp)
        assert request_after["fluid_reservation_status"] == "RESERVED"
        assert request_after["assigned_tank_id"] == tank["id"]

        # Tank reserved_liters reflects the reservation.
        resp = api.get_fluid_tank(
            tank["id"], TEST_USERS["pad_operator_headers"]
        )
        tank_after = validate_success(resp)
        assert tank_after["reserved_liters"] == 200

        # Station alert cleared.
        resp = api.get_station(
            station["id"], TEST_USERS["station_admin_headers"]
        )
        assert validate_success(resp)["active_supply_alert"] is False
