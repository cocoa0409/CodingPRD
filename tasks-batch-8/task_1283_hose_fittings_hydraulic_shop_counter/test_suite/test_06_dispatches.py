"""Emergency mobile service dispatches (PRD §2.9, §3.6): van window
overlap, state legality, and dispatch-driven order installation."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    advance_service_dispatch,
    assert_instant_equal,
    build_assembly_order,
    create_assembly_order,
    create_customer,
    create_equipment_asset,
    create_reel,
    create_service_dispatch,
    confirm_assembly_order,
    record_pressure_test,
    tag_assembly_order,
    validate_error,
    validate_success,
)


class TestVanWindowOverlap:
    def test_adjacent_van_window_allowed(self, api):
        """PRD §2.9: "Because the intervals are half-open, touching endpoints are allowed: a window that begins exactly when another ends, or ends exactly when another begins, does not conflict."

        VAN-1 holds 2026-08-02 09:00 -> 11:00; a new dispatch starting exactly at
        11:00 books successfully.

        Design: Difficulty/resource_temporal_overlap/van_half_open_adjacency_allowed
        """
        cust = create_customer(name="VanCo")
        d1 = create_service_dispatch(cust["id"], "VAN-1",
                                     window_start="2026-08-02T09:00:00Z",
                                     window_end="2026-08-02T11:00:00Z")
        assert d1["status"] == "REQUESTED"

        res = api.create_service_dispatch({
            "customer_id": cust["id"], "van_id": "VAN-1",
            "window_start": "2026-08-02T11:00:00Z",
            "window_end": "2026-08-02T12:00:00Z",
        }, TEST_USERS["counter_sales_headers"])
        d2 = validate_success(res, 201)
        assert d2["status"] == "REQUESTED"

    def test_overlapping_van_window_rejected(self, api):
        """PRD §3.6: "the van must be free per the half-open overlap arithmetic of §2.9 — considering only existing dispatches in `REQUESTED`, `DISPATCHED`, or `ON_SITE` status on the same van — with genuine overlaps rejected as `ERR_VAN_WINDOW_CONFLICT` (HTTP 409)"

        VAN-1 holds 09:00 -> 11:00; a 10:30 -> 11:30 booking genuinely overlaps
        and is rejected.

        Design: Difficulty/resource_temporal_overlap/van_half_open_adjacency_allowed
        """
        cust = create_customer(name="VanCo")
        create_service_dispatch(cust["id"], "VAN-1",
                                window_start="2026-08-02T09:00:00Z",
                                window_end="2026-08-02T11:00:00Z")

        res = api.create_service_dispatch({
            "customer_id": cust["id"], "van_id": "VAN-1",
            "window_start": "2026-08-02T10:30:00Z",
            "window_end": "2026-08-02T11:30:00Z",
        }, TEST_USERS["counter_sales_headers"])
        validate_error(res, ApiErrorId.ERR_VAN_WINDOW_CONFLICT,
                       expected_status=409)


class TestDispatchStateLegality:
    def test_dispatch_complete_from_requested_rejected(self, api):
        """PRD §3.6: "Completing the call is allowed from `ON_SITE` alone."
        PRD §2.11: "Existence comes third, and then the state rungs: the assembly-order terminal lockdown (any action against a `COMPLETED` or `CANCELLED` order fails with `ERR_ORDER_TERMINAL`), general state-transition legality (`ERR_INVALID_STATE`), and the optimistic-concurrency check from §2.10 (`ERR_STALE_VERSION`)."

        Completing a freshly REQUESTED dispatch fails with ERR_INVALID_STATE.

        Design: Corner/state_machines/dispatch_complete_from_requested_rejected
        """
        cust = create_customer(name="DispCo")
        disp = create_service_dispatch(cust["id"], "VAN-2",
                                       window_start="2026-08-03T09:00:00Z",
                                       window_end="2026-08-03T10:00:00Z")

        res = api.complete_service_dispatch(disp["id"], {},
                                            TEST_USERS["field_technician_headers"])
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

        after = validate_success(
            api.get_service_dispatch(disp["id"],
                                     TEST_USERS["shop_manager_headers"]), 200)
        assert after["status"] == "REQUESTED"


class TestDispatchCompletionInstallsOrder:
    def test_dispatch_completion_installs_tagged_order(self, api):
        """PRD §3.6: "When the reference is valid, the referenced order is driven through its own `TAGGED` → `COMPLETED` transition with the full settlement cascade of §3.5: final pricing from actual labor, coupling stock decremented and reservations released, and — when the order names an equipment asset — the installation timestamps, due-date and posture recomputation, and customer score refresh."
        PRD §3.5: "When the order names an `equipment_asset_id`, that asset must still be `ACTIVE` — completing onto a decommissioned machine is rejected with `ERR_ASSET_NOT_ACTIVE` — and completion then stamps the asset's `installed_assembly_order_id` with this order, overwrites its `installed_at` with the current logical clock, recomputes its `next_due_date` and `compliance_posture`, and finally recomputes the customer's `compliance_score_strict`, `compliance_score_projected`, and `program_status`."
        PRD §2.5: "Before the clock has ever been set, it reads exactly 2026-08-01T00:00:00Z, and it never falls back to wall-clock time on its own."

        The field-service path completes the TAGGED order and stamps the asset:
        installed_at 2026-08-01, next_due 2026-08-01 + 365d = 2027-08-01.

        Design: Corner/cross_cutting_layers/dispatch_completion_installs_order
        """
        cust = create_customer(name="FieldInstallCo")
        asset = create_equipment_asset(cust["id"], asset_tag="EX-99",
                                       machine_type="excavator")
        reel = create_reel(hose_sku="PARK-387-8FI", hose_diameter_in=0.5,
                           working_pressure_psi=3000, price_per_meter_cents=800,
                           initial_length_mm=50000)
        order = create_assembly_order(
            cust["id"], reel["id"],
            equipment_asset_id=asset["id"],
            cut_length_mm=1000, required_working_pressure_psi=2000,
            crimp_diameter_spec_mm=25.0, estimated_labor_minutes=10)
        confirm_assembly_order(order["id"])
        build_assembly_order(order["id"], measured_crimp_diameter_mm=25.0,
                             actual_labor_minutes=10)
        record_pressure_test(order["id"], test_pressure_psi=4000, result="PASSED")
        tag_assembly_order(order["id"], "TAG-FIELD1")

        disp = create_service_dispatch(cust["id"], "VAN-9",
                                       equipment_asset_id=asset["id"],
                                       window_start="2026-08-02T09:00:00Z",
                                       window_end="2026-08-02T10:00:00Z")
        advance_service_dispatch(disp["id"])
        on_site = advance_service_dispatch(disp["id"])
        assert on_site["status"] == "ON_SITE"

        res = api.complete_service_dispatch(
            disp["id"], {"installed_assembly_order_id": order["id"]},
            TEST_USERS["field_technician_headers"])
        completed_dispatch = validate_success(res, 200)
        assert completed_dispatch["status"] == "COMPLETED"

        order_after = validate_success(
            api.get_assembly_order(order["id"],
                                   TEST_USERS["counter_sales_headers"]), 200)
        assert order_after["status"] == "COMPLETED"

        asset_after = validate_success(
            api.get_equipment_asset(asset["id"],
                                    TEST_USERS["shop_manager_headers"]), 200)
        assert asset_after["installed_assembly_order_id"] == order["id"]
        assert_instant_equal(asset_after["installed_at"], "2026-08-01T00:00:00Z")
        assert_instant_equal(asset_after["next_due_date"], "2027-08-01T00:00:00Z")


class TestDispatchWindowShape:
    def test_dispatch_window_equal_start_end_rejected(self, api):
        """PRD §3.6: "the window's end must be strictly after its start or the booking fails with `ERR_INVALID_WINDOW`"
        PRD §2.9: "For both kinds, the window's end must be strictly after its start; an empty or inverted window is rejected at booking time."

        window_end equal to window_start is not strictly after -> ERR_INVALID_WINDOW (400).

        Design: Corner/validations/invalid_dispatch_window_rejected
        """
        cust = create_customer(name="WinCo")
        res = api.create_service_dispatch({
            "customer_id": cust["id"], "van_id": "VAN-3",
            "window_start": "2026-08-03T09:00:00Z",
            "window_end": "2026-08-03T09:00:00Z",
        }, TEST_USERS["counter_sales_headers"])
        validate_error(res, ApiErrorId.ERR_INVALID_WINDOW, expected_status=400)


class TestDispatchNotFound:
    def test_dispatch_get_unknown_id_not_found(self, api):
        """PRD §2.11: "For a nested path, identifiers are validated left to right, and the first identifier that does not resolve produces the 404 specific to its resource kind: `ERR_CUSTOMER_NOT_FOUND`, `ERR_ASSET_NOT_FOUND`, `ERR_REEL_NOT_FOUND`, `ERR_COUPLING_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_INSPECTION_NOT_FOUND`, or `ERR_DISPATCH_NOT_FOUND`."

        GET /api/service-dispatches/{unknown uuid} -> ERR_DISPATCH_NOT_FOUND (404).

        Design: Corner/errors/dispatch_get_unknown_id_not_found
        """
        res = api.get_service_dispatch(NON_EXISTENT_UUID,
                                       TEST_USERS["shop_manager_headers"])
        validate_error(res, ApiErrorId.ERR_DISPATCH_NOT_FOUND,
                       expected_status=404)
