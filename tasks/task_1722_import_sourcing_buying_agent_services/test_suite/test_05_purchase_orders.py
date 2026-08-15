"""Purchase-order creation invariants, amendment (OCC, fiscal bounds, state
precondition priority), capacity buckets, and unit conservation."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    accept_quotation,
    accept_quotation_payload,
    advance_to_production_complete,
    amend_po,
    assert_po_unit_conservation,
    book_and_pass_psi,
    book_shipment,
    create_agent,
    create_buyer,
    create_quotation,
    create_sourcing_request,
    get_purchase_order,
    make_buyer_manager_headers,
    make_grade_a_factory,
    make_sourcing_agent_headers,
    setup_po_scenario,
    validate_error,
    validate_success,
)


class TestPurchaseOrderCreation:
    def test_po_total_and_remaining_payable_computed(self, api):
        """PRD: "`total_cents` is exactly `ordered_qty * unit_price_cents`."
        PRD: "`shipped_qty` and `cancelled_qty` start at 0; `open_qty` is always `ordered_qty - shipped_qty - cancelled_qty`"
        PRD: "`milestone_plan_locked` starts false, `progress_pct` starts 0, `production_status` starts `PLACED`"
        PRD: "`remaining_payable_cents` is `total_cents` minus the sum of `total_chargeback_cents` over the PO's `APPROVED` quality claims."

        Design: Corner/entities/po_total_and_remaining_payable_computed
        """
        buyer = create_buyer()
        agent = create_agent()
        factory = make_grade_a_factory(agent["id"])
        sr = create_sourcing_request(
            buyer["id"], agent["id"], title="T", target_price_cents=250, quantity=40
        )
        quotation = create_quotation(sr["id"], factory["id"], unit_price_cents=250, moq=5)
        resp = api.accept_quotation(
            quotation["id"],
            accept_quotation_payload(40, quotation["version"]),
            make_buyer_manager_headers(buyer["id"]),
        )
        po = validate_success(resp, expected_status=200)
        assert po["total_cents"] == 10000  # 40 * 250
        assert po["open_qty"] == 40
        assert po["remaining_payable_cents"] == 10000
        assert po["progress_pct"] == 0
        assert po["production_status"] == "PLACED"
        assert po["milestone_plan_locked"] is False
        assert_po_unit_conservation(po)


class TestNestedPathExistence:
    def test_nested_path_existence_left_to_right(self, api):
        """PRD: "The server validates path identifiers left-to-right, parent before child. A nonexistent parent yields the parent's not-found error (`ERR_FACTORY_NOT_FOUND`, `ERR_SOURCING_REQUEST_NOT_FOUND`, `ERR_PURCHASE_ORDER_NOT_FOUND`)"

        Design: Corner/validations/nested_path_existence_left_to_right
        """
        agent = create_agent()
        validate_error(
            api.create_sample(
                NON_EXISTENT_UUID, {"notes": "orphan"},
                make_sourcing_agent_headers(agent["id"]),
            ),
            ApiErrorId.ERR_SOURCING_REQUEST_NOT_FOUND,
        )


class TestAmendOptimisticConcurrency:
    def _po(self, unit_price_cents=100, ordered_qty=10):
        ctx = setup_po_scenario(
            unit_price_cents=unit_price_cents, ordered_qty=ordered_qty, with_docs=False
        )
        return ctx

    def test_occ_stale_version_on_po_amend(self, api):
        """PRD: "Amending a `PurchaseOrder` requires the request body to carry `expected_po_version` equal to the PO's current `version`."
        PRD: "If the supplied expected version no longer matches the entity's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/validations/occ_stale_version_on_po_amend
        """
        ctx = self._po()
        po = ctx["po"]
        stale_version = po["version"]
        amended = amend_po(po["id"], ctx["agent"]["id"], stale_version, unit_price_cents=120)
        assert amended["unit_price_cents"] == 120
        assert amended["version"] == stale_version + 1

        validate_error(
            api.amend_purchase_order(
                po["id"],
                {"expected_po_version": stale_version, "unit_price_cents": 130},
                make_sourcing_agent_headers(ctx["agent"]["id"]),
            ),
            ApiErrorId.ERR_STALE_VERSION,
        )
        assert get_purchase_order(po["id"])["unit_price_cents"] == 120

    def test_occ_version_increments_on_every_mutation(self, api):
        """PRD: "`version` — an integer starting at 1 and incrementing by 1 on each successful mutation"
        PRD: "A successful amend recomputes `total_cents`, `open_qty`, and `provisional_commission_cents`, and increments `PurchaseOrder.version` by 1."

        Design: Corner/cross_cutting_layers/occ_version_increments_on_every_mutation
        """
        ctx = self._po()
        po = ctx["po"]
        assert po["version"] == 1
        v1 = amend_po(po["id"], ctx["agent"]["id"], po["version"], unit_price_cents=110)
        assert v1["version"] == 2
        v2 = amend_po(po["id"], ctx["agent"]["id"], v1["version"], ordered_qty=12)
        assert v2["version"] == 3
        assert v2["total_cents"] == 1320  # 12 * 110


class TestAmendStateVsFiscalPriority:
    def test_amend_cancelled_po_reports_state_error_not_capacity(self, api):
        """PRD: "The assigned `SourcingAgent` may amend a live PO — one whose `status` is `ACTIVE` or `PARTIALLY_SHIPPED`; anything else yields `ERR_PO_NOT_ACTIVE`."
        PRD: "When several validation rules could fire on the same request, the server evaluates them in this strict order and reports the first failure"
        The requested quantity (100) would also breach the factory's capacity of
        50, but the priority-5 state failure masks the priority-11 fiscal one.

        Design: Difficulty/priority_pair_validation_conflict/amend_cancelled_po_state_beats_capacity_fiscal
        """
        ctx = setup_po_scenario(
            unit_price_cents=100, ordered_qty=40, monthly_capacity_units=50,
            with_docs=False,
        )
        po = ctx["po"]
        cancelled = validate_success(
            api.cancel_purchase_order(
                po["id"], make_sourcing_agent_headers(ctx["agent"]["id"])
            )
        )
        assert cancelled["status"] == "CANCELLED"
        current = get_purchase_order(po["id"])
        validate_error(
            api.amend_purchase_order(
                po["id"],
                {"expected_po_version": current["version"], "ordered_qty": 100},
                make_sourcing_agent_headers(ctx["agent"]["id"]),
            ),
            ApiErrorId.ERR_PO_NOT_ACTIVE,
        )
        assert get_purchase_order(po["id"])["status"] == "CANCELLED"

    def test_amend_live_po_capacity_breach_reports_fiscal_error(self, api):
        """PRD: "A quantity or month change re-runs the §2.8 capacity check (`ERR_CAPACITY_EXCEEDED` on breach)."
        PRD: "When a quotation is accepted or a PO is amended in a way that would change the quantity or month, the check is `committed_units + candidate_qty <= monthly_capacity_units`; equality is allowed, anything larger is rejected with `ERR_CAPACITY_EXCEEDED` (HTTP 422)."
        On a live PO the state precondition passes, so the fiscal capacity
        failure is the one reported.

        Design: Difficulty/priority_pair_validation_conflict/amend_cancelled_po_state_beats_capacity_fiscal
        """
        ctx = setup_po_scenario(
            unit_price_cents=100, ordered_qty=40, monthly_capacity_units=50,
            with_docs=False,
        )
        po = ctx["po"]
        validate_error(
            api.amend_purchase_order(
                po["id"],
                {"expected_po_version": po["version"], "ordered_qty": 100},
                make_sourcing_agent_headers(ctx["agent"]["id"]),
            ),
            ApiErrorId.ERR_CAPACITY_EXCEEDED,
        )


class TestAmendBelowShipped:
    def _po_with_300_shipped(self):
        ctx = setup_po_scenario(ordered_qty=500, unit_price_cents=100)
        advance_to_production_complete(ctx)
        book_and_pass_psi(ctx, lot_size=500)
        shipment = book_shipment(ctx["po"]["id"], ctx["agent"]["id"], 300, "V1")
        ctx["shipment"] = shipment
        return ctx

    def test_amend_below_shipped_boundary_equality_allowed(self, api):
        """PRD: "The ordered quantity may not be amended below `shipped_qty + cancelled_qty` — equality is allowed, anything lower yields `ERR_AMEND_BELOW_SHIPPED`."

        Design: Corner/validations/amend_below_shipped_boundary_equality_allowed
        """
        ctx = self._po_with_300_shipped()
        po = get_purchase_order(ctx["po"]["id"])
        assert po["shipped_qty"] == 300

        validate_error(
            api.amend_purchase_order(
                po["id"],
                {"expected_po_version": po["version"], "ordered_qty": 299},
                make_sourcing_agent_headers(ctx["agent"]["id"]),
            ),
            ApiErrorId.ERR_AMEND_BELOW_SHIPPED,
        )
        current = get_purchase_order(po["id"])
        amended = amend_po(
            po["id"], ctx["agent"]["id"], current["version"], ordered_qty=300
        )
        assert amended["ordered_qty"] == 300
        assert amended["open_qty"] == 0
        assert_po_unit_conservation(amended)


class TestCapacityBucket:
    def _capacity_scenario(self, capacity=1000):
        """One grade-A factory with the given capacity and four standing
        quotations for 700 / 300 / 1 / 400 units."""
        buyer = create_buyer()
        agent = create_agent()
        factory = make_grade_a_factory(
            agent["id"], monthly_capacity_units=capacity
        )
        quotations = {}
        for key, qty in (("q700", 700), ("q300", 300), ("q1", 1), ("q400", 400)):
            sr = create_sourcing_request(
                buyer["id"], agent["id"], title=key, quantity=qty
            )
            quotations[key] = create_quotation(sr["id"], factory["id"], unit_price_cents=100)
        return buyer, factory, quotations

    def test_capacity_equality_accepted_then_overflow_rejected(self, api):
        """PRD: "When a quotation is accepted or a PO is amended in a way that would change the quantity or month, the check is `committed_units + candidate_qty <= monthly_capacity_units`; equality is allowed, anything larger is rejected with `ERR_CAPACITY_EXCEEDED` (HTTP 422)."
        700 + 300 == 1000 is accepted (equality); one further unit overflows.

        Design: Difficulty/resource_temporal_overlap/factory_monthly_capacity_aggregate_bucket
        """
        buyer, factory, q = self._capacity_scenario(capacity=1000)
        po700 = accept_quotation(buyer["id"], q["q700"], 700, delivery_month="2026-09")
        assert po700["status"] == "ACTIVE"
        po300 = accept_quotation(buyer["id"], q["q300"], 300, delivery_month="2026-09")
        assert po300["status"] == "ACTIVE"
        validate_error(
            api.accept_quotation(
                q["q1"]["id"],
                accept_quotation_payload(1, q["q1"]["version"],
                                         delivery_month="2026-09"),
                make_buyer_manager_headers(buyer["id"]),
            ),
            ApiErrorId.ERR_CAPACITY_EXCEEDED,
        )

    def test_capacity_tracked_per_delivery_month(self, api):
        """PRD: "The committed load for a given factory and month is the sum of `open_qty` plus `shipped_qty` over that factory's purchase orders whose `delivery_month` matches the target month and whose `status` is one of `ACTIVE`, `PARTIALLY_SHIPPED`, or `SHIPPED`."
        A 400-unit order into the 2026-10 bucket is unaffected by September's
        full 1000-unit bucket.

        Design: Difficulty/resource_temporal_overlap/factory_monthly_capacity_aggregate_bucket
        """
        buyer, factory, q = self._capacity_scenario(capacity=1000)
        accept_quotation(buyer["id"], q["q700"], 700, delivery_month="2026-09")
        accept_quotation(buyer["id"], q["q300"], 300, delivery_month="2026-09")
        po400 = accept_quotation(buyer["id"], q["q400"], 400, delivery_month="2026-10")
        assert po400["status"] == "ACTIVE"
        assert po400["delivery_month"] == "2026-10"


class TestUnitConservation:
    def _po_ready_with_shipment(self):
        """PO 500 @ 100, production complete, PSI passed, 300 units shipped."""
        ctx = setup_po_scenario(ordered_qty=500, unit_price_cents=100)
        advance_to_production_complete(ctx)
        book_and_pass_psi(ctx, lot_size=500)
        shipment = book_shipment(ctx["po"]["id"], ctx["agent"]["id"], 300, "V1")
        ctx["shipment"] = shipment
        return ctx

    def test_units_conserved_through_shipment_and_cancel(self, api):
        """PRD: "`shipped_qty` and `cancelled_qty` start at 0; `open_qty` is always `ordered_qty - shipped_qty - cancelled_qty` — the invariant `ordered == shipped + cancelled + open` holds throughout the lifecycle."
        PRD: "Cancellation subtracts the shipment's `shipped_qty` from `po.shipped_qty` and recomputes `open_qty`; if the PO had been `PARTIALLY_SHIPPED` and this cancellation removes its last live shipment, the PO reverts from `PARTIALLY_SHIPPED` back to `ACTIVE`."

        Design: Difficulty/compensating_invariant/po_units_conserved_across_ship_amend_cancel
        """
        ctx = self._po_ready_with_shipment()
        po = get_purchase_order(ctx["po"]["id"])
        assert po["shipped_qty"] == 300
        assert po["open_qty"] == 200
        assert po["status"] == "PARTIALLY_SHIPPED"
        assert_po_unit_conservation(po)

        cancelled = validate_success(
            api.cancel_shipment(
                ctx["shipment"]["id"],
                make_sourcing_agent_headers(ctx["agent"]["id"]),
            )
        )
        assert cancelled["status"] == "CANCELLED"
        po = get_purchase_order(ctx["po"]["id"])
        assert po["shipped_qty"] == 0
        assert po["open_qty"] == 500
        assert po["status"] == "ACTIVE"
        assert_po_unit_conservation(po)

    def test_units_conserved_through_amend_down_and_po_cancel(self, api):
        """PRD: "`open_qty` is always `ordered_qty - shipped_qty - cancelled_qty` — the invariant `ordered == shipped + cancelled + open` holds throughout the lifecycle."
        PRD: "Cancellation moves the PO to `CANCELLED`, adds `open_qty` into `cancelled_qty`, sets `open_qty` to 0, and releases the capacity commitment"

        Design: Difficulty/compensating_invariant/po_units_conserved_across_ship_amend_cancel
        """
        ctx = self._po_ready_with_shipment()
        validate_success(
            api.cancel_shipment(
                ctx["shipment"]["id"],
                make_sourcing_agent_headers(ctx["agent"]["id"]),
            )
        )
        po = get_purchase_order(ctx["po"]["id"])
        amended = amend_po(po["id"], ctx["agent"]["id"], po["version"], ordered_qty=400)
        assert amended["ordered_qty"] == 400
        assert amended["cancelled_qty"] == 0
        assert amended["open_qty"] == 400
        assert_po_unit_conservation(amended)

        cancelled = validate_success(
            api.cancel_purchase_order(
                po["id"], make_sourcing_agent_headers(ctx["agent"]["id"])
            )
        )
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["shipped_qty"] == 0
        assert cancelled["cancelled_qty"] == 400
        assert cancelled["open_qty"] == 0
        assert_po_unit_conservation(cancelled)
