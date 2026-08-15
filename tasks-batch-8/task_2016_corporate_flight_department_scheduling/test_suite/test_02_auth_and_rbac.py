"""Authentication, authorization, and validation-ordering rules."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    create_aircraft_payload,
    create_trip,
    make_dispatcher_headers,
    make_executive_requester_headers,
    reset_clock,
    setup_bu_and_passenger,
    setup_submitted_trip,
    validate_error,
    TEST_USERS,
)

MANAGER = TEST_USERS["manager_headers"]
FINANCE = TEST_USERS["finance_headers"]
PLANNER = TEST_USERS["planner_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


class TestAuthentication:
    def test_missing_role_header_unauthenticated(self, api):
        """PRD §2.1: "A request whose headers are missing, or whose declared role
        is not one of these five, is rejected with `ERR_UNAUTHENTICATED`
        (HTTP 401)."

        Design: Corner/errors/error_unauthenticated_missing_headers
        """
        reset_clock()
        resp = api.list_aircraft({"Content-Type": "application/json"})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestAuthorization:
    def test_finance_admin_cannot_create_aircraft(self, api):
        """PRD §2.1: "A request whose role is valid but not permitted on the
        target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §4: POST /flight-ops/aircraft lists only FlightDeptManager under
        Authorized Role(s).

        Design: Corner/errors/error_unauthorized_wrong_role
        """
        reset_clock()
        resp = api.create_aircraft(
            create_aircraft_payload(tail_number="N7001CF"), FINANCE)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

    def test_dispatcher_cannot_approve_trip(self, api):
        """PRD §2.1: "A request whose role is valid but not permitted on the
        target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §4: POST /flight-ops/trip-requests/{id}/approve lists only
        FlightDeptManager under Authorized Role(s).

        Design: Corner/roles/rbac_dispatcher_cannot_approve_trip
        """
        _bu, _pax, trip, _legs = setup_submitted_trip()
        resp = api.approve_trip(trip["id"], DISPATCHER)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

    def test_executive_requester_cannot_settle(self, api):
        """PRD §2.1: "A request whose role is valid but not permitted on the
        target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §4: POST /flight-ops/trip-requests/{id}/settle lists only
        FinanceAdmin under Authorized Role(s).

        Design: Corner/roles/rbac_executive_cannot_settle
        """
        bu, pax = setup_bu_and_passenger()
        trip = create_trip(pax, bu["id"])
        headers = make_executive_requester_headers(pax["id"])
        resp = api.settle_trip(trip["id"], 1, headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

    def test_maintenance_planner_cannot_assign_crew(self, api):
        """PRD §2.1: "A request whose role is valid but not permitted on the
        target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §4: POST /flight-ops/flight-legs/{id}/assign-crew lists only
        Dispatcher under Authorized Role(s).

        Design: Corner/roles/rbac_maintenance_planner_cannot_assign_crew
        """
        reset_clock()
        resp = api.assign_crew(NON_EXISTENT_UUID, "x", "y", PLANNER)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


class TestValidationOrdering:
    def test_state_check_beats_crew_legality(self, api):
        """PRD §2.6: "then state-machine validity — whether the target entity's
        current state even permits the requested transition (`ERR_INVALID_STATE`,
        HTTP 409) — then optimistic-concurrency freshness (`ERR_STALE_VERSION`,
        HTTP 412), and only then the business rules. Within the business tier the
        order is likewise fixed: crew legality (`ERR_CREW_ILLEGAL`), aircraft
        availability (`ERR_AIRCRAFT_NOT_AVAILABLE`), ..."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_safety_assign_crew_on_planned_leg_with_expired_training
        """
        from test_helpers import (
            create_aircraft, create_crew, setup_approved_trip,
        )
        reset_clock()
        create_aircraft()
        pic = create_crew("PIC", ("LIGHT_JET",), training_valid_until="2026-07-01T00:00:00Z")
        sic = create_crew("SIC", ("LIGHT_JET",))
        _bu, _pax, trip, legs = setup_approved_trip()
        # Leg is still PLANNED (assign-aircraft never called) AND the PIC's
        # training is expired: the state check must surface first.
        resp = api.assign_crew(legs[0]["id"], pic["id"], sic["id"],
                               make_dispatcher_headers("disp-1"))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_expired_training_crew_illegal_in_isolation(self, api):
        """PRD §3.4: "Both crew members must be `ACTIVE`, must each hold the
        assigned aircraft's `aircraft_type` within their `type_ratings`, and must
        each have `training_valid_until` strictly later than the leg's
        `scheduled_departure_utc` — a pilot whose recurrent training expires at or
        before departure is illegal for that leg. Crew-legality failures are
        rejected with `ERR_CREW_ILLEGAL` (HTTP 422)"

        Design: Difficulty/priority_pair_validation_conflict/state_vs_safety_assign_crew_on_planned_leg_with_expired_training
        """
        from test_helpers import (
            assign_aircraft, create_aircraft, create_crew, setup_approved_trip,
        )
        reset_clock()
        create_aircraft()
        pic = create_crew("PIC", ("LIGHT_JET",), training_valid_until="2026-07-01T00:00:00Z")
        sic = create_crew("SIC", ("LIGHT_JET",))
        _bu, _pax, trip, legs = setup_approved_trip()
        assign_aircraft(trip["id"])
        # Leg is AIRCRAFT_ASSIGNED (state valid); only the training rule fails.
        resp = api.assign_crew(legs[0]["id"], pic["id"], sic["id"],
                               make_dispatcher_headers("disp-1"))
        validate_error(resp, ApiErrorId.ERR_CREW_ILLEGAL)
