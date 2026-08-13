"""Order cutoff boundary, auth/existence priority, and store-suspension gate
(PRD §3.2, §2.9)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_order,
    create_plant,
    create_product,
    create_store,
    set_clock,
    validate_error,
    validate_success,
)


class TestOrderCutoffExactEquality:
    def test_confirm_at_exact_cutoff_allowed(self, api):
        """PRD §3.2: "The order cutoff is that instant minus the store's
        `lead_time_hours`, and a cutoff check passes when the logical clock
        is at or before the cutoff — equality is allowed."

        Design: Difficulty/boundary_precision_check/order_cutoff_exact_equality
        """
        plant = create_plant(name="Plant Nu")
        product_a = create_product(plant["id"])
        store = create_store(plant["id"], lead_time_hours=48)
        # Delivery 2026-08-10T08:00:00Z - 48h = cutoff 2026-08-08T08:00:00Z.
        set_clock("2026-08-08T08:00:00Z")
        order = create_order(store["id"], product_a["id"], qty=10)
        confirmed = validate_success(
            api.confirm_store_order(order["id"], TEST_USERS["planner_headers"])
        )
        assert confirmed["status"] == "CONFIRMED", (
            f"clock exactly at cutoff must confirm, got {confirmed['status']}"
        )

    def test_confirm_one_second_past_cutoff_rejected(self, api):
        """PRD §3.2: "the clock must be at or before the cutoff (else
        `ERR_ORDER_CUTOFF_PASSED`)." PRD §2.4: "All clock comparisons in the
        system are made at second precision."

        Design: Difficulty/boundary_precision_check/order_cutoff_exact_equality
        """
        plant = create_plant(name="Plant Nu 2")
        product_a = create_product(plant["id"])
        store = create_store(plant["id"], lead_time_hours=48)
        order = create_order(store["id"], product_a["id"], qty=10)
        # One second past the cutoff.
        set_clock("2026-08-08T08:00:01Z")
        resp = api.confirm_store_order(order["id"], TEST_USERS["planner_headers"])
        validate_error(resp, "ERR_ORDER_CUTOFF_PASSED", expected_status=409)
        after = validate_success(
            api.get_store_order(order["id"], TEST_USERS["planner_headers"])
        )
        assert after["status"] == "PLACED"


class TestAuthAndExistencePriority:
    def test_missing_auth_header_rejected(self, api):
        """PRD §2.1: "A request that omits either header, or names a role the
        system does not declare, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."
        PRD §2.9 step 1: "This check applies to every request."

        Design: Corner/validations/missing_auth_header_rejected
        """
        # No X-User-ID / X-User-Role headers — auth check beats NOT_FOUND.
        resp = api.get_plant(NON_EXISTENT_UUID, headers={})
        validate_error(resp, "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", expected_status=400)

    def test_not_found_beats_invalid_state(self, api):
        """PRD §2.9: step 3 (Existence) precedes step 6 (State preconditions):
        "Existence — every identifier named in the path and body (plant,
        product, store, driver, line, order, plan, batch, cycle, route,
        stop, return, sale, index, schedule) exists; failure yields
        `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/validations/not_found_beats_invalid_state
        """
        # Abort on a nonexistent batch id: existence fires before the state check.
        resp = api.abort_batch(NON_EXISTENT_UUID, TEST_USERS["planner_headers"])
        validate_error(resp, "ERR_NOT_FOUND", expected_status=404)


class TestSuspendedStoreBlocksOrderConfirm:
    def test_suspended_store_blocks_order_confirm(self, api):
        """PRD §3.2: "Confirming an order (a `Planner` action) moves it from
        `PLACED` to `CONFIRMED`, stamps `confirmed_at` with the clock, and
        enforces two checks: the store must still be `ACTIVE` (else
        `ERR_STORE_SUSPENDED`), and the clock must be at or before the
        cutoff (else `ERR_ORDER_CUTOFF_PASSED`)."

        Design: Corner/validations/suspended_store_blocks_order_confirm
        """
        plant = create_plant(name="Plant P Susp")
        product_a = create_product(plant["id"])
        store = create_store(plant["id"])
        set_clock("2026-08-06T00:00:00Z")
        order = create_order(store["id"], product_a["id"], qty=10)

        # Suspend the store, then attempt the confirm.
        validate_success(
            api.suspend_store(
                store["id"], {"reason": "stale ratio audit"}, TEST_USERS["admin_headers"]
            )
        )
        resp = api.confirm_store_order(order["id"], TEST_USERS["planner_headers"])
        validate_error(resp, "ERR_STORE_SUSPENDED", expected_status=409)
        after = validate_success(
            api.get_store_order(order["id"], TEST_USERS["planner_headers"])
        )
        assert after["status"] == "PLACED"
