"""Authentication, role authorization, ownership, and reference existence."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    accept_order,
    add_aircraft,
    add_carded_pilot,
    add_crew_member,
    create_active_contract,
    create_assignment,
    create_availability_period_payload,
    create_contract_payload,
    create_draft_invoice,
    create_incident,
    make_agency_finance_headers,
    make_carrier_finance_headers,
    make_pilot_headers,
    place_order,
    set_clock,
    setup_accepted_order,
    setup_carded_pair,
    submit_invoice,
    validate_error,
    validate_success,
)

OPS = TEST_USERS["carrier_ops_headers"]
DISPATCH = TEST_USERS["agency_dispatcher_headers"]
INSPECTOR = TEST_USERS["carding_inspector_headers"]


class TestAuthentication:
    def test_missing_auth_headers_unauthenticated(self, api):
        """PRD §2.1: "A request with a missing header, or a role that is not
        one of these declared values, is rejected with `ERR_UNAUTHENTICATED`
        (HTTP 401)."

        Design: Corner/validations/missing_auth_headers_unauthenticated
        """
        resp = api.list_contracts(headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


class TestRoleAuthorization:
    def test_pilot_cannot_create_contract(self, api):
        """PRD §2.1: "A request whose role is authenticated but does not
        appear on the endpoint's authorized-role list is rejected with
        `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
        PRD §4: "| POST | `/contracts` | Create a contract in DRAFT |
        CarrierOps |".

        Design: Corner/validations/pilot_cannot_create_contract
        """
        contract = create_active_contract()
        pilot = add_crew_member(contract["id"])

        resp = api.create_contract(
            create_contract_payload(contract_number="EU-2026-777",
                                    daily_availability_rate_cents=100,
                                    flight_hour_rate_cents=100,
                                    season_flight_hour_cap_tenths=100),
            make_pilot_headers(pilot["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE,
                       expected_status=403)

    def test_rbac_denial_matrix_spot_checks(self, api):
        """PRD §2.1: "A request whose role is authenticated but does not
        appear on the endpoint's authorized-role list is rejected with
        `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
        PRD §4: "| POST | `/dispatch-orders/{id}/accept` | Accept a placed
        order | CarrierOps |"; "| POST | `/agency-records` | Import an agency
        flight-time record | AgencyFinance |"; "| POST | `/aircraft` |
        Register an aircraft on a contract | CarrierOps |"; "| POST |
        `/invoices/{id}/reconcile` | Reconcile against agency records |
        AgencyFinance |".

        Design: Corner/rbac/rbac_denial_matrix_spot_checks
        """
        contract = create_active_contract()
        aircraft = add_aircraft(contract["id"])
        validate_success(api.create_availability_period(
            contract["id"],
            create_availability_period_payload(aircraft["id"],
                                               service_date="2026-08-03"),
            OPS), 201)
        incident = create_incident()
        order = place_order(contract["id"], incident["id"])
        invoice = create_draft_invoice(contract["id"], "2026-08-03", "2026-08-03")
        submit_invoice(invoice["id"], submitted_by="cf_1",
                       advance_clock_to="2026-08-09T00:00:00Z")

        resp1 = api.accept_dispatch_order(
            order["id"], make_agency_finance_headers("af_1"))
        validate_error(resp1, ApiErrorId.ERR_UNAUTHORIZED_ROLE,
                       expected_status=403)

        resp2 = api.create_agency_record(
            {"contract_id": contract["id"], "assignment_id": aircraft["id"],
             "record_date": "2026-08-03", "agency_flight_hours_tenths": 10},
            INSPECTOR)
        validate_error(resp2, ApiErrorId.ERR_UNAUTHORIZED_ROLE,
                       expected_status=403)

        resp3 = api.create_aircraft(
            {"tail_number": "N300AF", "model": "AT-802F",
             "tank_capacity_gallons": 800, "contract_id": contract["id"]},
            make_carrier_finance_headers("cf_1"))
        validate_error(resp3, ApiErrorId.ERR_UNAUTHORIZED_ROLE,
                       expected_status=403)

        resp4 = api.reconcile_invoice(invoice["id"], OPS)
        validate_error(resp4, ApiErrorId.ERR_UNAUTHORIZED_ROLE,
                       expected_status=403)


class TestPilotOwnership:
    def test_pilot_ownership_forbidden_on_others_assignment(self, api):
        """PRD §2.1: "When `X-User-Role` is `Pilot`, `X-User-ID` is the `id`
        of the acting `CrewMember`; ownership checks on any resource that
        references a crew member compare the resource's foreign-key field —
        most importantly an assignment's `pilot_id` — to `X-User-ID`, and a
        mismatch is rejected with `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403)."
        PRD §3.6: "a `Pilot` caller whose `X-User-ID` does not equal the
        assignment's `pilot_id` is rejected with `ERR_FORBIDDEN_OWNERSHIP`."

        Design: Corner/rbac/pilot_ownership_forbidden_on_others_assignment
        """
        ws = setup_carded_pair()
        pilot2 = add_carded_pilot(ws["contract"]["id"])
        order = setup_accepted_order(ws, quantity=1)
        assignment = create_assignment(
            order["id"], ws["aircraft"]["id"], ws["pilot"]["id"],
            "2026-08-02T08:00:00Z", "2026-08-02T10:00:00Z")

        # Pilot role passes the role check; the other pilot fails ownership.
        resp1 = api.create_flight_log(
            assignment["id"],
            {"logged_date": "2026-08-02", "hobbs_start": 0.0, "hobbs_stop": 1.0},
            make_pilot_headers(pilot2["id"]))
        validate_error(resp1, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP,
                       expected_status=403)

        resp2 = api.launch_assignment(
            assignment["id"], make_pilot_headers(pilot2["id"]))
        validate_error(resp2, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP,
                       expected_status=403)

        after = validate_success(api.get_assignment(assignment["id"], OPS))
        assert after["status"] == "ASSIGNED", "rejected launch leaves ASSIGNED"


class TestNotFoundSweep:
    def test_not_found_sweep_returns_entity_404s(self, api):
        """PRD §2.5: "The request is rejected with the not-found variant for
        the first reference that does not exist, and no later check runs."
        PRD §2.5: "Each resource has its own not-found error, all HTTP 404:
        `ERR_CONTRACT_NOT_FOUND`, `ERR_AIRCRAFT_NOT_FOUND`,
        `ERR_CREW_MEMBER_NOT_FOUND`, `ERR_INCIDENT_NOT_FOUND`,
        `ERR_DISPATCH_ORDER_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`,
        `ERR_INVOICE_NOT_FOUND`, `ERR_AVAILABILITY_PERIOD_NOT_FOUND`,
        `ERR_INSPECTION_NOT_FOUND`, and `ERR_RETARDANT_LOAD_NOT_FOUND`."

        Design: Corner/validations/not_found_sweep_returns_entity_404s
        """
        cases = [
            (api.get_aircraft(NON_EXISTENT_UUID, OPS),
             ApiErrorId.ERR_AIRCRAFT_NOT_FOUND),
            (api.get_crew_member(NON_EXISTENT_UUID, OPS),
             ApiErrorId.ERR_CREW_MEMBER_NOT_FOUND),
            (api.get_incident(NON_EXISTENT_UUID, DISPATCH),
             ApiErrorId.ERR_INCIDENT_NOT_FOUND),
            (api.get_dispatch_order(NON_EXISTENT_UUID, OPS),
             ApiErrorId.ERR_DISPATCH_ORDER_NOT_FOUND),
            (api.get_assignment(NON_EXISTENT_UUID, OPS),
             ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND),
            (api.get_invoice(NON_EXISTENT_UUID,
                             TEST_USERS["carrier_finance_headers"]),
             ApiErrorId.ERR_INVOICE_NOT_FOUND),
            (api.get_availability_period(NON_EXISTENT_UUID, OPS),
             ApiErrorId.ERR_AVAILABILITY_PERIOD_NOT_FOUND),
            (api.complete_carding_inspection(
                NON_EXISTENT_UUID,
                {"result": "PASSED", "completed_at": "2026-08-01T09:00:00Z"},
                INSPECTOR),
             ApiErrorId.ERR_INSPECTION_NOT_FOUND),
            (api.load_retardant_load(
                NON_EXISTENT_UUID, {"loaded_at": "2026-08-01T10:00:00Z"}, OPS),
             ApiErrorId.ERR_RETARDANT_LOAD_NOT_FOUND),
        ]
        for resp, expected in cases:
            validate_error(resp, expected, expected_status=404)
