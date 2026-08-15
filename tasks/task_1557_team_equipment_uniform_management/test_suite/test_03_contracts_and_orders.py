"""Supplier contracts and kit orders: activation gating, allocation caps,
pinned rounding, receive/cancel bookkeeping, amendments, and OCC."""
from test_helpers import (
    EM,
    TA,
    ApiErrorId,
    cap_for,
    committed_units_for,
    create_active_contract,
    create_contract,
    create_kit_order,
    create_pool,
    get_contract,
    get_order,
    get_pool,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestOrderContractGate:
    def test_order_blocked_until_contract_activated(self, api):
        """PRD §3.3: "The contract must be `ACTIVE` (`ERR_CONTRACT_NOT_ACTIVE`
        otherwise)."
        PRD §3.3: "A created order lands in `SUBMITTED` with `source` `MANUAL`,
        and its `expected_delivery_on` is computed as the submission date on the
        logical clock plus the contract's `default_lead_time_days`."
        PRD §2.4: "At server startup the logical clock reads exactly
        `2026-08-01T00:00:00Z`."

        Design: Difficulty/cross_entity_state_dependency/order_blocked_until_contract_activated
        """
        create_pool(season_label="2026-FALL", garment_type="GAME_JERSEY",
                    size_code="M", stock_on_hand=10)
        contract = create_contract(
            vendor_name="GATECO", season_label="2026-FALL",
            allocation_caps=[{"garment_type": "GAME_JERSEY", "max_units": 10}],
            default_lead_time_days=30)
        assert contract["status"] == "DRAFT"

        resp = api.create_kit_order(
            {
                "supplier_contract_id": contract["id"],
                "lines": [{"garment_type": "GAME_JERSEY", "size_code": "M",
                           "quantity": 2, "unit_price_cents": 5000}],
            },
            EM,
        )
        validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_ACTIVE)

        validate_success(api.activate_supplier_contract(contract["id"], TA))
        order = validate_success(api.create_kit_order(
            {
                "supplier_contract_id": contract["id"],
                "lines": [{"garment_type": "GAME_JERSEY", "size_code": "M",
                           "quantity": 2, "unit_price_cents": 5000}],
            },
            EM,
        ), 201)
        assert order["status"] == "SUBMITTED"
        assert order["source"] == "MANUAL"
        assert order["expected_delivery_on"] == "2026-08-31", (
            "Submission date 2026-08-01 on the logical clock plus the 30-day lead")

    def test_order_expected_delivery_uses_contract_lead_time(self, api):
        """PRD §3.3: "A created order lands in `SUBMITTED` with `source`
        `MANUAL`, and its `expected_delivery_on` is computed as the submission
        date on the logical clock plus the contract's `default_lead_time_days`."
        PRD §2.4: "At server startup the logical clock reads exactly
        `2026-08-01T00:00:00Z`."

        Design: Difficulty/cross_entity_state_dependency/order_blocked_until_contract_activated
        """
        create_pool(season_label="2026-FALL", garment_type="GAME_JERSEY",
                    size_code="M", stock_on_hand=10)
        contract = create_active_contract(
            vendor_name="LEADCO", season_label="2026-FALL",
            allocation_caps=[{"garment_type": "GAME_JERSEY", "max_units": 10}],
            default_lead_time_days=14)
        order = create_kit_order(contract["id"], quantity=2,
                                 garment_type="GAME_JERSEY", size_code="M")
        assert order["status"] == "SUBMITTED"
        assert order["expected_delivery_on"] == "2026-08-15", (
            "2026-08-01 plus the 14-day lead time")
        assert committed_units_for(get_contract(contract["id"]), "GAME_JERSEY") == 2


class TestAllocationCapBoundary:
    def test_allocation_cap_exact_fit_then_overflow(self, api):
        """PRD §3.3: "Per garment type, the ordered quantity may equal but never
        exceed the remaining allocation; overshooting is rejected with
        `ERR_ALLOCATION_CAP_EXCEEDED` (HTTP 402, the sole fiscal error on that
        status)."
        PRD §3.3: "The remaining allocation is the cap minus the committed
        total, and the two always sum to the cap."

        Design: Difficulty/boundary_precision_check/allocation_cap_exact_fit_then_overflow
        """
        create_pool(season_label="2026-FALL", garment_type="GAME_JERSEY",
                    size_code="M", stock_on_hand=10)
        contract = create_active_contract(
            vendor_name="CAPCO", season_label="2026-FALL",
            allocation_caps=[{"garment_type": "GAME_JERSEY", "max_units": 10}],
            default_lead_time_days=30)
        create_kit_order(contract["id"], quantity=6)

        exact = validate_success(api.create_kit_order(
            {
                "supplier_contract_id": contract["id"],
                "lines": [{"garment_type": "GAME_JERSEY", "size_code": "M",
                           "quantity": 4, "unit_price_cents": 5000}],
            },
            EM,
        ), 201)
        assert exact["status"] == "SUBMITTED", (
            "An order landing exactly on the cap (6 + 4 == 10) is accepted")

        resp = api.create_kit_order(
            {
                "supplier_contract_id": contract["id"],
                "lines": [{"garment_type": "GAME_JERSEY", "size_code": "M",
                           "quantity": 1, "unit_price_cents": 5000}],
            },
            EM,
        )
        validate_error(resp, ApiErrorId.ERR_ALLOCATION_CAP_EXCEEDED)

        contract_after = get_contract(contract["id"])
        committed = committed_units_for(contract_after, "GAME_JERSEY")
        assert committed == 10
        assert cap_for(contract_after, "GAME_JERSEY") - committed == 0, (
            "Committed plus remaining always sums to the cap")

    def test_allocation_cap_releases_on_cancel(self, api):
        """PRD §3.3: "Cancelling an open order — again only from `SUBMITTED` or
        `PARTIALLY_RECEIVED`, else `ERR_ORDER_NOT_OPEN` — moves it to `CANCELLED`
        and releases the outstanding (ordered minus received) quantities from
        the contract's committed units for each garment type; received
        quantities stay committed."
        PRD §3.3: "Per garment type, the ordered quantity may equal but never
        exceed the remaining allocation; overshooting is rejected with
        `ERR_ALLOCATION_CAP_EXCEEDED` (HTTP 402, the sole fiscal error on that
        status)."

        Design: Difficulty/boundary_precision_check/allocation_cap_exact_fit_then_overflow
        """
        create_pool(season_label="2026-FALL", garment_type="GAME_JERSEY",
                    size_code="M", stock_on_hand=10)
        contract = create_active_contract(
            vendor_name="CAPCO", season_label="2026-FALL",
            allocation_caps=[{"garment_type": "GAME_JERSEY", "max_units": 10}],
            default_lead_time_days=30)
        create_kit_order(contract["id"], quantity=6)
        exact = create_kit_order(contract["id"], quantity=4)

        resp = api.create_kit_order(
            {
                "supplier_contract_id": contract["id"],
                "lines": [{"garment_type": "GAME_JERSEY", "size_code": "M",
                           "quantity": 1, "unit_price_cents": 5000}],
            },
            EM,
        )
        validate_error(resp, ApiErrorId.ERR_ALLOCATION_CAP_EXCEEDED)

        validate_success(api.cancel_kit_order(exact["id"], EM))
        assert committed_units_for(get_contract(contract["id"]), "GAME_JERSEY") == 6, (
            "Cancellation releases the 4 outstanding units")

        refill = validate_success(api.create_kit_order(
            {
                "supplier_contract_id": contract["id"],
                "lines": [{"garment_type": "GAME_JERSEY", "size_code": "M",
                           "quantity": 4, "unit_price_cents": 5000}],
            },
            EM,
        ), 201)
        assert refill["status"] == "SUBMITTED", (
            "The released room can be ordered against again")


class TestOrderPricing:
    def test_order_total_per_line_rounding_order(self, api):
        """PRD §3.3: "First, each line's total is its `unit_price_cents`
        multiplied by its `quantity`, multiplied by one minus its
        `line_discount_pct`, rounded half-up to a whole cent. Second,
        `subtotal_cents` is the sum of those per-line totals. Third,
        `total_cents` is the subtotal multiplied by one minus the contract's
        `contract_rebate_pct`, again rounded half-up to a whole cent."
        PRD §3.3: "Summing the unrounded line values and rounding once at the
        end is a different, non-authoritative variant that can drift by one or
        more cents; only the pinned per-line-then-sum-then-rebate order is
        correct."

        Design: Difficulty/combinatorial_formula/order_total_per_line_rounding_order
        """
        create_pool(season_label="2026-FALL", garment_type="GAME_JERSEY",
                    size_code="M", stock_on_hand=10)
        create_pool(season_label="2026-FALL", garment_type="GAME_PANTS",
                    size_code="34", stock_on_hand=10)
        contract = create_active_contract(
            vendor_name="ROUND-CO", season_label="2026-FALL",
            allocation_caps=[{"garment_type": "GAME_JERSEY", "max_units": 10},
                             {"garment_type": "GAME_PANTS", "max_units": 10}],
            default_lead_time_days=14, contract_rebate_pct=0)
        order = validate_success(api.create_kit_order(
            {
                "supplier_contract_id": contract["id"],
                "lines": [
                    {"garment_type": "GAME_JERSEY", "size_code": "M", "quantity": 1,
                     "unit_price_cents": 1055, "line_discount_pct": 0.10},
                    {"garment_type": "GAME_PANTS", "size_code": "34", "quantity": 1,
                     "unit_price_cents": 1045, "line_discount_pct": 0.10},
                ],
            },
            EM,
        ), 201)
        assert order["subtotal_cents"] == 1891, (
            "Pinned order: round_half_up(949.5) = 950 plus round_half_up(940.5) = 941")
        assert order["subtotal_cents"] != 1890, (
            "Sum-then-round would yield 1890 and is forbidden")
        assert order["total_cents"] == 1891, "Zero rebate leaves the subtotal intact"

    def test_order_expected_delivery_and_status_on_pinned_rounding(self, api):
        """PRD §3.3: "A created order lands in `SUBMITTED` with `source`
        `MANUAL`, and its `expected_delivery_on` is computed as the submission
        date on the logical clock plus the contract's `default_lead_time_days`."
        PRD §2.4: "At server startup the logical clock reads exactly
        `2026-08-01T00:00:00Z`."

        Design: Difficulty/combinatorial_formula/order_total_per_line_rounding_order
        """
        create_pool(season_label="2026-FALL", garment_type="GAME_JERSEY",
                    size_code="M", stock_on_hand=10)
        create_pool(season_label="2026-FALL", garment_type="GAME_PANTS",
                    size_code="34", stock_on_hand=10)
        contract = create_active_contract(
            vendor_name="ROUND-CO", season_label="2026-FALL",
            allocation_caps=[{"garment_type": "GAME_JERSEY", "max_units": 10},
                             {"garment_type": "GAME_PANTS", "max_units": 10}],
            default_lead_time_days=14, contract_rebate_pct=0)
        order = create_kit_order(
            contract["id"],
            lines=[
                {"garment_type": "GAME_JERSEY", "size_code": "M", "quantity": 1,
                 "unit_price_cents": 1055, "line_discount_pct": 0.10},
                {"garment_type": "GAME_PANTS", "size_code": "34", "quantity": 1,
                 "unit_price_cents": 1045, "line_discount_pct": 0.10},
            ])
        assert order["status"] == "SUBMITTED"
        assert order["source"] == "MANUAL"
        assert order["expected_delivery_on"] == "2026-08-15", (
            "Submission date 2026-08-01 on the logical clock plus the 14-day lead")

    def test_order_total_rebate_applied_after_subtotal(self, api):
        """PRD §3.3: "Second, `subtotal_cents` is the sum of those per-line
        totals. Third, `total_cents` is the subtotal multiplied by one minus the
        contract's `contract_rebate_pct`, again rounded half-up to a whole cent."

        Design: Corner/calculations/order_total_rebate_applied_after_subtotal
        """
        create_pool(season_label="2026-FALL", garment_type="GAME_JERSEY",
                    size_code="L", stock_on_hand=50)
        contract = create_active_contract(
            vendor_name="REBATECO", season_label="2026-FALL",
            allocation_caps=[{"garment_type": "GAME_JERSEY", "max_units": 100}],
            default_lead_time_days=30, contract_rebate_pct=0.10)
        order = create_kit_order(contract["id"], quantity=10,
                                 garment_type="GAME_JERSEY", size_code="L",
                                 unit_price_cents=2000)
        assert order["subtotal_cents"] == 20000
        assert order["total_cents"] == 18000, (
            "The 10% contract rebate applies to the summed subtotal")


class TestReceiveAndCancel:
    def test_receive_exceeds_outstanding_rejected(self, api):
        """PRD §3.3: "Per line, the received quantity may not exceed what is
        still outstanding — ordered minus already received — or the call fails
        with `ERR_RECEIVE_EXCEEDS_OUTSTANDING`."
        PRD §3.3: "Each received line increases the matching pool's
        `stock_on_hand` by the received quantity, followed by reconciliation and
        the threshold check in the increase direction (which may clear
        `reorder_blocked`)"
        PRD §3.3: "The order moves to `PARTIALLY_RECEIVED` while any line
        remains outstanding and to `RECEIVED` once every line is fully received"

        Design: Corner/validations/receive_exceeds_outstanding_rejected
        """
        pool = create_pool(season_label="2026-FALL", garment_type="GAME_JERSEY",
                           size_code="M", stock_on_hand=2)
        contract = create_active_contract(
            vendor_name="RCVCO", season_label="2026-FALL",
            allocation_caps=[{"garment_type": "GAME_JERSEY", "max_units": 10}],
            default_lead_time_days=30)
        order = create_kit_order(contract["id"], quantity=3)

        resp = api.receive_kit_order(
            order["id"],
            {"received_lines": [{"garment_type": "GAME_JERSEY", "size_code": "M",
                                 "received_quantity": 4}]},
            EM,
        )
        validate_error(resp, ApiErrorId.ERR_RECEIVE_EXCEEDS_OUTSTANDING)

        received = validate_success(api.receive_kit_order(
            order["id"],
            {"received_lines": [{"garment_type": "GAME_JERSEY", "size_code": "M",
                                 "received_quantity": 3}]},
            EM,
        ))
        assert received["status"] == "RECEIVED", (
            "Receiving exactly the outstanding quantity completes the order")
        assert get_pool(pool["id"])["stock_on_hand"] == 5, "2 on hand + 3 received"

    def test_order_cancel_from_received_rejected(self, api):
        """PRD §3.3: "Cancelling an open order — again only from `SUBMITTED` or
        `PARTIALLY_RECEIVED`, else `ERR_ORDER_NOT_OPEN` — moves it to `CANCELLED`
        and releases the outstanding (ordered minus received) quantities from
        the contract's committed units for each garment type; received
        quantities stay committed."

        Design: Corner/state_machines/order_cancel_from_received_rejected
        """
        pool = create_pool(season_label="2026-FALL", garment_type="GAME_JERSEY",
                           size_code="M", stock_on_hand=2)
        contract = create_active_contract(
            vendor_name="TERMCO", season_label="2026-FALL",
            allocation_caps=[{"garment_type": "GAME_JERSEY", "max_units": 10}],
            default_lead_time_days=30)
        order = create_kit_order(contract["id"], quantity=2)
        validate_success(api.receive_kit_order(
            order["id"],
            {"received_lines": [{"garment_type": "GAME_JERSEY", "size_code": "M",
                                 "received_quantity": 2}]},
            EM,
        ))
        assert get_order(order["id"])["status"] == "RECEIVED"

        resp = api.cancel_kit_order(order["id"], EM)
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_OPEN)
        assert get_order(order["id"])["status"] == "RECEIVED"
        assert get_pool(pool["id"])["stock_on_hand"] == 4, (
            "The rejected cancel leaves the received stock in place")
        assert committed_units_for(get_contract(contract["id"]), "GAME_JERSEY") == 2, (
            "Received quantities stay committed even though cancel was attempted")


class TestCommitCancelConservation:
    def test_contract_commit_cancel_conservation(self, api):
        """PRD §3.3: "The remaining allocation is the cap minus the committed
        total, and the two always sum to the cap."
        PRD §3.3: "Cancelling an open order — again only from `SUBMITTED` or
        `PARTIALLY_RECEIVED`, else `ERR_ORDER_NOT_OPEN` — moves it to `CANCELLED`
        and releases the outstanding (ordered minus received) quantities from
        the contract's committed units for each garment type; received
        quantities stay committed."

        Design: Difficulty/compensating_invariant/contract_commit_cancel_conservation
        """
        pool = create_pool(season_label="2026-FALL", garment_type="GAME_JERSEY",
                           size_code="M", stock_on_hand=10)
        contract = create_active_contract(
            vendor_name="CONSVCO", season_label="2026-FALL",
            allocation_caps=[{"garment_type": "GAME_JERSEY", "max_units": 20}],
            default_lead_time_days=30)
        order = create_kit_order(contract["id"], quantity=7)

        after_submit = get_contract(contract["id"])
        assert committed_units_for(after_submit, "GAME_JERSEY") == 7
        assert cap_for(after_submit, "GAME_JERSEY") \
            - committed_units_for(after_submit, "GAME_JERSEY") == 13, (
                "7 committed + 13 remaining == cap 20")

        cancelled = validate_success(api.cancel_kit_order(order["id"], EM))
        assert cancelled["status"] == "CANCELLED"
        after_cancel = get_contract(contract["id"])
        assert committed_units_for(after_cancel, "GAME_JERSEY") == 0, (
            "Cancellation fully restores the allocation")
        assert cap_for(after_cancel, "GAME_JERSEY") \
            - committed_units_for(after_cancel, "GAME_JERSEY") == 20
        assert get_pool(pool["id"])["stock_on_hand"] == 10, (
            "Cancelling an order never touches physical stock")

    def test_partial_receive_then_cancel_keeps_received_committed(self, api):
        """PRD §3.3: "cancelled orders contributing only their already-received
        quantities (the outstanding portion is released at cancellation)".
        PRD §3.3: "Each received line increases the matching pool's
        `stock_on_hand` by the received quantity, followed by reconciliation and
        the threshold check in the increase direction (which may clear
        `reorder_blocked`); committed units on the contract do not change,
        because they already counted the full line from submission."

        Design: Difficulty/compensating_invariant/contract_commit_cancel_conservation
        """
        pool = create_pool(season_label="2026-FALL", garment_type="GAME_JERSEY",
                           size_code="M", stock_on_hand=10)
        contract = create_active_contract(
            vendor_name="CONSVCO", season_label="2026-FALL",
            allocation_caps=[{"garment_type": "GAME_JERSEY", "max_units": 20}],
            default_lead_time_days=30)
        order = create_kit_order(contract["id"], quantity=7)

        partial = validate_success(api.receive_kit_order(
            order["id"],
            {"received_lines": [{"garment_type": "GAME_JERSEY", "size_code": "M",
                                 "received_quantity": 3}]},
            EM,
        ))
        assert partial["status"] == "PARTIALLY_RECEIVED"
        assert get_pool(pool["id"])["stock_on_hand"] == 13
        assert committed_units_for(get_contract(contract["id"]), "GAME_JERSEY") == 7

        cancelled = validate_success(api.cancel_kit_order(order["id"], EM))
        assert cancelled["status"] == "CANCELLED"
        assert committed_units_for(get_contract(contract["id"]), "GAME_JERSEY") == 3, (
            "Only the 3 received units stay committed; the 4 outstanding release")
        assert get_pool(pool["id"])["stock_on_hand"] == 13


class TestAmendmentsAndClose:
    def test_occ_contract_amend_stale_version_rejected(self, api):
        """PRD §2.8: "A contract amendment must carry
        `expected_supplier_contract_version`, holding the contract `version` the
        client last observed. If the contract's version has advanced beyond that
        value — for example because activation or a prior amendment has since
        landed — the amendment is rejected with `ERR_STALE_CONTRACT_VERSION`
        (HTTP 412), so allocation caps are never rebased on a superseded read."

        Design: Corner/complexity_layers/occ_contract_amend_stale_version_rejected
        """
        contract = create_contract(
            vendor_name="OCCCO", season_label="2026-FALL",
            allocation_caps=[{"garment_type": "GAME_JERSEY", "max_units": 20}],
            default_lead_time_days=30)
        draft_version = contract["version"]
        activated = validate_success(
            api.activate_supplier_contract(contract["id"], TA))
        active_version = activated["version"]
        assert active_version == draft_version + 1

        resp = api.amend_supplier_contract(
            contract["id"],
            {"allocation_caps": [{"garment_type": "GAME_JERSEY", "max_units": 25}],
             "expected_supplier_contract_version": draft_version},
            TA,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_CONTRACT_VERSION)

        amended = validate_success(api.amend_supplier_contract(
            contract["id"],
            {"allocation_caps": [{"garment_type": "GAME_JERSEY", "max_units": 25}],
             "expected_supplier_contract_version": active_version},
            TA,
        ))
        assert amended["version"] == active_version + 1
        assert cap_for(amended, "GAME_JERSEY") == 25

    def test_amendment_below_committed_rejected(self, api):
        """PRD §3.3: "While `ACTIVE`, the contract's caps can be amended — the
        amendment payload carries a replacement `allocation_caps` array plus the
        `expected_supplier_contract_version` guard of §2.8 — but no amended cap
        may fall below the units already committed for that garment type, on
        pain of `ERR_AMENDMENT_BELOW_COMMITTED`."
        PRD §3.3: "Because the figure is derived on read, creating or cancelling
        an order does not mutate a stored contract field and therefore does not
        increment the contract's `version`."

        Design: Corner/validations/amendment_below_committed_rejected
        """
        create_pool(season_label="2026-FALL", garment_type="GAME_JERSEY",
                    size_code="M", stock_on_hand=20)
        contract = create_active_contract(
            vendor_name="AMENDCO", season_label="2026-FALL",
            allocation_caps=[{"garment_type": "GAME_JERSEY", "max_units": 20}],
            default_lead_time_days=30)
        active_version = contract["version"]
        create_kit_order(contract["id"], quantity=7)

        contract_now = get_contract(contract["id"])
        assert contract_now["version"] == active_version, (
            "Order creation does not increment the contract's version")

        resp = api.amend_supplier_contract(
            contract["id"],
            {"allocation_caps": [{"garment_type": "GAME_JERSEY", "max_units": 5}],
             "expected_supplier_contract_version": active_version},
            TA,
        )
        validate_error(resp, ApiErrorId.ERR_AMENDMENT_BELOW_COMMITTED)
        assert cap_for(get_contract(contract["id"]), "GAME_JERSEY") == 20, (
            "The rejected amendment leaves the cap at 20")

    def test_contract_close_blocked_by_open_order_rejected(self, api):
        """PRD §3.3: "Closing a contract moves it `ACTIVE → CLOSED` and is
        refused with `ERR_OPEN_ORDERS_EXIST` while any of its orders remains
        `SUBMITTED` or `PARTIALLY_RECEIVED`."

        Design: Corner/validations/contract_close_blocked_by_open_order_rejected
        """
        create_pool(season_label="2026-FALL", garment_type="GAME_JERSEY",
                    size_code="M", stock_on_hand=10)
        contract = create_active_contract(
            vendor_name="CLOSECO", season_label="2026-FALL",
            allocation_caps=[{"garment_type": "GAME_JERSEY", "max_units": 10}],
            default_lead_time_days=30)
        order = create_kit_order(contract["id"], quantity=2)

        resp = api.close_supplier_contract(contract["id"], TA)
        validate_error(resp, ApiErrorId.ERR_OPEN_ORDERS_EXIST)

        validate_success(api.cancel_kit_order(order["id"], EM))
        closed = validate_success(api.close_supplier_contract(contract["id"], TA))
        assert closed["status"] == "CLOSED", (
            "Once no order remains open, the contract closes")


class TestGarmentCoverage:
    def test_order_garment_not_covered_rejected(self, api):
        """PRD §3.3: "Every line's garment type must appear in the contract's
        caps, otherwise `ERR_GARMENT_NOT_COVERED_BY_CONTRACT`."

        Design: Corner/validations/order_garment_not_covered_rejected
        """
        create_pool(season_label="2026-FALL", garment_type="SOCKS", size_code="L",
                    stock_on_hand=10)
        contract = create_active_contract(
            vendor_name="COVERCO", season_label="2026-FALL",
            allocation_caps=[{"garment_type": "GAME_JERSEY", "max_units": 10}],
            default_lead_time_days=30)
        resp = api.create_kit_order(
            {
                "supplier_contract_id": contract["id"],
                "lines": [{"garment_type": "SOCKS", "size_code": "L",
                           "quantity": 2, "unit_price_cents": 500}],
            },
            EM,
        )
        validate_error(resp, ApiErrorId.ERR_GARMENT_NOT_COVERED_BY_CONTRACT)


class TestValidationCascadePriority:
    def test_order_create_state_beats_fiscal(self, api):
        """PRD §2.9: "Incoming requests are checked against a fixed priority
        cascade so that an earlier failure always masks a later one; the client
        sees the first failing category, not an arbitrary one."
        PRD §2.9: "5. **State preconditions** — the target resources sit in the
        states the operation requires"
        PRD §2.9: "9. **Capacity and fiscal limits** — allocation caps, pool
        sufficiency, recount floors, amendment floors, and receive ceilings"
        PRD §3.3: "The contract must be `ACTIVE` (`ERR_CONTRACT_NOT_ACTIVE`
        otherwise)."

        Design: Difficulty/priority_pair_validation_conflict/order_create_state_beats_fiscal
        """
        create_pool(season_label="2026-FALL", garment_type="GAME_JERSEY",
                    size_code="M", stock_on_hand=10)
        contract = create_contract(
            vendor_name="DRAFTCO", season_label="2026-FALL",
            allocation_caps=[{"garment_type": "GAME_JERSEY", "max_units": 10}],
            default_lead_time_days=30)

        resp = api.create_kit_order(
            {
                "supplier_contract_id": contract["id"],
                "lines": [{"garment_type": "GAME_JERSEY", "size_code": "M",
                           "quantity": 99, "unit_price_cents": 5000}],
            },
            EM,
        )
        validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_ACTIVE)
        assert resp.status_code == 409, (
            "The state error (priority 5) masks the fiscal cap error (priority 9)")

        _data, meta = validate_paginated(api.list_kit_orders(
            EM, params={"supplier_contract_id": contract["id"]}))
        assert meta["total_count"] == 0, "No order may be persisted by the rejection"

    def test_order_create_fiscal_fires_once_state_passes(self, api):
        """PRD §2.9: "Incoming requests are checked against a fixed priority
        cascade so that an earlier failure always masks a later one; the client
        sees the first failing category, not an arbitrary one."
        PRD §3.3: "Per garment type, the ordered quantity may equal but never
        exceed the remaining allocation; overshooting is rejected with
        `ERR_ALLOCATION_CAP_EXCEEDED` (HTTP 402, the sole fiscal error on that
        status)."

        Design: Difficulty/priority_pair_validation_conflict/order_create_state_beats_fiscal
        """
        create_pool(season_label="2026-FALL", garment_type="GAME_JERSEY",
                    size_code="M", stock_on_hand=10)
        contract = create_contract(
            vendor_name="DRAFTCO", season_label="2026-FALL",
            allocation_caps=[{"garment_type": "GAME_JERSEY", "max_units": 10}],
            default_lead_time_days=30)

        resp = api.create_kit_order(
            {
                "supplier_contract_id": contract["id"],
                "lines": [{"garment_type": "GAME_JERSEY", "size_code": "M",
                           "quantity": 99, "unit_price_cents": 5000}],
            },
            EM,
        )
        validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_ACTIVE)

        validate_success(api.activate_supplier_contract(contract["id"], TA))
        resp2 = api.create_kit_order(
            {
                "supplier_contract_id": contract["id"],
                "lines": [{"garment_type": "GAME_JERSEY", "size_code": "M",
                           "quantity": 99, "unit_price_cents": 5000}],
            },
            EM,
        )
        validate_error(resp2, ApiErrorId.ERR_ALLOCATION_CAP_EXCEEDED)
        assert resp2.status_code == 402, (
            "With the state check satisfied, the fiscal cap check fires at 402")


class TestOrderListing:
    def test_kit_orders_filtered_by_contract_pagination_envelope(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of returned items;
        it defaults to 10, with a minimum of 1 and a maximum of 100. The
        `offset` parameter skips that many items from the start of the result
        set and defaults to 0."
        PRD §2.3: "List responses carry `limit`, `offset`, `total_count`, and
        `has_more` in the `meta` object of the envelope."
        PRD §3.3: "Orders can be listed filtered by `supplier_contract_id`,
        `status`, or `source`."

        Design: Corner/endpoints/kit_orders_filtered_by_contract_pagination_envelope
        """
        create_pool(season_label="2026-FALL", garment_type="GAME_JERSEY",
                    size_code="M", stock_on_hand=50)
        contract_a = create_active_contract(
            vendor_name="PAGECO-A", season_label="2026-FALL",
            allocation_caps=[{"garment_type": "GAME_JERSEY", "max_units": 100}],
            default_lead_time_days=30)
        contract_b = create_active_contract(
            vendor_name="PAGECO-B", season_label="2026-FALL",
            allocation_caps=[{"garment_type": "GAME_JERSEY", "max_units": 100}],
            default_lead_time_days=30)
        create_kit_order(contract_a["id"], quantity=1)
        create_kit_order(contract_a["id"], quantity=1)
        create_kit_order(contract_b["id"], quantity=1)

        page1, meta1 = validate_paginated(api.list_kit_orders(
            EM, params={"supplier_contract_id": contract_a["id"],
                        "limit": 1, "offset": 0}))
        assert meta1["total_count"] == 2
        assert meta1["has_more"] is True
        assert len(page1) == 1
        assert page1[0]["supplier_contract_id"] == contract_a["id"], (
            "The contract filter excludes the second contract's order")

        page2, meta2 = validate_paginated(api.list_kit_orders(
            EM, params={"supplier_contract_id": contract_a["id"],
                        "limit": 1, "offset": 1}))
        assert meta2["total_count"] == 2
        assert meta2["has_more"] is False
        assert len(page2) == 1
        assert page2[0]["supplier_contract_id"] == contract_a["id"]

        body = api.list_kit_orders(
            EM, params={"supplier_contract_id": contract_a["id"],
                        "limit": 1, "offset": 0}).json()
        assert body["response_type"] == "array"
        assert isinstance(body["meta"].get("api_request_id"), str)
