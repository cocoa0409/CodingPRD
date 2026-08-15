"""Return/washout volume conservation, role-based access control, ownership
checks, authentication, terminal-state lockdowns, the response envelope, and
immediate consistency of mutation responses."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    create_draft_mix,
    create_plant,
    get_load,
    get_order,
    get_truck,
    make_customer_headers,
    place_order,
    schedule_load,
    set_clock,
    setup_completed_load,
    setup_confirmed_order,
    setup_pouring_load,
    validate_error,
    validate_success,
)

PM = TEST_USERS["plant_manager_headers"]
DISP = TEST_USERS["dispatcher_headers"]
BATCH_OP = TEST_USERS["batch_operator_headers"]
DRV1 = TEST_USERS["driver_headers"]
QC_A = TEST_USERS["qc_a_headers"]


class TestReturnWashoutConservation:
    def test_unconserved_volume_rejected_then_conserved_return_accepted(self, api):
        """PRD §3.7: "The returned quantity must be greater than zero, and
        volume must be conserved exactly: discharged plus returned must equal
        the batched `qty_yd3`, otherwise `ERR_VOLUME_NOT_CONSERVED`."

        Design: Difficulty/compensating_invariant/load_volume_conservation_return_washout
        """
        ctx, load = setup_pouring_load()
        bad = api.return_load(
            load["id"],
            {"discharged_qty_yd3": 5.0, "returned_qty_yd3": 3.5,
             "disposition": "RECYCLED"},
            DRV1,
        )
        validate_error(bad, ApiErrorId.ERR_VOLUME_NOT_CONSERVED.value)
        assert get_load(load["id"])["status"] == "POURING"

        returned = validate_success(
            api.return_load(
                load["id"],
                {"discharged_qty_yd3": 5.0, "returned_qty_yd3": 3.0,
                 "disposition": "RECYCLED"},
                DRV1,
            ),
            200,
        )
        assert returned["status"] == "RETURNED"
        assert returned["discharged_qty_yd3"] == pytest.approx(5.0)
        assert returned["returned_qty_yd3"] == pytest.approx(3.0)
        assert (
            returned["discharged_qty_yd3"] + returned["returned_qty_yd3"]
            == pytest.approx(8.0)
        ), "discharged + returned must balance the batched 8.0 yd3"

    def test_washout_records_water_and_releases_truck(self, api):
        """PRD §3.7: "The load moves to `RETURNED`, its `discharged_qty_yd3`
        is set from the input, a return record is created carrying the
        `returned_qty_yd3` and `disposition`, and the truck moves
        `ON_DELIVERY → IN_WASHOUT`. Washout is a `BatchOperator` action on the
        returned load: the load moves `RETURNED → WASHED_OUT`, the supplied
        `washout_water_gal` is recorded onto the return record (null until
        then), and the truck returns `IN_WASHOUT → AVAILABLE` with
        `last_available_at` stamped."

        Design: Difficulty/compensating_invariant/load_volume_conservation_return_washout
        """
        ctx, load = setup_pouring_load()
        validate_success(
            api.return_load(
                load["id"],
                {"discharged_qty_yd3": 5.0, "returned_qty_yd3": 3.0,
                 "disposition": "RECYCLED"},
                DRV1,
            ),
            200,
        )
        truck_mid = get_truck(ctx["trucks"]["T1"]["id"])
        assert truck_mid["status"] == "IN_WASHOUT"

        washed = validate_success(
            api.washout_load(load["id"], {"washout_water_gal": 120}, BATCH_OP), 200
        )
        assert washed["status"] == "WASHED_OUT"

        records = validate_success(api.get_return_record(load["id"], DISP), 200)
        assert len(records) == 1
        assert records[0]["returned_qty_yd3"] == pytest.approx(3.0)
        assert records[0]["washout_water_gal"] == pytest.approx(120)

        truck_after = get_truck(ctx["trucks"]["T1"]["id"])
        assert truck_after["status"] == "AVAILABLE"


class TestTerminalLockdown:
    def test_cancel_completed_load_rejected_terminal(self, api):
        """PRD §3.7: "`COMPLETED`, `WASHED_OUT`, and `CANCELLED` are the
        load's terminal states."
        PRD §2.8: "State-level checks follow: the optimistic-concurrency check
        (`ERR_STALE_VERSION`), the from-state validity check
        (`ERR_INVALID_STATE`), and the terminal-state check
        (`ERR_ALREADY_TERMINAL`)."

        Design: Corner/state_machines/cancel_completed_load_rejected_terminal
        """
        ctx, load = setup_completed_load(indices=[("2026-08", 115.0)])
        assert load["status"] == "COMPLETED"
        res = api.cancel_load(load["id"], DISP)
        validate_error(res, ApiErrorId.ERR_ALREADY_TERMINAL.value)
        after = get_load(load["id"])
        assert after["status"] == "COMPLETED"
        assert after["final_charge_cents"] == 159300

    def test_retired_mix_design_terminal(self, api):
        """PRD §3.1: "Activation by a `PlantManager` moves a design
        `DRAFT → ACTIVE`; retirement moves it `ACTIVE → RETIRED`, and
        `RETIRED` is terminal — a retired design can never return."

        Design: Corner/state_machines/retired_mix_design_terminal_lockdown
        """
        plant, _ = create_plant()
        mix = create_draft_mix(plant["id"], admixtures=[])
        validate_success(api.activate_mix_design(mix["id"], PM), 200)
        retired = validate_success(api.retire_mix_design(mix["id"], PM), 200)
        assert retired["status"] == "RETIRED"

        res = api.activate_mix_design(mix["id"], PM)
        validate_error(res, ApiErrorId.ERR_ALREADY_TERMINAL.value)
        after = validate_success(api.get_mix_design(mix["id"], PM), 200)
        assert after["status"] == "RETIRED"


class TestRbac:
    def test_customer_cannot_confirm_order(self, api):
        """PRD §3.3: "Confirmation is a `Dispatcher` action and is where
        pricing locks in."
        PRD §2.1: "A request whose role is recognized but not permitted for
        the endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/customer_cannot_confirm_order_forbidden
        """
        from test_helpers import setup_standard_catalog

        catalog = setup_standard_catalog()
        order = place_order(
            catalog["plant"]["id"], catalog["mix"]["id"], catalog["customer"]["id"]
        )
        res = api.confirm_order(
            order["id"], make_customer_headers(catalog["customer"]["id"])
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)
        assert get_order(order["id"])["delivery_status"] == "PLACED"

    def test_driver_cannot_batch(self, api):
        """PRD §3.5: "Batching is a `BatchOperator` action that turns a
        `SCHEDULED` load into a `BATCHED` one and cuts its batch ticket."
        PRD §2.1: "A request whose role is recognized but not permitted for
        the endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/driver_cannot_batch_forbidden
        """
        ctx = setup_confirmed_order()
        load = schedule_load(
            ctx["order"]["id"], ctx["order_version"],
            qty_yd3=8.0, truck_id=ctx["trucks"]["T1"]["id"],
        )
        res = api.batch_load(
            load["id"], {"batch_time": "2026-08-15T10:00:00Z"}, DRV1
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)
        assert get_load(load["id"])["status"] == "SCHEDULED"

    def test_qctech_cannot_adjust_invoice(self, api):
        """PRD §3.9: "A `PlantManager` resolves a dispute by adjusting the
        invoice with a non-empty `adjustment_lines` array (an empty array is
        rejected with `ERR_VALIDATION`, HTTP 400); the adjustment lines are
        appended to `line_items`, the new `total_cents` equals the old total
        plus the sum of the adjustment amounts, the invoice returns `DISPUTED
        → ISSUED`, and the order's billing follows `DISPUTED → INVOICED`."
        PRD §2.1: "A request whose role is recognized but not permitted for
        the endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §2.8: "Authentication (missing or unrecognized headers,
        `ERR_UNAUTHENTICATED`) is checked first, followed by role permission
        (`ERR_FORBIDDEN`) and customer ownership (`ERR_OWNERSHIP_MISMATCH`).
        Referenced-resource existence (`ERR_NOT_FOUND`) and basic request
        shape — missing required fields, wrong types, out-of-range enum
        values, uniqueness violations (`ERR_VALIDATION`) — come next."

        Design: Corner/rbac/qctech_cannot_adjust_invoice_forbidden
        """
        create_plant()
        res = api.adjust_invoice(
            NON_EXISTENT_UUID,
            {"adjustment_lines": [{"description": "x", "amount_cents": 1}]},
            QC_A,
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)

    def test_plant_manager_cannot_place_order(self, api):
        """PRD §4: "| POST | /v1/orders | Place an order; `customer_id` taken
        from `X-User-ID` | Customer |"
        PRD §2.1: "A request whose role is recognized but not permitted for
        the endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/plant_manager_cannot_place_order_forbidden
        """
        plant, _ = create_plant()
        mix = create_draft_mix(plant["id"], admixtures=[])
        res = api.create_order(
            {
                "plant_id": plant["id"],
                "mix_design_id": mix["id"],
                "qty_yd3": 8.0,
                "pour_date": "2026-08-15",
                "pour_window_start": "07:00",
                "pour_window_end": "10:00",
                "slump_in": 4.5,
            },
            PM,
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)

    def test_dispatcher_shared_cancel_allowed(self, api):
        """PRD §3.3: "Cancelling an order is available to the owning
        `Customer` or a `Dispatcher`. Cancelling from `PLACED` is
        unconditional and moves billing `UNPRICED → VOID`."

        Design: Corner/rbac/dispatcher_shared_cancel_allowed
        """
        from test_helpers import create_customer

        plant, _ = create_plant()
        mix = create_draft_mix(plant["id"], admixtures=[])
        customer = create_customer()
        order = place_order(plant["id"], mix["id"], customer["id"])

        cancelled = validate_success(api.cancel_order(order["id"], DISP), 200)
        assert cancelled["delivery_status"] == "CANCELLED"
        assert cancelled["billing_status"] == "VOID"

    def test_customer_cannot_read_other_customers_order(self, api):
        """PRD §2.1: "Separately, customer-scoped reads and writes are
        ownership-checked: when a `Customer` acts on an order or invoice, the
        `X-User-ID` must equal the `customer_id` recorded on that resource,
        otherwise the request is rejected with `ERR_OWNERSHIP_MISMATCH`
        (HTTP 403)."

        Design: Corner/validations/customer_cannot_read_other_customers_order
        """
        from test_helpers import create_customer

        plant, _ = create_plant()
        mix = create_draft_mix(plant["id"], admixtures=[])
        customer_a = create_customer(name="Cust A")
        customer_b = create_customer(name="Cust B")
        order = place_order(plant["id"], mix["id"], customer_a["id"])

        res = api.get_order(order["id"], make_customer_headers(customer_b["id"]))
        validate_error(res, ApiErrorId.ERR_OWNERSHIP_MISMATCH.value)


class TestAuthentication:
    def test_missing_auth_headers_unauthenticated(self, api):
        """PRD §2.1: "Every request carries two identity headers: `X-User-ID`
        and `X-User-Role`. A request missing either header, or presenting a
        role the server does not recognize, is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/missing_auth_header_unauthenticated
        """
        plant, _ = create_plant()
        res = api.get_plant(plant["id"], headers={"Content-Type": "application/json"})
        validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED.value)


class TestResponseEnvelope:
    def test_success_and_error_envelope_shapes(self, api):
        """PRD §2.2: "The `api_request_id` is a server-generated unique
        identifier for the request that starts with `req_`."
        PRD §2.2: "The `response_type` is either "object" for a single
        resource or "array" for a list of resources."
        PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."

        Design: Corner/endpoints/response_envelope_shape_success_and_error
        """
        plant, _ = create_plant()

        ok = api.get_plant(plant["id"], DISP)
        body = ok.json()
        assert ok.status_code == 200
        assert "api_request_id" in body["meta"]
        assert "api_request_timestamp" in body["meta"]
        assert body["response_type"] == "object"
        assert body["data"]["id"] == plant["id"]

        err = api.get_plant(NON_EXISTENT_UUID, DISP)
        err_body = err.json()
        assert err.status_code == 404
        assert err_body["response_type"] == "error"
        assert err_body["data"]["error_id"] == "ERR_NOT_FOUND"
        assert "message" in err_body["data"]


class TestImmediateConsistency:
    def test_complete_response_carries_recomputed_fields(self, api):
        """PRD §3.7: "Completion stamps `complete_time` and derives
        `on_site_minutes` as the elapsed seconds between `arrival_time` and
        `complete_time` divided by 60 and rounded down to the whole minute."
        PRD §2.4: "Two resource types are deliberately lighter: cement price
        index rows and batch tickets carry only `id` and `created_at` — both
        `updated_at` and `version` are absent on these two resources, and
        neither can ever be mutated after creation." (by contrast, loads carry
        a `version` that "increments on every mutation of the resource")

        Design: Corner/consistency_model/immediate_consistency_mutation_response_is_final
        """
        ctx = setup_confirmed_order(indices=[("2026-08", 115.0)])
        load = schedule_load(
            ctx["order"]["id"], ctx["order_version"],
            qty_yd3=8.0, truck_id=ctx["trucks"]["T1"]["id"],
        )
        created_version = load["version"]
        validate_success(
            api.batch_load(load["id"], {"batch_time": "2026-08-15T10:00:00Z"},
                           BATCH_OP),
            200,
        )
        validate_success(api.depart_load(load["id"], DRV1), 200)
        set_clock("2026-08-15T10:30:00Z")
        validate_success(api.arrive_load(load["id"], DRV1), 200)
        validate_success(api.start_pour_load(load["id"], DRV1), 200)
        set_clock("2026-08-15T12:00:00Z")
        completed = validate_success(
            api.complete_load(load["id"], {"discharged_qty_yd3": 8.0}, DRV1), 200
        )
        # The mutation response itself carries the recomputed values.
        assert completed["status"] == "COMPLETED"
        assert completed["on_site_minutes"] == 90
        assert completed["final_charge_cents"] == 159300
        # batch, depart, arrive, start-pour, complete each mutated the load.
        assert completed["version"] == created_version + 5
