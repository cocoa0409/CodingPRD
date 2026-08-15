"""Auth header enforcement, role-based access control, and ownership checks."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_diversion_payload,
    create_facility_payload,
    create_transfer_request_payload,
    dispatch_consult,
    get_success_data,
    make_accepting_physician_headers,
    make_bed_manager_headers,
    make_coordinator_headers,
    make_house_supervisor_headers,
    set_clock,
    setup_facility_with_physician,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["sysadmin_headers"]
BED_MGR = TEST_USERS["bed_manager_headers"]
COORD = TEST_USERS["coordinator_headers"]
SUPERVISOR = TEST_USERS["house_supervisor_headers"]
PLANNER = TEST_USERS["capacity_planner_headers"]


class TestAuthHeaders:
    def test_missing_auth_header_returns_400(self, api):
        """PRD §2.1: "A request in which either header is missing or empty is
        rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/missing_auth_header_returns_400
        """
        facility = get_success_data(api.create_facility(
            create_facility_payload(name="Auth Fac", region="R1"), ADMIN))
        resp = api.get_facility(facility["id"], {})
        validate_error(
            resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

    def test_auth_beats_role_priority(self, api):
        """PRD §2.8: "Authentication context comes first: missing or empty
        headers are rejected before anything else, followed by role
        authorization and entity-backed ownership checks."

        Design: Corner/validations/auth_beats_role_priority
        """
        # No headers at all AND the endpoint is role-restricted: the missing
        # header error must surface, not the permission error.
        resp = api.create_facility(
            create_facility_payload(name="Nope", region="R1"), {})
        validate_error(
            resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


class TestRoleDenial:
    def test_wrong_role_denied_on_exclusive_operation(self, api):
        """PRD §2.1: "Each write endpoint is restricted to the roles listed in
        Section 4; a request whose role is not authorized for the endpoint, or
        that fails an entity-backed ownership check, is rejected with
        `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

        Design: Corner/validations/wrong_role_denied_on_exclusive_operation
        """
        resp = api.create_facility(
            create_facility_payload(name="Nope", region="R1"),
            make_accepting_physician_headers("some-physician-id"))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_coordinator_cannot_respond_to_consult(self, api):
        """PRD §3.3: "The consulted physician responds through a decision
        operation carrying `decision` and, when declining, a `decline_reason`."
        PRD §4: the consult-response row authorizes only `AcceptingPhysician`.
        PRD §2.1: "Each write endpoint is restricted to the roles listed in
        Section 4; a request whose role is not authorized for the endpoint, or
        that fails an entity-backed ownership check, is rejected with
        `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

        Design: Corner/rbac/coordinator_cannot_respond_to_consult
        """
        set_clock()
        bundle = setup_facility_with_physician(name="RBAC Fac")
        facility = bundle["facility"]
        physician = bundle["physician"]
        from test_helpers import create_transfer_request
        request = create_transfer_request(facility["id"], patient_ref="PRB")
        dispatch_consult(request["id"], physician["id"])
        resp = api.consult_response(
            request["id"], {"decision": "ACCEPT"}, COORD)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_bed_manager_cannot_declare_diversion(self, api):
        """PRD §3.7: "A `HouseSupervisor` declares a diversion window on a
        facility by supplying a `level` of `FULL` or `SERVICE`, the window
        bounds `starts_at` and `ends_at`".
        PRD §2.1: "Each write endpoint is restricted to the roles listed in
        Section 4; a request whose role is not authorized for the endpoint, or
        that fails an entity-backed ownership check, is rejected with
        `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

        Design: Corner/rbac/bed_manager_cannot_declare_diversion
        """
        facility = get_success_data(api.create_facility(
            create_facility_payload(name="RBAC2 Fac", region="R1"), ADMIN))
        resp = api.create_diversion(
            facility["id"],
            create_diversion_payload(level="FULL",
                                     starts_at="2026-08-01T00:00:00Z",
                                     ends_at="2026-08-01T02:00:00Z"),
            BED_MGR)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_planner_exclusive_forecast_publish(self, api):
        """PRD §3.9: "A `CapacityPlanner` generates a capacity forecast for a
        facility by supplying `horizon_hours`, the number of hours to project,
        between 1 and 72."
        PRD §2.1: "Each write endpoint is restricted to the roles listed in
        Section 4; a request whose role is not authorized for the endpoint, or
        that fails an entity-backed ownership check, is rejected with
        `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

        Design: Corner/rbac/planner_exclusive_forecast_publish
        """
        set_clock()
        facility = get_success_data(api.create_facility(
            create_facility_payload(name="RBAC3 Fac", region="R1"), ADMIN))
        forecast = get_success_data(api.create_capacity_forecast(
            facility["id"], {"horizon_hours": 2}, PLANNER))
        resp = api.publish_capacity_forecast(forecast["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
        resp2 = api.create_capacity_forecast(
            facility["id"], {"horizon_hours": 2}, SUPERVISOR)
        validate_error(resp2, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


class TestEntityBackedOwnership:
    def test_consult_ownership_wrong_physician_denied(self, api):
        """PRD §3.3: "Only the physician whose `id` equals the request's
        `accepting_physician_id` may respond — an `AcceptingPhysician` caller
        whose `X-User-ID` does not match is rejected with
        `ERR_INSUFFICIENT_PERMISSIONS`".

        Design: Corner/validations/consult_ownership_wrong_physician_denied
        """
        set_clock()
        facility = get_success_data(api.create_facility(
            create_facility_payload(name="Own Fac", region="R1"), ADMIN))
        from test_helpers import add_physician, create_transfer_request
        dr_a = add_physician(facility["id"], full_name="Dr A",
                             services=("CARDIAC",))
        dr_b = add_physician(facility["id"], full_name="Dr B",
                             services=("CARDIAC",))
        request = create_transfer_request(facility["id"], patient_ref="POWN")
        dispatch_consult(request["id"], dr_a["id"])
        resp = api.consult_response(
            request["id"], {"decision": "ACCEPT"},
            make_accepting_physician_headers(dr_b["id"]))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
        after = validate_success(api.get_transfer_request(request["id"], COORD))
        assert after["status"] == "CONSULT_PENDING"
