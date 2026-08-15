"""TripRequest dual-axis state machine: valid/invalid transitions, terminal
lockdown, idempotency, parallel-dimension independence, and OCC."""
from test_helpers import (
    ApiErrorId,
    add_catering,
    confirm_catering,
    assign_aircraft,
    create_trip,
    get_success_data,
    make_dispatcher_headers,
    make_executive_requester_headers,
    reset_clock,
    setup_bu_and_passenger,
    setup_approved_trip,
    setup_assigned_trip,
    setup_submitted_trip,
    submit_trip,
    validate_error,
    validate_success,
    TEST_USERS,
)

MANAGER = TEST_USERS["manager_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


class TestTripTransitions:
    def test_submit_from_draft_succeeds(self, api):
        """PRD §3.2: "Submission moves `approval_status` from `DRAFT` to
        `SUBMITTED`"
        PRD §3.2: "A new trip opens with `approval_status` in `DRAFT`,
        `assignment_status` in `UNASSIGNED`, and `settlement_status` in
        `UNSETTLED`"

        Design: Corner/state_machines/trip_submit_from_draft_succeeds
        """
        _bu, _pax, trip, _legs = setup_submitted_trip()
        data = get_success_data(api.get_trip_request(trip["id"], MANAGER))
        assert data["approval_status"] == "SUBMITTED"
        assert data["assignment_status"] == "UNASSIGNED"

    def test_approve_from_draft_rejected_invalid_state(self, api):
        """PRD §3.2: "From `SUBMITTED`, a `FlightDeptManager` either approves or
        rejects."
        PRD §2.6: "then state-machine validity — whether the target entity's
        current state even permits the requested transition (`ERR_INVALID_STATE`,
        HTTP 409)"

        Design: Corner/state_machines/trip_approve_from_draft_rejected_invalid_state
        """
        bu, pax = setup_bu_and_passenger()
        trip = create_trip(pax, bu["id"])
        resp = api.approve_trip(trip["id"], MANAGER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_terminal_rejected_lockdown(self, api):
        """PRD §3.2: "Rejection moves `approval_status` to `REJECTED` — a terminal
        state for the trip"

        Design: Corner/state_machines/terminal_trip_rejected_lockdown_no_further_transitions
        """
        _bu, requester, trip, _legs = setup_submitted_trip()
        get_success_data(api.reject_trip(trip["id"], MANAGER))
        resp = api.submit_trip(trip["id"], make_executive_requester_headers(requester["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_cancel_already_cancelled_returns_invalid_state(self, api):
        """PRD §3.2: "a `Dispatcher`, the originating `ExecutiveRequester`, or a
        `FlightDeptManager` can cancel a trip whose `assignment_status` is
        `UNASSIGNED` or `ASSIGNED`, moving it to the terminal `CANCELLED`."

        Design: Corner/state_machines/cancel_already_cancelled_trip_idempotency_returns_invalid_state
        """
        _bu, _pax, trip, _legs = setup_approved_trip()
        get_success_data(api.cancel_trip(trip["id"], make_dispatcher_headers("disp-1")))
        resp = api.cancel_trip(trip["id"], make_dispatcher_headers("disp-1"))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestParallelDimensions:
    def test_approval_leaves_assignment_unassigned(self, api):
        """PRD §1 (Introduction): "The system is organized as a dual-axis view of
        a trip — an approval dimension owned by department management and an
        assignment dimension owned by dispatch"
        PRD §3.2: "it moves `approval_status` to `APPROVED`"

        Design: Difficulty/non_linear_state_machine/trip_request_parallel_dimensions_independent
        """
        _bu, _pax, trip, _legs = setup_approved_trip()
        data = get_success_data(api.get_trip_request(trip["id"], MANAGER))
        assert data["approval_status"] == "APPROVED"
        assert data["assignment_status"] == "UNASSIGNED", (
            "approval must not advance the assignment axis"
        )

    def test_cancel_after_approve_keeps_approval_status(self, api):
        """PRD §3.2: "a `Dispatcher`, the originating `ExecutiveRequester`, or a
        `FlightDeptManager` can cancel a trip whose `assignment_status` is
        `UNASSIGNED` or `ASSIGNED`, moving it to the terminal `CANCELLED`."

        Design: Difficulty/non_linear_state_machine/trip_request_parallel_dimensions_independent
        """
        _bu, _pax, trip, _legs = setup_approved_trip()
        get_success_data(api.cancel_trip(trip["id"], make_dispatcher_headers("disp-1")))
        data = get_success_data(api.get_trip_request(trip["id"], MANAGER))
        assert data["approval_status"] == "APPROVED", "approval axis unchanged by cancel"
        assert data["assignment_status"] == "CANCELLED", "assignment axis advanced"


class TestRejectCascade:
    def test_reject_cascades_leg_to_cancelled(self, api):
        """PRD §3.2: "Rejection moves `approval_status` to `REJECTED` — a terminal
        state for the trip — and cascades: every `PLANNED` leg drops to
        `CANCELLED`, and every catering order or ground transport still in
        `REQUESTED` or `CONFIRMED` is cancelled with it."

        Design: Difficulty/transitive_cascade/reject_trip_cascades_leg_then_services
        """
        _bu, requester, trip, legs = setup_submitted_trip()
        add_catering(legs[0]["id"])
        get_success_data(api.reject_trip(trip["id"], MANAGER))
        leg = get_success_data(api.get_flight_leg(legs[0]["id"], DISPATCHER))
        assert leg["status"] == "CANCELLED", "reject cascades PLANNED legs to CANCELLED"

    def test_reject_cascades_confirmed_services_to_cancelled(self, api):
        """PRD §3.2: "Rejection moves `approval_status` to `REJECTED` — a terminal
        state for the trip — and cascades: every `PLANNED` leg drops to
        `CANCELLED`, and every catering order or ground transport still in
        `REQUESTED` or `CONFIRMED` is cancelled with it."

        Design: Difficulty/transitive_cascade/reject_trip_cascades_leg_then_services
        """
        _bu, requester, trip, legs = setup_submitted_trip()
        order = confirm_catering(add_catering(legs[0]["id"])["id"])
        get_success_data(api.reject_trip(trip["id"], MANAGER))
        orders, _meta = None, None
        resp = api.list_catering_orders(legs[0]["id"], DISPATCHER)
        body = resp.json()
        orders = body["data"]
        assert orders[0]["status"] == "CANCELLED", (
            "CONFIRMED catering order is cancelled by the reject cascade"
        )


class TestOptimisticConcurrency:
    def test_version_increments_on_each_mutation(self, api):
        """PRD §2.5: "**`version` (integer):** A system-managed integer that
        increments with every modification to the resource, including mutations
        driven by cascades or settlement math."

        Design: Corner/cross_cutting_layers/occ_version_increments_on_mutation
        """
        reset_clock()
        bu, pax = setup_bu_and_passenger()
        trip = create_trip(pax, bu["id"])
        v0 = trip["version"]
        assert v0 == 1
        headers = make_executive_requester_headers(pax["id"])
        get_success_data(api.create_flight_leg(trip["id"], {
            "leg_sequence": 1, "origin_icao": "KTEB", "destination_icao": "KDCA",
            "scheduled_departure_utc": "2026-08-10T12:00:00Z",
            "scheduled_arrival_utc": "2026-08-10T14:00:00Z",
            "distance_statute_miles": 200,
        }, headers))
        v1 = get_success_data(api.submit_trip(trip["id"], headers))["version"]
        assert v1 == v0 + 1, "submit increments the trip version by one"
        v2 = get_success_data(api.approve_trip(trip["id"], MANAGER))["version"]
        assert v2 == v1 + 1, "approve increments the trip version by one"

    def test_assign_aircraft_missing_version_fails_validation(self, api):
        """PRD §2.9: "Each of these requests must carry
        `expected_trip_request_version`, a non-optional input field holding the
        `version` of the `TripRequest` the client last observed."
        PRD §2.6: "A malformed body — wrong types, missing required fields,
        unparseable payloads — is rejected with `ERR_VALIDATION` (HTTP 400)."

        Design: Corner/validations/assign_aircraft_without_occ_version_fails_validation
        """
        _bu, _pax, trip, _legs = setup_approved_trip()
        resp = api.assign_aircraft_raw(trip["id"], {}, DISPATCHER)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_assign_aircraft_stale_version_returns_412(self, api):
        """PRD §2.9: "If that value does not match the trip's current `version`
        on the server — because another writer has advanced the trip since the
        client read it, for example through a passenger-list change, a leg
        insertion, or a prior settle — the request is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/validations/assign_aircraft_with_stale_version_returns_412
        """
        from test_helpers import add_leg, create_aircraft
        reset_clock()
        create_aircraft()
        _bu, requester, trip, _legs = setup_approved_trip()
        observed_version = trip["version"]
        # A leg insertion after the client observed the version advances the
        # trip version (PRD §2.9 lists "a leg insertion" as a version advancer),
        # leaving the trip still UNASSIGNED so the OCC check is reachable.
        add_leg(trip, requester, leg_sequence=2,
                scheduled_departure_utc="2026-08-11T12:00:00Z",
                scheduled_arrival_utc="2026-08-11T14:00:00Z",
                distance_statute_miles=200)
        resp = api.assign_aircraft(trip["id"], observed_version, DISPATCHER)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
