"""Planogram lifecycle, service tickets, telemetry immutability, listings."""
from test_helpers import (
    ADMIN,
    PLANNER,
    TELEMETRY,
    WAREHOUSE,
    ApiErrorId,
    activate_planogram,
    create_draft_planogram,
    create_location,
    create_operator,
    create_order,
    create_product,
    create_route,
    create_service_ticket,
    get_location,
    get_planogram,
    get_success_data,
    ingest_telemetry,
    make_operator_manager_headers,
    setup_selling_location,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestInitialStates:
    def test_initial_states_on_create(self, api):
        """PRD §3.3: "The planogram starts `DRAFT` with `activated_at` still
        null"
        PRD §3.5: "starts with `fulfillment_status` `DRAFT` and
        `settlement_status` `UNINVOICED`"
        PRD §3.5: "The monetary fields begin in their zero-state:
        `order_total_cents`, `promo_discount_cents`, `amount_due_cents`, and
        `credit_applied_cents` at 0, while `provisional_margin_per_vend_cents`,
        `realized_margin_per_vend_cents`, `cashless_fee_cents`,
        `settled_tender`, and `settlement_telemetry_event_id` stay null until
        the lifecycle produces them."
        PRD §3.8: "the ticket enters `OPEN` with `service_date` still null."

        Design: Corner/state_machines/initial_states_on_create
        """
        world = setup_selling_location(
            products_spec=[{"sku": "INI-1", "name": "Init item"}],
            activate=False,
        )
        pg = world["planogram"]
        assert pg["status"] == "DRAFT"
        assert pg.get("activated_at") is None

        order = create_order(
            world,
            [{"product_id": world["products"][0]["id"], "quantity_cases": 1}],
        )
        assert order["fulfillment_status"] == "DRAFT"
        assert order["settlement_status"] == "UNINVOICED"
        assert order["provisional_margin_per_vend_cents"] is None
        assert order["realized_margin_per_vend_cents"] is None
        assert order["total_cases"] == 1

        ticket = create_service_ticket(
            world["location"]["id"], world["operator"]["id"],
            issue_type="PART_REPLACEMENT",
            parts=[{"part_sku": "MTR-12", "part_name": "Spiral motor",
                    "quantity": 2, "unit_price_cents": 4500}],
        )
        assert ticket["status"] == "OPEN"
        assert ticket["service_date"] is None
        # PRD §3.8: parts_total_cents is the sum of quantity*unit_price_cents.
        assert ticket["parts_total_cents"] == 2 * 4500


class TestPlanogramLifecycle:
    def test_planogram_activate_twice_rejected(self, api):
        """PRD §3.3: "The planogram itself must be `DRAFT`
        (`ERR_PLANOGRAM_NOT_DRAFT`)"

        Design: Corner/state_machines/planogram_activate_twice_rejected
        """
        world = setup_selling_location(
            products_spec=[{"sku": "PG2-1", "name": "Pg2 item"}],
            planogram_name="PG-Twice",
        )
        pg_id = world["planogram"]["id"]
        loc_version = get_location(world["location"]["id"])["version"]

        err = api.activate_planogram(
            pg_id,
            {"expected_location_version": loc_version},
            make_operator_manager_headers(world["operator"]["id"]),
        )
        validate_error(err, ApiErrorId.ERR_PLANOGRAM_NOT_DRAFT)
        assert get_planogram(pg_id)["status"] == "ACTIVE"

    def test_planogram_activation_supersedes_incumbent(self, api):
        """PRD §3.3: "On success, the location's previous `ACTIVE` planogram,
        if any, is atomically superseded to `ARCHIVED`, so at most one
        planogram is ever `ACTIVE` per location; `activated_at` is stamped with
        the current logical clock; and the owning location's `version`
        increments by exactly one, making the supersede observable through the
        parent."
        PRD §2.5: "Before any administrative adjustment, the logical clock
        reads exactly 2026-08-01T00:00:00Z."

        Design: Corner/state_machines/planogram_activation_supersedes_incumbent
        """
        world = setup_selling_location(
            products_spec=[{"sku": "SUP-1", "name": "Sup item"}],
            planogram_name="PG-One",
        )
        pg1_id = world["planogram"]["id"]
        loc_id = world["location"]["id"]
        version_before = get_location(loc_id)["version"]

        pg2 = create_draft_planogram(
            loc_id,
            [{"slot_code": "B1", "product_id": world["products"][0]["id"],
              "par_level_units": 30, "vend_price_cents": 160}],
            world["operator"]["id"],
            "PG-Two",
        )
        activated = activate_planogram(pg2["id"], loc_id, world["operator"]["id"])

        assert activated["status"] == "ACTIVE"
        # Default logical clock stamps the activation (PRD §2.5); compare the
        # second-precision prefix to remain format-agnostic about millis.
        assert activated["activated_at"].startswith("2026-08-01T00:00:00")
        assert get_planogram(pg1_id)["status"] == "ARCHIVED"
        version_after = get_location(loc_id)["version"]
        assert version_after == version_before + 1, (
            "the second activation must advance the location version by exactly 1"
        )

    def test_planogram_activate_stale_location_version(self, api):
        """PRD §2.7: "Activating a planogram requires the request to carry
        `expected_location_version`, the client's last observed `version` of
        the owning location. Because activation supersedes the location's
        incumbent active planogram, the check guards against acting on a stale
        view of which planogram is incumbent: if the location's current
        `version` has advanced beyond the supplied value, the request is
        rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/planogram_activate_stale_location_version
        """
        op = create_operator("Op OCC1")
        route = create_route("R-OCC1", ("MON",), 50, 0)
        product = create_product(sku="OCC-1", name="Occ item")
        loc = create_location(op["id"], route["id"], "L-Occ1")
        stale_version = loc["version"]
        om = make_operator_manager_headers(op["id"])

        pg1 = create_draft_planogram(
            loc["id"],
            [{"slot_code": "A1", "product_id": product["id"],
              "par_level_units": 10, "vend_price_cents": 150}],
            op["id"], "PG-First",
        )
        # First activation consumes the observed location version.
        resp1 = api.activate_planogram(
            pg1["id"], {"expected_location_version": stale_version}, om,
        )
        validate_success(resp1, 200)

        pg2 = create_draft_planogram(
            loc["id"],
            [{"slot_code": "B1", "product_id": product["id"],
              "par_level_units": 20, "vend_price_cents": 160}],
            op["id"], "PG-Second",
        )
        # Replaying the pre-activation version is stale by exactly one.
        err = api.activate_planogram(
            pg2["id"], {"expected_location_version": stale_version}, om,
        )
        validate_error(err, ApiErrorId.ERR_STALE_VERSION)
        assert get_planogram(pg2["id"])["status"] == "DRAFT"
        assert get_planogram(pg1["id"])["status"] == "ACTIVE"


class TestCullPrecondition:
    def test_cull_evaluate_requires_active_planogram(self, api):
        """PRD §3.3: "Slow movers are culled by running an evaluation against
        the active planogram, invoked by an `OperatorManager` on a planogram
        that is `ACTIVE` (anything else rejects with
        `ERR_PLANOGRAM_NOT_ACTIVE`)."

        Design: Corner/state_machines/cull_evaluate_requires_active_planogram
        """
        world = setup_selling_location(
            products_spec=[{"sku": "CLD-1", "name": "Cld item"}],
            planogram_name="PG-Draft",
            activate=False,
        )
        pg_id = world["planogram"]["id"]
        err = api.cull_evaluate_planogram(pg_id, world["om_headers"])
        validate_error(err, ApiErrorId.ERR_PLANOGRAM_NOT_ACTIVE)

        reread = get_planogram(pg_id)
        assert reread["status"] == "DRAFT"
        assert reread["slots"][0]["cull_flag"] is False, (
            "a rejected cull evaluation must not write cull flags"
        )


class TestTelemetryEventShape:
    def test_telemetry_event_immutable_append_only(self, api):
        """PRD §2.4: "Because the DEX event log is append-only and immutable,
        a telemetry event carries only `id` and `created_at`; both
        `updated_at` and `version` are absent, and no update or delete
        operations exist for it."

        Design: Corner/entities/telemetry_event_immutable_append_only
        """
        op = create_operator("Op Imm")
        route = create_route("R-IMM", ("MON",), 50, 0)
        loc = create_location(op["id"], route["id"], "L-Imm", "GYM")
        resp = api.create_telemetry_event(
            {
                "location_id": loc["id"],
                "recorded_at": "2026-08-01T05:00:00Z",
                "cash_collected_cents": 100,
                "cashless_sales_cents": 50,
                "items": [],
            },
            TELEMETRY,
        )
        event = validate_success(resp, 201)
        assert isinstance(event["id"], str) and event["id"]
        assert isinstance(event["created_at"], str)
        assert "updated_at" not in event, "telemetry events carry no updated_at"
        assert "version" not in event, "telemetry events carry no version"
        assert event["cash_collected_cents"] == 100
        assert event["cashless_sales_cents"] == 50


class TestListings:
    def test_list_pagination_limit_offset(self, api):
        """PRD §2.3: "The `limit` parameter specifies the maximum number of
        items to return: it defaults to 10, with a minimum of 1 and a maximum
        of 100. The `offset` parameter specifies how many items to skip and
        defaults to 0."
        PRD §2.3: "The `meta` object of every list response carries the
        pagination fields `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/list_pagination_limit_offset
        """
        first = create_product(sku="PG-A", name="Page A")
        second = create_product(sku="PG-B", name="Page B", category="CANDY",
                                eligible_location_types=["GYM"])

        page1, meta1 = validate_paginated(
            api.list_products(ADMIN, params={"limit": 1, "offset": 0})
        )
        assert len(page1) == 1
        assert meta1["total_count"] == 2
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(
            api.list_products(ADMIN, params={"limit": 1, "offset": 1})
        )
        assert len(page2) == 1
        assert meta2["total_count"] == 2
        assert meta2["has_more"] is False

        assert page1[0]["id"] != page2[0]["id"]
        assert {page1[0]["id"], page2[0]["id"]} == {first["id"], second["id"]}

    def test_list_filter_by_operator_fk(self, api):
        """PRD §3.3: "Locations can be listed with `operator_id` and `route_id`
        filters"

        Design: Corner/endpoints/list_filter_by_operator_fk
        """
        op_a = create_operator("Op FA")
        op_b = create_operator("Op FB")
        route = create_route("R-FLT", ("MON",), 50, 0)
        loc_a = create_location(op_a["id"], route["id"], "L-FA")
        create_location(op_b["id"], route["id"], "L-FB", "GYM")

        data, meta = validate_paginated(
            api.list_locations(ADMIN, params={"operator_id": op_a["id"]})
        )
        assert meta["total_count"] == 1
        assert len(data) == 1
        assert data[0]["id"] == loc_a["id"]


class TestServiceTicketGates:
    def test_ticket_state_gates(self, api):
        """PRD §3.8: "Completion by `WarehouseOps` moves a ticket `SCHEDULED` →
        `COMPLETED`; any other from-state rejects with
        `ERR_TICKET_NOT_SCHEDULED`."
        PRD §3.8: "Scheduling by a `RoutePlanner` moves a ticket `OPEN` →
        `SCHEDULED`: the ticket must be `OPEN` (else `ERR_TICKET_NOT_OPEN`)"

        Design: Corner/state_machines/ticket_state_gates
        """
        op = create_operator("Op Tkt")
        route = create_route("R-TKT", ("MON",), 50, 0)
        loc = create_location(op["id"], route["id"], "L-Tkt", "GYM")
        om = make_operator_manager_headers(op["id"])

        t1 = create_service_ticket(loc["id"], op["id"], issue_type="REPAIR")
        t2 = create_service_ticket(loc["id"], op["id"], issue_type="PREVENTIVE")
        validate_success(
            api.schedule_service_ticket(t2["id"], {"service_date": "2026-08-05"},
                                        PLANNER),
            200,
        )

        # complete on an OPEN ticket
        err1 = api.complete_service_ticket(t1["id"], WAREHOUSE)
        validate_error(err1, ApiErrorId.ERR_TICKET_NOT_SCHEDULED)

        # schedule an already-SCHEDULED ticket
        err2 = api.schedule_service_ticket(t2["id"], {"service_date": "2026-08-06"},
                                           PLANNER)
        validate_error(err2, ApiErrorId.ERR_TICKET_NOT_OPEN)

        reread1 = get_success_data(api.get_service_ticket(t1["id"], ADMIN))
        reread2 = get_success_data(api.get_service_ticket(t2["id"], ADMIN))
        assert reread1["status"] == "OPEN"
        assert reread2["status"] == "SCHEDULED"
        assert reread2["service_date"] == "2026-08-05"

    def test_ticket_schedule_past_date_rejected(self, api):
        """PRD §3.8: "the supplied `service_date` must be strictly after the
        current logical date (else `ERR_DATE_NOT_FUTURE`)"
        PRD §2.5: "a date equal to that current date fails the rule."

        Design: Corner/errors/ticket_schedule_past_date_rejected
        """
        op = create_operator("Op TkD")
        route = create_route("R-TKD", ("MON",), 50, 0)
        loc = create_location(op["id"], route["id"], "L-TkD", "GYM")
        ticket = create_service_ticket(loc["id"], op["id"], issue_type="PREVENTIVE")

        # 2026-08-01 equals the default logical date, so it is not future.
        err = api.schedule_service_ticket(
            ticket["id"], {"service_date": "2026-08-01"}, PLANNER,
        )
        validate_error(err, ApiErrorId.ERR_DATE_NOT_FUTURE)

        reread = get_success_data(api.get_service_ticket(ticket["id"], ADMIN))
        assert reread["status"] == "OPEN"
        assert reread["service_date"] is None
