"""Final invoice composition, shipping readiness gates, order completion, and
the customer credit conservation invariant."""
from test_helpers import (
    ApiErrorId,
    add_shipment,
    assert_credit_invariants,
    get_customer,
    get_order,
    make_assignment,
    make_loaner,
    record_run_in,
    set_clock,
    setup_completed_order,
    setup_order_in_run_in,
    setup_ready_to_ship_order,
    setup_shipped_order,
    TEST_USERS,
    validate_error,
    validate_success,
)

IC = TEST_USERS["intake_coordinator_headers"]
SM = TEST_USERS["service_manager_headers"]

# Scope used by the invoice tests: REGRIND 4.0h/12000 (46000) + CUT_NEW
# 6.5h/450000 (542300) = 588300, priced above a 500000 quoted estimate.
INVOICE_COMPONENTS = [
    ("PINION_1", "REGRINDABLE", 3, "REGRIND", 4.0, 12_000),
    ("GEAR_2", "CUT_ONLY", 4, "CUT_NEW", 6.5, 450_000),
]


class TestFinalInvoiceVsQuotedEstimate:
    def test_final_invoice_diverges_from_quoted_estimate(
            self, api, quality_inspector_headers):
        """PRD §3.2: "The coordinator also records a `quoted_estimate_cents` —
        a provisional figure quoted from the flat inspection book rate before
        anything is known about teardown actuals, and deliberately divergent
        from the eventual invoice".
        PRD §3.4: "the order advances `RUN_IN → READY_TO_SHIP`, and the
        `final_invoice_cents` is computed: the sum of `line_total_cents` over
        the order's `APPROVED` decisions, plus the `freight_charge_cents` of
        every shipment on the order whose own status is not `CANCELLED`."

        Design: Difficulty/dual_variant_calc/provisional_estimate_vs_final_invoice_on_reman_order
        """
        ctx = setup_order_in_run_in(
            serial_number="GBX-1001", quoted_estimate_cents=500_000,
            components=INVOICE_COMPONENTS)
        order_id = ctx["order"]["id"]
        shipment = add_shipment(order_id, direction="OUTBOUND", weight_kg=1_500,
                                rigging_bay_date="2026-08-10",
                                rigging_bay_hours=4)
        api.dispatch_shipment(shipment["id"], IC)
        api.deliver_shipment(shipment["id"], IC)

        record_run_in(order_id, duration_minutes=120, max_temp_c=88.0,
                      vibration_mm_s=3.1, oil_particle_count=2_400)
        order = get_order(order_id)
        assert order["quoted_estimate_cents"] == 500_000
        assert order["approved_scope_cents"] == 588_300
        # 588300 + (120000 + 4*9500) = 588300 + 158000 = 746300.
        assert order["final_invoice_cents"] == 746_300
        assert order["final_invoice_cents"] != order["quoted_estimate_cents"]
        assert order["status"] == "READY_TO_SHIP"

    def test_final_invoice_excludes_cancelled_shipment_freight(
            self, api, intake_coordinator_headers):
        """PRD §3.4: "the `final_invoice_cents` is computed: the sum of
        `line_total_cents` over the order's `APPROVED` decisions, plus the
        `freight_charge_cents` of every shipment on the order whose own
        status is not `CANCELLED`."

        Design: Difficulty/dual_variant_calc/provisional_estimate_vs_final_invoice_on_reman_order
        """
        ctx = setup_order_in_run_in(
            serial_number="GBX-1002", quoted_estimate_cents=500_000,
            components=INVOICE_COMPONENTS)
        order_id = ctx["order"]["id"]
        add_shipment(order_id, direction="OUTBOUND", weight_kg=1_500,
                     rigging_bay_date="2026-08-10", rigging_bay_hours=4)
        cancelled = add_shipment(order_id, direction="INBOUND", weight_kg=400,
                                 rigging_bay_date="2026-08-11",
                                 rigging_bay_hours=2)
        api.cancel_shipment(cancelled["id"], intake_coordinator_headers)

        record_run_in(order_id, duration_minutes=120, max_temp_c=88.0,
                      vibration_mm_s=3.1, oil_particle_count=2_400)
        order = get_order(order_id)
        # The cancelled 64000-cent shipment contributes nothing:
        # 588300 + 158000 = 746300, not 810300.
        assert order["final_invoice_cents"] == 746_300
        assert order["status"] == "READY_TO_SHIP"


class TestCreditConservation:
    def test_customer_approve_then_complete_zeroes_outstanding(self, api):
        """PRD §3.5: "the customer's `outstanding_approved_cents` is reduced
        by the order's `approved_scope_cents` — the only debit point in the
        whole credit lifecycle — with `credit_hold` recomputed".
        PRD §3.3: "Approval moves the order `SCOPE_APPROVAL → APPROVED`,
        flips all pending decisions to `APPROVED`, and adds the scope to the
        customer's outstanding exposure with `credit_hold` recomputed."

        Design: Difficulty/compensating_invariant/scope_approve_then_complete_conserves_customer_outstanding
        """
        # Default pipeline: REGRIND 4.0h/12000 → scope 46000, customer
        # approval (estimate 10000 < scope).
        ctx = setup_completed_order(serial_number="GBX-LG1",
                                    rigging_bay_date="2026-08-06")
        customer = ctx["customer"]
        assert ctx["order"]["approved_scope_cents"] == 46_000
        # After completion the exposure is debited back to zero.
        assert customer["outstanding_approved_cents"] == 0
        assert customer["credit_hold"] is False
        assert_credit_invariants(customer)
        assert ctx["order"]["status"] == "COMPLETED"
        assert ctx["unit"]["physical_status"] == "IN_SERVICE"

    def test_auto_approve_then_complete_zeroes_outstanding(self, api):
        """PRD §2.10: "Exposure enters the sum at scope approval (whether by
        the customer or by automatic approval) and leaves it at exactly one
        point: order completion."

        Design: Difficulty/compensating_invariant/scope_approve_then_complete_conserves_customer_outstanding
        """
        ctx = setup_completed_order(serial_number="GBX-LG2", auto=True,
                                    rigging_bay_date="2026-08-07")
        # Auto-approved scope: REGRIND 2.0h * 8500 + 5000 = 22000.
        assert ctx["order"]["approved_scope_cents"] == 22_000
        assert ctx["customer"]["outstanding_approved_cents"] == 0
        assert ctx["customer"]["credit_hold"] is False
        assert ctx["order"]["status"] == "COMPLETED"
        assert ctx["unit"]["physical_status"] == "IN_SERVICE"

    def test_outstanding_peaks_between_approval_and_completion(self, api):
        """PRD §2.10: "Each customer carries a running exposure figure,
        `outstanding_approved_cents`: the sum of `approved_scope_cents` over
        that customer's orders whose `status` is one of `APPROVED`,
        `IN_BUILD`, `ASSEMBLY`, `RUN_IN`, `READY_TO_SHIP`, or `SHIPPED`.
        Orders in `INTAKE`, `TEARDOWN`, `SCOPE_APPROVAL`, `COMPLETED`, or
        `CANCELLED` contribute nothing."

        Design: Difficulty/compensating_invariant/scope_approve_then_complete_conserves_customer_outstanding
        """
        ctx = setup_shipped_order(serial_number="GBX-LG3",
                                  rigging_bay_date="2026-08-08")
        # SHIPPED is inside the exposure set: the approved 46000 still shows.
        mid = get_customer(ctx["customer"]["id"])
        assert mid["outstanding_approved_cents"] == 46_000
        assert mid["credit_hold"] is False
        api.deliver_shipment(ctx["shipment"]["id"], IC)
        order = validate_success(
            api.complete_order(ctx["order"]["id"], SM))
        assert order["status"] == "COMPLETED"
        after = get_customer(ctx["customer"]["id"])
        assert after["outstanding_approved_cents"] == 0


class TestShippingGates:
    def test_ship_blocked_by_outstanding_loaner(
            self, api, service_manager_headers, intake_coordinator_headers):
        """PRD §3.5: "Shipping the order (`READY_TO_SHIP → SHIPPED`) is a
        `ServiceManager` action with two readiness guards: an `OUTBOUND`
        shipment must exist for the order and still be `BOOKED`
        (`ERR_FREIGHT_NOT_READY`), and no loaner assignment for the order may
        still be `CHECKED_OUT` (`ERR_LOANER_OUTSTANDING`, §3.6)."

        Design: Corner/state_machines/ship_blocked_while_loaner_checked_out
        """
        set_clock("2026-08-03T00:00:00Z")
        ctx = setup_ready_to_ship_order(serial_number="GBX-LS")
        order_id = ctx["order"]["id"]
        add_shipment(order_id, direction="OUTBOUND", weight_kg=400,
                     rigging_bay_date="2026-08-04", rigging_bay_hours=2)
        loaner = make_loaner(serial_number="LN-SHIP")
        assignment = make_assignment(loaner["id"], order_id,
                                     start_date="2026-08-01",
                                     end_date="2026-08-15")
        api.checkout_loaner(assignment["id"], intake_coordinator_headers)

        resp = api.ship_order(order_id, service_manager_headers)
        validate_error(resp, ApiErrorId.ERR_LOANER_OUTSTANDING.value)
        assert get_order(order_id)["status"] == "READY_TO_SHIP"

    def test_engineer_cannot_ship(self, api, reman_engineer_headers):
        """PRD §4: the ship row of the endpoint table authorizes only
        ServiceManager.
        PRD §2.1: "A request whose role is not permitted for the target
        endpoint — or that fails an entity-backed ownership check — is
        rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/roles/engineer_cannot_ship_order
        """
        ctx = setup_ready_to_ship_order(serial_number="GBX-RB")
        add_shipment(ctx["order"]["id"], direction="OUTBOUND", weight_kg=400,
                     rigging_bay_date="2026-08-15", rigging_bay_hours=2)
        resp = api.ship_order(ctx["order"]["id"], reman_engineer_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)
        assert get_order(ctx["order"]["id"])["status"] == "READY_TO_SHIP"

    def test_complete_before_delivery_rejected(self, api,
                                               service_manager_headers):
        """PRD §3.5: "Once the outbound shipment stands `DELIVERED`, the
        service manager completes the order (`SHIPPED → COMPLETED`;
        attempting it earlier fails with `ERR_FREIGHT_NOT_READY`)."

        Design: Corner/errors/error_freight_not_ready_on_complete
        """
        ctx = setup_shipped_order(serial_number="GBX-TR",
                                  rigging_bay_date="2026-08-14")
        # Ship moved the outbound shipment to IN_TRANSIT, not DELIVERED.
        assert validate_success(
            api.get_shipment(ctx["shipment"]["id"], IC)
        )["status"] == "IN_TRANSIT"
        resp = api.complete_order(ctx["order"]["id"], service_manager_headers)
        validate_error(resp, ApiErrorId.ERR_FREIGHT_NOT_READY.value)
        assert get_order(ctx["order"]["id"])["status"] == "SHIPPED"


class TestTerminalLockdown:
    def test_completed_order_locked(self, api, reman_engineer_headers):
        """PRD §2.6: "Terminal states admit no further transitions at all: a
        `COMPLETED` or `CANCELLED` order, a `SCRAPPED` unit (on its physical
        dimension), a `RETURNED` or `CANCELLED` loaner assignment, a
        `DELIVERED` or `CANCELLED` shipment, and an `APPROVED` or `DENIED`
        warranty claim are each locked against any further action."

        Design: Corner/state_machines/order_terminal_completed_lockdown
        """
        ctx = setup_completed_order(serial_number="GBX-T1",
                                    rigging_bay_date="2026-08-07")
        resp = api.start_teardown(ctx["order"]["id"], reman_engineer_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
        assert get_order(ctx["order"]["id"])["status"] == "COMPLETED"
