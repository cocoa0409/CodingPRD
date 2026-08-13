"""Client onboarding, retailer program lifecycle, and program-level access rules."""
import pytest

from test_helpers import (
    CLAIMS_ADJUSTER,
    COMPLIANCE_OFFICER,
    DESIGNER,
    NON_EXISTENT_UUID,
    PLATFORM_ADMIN,
    PRODUCTION_PLANNER,
    PROGRAM_MANAGER,
    ApiErrorId,
    add_compliance_rule,
    api_client,
    assert_client,
    assert_design,
    assert_program,
    create_client,
    create_client_payload,
    create_design_entity,
    create_program,
    create_program_payload,
    get_design,
    get_program,
    is_valid_uuid,
    setup_program_in_design,
    setup_produced_run,
    start_fulfillment,
    submit_design,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestClientOnboarding:

    def test_create_client_returns_201_and_system_fields(self):
        """PRD §4: "Operations that create a new resource — a client, program,
        compliance rule, design, production run, store, kit, shipment, damage
        claim, or field service request — return `201 Created`."
        PRD §3.1: "A client carries a `status` field whose lifecycle has two
        values, `ACTIVE` and `SUSPENDED`, and every client starts `ACTIVE`."
        PRD §2.4: "`id` (string): a unique, server-minted identifier formatted
        as a UUID, with no type prefix."

        Design: Corner/entities/create_client_returns_201_and_system_fields
        """
        resp = api_client.create_client(
            create_client_payload(name="Acme Corp",
                                  contact_email="ops@acme.example"),
            PLATFORM_ADMIN)
        data = validate_success(resp, expected_status=201)
        assert_client(data)
        assert data["status"] == "ACTIVE", \
            f"new client must start ACTIVE, got {data['status']}"
        assert is_valid_uuid(data["id"])
        assert isinstance(data["version"], int)

    def test_get_client_not_found_returns_404(self):
        """PRD §2.9: "the existence of each path-referenced resource — program,
        then design, run, kit, shipment, claim, or field service request, in the
        order they appear — is confirmed in sequence, and the request is rejected
        with `ERR_NOT_FOUND` at the first identifier that does not correspond to
        an existing resource, before any later identifier or any business rule is
        examined."

        Design: Corner/entities/get_client_not_found_returns_404
        """
        resp = api_client.get_client(NON_EXISTENT_UUID, PLATFORM_ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestProgramCreation:

    def test_create_program_missing_store_count_returns_400(self):
        """PRD §3.1: "The `store_count` must be at least 1 and
        `program_revenue_cents` at least 0; violations are rejected with
        `ERR_INVALID_REQUEST`."
        PRD §2.9: "9. Field-level and fiscal sanity — required fields present,
        enums valid, quantities non-negative or positive as specified; otherwise
        `ERR_INVALID_REQUEST`."

        Design: Corner/entities/create_program_missing_required_field_returns_400
        """
        client = create_client()
        payload = create_program_payload(client["id"])
        del payload["store_count"]
        resp = api_client.create_program(payload, PROGRAM_MANAGER)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_production_planner_cannot_create_program(self):
        """PRD §2.1: "A request whose role is recognized but not permitted for
        the target endpoint is rejected with `ERR_UNAUTHORIZED`."
        PRD §2.1: "A `ProgramManager` owns the retailer program lifecycle and
        the store roster."

        Design: Corner/rbac/production_planner_cannot_create_program
        """
        client = create_client()
        resp = api_client.create_program(
            create_program_payload(client["id"]), PRODUCTION_PLANNER)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

    def test_missing_auth_headers_returns_unauthenticated(self):
        """PRD §2.1: "A request missing either header, or presenting a role the
        system does not recognize, is rejected with `ERR_UNAUTHENTICATED`."
        PRD §2.9: "More generally, when several checks apply to a single request
        they are evaluated in a fixed priority order, and the first failing check
        determines the error returned:" (authentication is check 1, field-level
        fiscal sanity is check 9).

        Design: Corner/validations/priority_auth_beats_business
        """
        # Payload is also invalid (empty name, no contact_email): authentication
        # is evaluated first, so ERR_UNAUTHENTICATED must surface.
        resp = api_client.create_client({"name": ""}, headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestClientProgramListing:

    def test_list_programs_for_client_reverse_reachable(self):
        """PRD §3.1: "Anyone may read a program back, and a client's full
        program roster can be listed through the client's program listing."
        PRD §2.3: "List responses carry the fields `limit`, `offset`,
        `total_count`, and `has_more` in the `meta` object of the envelope."

        Design: Corner/endpoints/list_programs_for_client_reverse_reachable
        """
        client = create_client()
        p1 = create_program(client["id"], store_count=10,
                            program_revenue_cents=100000, program_name="P1")
        p2 = create_program(client["id"], store_count=20,
                            program_revenue_cents=200000, program_name="P2")
        data, meta = validate_paginated(
            api_client.list_client_programs(client["id"], PROGRAM_MANAGER))
        assert len(data) == 2, f"expected 2 programs, got {len(data)}"
        assert meta["total_count"] == 2
        returned_ids = {p["id"] for p in data}
        assert returned_ids == {p1["id"], p2["id"]}
        for program in data:
            assert program["client_id"] == client["id"]


class TestProgramCancellation:

    def test_program_cancel_from_fulfillment_rejected(self):
        """PRD §3.1: "Once a program has entered `PRODUCTION` it can no longer
        be cancelled."
        PRD §3.1: "Cancelling, by contrast, is available only while the program
        is still young: a program in `DRAFT` or `DESIGN` may move to `CANCELLED`".

        Design: Corner/state_machines/program_cancel_from_fulfillment_rejected
        """
        ctx = setup_produced_run(store_count=3, num_stores=1,
                                 program_revenue_cents=1000000)
        program = start_fulfillment(ctx["program"]["id"])
        assert program["status"] == "FULFILLMENT"

        resp = api_client.cancel_program(program["id"], PROGRAM_MANAGER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        program_after = get_program(program["id"])
        assert program_after["status"] == "FULFILLMENT", \
            f"program must remain FULFILLMENT, got {program_after['status']}"

    def test_cancel_cascades_non_terminal_designs_to_rejected(self):
        """PRD §3.1: "Cancelling, by contrast, is available only while the
        program is still young: a program in `DRAFT` or `DESIGN` may move to
        `CANCELLED`, and the cancellation cascades every non-terminal design of
        the program to `REJECTED`."

        Design: Difficulty/compensating_invariant/program_cancel_rejects_designs_conserves_design_count
        """
        _client, program = setup_program_in_design()
        d1 = create_design_entity(program["id"], design_code="D1")
        d2 = create_design_entity(program["id"], design_code="D2",
                                  width_in=42, height_in=62, depth_in=26,
                                  weight_lb=32, material="ACRYLIC")

        cancelled = validate_success(
            api_client.cancel_program(program["id"], PROGRAM_MANAGER), 200)
        assert cancelled["status"] == "CANCELLED"

        data, meta = validate_paginated(
            api_client.list_program_designs(program["id"], PROGRAM_MANAGER))
        assert len(data) == 2, \
            f"design count must be conserved at 2, got {len(data)}"
        for design in data:
            assert design["status"] == "REJECTED", \
                f"every non-terminal design must be REJECTED, got {design['status']}"
        returned_ids = {d["id"] for d in data}
        assert returned_ids == {d1["id"], d2["id"]}

    def test_cancel_rejects_designs_in_mixed_non_terminal_states(self):
        """PRD §2.8: "Cancelling a program cascades every non-terminal design of
        that program to `REJECTED`."

        Design: Difficulty/compensating_invariant/program_cancel_rejects_designs_conserves_design_count
        """
        _client, program = setup_program_in_design()
        d1 = create_design_entity(program["id"], design_code="D1")
        d2 = create_design_entity(program["id"], design_code="D2")
        d2 = submit_design(d2["id"])
        assert d1["status"] == "DRAFT" and d2["status"] == "SUBMITTED"

        validate_success(api_client.cancel_program(program["id"], PROGRAM_MANAGER),
                         200)

        for design_id in (d1["id"], d2["id"]):
            design = get_design(design_id)
            assert design["status"] == "REJECTED", \
                f"design {design_id} must be REJECTED, got {design['status']}"
        data, _meta = validate_paginated(
            api_client.list_program_designs(program["id"], PROGRAM_MANAGER))
        assert len(data) == 2, "designs transition state but are never deleted"
