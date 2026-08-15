"""Header/role enforcement, ownership, response envelope, and list scoping."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    create_uld_payload,
    get_booking,
    make_booking,
    make_flight,
    make_forwarder_headers,
    make_open_flight,
    make_uld_type,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestHeaderEnforcement:
    def test_request_missing_header_context_rejected(self, api):
        """PRD §2.1: "Every request must include `X-User-ID` to identify the
        acting operator and `X-User-Role` to declare the capacity in which they
        act. A request in which either header is missing or empty is rejected
        with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/errors/request_missing_header_context_rejected
        """
        res = api.list_flights(headers={})
        validate_error(
            res, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER
        )

    def test_role_check_precedes_existence_forbidden(self, api, ramp_operator_headers):
        """PRD §2.7: "A failure at any rung stops evaluation immediately and
        produces that rung's error, so an earlier failure always masks later
        ones." — rung 2 is "Role authorization. The declared role must be among
        the endpoint's authorized roles, else `ERR_FORBIDDEN` (HTTP 403)." and
        rung 3 is "Resource existence. ... Any miss yields `ERR_NOT_FOUND`
        (HTTP 404)."
        PRD §4: "Close an OPEN_FOR_BOOKING flight; requires no DRAFT plans |
        CapacityController"

        Design: Corner/validations/role_check_precedes_existence_forbidden
        """
        res = api.close_flight(NON_EXISTENT_UUID, ramp_operator_headers)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN)


class TestRoleExclusivity:
    def test_forwarder_cannot_accept_booking(
        self, api, forwarder_agent_headers, capacity_controller_headers
    ):
        """PRD §2.1: "a request whose `X-User-Role` is not among an endpoint's
        declared roles is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: "Accept a REQUESTED booking, debiting flight capacity |
        CapacityController"

        Design: Corner/rbac/forwarder_cannot_accept_booking
        """
        flight = make_open_flight(flight_number="CA340")
        booking = make_booking(flight["id"], shipper_ref="SHP-RB")
        res = api.accept_booking(booking["id"], forwarder_agent_headers)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN)
        assert get_booking(booking["id"])["status"] == "REQUESTED", (
            "A forbidden call must not mutate the booking"
        )

    def test_claims_adjuster_cannot_place_customs_hold(
        self, api, claims_adjuster_headers
    ):
        """PRD §2.1: "a request whose `X-User-Role` is not among an endpoint's
        declared roles is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: "Place a customs hold on a booking (ACTIVE) | CustomsOfficer"

        Design: Corner/rbac/claims_adjuster_cannot_place_customs_hold
        """
        flight = make_flight(flight_number="CA341")
        booking = make_booking(flight["id"], shipper_ref="SHP-RB2")
        res = api.create_customs_hold(
            booking["id"], {"reason_code": "DOC_CHECK"}, claims_adjuster_headers
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN)

    def test_dg_inspector_cannot_create_uld(self, api, dg_inspector_headers):
        """PRD §2.1: "a request whose `X-User-Role` is not among an endpoint's
        declared roles is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: "Register a ULD unit (SERVICEABLE) | RampOperator"

        Design: Corner/rbac/dg_inspector_cannot_create_uld
        """
        uld_type = make_uld_type()
        res = api.create_uld(
            create_uld_payload(uld_type["id"], uld_code="AKE00122CA"),
            dg_inspector_headers,
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN)


class TestOwnershipEnforcement:
    def test_cancel_other_forwarders_booking_forbidden(self, api):
        """PRD §3.2: "The forwarder's own escape hatch is cancellation,
        restricted to the booking's owner — an `X-User-ID` that does not match
        `created_by_user_id` is refused with `ERR_BOOKING_NOT_OWNED` — and
        permitted only from `REQUESTED` or `ACCEPTED` (`ERR_BOOKING_INVALID_STATE`
        otherwise)."

        Design: Corner/validations/cancel_other_forwarders_booking_forbidden
        """
        flight = make_flight(flight_number="CA328")
        booking = make_booking(flight["id"], user_id="fwd-1", shipper_ref="SHP-OWN")
        res = api.cancel_booking(booking["id"], make_forwarder_headers("fwd-2"))
        validate_error(res, ApiErrorId.ERR_BOOKING_NOT_OWNED)
        cancelled = validate_success(
            api.cancel_booking(booking["id"], make_forwarder_headers("fwd-1"))
        )
        assert cancelled["status"] == "CANCELLED"


class TestResponseEnvelope:
    def test_response_envelope_object_and_error_shapes(
        self, api, capacity_controller_headers
    ):
        """PRD §2.2: "The `api_request_id` is a server-generated unique
        identifier for the request that starts with `req_`." and "The
        `response_type` is either "object" for a single resource or "array" for
        a list of resources."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error." and "The `message` provides a
        human-readable explanation of what went wrong."

        Design: Corner/endpoints/response_envelope_object_and_error_shapes
        """
        flight = make_flight(flight_number="CA329")
        success_res = api.get_flight(flight["id"], capacity_controller_headers)
        body = success_res.json()
        assert success_res.status_code == 200
        assert body["response_type"] == "object"
        assert isinstance(body["meta"]["api_request_id"], str)
        assert body["meta"]["api_request_id"].startswith("req_")
        assert isinstance(body["meta"]["api_request_timestamp"], str)

        error_res = api.get_flight(NON_EXISTENT_UUID, capacity_controller_headers)
        error_data = validate_error(error_res, ApiErrorId.ERR_NOT_FOUND)
        assert error_data["error_id"] == "ERR_NOT_FOUND"
        assert error_data["message"].strip(), "error message must be non-empty"


class TestResourceLookupAndScoping:
    def test_unknown_flight_returns_not_found(self, api, capacity_controller_headers):
        """PRD §2.7: "Resource identifiers in the path must exist and are
        validated left to right — a request naming a non-existent booking id
        and a non-existent declaration id fails on the booking first — and
        identifiers referenced in the request body (`flight_id`, `uld_type_id`,
        `uld_id`, `booking_id`) must likewise exist. Any miss yields
        `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/unknown_flight_returns_not_found
        """
        res = api.get_flight(NON_EXISTENT_UUID, capacity_controller_headers)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND)

    def test_flight_bookings_sublist_filters_by_parent(
        self, api, capacity_controller_headers
    ):
        """PRD §4: "List bookings allocated to a flight" — the sub-list is
        scoped to the flight named in the path.
        PRD §2.3: "Unless otherwise specified, every list endpoint returns
        resources sorted by `created_at` in ascending order."

        Design: Corner/entities/flight_bookings_sublist_filters_by_parent
        """
        flight1 = make_flight(flight_number="CA304", max_payload_kg=5000)
        flight2 = make_flight(flight_number="CA305", max_payload_kg=5000)
        booking1 = make_booking(
            flight1["id"], shipper_ref="SHP-S1", gross_weight_kg=100, volume_m3=1
        )
        make_booking(flight2["id"], shipper_ref="SHP-S2", gross_weight_kg=200, volume_m3=2)
        rows, meta = validate_paginated(
            api.list_flight_bookings(flight1["id"], capacity_controller_headers)
        )
        assert len(rows) == 1 and meta["total_count"] == 1, (
            "The sub-list must not leak bookings from another flight"
        )
        assert rows[0]["id"] == booking1["id"]
