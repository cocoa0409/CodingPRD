"""Program creation, system-minted fields, reads, pagination (PRD §2.2-§2.5, §3.1)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_aircraft,
    assert_calendar_day,
    assert_customer,
    assert_iso8601_3dp,
    assert_program,
    create_aircraft,
    create_customer,
    create_engagement,
    create_program,
    get_program,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import create_program_payload


class TestProgramCreationDefaults:
    def test_program_created_in_quoted_with_derived_defaults(self, api, program_manager_headers):
        """PRD §3.1: "A new program starts in `QUOTED` with
        `committed_delivery_date` equal to the contractual date, all totals at
        zero, `rework_cycles` at zero, and no approved scheme."
        PRD §3.7: "the program's `total_contract_value_cents` — defined as
        `base_price_cents` plus the signed `delta_price_cents` of every
        `APPROVED` change order".

        Design: Corner/entities/program_creation_success_with_derived_defaults
        """
        ctx = create_engagement()
        resp = api.get_program(ctx["program"]["id"], program_manager_headers)
        program = validate_success(resp)
        assert_program(program)
        assert program["status"] == "QUOTED"
        assert_calendar_day(
            program["committed_delivery_date"], "2026-09-01", "committed_delivery_date"
        )
        assert program["total_contract_value_cents"] == 12345673
        assert program["discovery_cost_total_cents"] == 0
        assert program["billed_total_cents"] == 0
        assert program["penalty_final_cents"] == 0
        assert program["projected_penalty_cents"] == 0
        assert program["rework_cycles"] == 0
        assert program["approved_scheme_id"] is None

    def test_program_create_missing_base_price_rejected(
        self, api, program_manager_headers
    ):
        """PRD §2.10: "the request body parses and every required input field
        is present and type/enum-valid (`ERR_INVALID_REQUEST`, 400)."
        PRD §3.1 lists `base_price_cents` among the commercial terms named at
        program creation.

        Design: Corner/entities/program_create_missing_required_field
        """
        ctx = create_engagement()
        payload = create_program_payload(
            aircraft_id=ctx["aircraft"]["id"], customer_id=ctx["customer"]["id"]
        )
        del payload["base_price_cents"]
        # The aircraft from create_engagement is already bound to a program;
        # register a fresh one so only the missing field can fail.
        aircraft = create_aircraft(ctx["customer"]["id"], tail_number="N900ZZ")
        payload["aircraft_id"] = aircraft["id"]
        resp = api.create_program(payload, program_manager_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestSystemMintedFields:
    def test_program_system_fields_are_server_minted(self, api):
        """PRD §2.5: "**`id` (string):** a unique, server-minted identifier
        formatted as a UUID, with no type prefix." and "**`created_at`
        (string):** an ISO 8601 timestamp in UTC with three fractional digits
        (e.g., `2025-05-24T10:30:00.123Z`), set when the resource is first
        created."

        Design: Corner/entities/program_system_fields_server_minted
        """
        ctx = create_engagement()
        program = ctx["program"]
        assert is_valid_uuid(program["id"]), "id must be a server-minted UUID"
        assert_iso8601_3dp(program["created_at"], "created_at")
        assert isinstance(program["version"], int) and program["version"] >= 1

    def test_customer_credit_status_defaults_to_good_standing(self, api):
        """PRD §3.1: "A `CenterAdmin` registers each operator as a **Customer**
        with a `name` and `contact_email`; every customer begins life with
        `credit_status` of `GOOD_STANDING`."

        Design: Corner/entities/customer_credit_status_default_applied
        """
        customer = create_customer()
        assert_customer(customer)
        assert customer["credit_status"] == "GOOD_STANDING"


class TestProgramReads:
    def test_program_get_not_found(self, api, program_manager_headers):
        """PRD §2.8: "When an endpoint path contains resource identifiers, the
        system validates the existence of each identifier in sequential,
        left-to-right order, rejecting with `ERR_NOT_FOUND` (HTTP 404) at the
        first identifier that does not correspond to an existing resource."

        Design: Corner/entities/program_get_not_found_returns_404
        """
        resp = api.get_program(NON_EXISTENT_UUID, program_manager_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_aircraft_retrieval_returns_persisted_fields(self, api, finance_clerk_headers):
        """PRD §3.1: "Aircraft are registered against a customer with a
        `tail_number`, a `model`, and a `max_delta_lbs` value ... An aircraft
        begins `IN_SERVICE`". PRD §4 mounts GET /completion/aircraft/{id} for
        role "Any".

        Design: Corner/endpoints/aircraft_retrieval_returns_persisted_fields
        """
        customer = create_customer()
        aircraft = create_aircraft(customer["id"])
        resp = api.get_aircraft(aircraft["id"], finance_clerk_headers)
        data = validate_success(resp)
        assert_aircraft(data)
        assert data["tail_number"] == "N1869A"
        assert data["status"] == "IN_SERVICE"
        assert data["customer_id"] == customer["id"]


class TestAdvanceInputValidation:
    def test_advance_with_invalid_phase_enum_rejected(self, api, program_manager_headers):
        """PRD §2.10: "the request body parses and every required input field
        is present and type/enum-valid (`ERR_INVALID_REQUEST`, 400)."
        PRD §3.5: the phase machine is "walked by the `ProgramManager` through
        explicit advances, each naming a `to_phase`".

        Design: Corner/entities/advance_with_invalid_enum_rejected
        """
        ctx = create_engagement()
        resp = api.advance_program(
            ctx["program"]["id"], {"to_phase": "FLYING"}, program_manager_headers
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        assert get_program(ctx["program"]["id"])["status"] == "QUOTED"


class TestAircraftBusy:
    def test_second_program_for_aircraft_in_refurb_rejected(
        self, api, program_manager_headers
    ):
        """PRD §3.1: "An aircraft already `IN_REFURB` cannot start another
        program; the attempt is rejected with `ERR_AIRCRAFT_BUSY`."

        Design: Corner/errors/aircraft_busy_blocks_second_program
        """
        from test_helpers import setup_inducted_program

        ctx = setup_inducted_program()
        resp = api.create_program(
            create_program_payload(
                aircraft_id=ctx["aircraft"]["id"],
                customer_id=ctx["customer"]["id"],
                base_price_cents=5000000,
                daily_penalty_rate_cents=100000,
                contractual_delivery_date="2026-10-01",
            ),
            program_manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_AIRCRAFT_BUSY)


class TestSchemeReferentialIntegrity:
    def test_scheme_create_with_dangling_program_fk_rejected(self, api, design_lead_headers):
        """PRD §2.8: "Request bodies carry foreign keys, and these are checked
        for existence and cross-consistency with `ERR_REFERENTIAL_INTEGRITY`
        (HTTP 422) on failure. ... Dangling or cross-wired references are never
        accepted."

        Design: Corner/entities/scheme_create_dangling_program_fk_rejected
        """
        resp = api.create_paint_scheme(
            {
                "program_id": "11111111-2222-3333-4444-555555555555",
                "drawing_ref": "DWG-X",
                "painted_area_sqft": 2400,
                "coat_count": 2,
            },
            design_lead_headers,
        )
        validate_error(resp, ApiErrorId.ERR_REFERENTIAL_INTEGRITY)


class TestCustomerPagination:
    def test_customers_list_pagination_envelope(self, api, program_manager_headers):
        """PRD §2.3: "The `limit` parameter specifies the maximum number of
        items to return. If not provided, it defaults to 10, with a minimum of
        1 and a maximum of 100. The `offset` parameter specifies the number of
        items to skip and defaults to 0." and "Paginated list-based responses
        include the following fields in the `meta` object of the response
        envelope: `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/customers_list_pagination_and_filter
        """
        create_customer(name="Apex Aviation LLC", contact_email="ops@apex.example")
        create_customer(name="Borealis Air", contact_email="ops@borealis.example")
        create_customer(name="Cirrus Holdings", contact_email="ops@cirrus.example")

        page1, meta1 = validate_paginated(
            api.list_customers(program_manager_headers, params={"limit": 2, "offset": 0})
        )
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(
            api.list_customers(program_manager_headers, params={"limit": 2, "offset": 2})
        )
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False
