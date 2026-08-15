"""Procurement: design-release cascade, manual change orders, lead times, budget."""

from test_helpers import (
    ONE_RADIO_EQUIPMENT,
    TEST_USERS,
    TWO_LINE_EQUIPMENT,
    ApiErrorId,
    assert_equipment_order,
    assert_timestamp_equals,
    create_equipment_order_payload,
    get_work_order,
    make_customer_headers,
    set_clock,
    setup_approved_work_order,
    setup_pending_approval,
    validate_error,
    validate_success,
)

MANAGER = TEST_USERS["shop_manager_headers"]


class TestDesignApprovalReleasesProcurement:
    def test_approval_advances_work_order_to_parts_pending(self, api):
        """PRD §3.2: "When the list is non-empty, the work order advances to `PARTS_PENDING` instead, and the server auto-creates one equipment order per equipment line, in line order, each in `PLANNED` with `source` `DESIGN_RELEASE`, each carrying `source_design_revision` equal to the approved `revision`, each assigned its `seq`, with `parts_pending_count` recomputed so that it lands exactly on the number of lines created."

        Design: Difficulty/transitive_cascade/design_approval_releases_procurement
        """
        bundle = setup_pending_approval(
            customer_name="Release Owner", customer_email="r@x.com",
            equipment_list=TWO_LINE_EQUIPMENT, layout_notes="two-screen panel",
            work_order_overrides={"estimated_downtime_days": 20,
                                  "quoted_labor_hours": 40,
                                  "bay_window_end": "2026-08-30T00:00:00Z"})
        decided = validate_success(api.decide_panel_design(
            bundle["design"]["id"], "APPROVE",
            make_customer_headers(bundle["customer"]["id"])))
        assert decided["status"] == "APPROVED"
        work_order = get_work_order(bundle["work_order"]["id"])
        assert work_order["status"] == "PARTS_PENDING", (
            f"non-empty approval must land PARTS_PENDING, got {work_order['status']}")
        assert work_order["parts_pending_count"] == 2, (
            "parts_pending_count lands exactly on the number of lines created")

    def test_approval_creates_one_planned_order_per_line_in_order(self, api):
        """PRD §3.2: "When the list is non-empty, the work order advances to `PARTS_PENDING` instead, and the server auto-creates one equipment order per equipment line, in line order, each in `PLANNED` with `source` `DESIGN_RELEASE`, each carrying `source_design_revision` equal to the approved `revision`, each assigned its `seq`, with `parts_pending_count` recomputed so that it lands exactly on the number of lines created."
        PRD §3.3: "The equipment-order list sorts by `created_at` ascending and then by `seq` ascending, and can be filtered by `work_order_id`, by `status`, or by both."

        Design: Difficulty/transitive_cascade/design_approval_releases_procurement
        """
        bundle = setup_approved_work_order(
            customer_name="Release Owner", customer_email="r@x.com",
            equipment_list=TWO_LINE_EQUIPMENT, layout_notes="two-screen panel",
            work_order_overrides={"estimated_downtime_days": 20,
                                  "quoted_labor_hours": 40,
                                  "bay_window_end": "2026-08-30T00:00:00Z"})
        orders = bundle["orders"]
        assert len(orders) == 2, f"expected 2 cascade orders, got {len(orders)}"
        first, second = orders[0], orders[1]
        for order in (first, second):
            assert_equipment_order(order)
            assert order["source"] == "DESIGN_RELEASE"
            assert order["status"] == "PLANNED"
            assert order["source_design_revision"] == bundle["design"]["revision"], (
                "each cascade order carries the approved design's revision")
        assert first["part_number"] == "GTN750XI" and first["lead_time_days"] == 21
        assert second["part_number"] == "GFC500" and second["lead_time_days"] == 14
        assert first["seq"] < second["seq"], (
            "seq increases with creation order so cascade rows keep line order")


class TestManualChangeOrders:
    def test_manual_order_moves_approved_to_parts_pending(self, api):
        """PRD §3.3: "A manual line is stamped with `source` `MANUAL`, carries a null `source_design_revision`, receives the next `seq`, and starts in `PLANNED`."
        PRD §3.3: "If the work order was `APPROVED`, adding the line cascades it to `PARTS_PENDING` and recomputes `parts_pending_count`; if it was already `PARTS_PENDING`, only the count moves."

        Design: Corner/state_machines/manual_order_moves_approved_to_parts_pending
        """
        bundle = setup_approved_work_order(customer_name="Manual Mo",
                                           customer_email="m@x.com",
                                           equipment_list=[], layout_notes="wiring only")
        assert bundle["work_order"]["status"] == "APPROVED"
        created = validate_success(api.create_equipment_order(
            create_equipment_order_payload(
                bundle["work_order"]["id"], part_number="GI275",
                description="Engine display", quantity=1,
                unit_price_cents=100000, lead_time_days=7),
            MANAGER), 201)
        assert_equipment_order(created)
        assert created["status"] == "PLANNED"
        assert created["source"] == "MANUAL"
        assert created["source_design_revision"] is None
        work_order = get_work_order(bundle["work_order"]["id"])
        assert work_order["status"] == "PARTS_PENDING"
        assert work_order["parts_pending_count"] == 1


class TestChangeOrderBudget:
    def test_manual_orders_capped_at_110_percent_of_approved_subtotal(self, api):
        """PRD §3.3: "The committed parts spend of a work order is the sum of `quantity` times `unit_price_cents` over all of its equipment orders that are not `CANCELLED`, including the line being added. A manual line whose extended price would push that commitment beyond the greater of two bounds — 110 percent of the approved design's equipment subtotal, or a floor of 250,000 cents — is rejected with `ERR_BUDGET_EXCEEDED`."

        Design: Corner/endpoints/manual_equipment_order_budget_cap
        """
        bundle = setup_approved_work_order(
            customer_name="Budget Bob", customer_email="b2@x.com",
            equipment_list=TWO_LINE_EQUIPMENT, layout_notes="two-line",
            work_order_overrides={"estimated_downtime_days": 20,
                                  "quoted_labor_hours": 40,
                                  "bay_window_end": "2026-08-30T00:00:00Z"})
        # Approved subtotal 2600000 -> cap max(2860000, 250000) = 2860000.
        first = validate_success(api.create_equipment_order(
            create_equipment_order_payload(
                bundle["work_order"]["id"], part_number="GI275",
                description="Engine display", unit_price_cents=200000,
                lead_time_days=7),
            MANAGER), 201)
        assert first["source"] == "MANUAL" and first["status"] == "PLANNED", (
            "committed 2800000 <= 2860000 cap, so the first manual line lands")

        response = api.create_equipment_order(
            create_equipment_order_payload(
                bundle["work_order"]["id"], part_number="G5",
                description="Standby instrument", unit_price_cents=100000,
                lead_time_days=7),
            MANAGER)
        validate_error(response, ApiErrorId.ERR_BUDGET_EXCEEDED)
        work_order = get_work_order(bundle["work_order"]["id"])
        assert work_order["parts_pending_count"] == 3, (
            "two design-release lines plus the one accepted manual line remain pending")


class TestOrderLifecycle:
    def test_receive_from_planned_rejected_then_valid_path(self, api):
        """PRD §3.3: "Equipment orders move through `PLANNED`, then `ORDERED`, and finally `RECEIVED` or `CANCELLED`."
        PRD §2.9: "`parts_pending_count` counts the work order's equipment orders in `PLANNED` or `ORDERED`."

        Design: Corner/state_machines/receive_planned_order_rejected
        """
        bundle = setup_approved_work_order(
            customer_name="Recv Rita", customer_email="r2@x.com",
            equipment_list=ONE_RADIO_EQUIPMENT, layout_notes="one radio",
            work_order_overrides={"estimated_downtime_days": 20,
                                  "quoted_labor_hours": 10,
                                  "bay_window_end": "2026-08-30T00:00:00Z"})
        order = bundle["orders"][0]
        response = api.receive_equipment_order(order["id"], MANAGER)
        validate_error(response, ApiErrorId.ERR_INVALID_STATE)

        validate_success(api.mark_ordered(order["id"], MANAGER))
        received = validate_success(api.receive_equipment_order(order["id"], MANAGER))
        assert received["status"] == "RECEIVED"
        assert get_work_order(bundle["work_order"]["id"])["parts_pending_count"] == 0, (
            "a RECEIVED order leaves the PLANNED/ORDERED pending set")


class TestPromisedDateAndLateness:
    def test_promised_date_and_strict_lateness_boundary(self, api):
        """PRD §3.3: "Marking an order placed records `ordered_at` from the logical clock and computes `promised_date` as exactly `lead_time_days` full 24-hour days after that instant, preserving the time of day; both fields stay null until the order is marked ordered."
        PRD §3.3: "Receiving the parts records `received_at` — likewise null until receipt — and resolves `is_late`: the order is late only when `received_at` falls strictly later than `promised_date`, and arrival exactly on the promised instant is on time."

        Design: Corner/calculations/promised_date_and_strict_lateness
        """
        bundle = setup_approved_work_order(
            customer_name="Late Larry", customer_email="l2@x.com",
            equipment_list=ONE_RADIO_EQUIPMENT, layout_notes="one radio",
            work_order_overrides={"estimated_downtime_days": 20,
                                  "quoted_labor_hours": 10,
                                  "bay_window_end": "2026-08-30T00:00:00Z"})
        order = bundle["orders"][0]
        ordered = validate_success(api.mark_ordered(order["id"], MANAGER))
        assert_timestamp_equals(ordered["ordered_at"], "2026-08-01T09:00:00Z")
        assert_timestamp_equals(ordered["promised_date"], "2026-08-15T09:00:00Z")

        set_clock("2026-08-15T09:00:00Z")
        received = validate_success(api.receive_equipment_order(order["id"], MANAGER))
        assert_timestamp_equals(received["received_at"], "2026-08-15T09:00:00Z")
        assert received["is_late"] is False, (
            "arrival exactly on the promised instant is on time (strict > boundary)")


class TestPartsPendingBoundary:
    def test_begin_installation_rejected_with_one_pending_order(self, api):
        """PRD §3.4: "Beginning installation moves the work order from `APPROVED` or `PARTS_PENDING` to `INSTALLATION`, and it is refused while any equipment order is still `PLANNED` or `ORDERED` — that is, while `parts_pending_count` is above zero — with `ERR_PARTS_PENDING`."

        Design: Difficulty/boundary_precision_check/parts_pending_one_vs_zero
        """
        bundle = setup_approved_work_order(
            customer_name="Parts Owner", customer_email="parts@x.com",
            equipment_list=ONE_RADIO_EQUIPMENT, layout_notes="one radio",
            work_order_overrides={"estimated_downtime_days": 20,
                                  "quoted_labor_hours": 10,
                                  "bay_window_end": "2026-08-30T00:00:00Z"})
        assert bundle["work_order"]["parts_pending_count"] == 1
        response = api.begin_installation(bundle["work_order"]["id"], MANAGER)
        validate_error(response, ApiErrorId.ERR_PARTS_PENDING)
        work_order = get_work_order(bundle["work_order"]["id"])
        assert work_order["status"] == "PARTS_PENDING"
        assert work_order["parts_pending_count"] == 1

    def test_begin_installation_accepted_at_zero_pending(self, api):
        """PRD §3.4: "Beginning installation moves the work order from `APPROVED` or `PARTS_PENDING` to `INSTALLATION`, and it is refused while any equipment order is still `PLANNED` or `ORDERED` — that is, while `parts_pending_count` is above zero — with `ERR_PARTS_PENDING`."
        PRD §3.4: "On induction the server stamps `inducted_at` from the logical clock and advances the work order's `version`."

        Design: Difficulty/boundary_precision_check/parts_pending_one_vs_zero
        """
        bundle = setup_approved_work_order(
            customer_name="Parts Owner", customer_email="parts@x.com",
            equipment_list=ONE_RADIO_EQUIPMENT, layout_notes="one radio",
            work_order_overrides={"estimated_downtime_days": 20,
                                  "quoted_labor_hours": 10,
                                  "bay_window_end": "2026-08-30T00:00:00Z"})
        order = bundle["orders"][0]
        validate_success(api.mark_ordered(order["id"], MANAGER))
        validate_success(api.receive_equipment_order(order["id"], MANAGER))
        inducted = validate_success(
            api.begin_installation(bundle["work_order"]["id"], MANAGER))
        assert inducted["status"] == "INSTALLATION"
        assert inducted["parts_pending_count"] == 0, (
            "the received order leaves the pending set, so the gate opens at zero")
        assert_timestamp_equals(inducted["inducted_at"], "2026-08-01T09:00:00Z")
