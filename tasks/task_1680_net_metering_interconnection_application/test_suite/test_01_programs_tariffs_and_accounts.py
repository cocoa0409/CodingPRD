"""Program configuration, tariff windows, account lifecycle, and list reads."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_customer_account,
    assert_application,
    assert_capacity_ledger_invariant,
    assert_instant_equal,
    assert_program,
    assert_service_account,
    assert_tariff_schedule,
    create_application_payload,
    create_draft_application,
    create_program,
    create_tariff,
    drive_to_capacity_reserved,
    get_success_data,
    setup_program_with_grid,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["program_administrator_headers"]


class TestProgramCreationDefaults:
    def test_program_created_open_with_zeroed_capacity_ledger(self, api):
        """PRD §3.1: "A new program starts in `program_status` `OPEN` with its
        capacity ledger initialized to zero reservations, zero interconnected
        watts, and an empty queue."
        PRD §2.7: "All four figures are computed by the server, start at zero
        (with `available_capacity_watts` starting at the full cap), and move
        only as side effects of the workflows in §3."

        Design: Corner/entities/e_program_creation_defaults
        """
        resp = api.create_program(
            {
                "name": "P1",
                "aggregate_cap_watts": 1_000_000,
                "metering_variant": "MONETARY_CREDIT",
                "true_up_mode": "AVOIDED_COST_PAYOUT",
                "true_up_month": 4,
                "screening_basis": "COMMITTED",
            },
            ADMIN,
        )
        program = validate_success(resp, 201)
        assert_program(program)
        assert program["program_status"] == "OPEN"
        assert program["interconnected_watts"] == 0
        assert program["reserved_watts"] == 0
        assert program["queued_count"] == 0
        assert program["available_capacity_watts"] == 1_000_000, (
            "available capacity starts at the full aggregate cap")
        assert_capacity_ledger_invariant(program)

        fetched = validate_success(api.get_program(program["id"], ADMIN))
        assert fetched["program_status"] == "OPEN"
        assert fetched["available_capacity_watts"] == 1_000_000


class TestAccountCreationDefaults:
    def test_account_created_active_standard_with_zero_balances(self, api):
        """PRD §3.2: "New accounts start with `account_status` `ACTIVE`,
        `metering_status` `STANDARD`, a null `meter_serial`, and zero balances
        (`credit_balance_cents` and `banked_wh`)."

        Design: Corner/entities/e_account_creation_defaults
        """
        sc = setup_program_with_grid("D", with_tariff=False)
        ctx = add_customer_account(sc, "D", service_class="RESIDENTIAL",
                                   prior_annual_usage_wh=12_000_000)
        account = ctx["account"]
        assert_service_account(account)
        assert account["account_status"] == "ACTIVE"
        assert account["metering_status"] == "STANDARD"
        assert account["meter_serial"] is None
        assert account["credit_balance_cents"] == 0
        assert account["banked_wh"] == 0

        fetched = validate_success(
            api.get_service_account(account["id"], ADMIN))
        assert fetched["account_status"] == "ACTIVE"
        assert fetched["metering_status"] == "STANDARD"


class TestTariffOpenEndedDefault:
    def test_omitted_effective_to_stores_open_ended_window(self, api):
        """PRD §3.1: "Each schedule belongs to a program via `program_id`,
        carries a human-readable `schedule_code`, and defines a half-open
        effectiveness window — inclusive of `effective_from`, exclusive of
        `effective_to`, with a null `effective_to` meaning open-ended."

        Design: Corner/entities/e_tariff_open_ended_default
        """
        program = create_program("P4")
        resp = api.create_tariff_schedule(
            {
                "program_id": program["id"],
                "schedule_code": "T-OPEN",
                "effective_from": "2026-01-01T00:00:00Z",
                "import_rate_millicents_per_kwh": 30_000,
                "export_rate_millicents_per_kwh": 12_000,
                "net_surplus_rate_millicents_per_kwh": 4_500,
            },
            ADMIN,
        )
        tariff = validate_success(resp, 201)
        assert_tariff_schedule(tariff)
        assert tariff["effective_to"] is None, (
            "An omitted effective_to stores an open-ended (null) window")


class TestTariffWindowOverlap:
    def test_overlapping_window_rejected_touching_boundary_allowed(self, api):
        """PRD §3.1: "Two schedules of the same program may touch at a
        boundary but may not overlap; an overlapping creation is rejected with
        `ERR_TARIFF_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/rto_tariff_window_half_open_overlap
        """
        program = create_program("TOV")
        t1 = create_tariff(program["id"], schedule_code="T1",
                           effective_from="2026-01-01T00:00:00Z",
                           effective_to="2027-01-01T00:00:00Z")
        # 2026-12-01 falls inside T1's [2026-01-01, 2027-01-01) window.
        resp = api.create_tariff_schedule(
            {
                "program_id": program["id"],
                "schedule_code": "T2",
                "effective_from": "2026-12-01T00:00:00Z",
                "import_rate_millicents_per_kwh": 31_000,
                "export_rate_millicents_per_kwh": 12_000,
                "net_surplus_rate_millicents_per_kwh": 4_500,
            },
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_TARIFF_WINDOW_OVERLAP)

        # A window starting exactly at T1's effective_to merely touches it.
        resp = api.create_tariff_schedule(
            {
                "program_id": program["id"],
                "schedule_code": "T3",
                "effective_from": "2027-01-01T00:00:00Z",
                "import_rate_millicents_per_kwh": 31_000,
                "export_rate_millicents_per_kwh": 12_000,
                "net_surplus_rate_millicents_per_kwh": 4_500,
            },
            ADMIN,
        )
        t3 = validate_success(resp, 201)
        assert_instant_equal(t3["effective_from"], "2027-01-01T00:00:00Z",
                             "T3 effective_from")

        data, meta = validate_paginated(
            api.list_tariff_schedules(ADMIN, params={"program_id":
                                                     program["id"]}))
        assert meta["total_count"] == 2
        assert {t["id"] for t in data} == {t1["id"], t3["id"]}

    def test_open_ended_window_blocks_later_and_foreign_program_is_free(
            self, api):
        """PRD §3.1: "Each schedule belongs to a program via `program_id` ...
        with a null `effective_to` meaning open-ended. Two schedules of the
        same program may touch at a boundary but may not overlap; an
        overlapping creation is rejected with `ERR_TARIFF_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/rto_tariff_window_half_open_overlap
        """
        program = create_program("TOV2")
        create_tariff(program["id"], schedule_code="T1",
                      effective_from="2026-01-01T00:00:00Z")
        # An open-ended window absorbs every later start.
        resp = api.create_tariff_schedule(
            {
                "program_id": program["id"],
                "schedule_code": "T2",
                "effective_from": "2027-01-01T00:00:00Z",
                "import_rate_millicents_per_kwh": 31_000,
                "export_rate_millicents_per_kwh": 12_000,
                "net_surplus_rate_millicents_per_kwh": 4_500,
            },
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_TARIFF_WINDOW_OVERLAP)

        # A window ending exactly at T1's effective_from touches, not overlaps.
        resp = api.create_tariff_schedule(
            {
                "program_id": program["id"],
                "schedule_code": "T0",
                "effective_from": "2025-01-01T00:00:00Z",
                "effective_to": "2026-01-01T00:00:00Z",
                "import_rate_millicents_per_kwh": 29_000,
                "export_rate_millicents_per_kwh": 11_000,
                "net_surplus_rate_millicents_per_kwh": 4_000,
            },
            ADMIN,
        )
        validate_success(resp, 201)

        # The overlap rule is scoped to schedules of the same program.
        other = create_program("TOV3")
        resp = api.create_tariff_schedule(
            {
                "program_id": other["id"],
                "schedule_code": "X1",
                "effective_from": "2026-06-01T00:00:00Z",
                "import_rate_millicents_per_kwh": 31_000,
                "export_rate_millicents_per_kwh": 12_000,
                "net_surplus_rate_millicents_per_kwh": 4_500,
            },
            ADMIN,
        )
        validate_success(resp, 201)


class TestLogicalClock:
    def test_clock_default_value(self, api):
        """PRD §2.4: "Before any client call is made, the logical clock reads
        exactly `2026-08-01T00:00:00Z`."

        Design: Corner/endpoints/ep_clock_default_value
        """
        create_program("CLK")
        data = validate_success(api.get_clock(ADMIN))
        assert_instant_equal(data["current_utc"], "2026-08-01T00:00:00Z",
                             "default logical clock")


class TestProgramComputedRead:
    def test_program_read_reflects_landed_reservation(self, api):
        """PRD §2.7: "The program's `available_capacity_watts` is its
        `aggregate_cap_watts` minus its `interconnected_watts` minus its
        `reserved_watts`, where `interconnected_watts` is the sum of
        `system_size_watts_ac` over the program's applications that have
        reached `PTO_GRANTED` or `OPERATING`, and `reserved_watts` is the sum
        of `capacity_reserved_watts` over applications currently holding a
        reservation."

        Design: Corner/endpoints/ep_get_program_computed_read
        """
        sc = setup_program_with_grid("CR")
        ctx = add_customer_account(sc, "1")
        drive_to_capacity_reserved(sc, ctx, size=10_000, production=15_000_000)

        program = validate_success(api.get_program(sc["program"]["id"], ADMIN))
        assert_program(program)
        assert program["reserved_watts"] == 10_000
        assert program["available_capacity_watts"] == 990_000
        assert program["interconnected_watts"] == 0
        assert program["queued_count"] == 0
        assert_capacity_ledger_invariant(program)


class TestApplicationListFilterAndEnvelope:
    def test_status_filter_and_pagination_envelope(self, api):
        """PRD §3.3: "Application lists may be filtered by `service_account_id`,
        `program_id`, or `application_status`."
        PRD §2.3: "The `limit` parameter specifies the maximum number of items
        to return. If not provided, it defaults to 10, with a minimum of 1 and
        maximum of 100. The `offset` parameter specifies the number of items to
        skip and defaults to 0."

        Design: Corner/endpoints/ep_list_applications_filter_and_pagination_envelope
        """
        sc = setup_program_with_grid("LS", with_tariff=False)
        ctx1 = add_customer_account(sc, "1")
        ctx2 = add_customer_account(sc, "2")
        ctx3 = add_customer_account(sc, "3")
        app1 = create_draft_application(sc, ctx1, size=10_000,
                                        production=15_000_000)
        app2 = create_draft_application(sc, ctx2, size=5_000,
                                        production=8_000_000,
                                        technology="WIND")
        app3 = create_draft_application(sc, ctx3, size=5_000,
                                        production=8_000_000,
                                        technology="FUEL_CELL")
        get_success_data(api.withdraw_application(app3["id"], ctx3["applicant"]))

        resp = api.list_applications(ADMIN,
                                     params={"application_status": "DRAFT"})
        assert resp.json()["response_type"] == "array"
        data, meta = validate_paginated(resp)
        assert meta["total_count"] == 2
        assert meta["has_more"] is False
        assert meta["limit"] == 10, "default limit is 10"
        assert meta["offset"] == 0
        assert {a["id"] for a in data} == {app1["id"], app2["id"]}

        body = api.list_applications(
            ADMIN, params={"application_status": "WITHDRAWN"}).json()
        assert body["meta"]["total_count"] == 1
        assert body["data"][0]["id"] == app3["id"]
        assert_application(body["data"][0])

        for envelope in (resp.json(), body):
            assert isinstance(
                envelope["meta"].get("api_request_id"), str)
            assert isinstance(
                envelope["meta"].get("api_request_timestamp"), str)


class TestProgramCloseGate:
    def test_close_blocked_until_last_application_terminates(self, api):
        """PRD §3.1: "Closing is terminal: a program may move from `OPEN`,
        `CAP_REACHED`, or `SUSPENDED` to `CLOSED` only when no application of
        the program remains in a non-terminal status; otherwise the close is
        rejected with `ERR_PROGRAM_HAS_INFLIGHT_WORK`."
        PRD §3.3: "it requires the program to be `OPEN` or `CAP_REACHED`
        (otherwise `ERR_PROGRAM_NOT_ACCEPTING`)"

        Design: Corner/state_machines/sm_program_close_blocked_then_succeeds
        """
        sc = setup_program_with_grid("PC")
        ctx = add_customer_account(sc, "1")
        app = create_draft_application(sc, ctx, size=10_000,
                                       production=15_000_000)

        resp = api.close_program(sc["program"]["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_PROGRAM_HAS_INFLIGHT_WORK)

        get_success_data(api.withdraw_application(app["id"], ctx["applicant"]))
        program = validate_success(
            api.close_program(sc["program"]["id"], ADMIN))
        assert program["program_status"] == "CLOSED"

        # Creation still lands in DRAFT, but the submission gate refuses.
        app2 = validate_success(api.create_application(
            create_application_payload(
                ctx["account"]["id"], sc["program"]["id"],
                system_size_watts_ac=5_000,
                estimated_annual_production_wh=5_000_000),
            ctx["applicant"]), 201)
        resp = api.submit_application(app2["id"], ctx["applicant"])
        validate_error(resp, ApiErrorId.ERR_PROGRAM_NOT_ACCEPTING)


class TestAccountCloseGate:
    def test_account_close_blocked_with_inflight_application(self, api):
        """PRD §3.2: "an administrator may ... close an account — from either
        `ACTIVE` or `SUSPENDED` — provided no non-terminal application
        references it, failing which the close is rejected with
        `ERR_ACCOUNT_HAS_INFLIGHT_APPLICATIONS`."

        Design: Corner/state_machines/sm_account_close_blocked_with_inflight_application
        """
        sc = setup_program_with_grid("AC", with_tariff=False)
        ctx = add_customer_account(sc, "1")
        create_draft_application(sc, ctx, size=10_000, production=15_000_000)

        resp = api.close_service_account(ctx["account"]["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_HAS_INFLIGHT_APPLICATIONS)

        account = validate_success(
            api.get_service_account(ctx["account"]["id"], ADMIN))
        assert account["account_status"] == "ACTIVE"
