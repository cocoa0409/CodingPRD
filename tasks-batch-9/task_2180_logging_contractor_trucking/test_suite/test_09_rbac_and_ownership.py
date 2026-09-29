"""Authentication, role authorisation and the three identity-binding ownership rules."""
import pytest

from test_helpers import (
    ApiErrorId,
    build_network,
    build_user_headers,
    certify_ticket,
    compile_statement,
    create_haul_contractor,
    create_mill,
    deliver_load,
    file_all_coverages,
    load_at_mill,
    make_accountant_headers,
    make_carrier_headers,
    make_scaler_headers,
    read_delivery_ticket,
    read_load,
    read_mill,
    read_mill_contract,
    read_settlement_statement,
    dispatch_load,
    submit_statement,
    validate_error,
    validate_paginated,
    validate_success,
    write_ticket,
)


class TestAuthenticationAndAuthorisation:
    def test_a_role_outside_the_six_declared_names_is_unauthenticated(self, api):
        """PRD §2.1: "Every request to every endpoint — reads included — must carry two
        headers: `X-User-ID`, identifying the caller, and `X-User-Role`, naming the
        caller's role. If either header is absent, or if `X-User-Role` is not one of
        the six role names below spelled exactly, the request is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."
        PRD §2.1: "The six roles are `PlatformAdmin`, `OperationsManager`,
        `HaulContractor`, `MillScaler`, `SafetyOfficer` and `SettlementAccountant`."

        Design: Corner/validations/unknown_x_user_role_header_returns_unauthenticated
        """
        headers = build_user_headers("aud-1", "Auditor")

        response = api.create_mill(
            {"name": "Cascade Mill A", "state_code": "OR", "receiving_status": "OPEN"},
            headers,
        )
        validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)

    def test_an_operations_manager_may_not_certify_a_scale_ticket(
        self, api, ops_headers
    ):
        """PRD §2.1: "If both headers are well-formed but the named role is not among
        the roles authorised for the endpoint being called, the request is rejected
        with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §2.1: "A `MillScaler` is a scale-house operator acting on behalf of exactly
        one mill."

        Design: Corner/rbac/operations_manager_cannot_certify_a_delivery_ticket
        """
        scn = build_network()
        load = load_at_mill(scn)
        ticket = write_ticket(scn, load["id"])

        response = api.certify_delivery_ticket(ticket["id"], ops_headers)
        validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value, 403)

        assert read_delivery_ticket(ticket["id"])["ticket_status"] == "DRAFT"
        assert read_load(load["id"])["dispatch_status"] == "AT_MILL"

    def test_a_haul_contractor_may_not_dispatch_a_load(self, api):
        """PRD §2.1: "If both headers are well-formed but the named role is not among
        the roles authorised for the endpoint being called, the request is rejected
        with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §2.1: "An `OperationsManager` is the logging contractor's woods boss: they
        open tracts, compile and approve production plans, allocate crews and
        equipment, run the tract through its lifecycle, declare and lift shutdowns, and
        dispatch loads."

        Design: Corner/rbac/haul_contractor_cannot_dispatch_a_load
        """
        scn = build_network()

        response = api.create_load(
            {
                "tract_id": scn["tract_id"],
                "mill_contract_id": scn["mc_a_id"],
                "haul_route_id": scn["route_a_id"],
                "truck_id": scn["truck_id"],
                "declared_species": "DOUGLAS_FIR",
                "declared_grade": "SAWLOG_1",
                "estimated_net_tons": 26.5,
                "scheduled_depart_at": "2026-08-03T08:00:00Z",
                "scheduled_arrive_at": "2026-08-03T10:00:00Z",
            },
            scn["carrier_headers"],
        )
        validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value, 403)

        contract = read_mill_contract(scn["mc_a_id"])
        assert contract["reserved_tons"] == pytest.approx(0.00, abs=0.005)
        assert contract["available_tons"] == pytest.approx(500.00, abs=0.005)

    def test_a_safety_officer_may_not_compile_a_settlement_statement(
        self, api, safety_headers
    ):
        """PRD §2.1: "A `SafetyOfficer` is an independent compliance auditor who
        records safety findings, revokes insurance certificates, and suspends or
        reinstates carriers, but who never dispatches, scales or settles."
        PRD §2.1: "If both headers are well-formed but the named role is not among the
        roles authorised for the endpoint being called, the request is rejected with
        `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/safety_officer_cannot_compile_a_settlement_statement
        """
        carrier = create_haul_contractor()
        file_all_coverages(carrier["id"])
        version = validate_success(
            api.get_haul_contractor(carrier["id"], safety_headers)
        )["version"]

        response = api.create_settlement_statement(
            {
                "haul_contractor_id": carrier["id"],
                "period_start": "2026-08-01",
                "period_end": "2026-08-31",
                "expected_haul_contractor_version": version,
            },
            safety_headers,
        )
        validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value, 403)

        rows, meta = validate_paginated(
            api.list_settlement_statements(
                safety_headers,
                params={"haul_contractor_id": carrier["id"], "limit": 100},
            )
        )
        assert meta["total_count"] == 0, "no statement is created by a refused compile"


class TestIdentityBoundOwnership:
    def test_a_carrier_cannot_depart_another_carriers_load(self, api, admin_headers):
        """PRD §2.1: "When `X-User-Role` is `HaulContractor`, `X-User-ID` is the `id` of
        the acting `HaulContractor`; ownership checks on any resource that references a
        `HaulContractor` compare the resource's `haul_contractor_id` to `X-User-ID`. A
        carrier that acts on a load, truck, insurance certificate or settlement
        statement belonging to a different carrier is refused with
        `ERR_CONTRACTOR_NOT_OWNER` (HTTP 403)."

        Design: Corner/rbac/a_carrier_cannot_depart_another_carriers_load
        """
        scn = build_network()
        load = dispatch_load(scn)
        other = create_haul_contractor(
            name="Summit Log Transport", dot_number="DOT-880911", base_state_code="WA"
        )

        response = api.depart_load(load["id"], make_carrier_headers(other["id"]))
        validate_error(response, ApiErrorId.ERR_CONTRACTOR_NOT_OWNER.value, 403)

        load_row = read_load(load["id"])
        assert load_row["dispatch_status"] == "DISPATCHED"
        assert load_row.get("departed_at") is None
        assert load_row["haul_contractor_id"] == scn["hc_id"]

    def test_a_scaler_cannot_close_a_different_mills_yard(self, api):
        """PRD §2.1: "When `X-User-Role` is `MillScaler`, `X-User-ID` is the `id` of the
        acting `Mill`; ownership checks on any resource that references a `Mill` compare
        the resource's `mill_id` to `X-User-ID`. A scaler acting on a ticket, load or
        mill whose mill identity differs from its own is refused with
        `ERR_SCALER_MILL_MISMATCH` (HTTP 403)."

        Design: Corner/rbac/a_scaler_cannot_close_a_different_mills_yard
        """
        mill_a = create_mill(name="Cascade Mill A")
        mill_b = create_mill(name="Coast Mill B")

        response = api.patch_mill(
            mill_a["id"], {"receiving_status": "CLOSED"}, make_scaler_headers(mill_b["id"])
        )
        validate_error(response, ApiErrorId.ERR_SCALER_MILL_MISMATCH.value, 403)

        row = read_mill(mill_a["id"])
        assert row["receiving_status"] == "OPEN"
        assert row["version"] == 1

    def test_the_accountant_who_compiled_a_statement_cannot_approve_it(self, api):
        """PRD §2.1: "Segregation of duties is enforced on one operation only: the
        accountant approving a settlement statement must present an `X-User-ID`
        different from the `compiled_by_user_id` recorded when that statement was
        compiled. Self-approval is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP
        403)."
        PRD §3.9: "**Approving** moves a `SUBMITTED` statement to `APPROVED` and
        records the approver's `X-User-ID` as `approved_by_user_id`, subject to the
        segregation-of-duties rule of §2.1."

        Design: Corner/rbac/the_accountant_who_compiled_a_statement_cannot_approve_it
        """
        scn = build_network()
        load, ticket = deliver_load(scn)
        statement = compile_statement(scn, compiler_user_id="acct-1")
        submit_statement(statement["id"], user_id="acct-1")

        response = api.approve_settlement_statement(
            statement["id"], make_accountant_headers("acct-1")
        )
        validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)

        validate_success(
            api.approve_settlement_statement(
                statement["id"], make_accountant_headers("acct-2")
            )
        )

        final = read_settlement_statement(statement["id"])
        assert final["compiled_by_user_id"] == "acct-1"
        assert final["approved_by_user_id"] == "acct-2"
        assert final["status"] == "APPROVED"


class TestOwnershipOutranksState:
    def test_a_foreign_scaler_is_refused_before_the_ticket_state_is_consulted(
        self, api
    ):
        """PRD §2.7: "**Resource ownership.** The three ownership rules of §2.1 —
        scaler-to-mill (`ERR_SCALER_MILL_MISMATCH`), carrier-to-carrier
        (`ERR_CONTRACTOR_NOT_OWNER`) and accountant segregation of duties
        (`ERR_SEGREGATION_OF_DUTIES`) — share this rung and are evaluated after
        existence but before any state check."
        PRD §3.8: "In either case the ticket must still be `DRAFT` — otherwise
        `ERR_INVALID_TICKET_STATE` — its load must still be `AT_MILL`, and the caller's
        `X-User-ID` must equal the ticket's `mill_id`."

        Design: Difficulty/priority_pair_validation_conflict/scaler_mill_ownership_error_outranks_already_certified_ticket_state
        """
        scn = build_network()
        mill_b = create_mill(name="Coast Mill B")
        load, ticket = deliver_load(scn)

        response = api.certify_delivery_ticket(
            ticket["id"], make_scaler_headers(mill_b["id"])
        )
        error = validate_error(
            response, ApiErrorId.ERR_SCALER_MILL_MISMATCH.value, 403
        )
        assert error["error_id"] != ApiErrorId.ERR_INVALID_TICKET_STATE.value

    def test_the_refused_call_leaves_the_certified_ticket_untouched(self, api):
        """PRD §2.7: "The first check that fails determines the response; later checks
        are never reached, and their failure conditions are therefore invisible on that
        request."
        PRD §3.8: "Hop one: the ticket's `ticket_status` becomes `CERTIFIED`,
        `certified_at` is stamped with the logical clock, and `certified_by_user_id`
        records the certifying scaler."

        Design: Difficulty/priority_pair_validation_conflict/scaler_mill_ownership_error_outranks_already_certified_ticket_state
        """
        scn = build_network()
        mill_b = create_mill(name="Coast Mill B")
        load, ticket = deliver_load(scn)

        validate_error(
            api.certify_delivery_ticket(ticket["id"], make_scaler_headers(mill_b["id"])),
            ApiErrorId.ERR_SCALER_MILL_MISMATCH.value,
            403,
        )

        ticket_row = read_delivery_ticket(ticket["id"])
        assert ticket_row["ticket_status"] == "CERTIFIED"
        assert ticket_row["certified_by_user_id"] == scn["mill_a_id"]
