"""State guards, cross-entity dependencies, temporal overlap, and compensating invariants
(depth queue A — rules 5, 7, 8, 9).

Each rule-5 instance is constructed so that only the state-machine guard (priority 8) is
reachable — the other named validation is structurally unreachable in the scenario — so the
test is a single-applicable-failure scenario, not an error-precedence assertion.
"""
import pytest
from test_helpers import (
    api_client,
    get_success_data,
    validate_success,
    validate_error,
    validate_paginated,
    create_client_payload,
    create_contract_payload,
    create_inventory_item_payload,
    create_crew_payload,
    create_work_order_payload,
    create_storage_bay_payload,
    create_storage_lot_payload,
    create_damage_report_payload,
    setup_active_contract,
    create_work_order_with_visits,
    schedule_work_order,
    create_completed_takedown,
    create_stored_lot,
    create_client,
    create_draft_contract,
    create_storage_bay,
    make_client_contact_headers,
    TEST_USERS,
)

AM = TEST_USERS["account_manager_headers"]
FS = TEST_USERS["field_supervisor_headers"]
PA = TEST_USERS["platform_admin_headers"]


# =====================================================================
# Rule 5 — priority_pair_validation_conflict
# (single-applicable-failure scenarios → ERR_INVALID_STATE)
# =====================================================================
class TestStateGuardOnReschedule:
    """Difficulty/priority_pair_validation_conflict/state_beats_business_constraint_on_schedule."""

    def _scheduled_wo_on_active_contract(self):
        ctx = setup_active_contract(
            account_type="COMMERCIAL", contract_type="COMMERCIAL",
            sku="TREE-I-PR1", sku_overrides={"unit_replacement_cents": 9000, "on_hand_qty": 30},
            line_quantity=4, unit_install_cents=5000)
        crew = get_success_data(api_client.create_crew(create_crew_payload(crew_name="India PR1"), FS))
        wo, _visits = create_work_order_with_visits(ctx["contract_id"], job_type="INSTALL")
        schedule_work_order(wo["id"], crew["id"], "2026-11-12T00:00:00Z")
        return ctx, crew, wo

    def test_reschedule_already_scheduled_workorder_rejected(self):
        """PRD §2.6: "The general state-machine guard is priority 8: if the requested
        transition is not defined from the target's current state, the request is rejected
        with `ERR_INVALID_STATE` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_business_constraint_on_schedule
        """
        _ctx, crew, wo = self._scheduled_wo_on_active_contract()
        # WO is already SCHEDULED; contract stays ACTIVE so ERR_CONTRACT_NOT_ACTIVE cannot fire.
        res = api_client.schedule_work_order(
            wo["id"], {"crew_id": crew["id"], "scheduled_date": "2026-11-20T00:00:00Z"}, FS)
        validate_error(res, "ERR_INVALID_STATE", 409)

    def test_dispatch_already_scheduled_then_reschedule_still_invalid_state(self):
        """PRD §2.6: "The general state-machine guard is priority 8: if the requested
        transition is not defined from the target's current state, the request is rejected
        with `ERR_INVALID_STATE` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_business_constraint_on_schedule
        """
        _ctx, crew, wo = self._scheduled_wo_on_active_contract()
        get_success_data(api_client.dispatch_work_order(wo["id"], FS))
        # DISPATCHED has no schedule transition either; contract still ACTIVE.
        res = api_client.schedule_work_order(
            wo["id"], {"crew_id": crew["id"], "scheduled_date": "2026-12-01T00:00:00Z"}, FS)
        validate_error(res, "ERR_INVALID_STATE", 409)


class TestStateGuardOnCancelledWorkOrder:
    """Difficulty/priority_pair_validation_conflict/business_safety_beats_business_temporal_unreachable_so_state_vs_safety."""

    def _cancelled_second_wo(self):
        ctx = setup_active_contract(
            account_type="COMMERCIAL", contract_type="COMMERCIAL",
            sku="TREE-J-PR2", sku_overrides={"unit_replacement_cents": 9000, "on_hand_qty": 30},
            line_quantity=4, unit_install_cents=5000)
        crew = get_success_data(api_client.create_crew(create_crew_payload(crew_name="Juliet PR2"), FS))
        wo_first, _v1 = create_work_order_with_visits(ctx["contract_id"], job_type="INSTALL")
        schedule_work_order(wo_first["id"], crew["id"], "2026-11-10T00:00:00Z")
        wo_second, _v2 = create_work_order_with_visits(ctx["contract_id"], job_type="REFRESH")
        get_success_data(api_client.cancel_work_order(wo_second["id"], FS))
        return crew, wo_second

    def test_schedule_cancelled_workorder_rejected_with_invalid_state(self):
        """PRD §2.6: "The general state-machine guard is priority 8: if the requested
        transition is not defined from the target's current state, the request is rejected
        with `ERR_INVALID_STATE` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/business_safety_beats_business_temporal_unreachable_so_state_vs_safety
        """
        crew, wo_second = self._cancelled_second_wo()
        # WO is CANCELLED → no schedule transition defined; the double-book check never runs.
        res = api_client.schedule_work_order(
            wo_second["id"], {"crew_id": crew["id"], "scheduled_date": "2026-11-10T00:00:00Z"}, FS)
        validate_error(res, "ERR_INVALID_STATE", 409)

    def test_schedule_cancelled_workorder_on_clear_date_still_invalid_state(self):
        """PRD §2.6: "The general state-machine guard is priority 8: if the requested
        transition is not defined from the target's current state, the request is rejected
        with `ERR_INVALID_STATE` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/business_safety_beats_business_temporal_unreachable_so_state_vs_safety
        """
        crew, wo_second = self._cancelled_second_wo()
        # Even on a date that would NOT double-book, the CANCELLED state still blocks.
        res = api_client.schedule_work_order(
            wo_second["id"], {"crew_id": crew["id"], "scheduled_date": "2027-06-01T00:00:00Z"}, FS)
        validate_error(res, "ERR_INVALID_STATE", 409)


# =====================================================================
# Rule 7 — cross_entity_state_dependency
# =====================================================================
class TestWorkOrderScheduleRequiresContractActive:
    """Difficulty/cross_entity_state_dependency/workorder_schedule_requires_contract_active."""

    def _signed_not_active(self):
        client = create_client(account_type="COMMERCIAL")
        item = get_success_data(api_client.create_inventory_item(
            create_inventory_item_payload(sku="TREE-M-CE", on_hand_qty=30), PA))
        contract = create_draft_contract(client["id"], contract_type="COMMERCIAL")
        proposal = get_success_data(api_client.create_design_proposal(
            contract["id"], {"theme": "T"}, AM))
        get_success_data(api_client.create_line_item(
            proposal["id"], {"inventory_item_id": item["id"], "quantity": 4, "unit_install_cents": 5000}, AM))
        get_success_data(api_client.submit_proposal(proposal["id"], AM))
        proposed = get_success_data(api_client.propose_contract(client["id"], contract["id"], AM))
        cc = make_client_contact_headers(client["id"])
        get_success_data(api_client.accept_proposal(
            proposal["id"], {"expected_contract_version": proposed["version"]}, cc))
        get_success_data(api_client.sign_contract(client["id"], contract["id"], cc))
        crew = get_success_data(api_client.create_crew(create_crew_payload(crew_name="Mike CE"), FS))
        wo, _visits = create_work_order_with_visits(contract["id"], job_type="INSTALL")
        return crew, wo

    def test_schedule_on_signed_contract_rejected(self):
        """PRD §3.4: "Scheduling is permitted only when the work order is `UNSCHEDULED`, the
        owning contract is `ACTIVE` (otherwise `ERR_CONTRACT_NOT_ACTIVE`, HTTP 409), the work
        order has at least one visit, and the crew clears the double-booking check described
        below."

        Design: Difficulty/cross_entity_state_dependency/workorder_schedule_requires_contract_active
        """
        crew, wo = self._signed_not_active()
        res = api_client.schedule_work_order(
            wo["id"], {"crew_id": crew["id"], "scheduled_date": "2026-11-10T00:00:00Z"}, FS)
        validate_error(res, "ERR_CONTRACT_NOT_ACTIVE", 409)

    def test_schedule_succeeds_only_after_activation(self):
        """PRD §3.4: "Scheduling is permitted only when the work order is `UNSCHEDULED`, the
        owning contract is `ACTIVE` (otherwise `ERR_CONTRACT_NOT_ACTIVE`, HTTP 409), the work
        order has at least one visit, and the crew clears the double-booking check described
        below."

        Design: Difficulty/cross_entity_state_dependency/workorder_schedule_requires_contract_active
        """
        ctx = setup_active_contract(
            account_type="COMMERCIAL", contract_type="COMMERCIAL",
            sku="TREE-M2-CE", sku_overrides={"on_hand_qty": 30},
            line_quantity=4, unit_install_cents=5000)
        crew = get_success_data(api_client.create_crew(create_crew_payload(crew_name="Mike2 CE"), FS))
        wo, _visits = create_work_order_with_visits(ctx["contract_id"], job_type="INSTALL")
        scheduled = validate_success(api_client.schedule_work_order(
            wo["id"], {"crew_id": crew["id"], "scheduled_date": "2026-11-10T00:00:00Z"}, FS), 200)
        assert scheduled["schedule_status"] == "SCHEDULED"


class TestDamageAssessRequiresCompletedTakedown:
    """Difficulty/cross_entity_state_dependency/damage_assess_requires_workorder_completed_takedown."""

    def _open_report_on_dispatched_takedown(self):
        ctx = setup_active_contract(
            account_type="COMMERCIAL", contract_type="COMMERCIAL",
            sku="TREE-N-CE", sku_overrides={"on_hand_qty": 30},
            line_quantity=4, unit_install_cents=5000)
        crew = get_success_data(api_client.create_crew(create_crew_payload(crew_name="Nov CE"), FS))
        wo, _visits = create_work_order_with_visits(ctx["contract_id"], job_type="TAKEDOWN")
        schedule_work_order(wo["id"], crew["id"], "2027-01-15T00:00:00Z")
        get_success_data(api_client.dispatch_work_order(wo["id"], FS))
        dr = get_success_data(api_client.create_damage_report(
            wo["id"], create_damage_report_payload(ctx["sku_id"], damaged_qty=2), FS))
        return dr

    def test_assess_on_dispatched_not_completed_takedown_rejected(self):
        """PRD §3.7: "Assessment is permitted only when the report is `OPEN` and the parent
        work order is a `TAKEDOWN` whose `schedule_status` is `COMPLETED`; if the parent work
        order is not a completed takedown, the request is rejected with
        `ERR_DAMAGE_CONTEXT_INVALID` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/damage_assess_requires_workorder_completed_takedown
        """
        dr = self._open_report_on_dispatched_takedown()
        res = api_client.assess_damage_report(dr["id"], {"resolution_path": "REPAIR"}, FS)
        validate_error(res, "ERR_DAMAGE_CONTEXT_INVALID", 409)

    def test_assess_succeeds_once_takedown_completed(self):
        """PRD §3.7: "Assessment is permitted only when the report is `OPEN` and the parent
        work order is a `TAKEDOWN` whose `schedule_status` is `COMPLETED`; if the parent work
        order is not a completed takedown, the request is rejected with
        `ERR_DAMAGE_CONTEXT_INVALID` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/damage_assess_requires_workorder_completed_takedown
        """
        ctx = setup_active_contract(
            account_type="COMMERCIAL", contract_type="COMMERCIAL",
            sku="TREE-N2-CE", sku_overrides={"unit_replacement_cents": 9000, "on_hand_qty": 30},
            line_quantity=4, unit_install_cents=5000)
        crew = get_success_data(api_client.create_crew(create_crew_payload(crew_name="Nov2 CE"), FS))
        completed_wo = create_completed_takedown(ctx, crew["id"], scheduled_date="2027-02-15T00:00:00Z")
        dr = get_success_data(api_client.create_damage_report(
            completed_wo["id"], create_damage_report_payload(ctx["sku_id"], damaged_qty=2), FS))
        assessed = validate_success(api_client.assess_damage_report(dr["id"], {"resolution_path": "REPAIR"}, FS), 200)
        assert assessed["status"] == "ASSESSED"


# =====================================================================
# Rule 8 — resource_temporal_overlap
# =====================================================================
class TestCrewDoubleBookClosedIntervalBuffer:
    """Difficulty/resource_temporal_overlap/crew_double_book_closed_interval_with_buffer."""

    def _two_workorders_one_scheduled(self):
        ctx = setup_active_contract(
            account_type="COMMERCIAL", contract_type="COMMERCIAL",
            sku="TREE-O-OV", sku_overrides={"on_hand_qty": 30},
            line_quantity=4, unit_install_cents=5000)
        crew = get_success_data(api_client.create_crew(create_crew_payload(crew_name="Oscar OV"), FS))
        wo_first, _v1 = create_work_order_with_visits(ctx["contract_id"], job_type="INSTALL")
        schedule_work_order(wo_first["id"], crew["id"], "2026-11-10T00:00:00Z")
        wo_second, _v2 = create_work_order_with_visits(ctx["contract_id"], job_type="REFRESH")
        return crew, wo_second

    def test_schedule_within_one_day_buffer_rejected(self):
        """PRD §3.4: "The requested `scheduled_date` must clear every other non-cancelled
        work-order window already on that crew by at least a one-day buffer — the comparison is
        a closed-interval, buffer-strict check, so a date falling within one day of an existing
        window is a collision. A violation is rejected with `ERR_CREW_DOUBLE_BOOKED` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/crew_double_book_closed_interval_with_buffer
        """
        crew, wo_second = self._two_workorders_one_scheduled()
        # 2026-11-11 is one day after the existing 2026-11-10 window → within buffer.
        res = api_client.schedule_work_order(
            wo_second["id"], {"crew_id": crew["id"], "scheduled_date": "2026-11-11T00:00:00Z"}, FS)
        validate_error(res, "ERR_CREW_DOUBLE_BOOKED", 409)

    def test_schedule_well_clear_of_buffer_succeeds(self):
        """PRD §3.4: "The requested `scheduled_date` must clear every other non-cancelled
        work-order window already on that crew by at least a one-day buffer — the comparison is
        a closed-interval, buffer-strict check, so a date falling within one day of an existing
        window is a collision. A violation is rejected with `ERR_CREW_DOUBLE_BOOKED` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/crew_double_book_closed_interval_with_buffer
        """
        crew, wo_second = self._two_workorders_one_scheduled()
        # A date many days clear of the existing window must schedule successfully.
        scheduled = validate_success(api_client.schedule_work_order(
            wo_second["id"], {"crew_id": crew["id"], "scheduled_date": "2026-12-15T00:00:00Z"}, FS), 200)
        assert scheduled["schedule_status"] == "SCHEDULED"


class TestStorageBayCapacityHalfOpenAggregate:
    """Difficulty/resource_temporal_overlap/storage_bay_capacity_half_open_aggregate."""

    def _bay_with_reserved_80(self, bay_code):
        client_a = create_client(account_type="COMMERCIAL")
        bay = create_storage_bay(bay_code=bay_code, capacity_units=100)
        contract_a = create_draft_contract(client_a["id"], contract_type="COMMERCIAL")
        get_success_data(api_client.create_storage_lot(
            create_storage_lot_payload(contract_a["id"], bay["id"], unit_count=80,
                                       stored_from="2027-01-01T00:00:00Z",
                                       released_on="2027-03-01T00:00:00Z"), FS))
        client_b = create_client(account_type="COMMERCIAL")
        contract_b = create_draft_contract(client_b["id"], contract_type="COMMERCIAL")
        return bay, contract_b

    def test_overlapping_lot_exceeding_capacity_rejected(self):
        """PRD §3.6: "across the half-open interval from `stored_from` up to but not including
        `released_on`, the sum of `unit_count` over all lots whose intervals overlap, including
        the new lot, must not exceed the bay's `capacity_units`; a reservation that would
        exceed it is rejected with `ERR_BAY_CAPACITY_EXCEEDED` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/storage_bay_capacity_half_open_aggregate
        """
        bay, contract_b = self._bay_with_reserved_80("BAY-P-OV")
        # 80 + 30 = 110 > 100 over the overlapping interval [2027-02-01, 2027-04-01).
        res = api_client.create_storage_lot(
            create_storage_lot_payload(contract_b["id"], bay["id"], unit_count=30,
                                       stored_from="2027-02-01T00:00:00Z",
                                       released_on="2027-04-01T00:00:00Z"), FS)
        validate_error(res, "ERR_BAY_CAPACITY_EXCEEDED", 409)

    def test_non_overlapping_interval_succeeds_half_open(self):
        """PRD §3.6: "across the half-open interval from `stored_from` up to but not including
        `released_on`, the sum of `unit_count` over all lots whose intervals overlap, including
        the new lot, must not exceed the bay's `capacity_units`; a reservation that would
        exceed it is rejected with `ERR_BAY_CAPACITY_EXCEEDED` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/storage_bay_capacity_half_open_aggregate
        """
        bay, contract_b = self._bay_with_reserved_80("BAY-P2-OV")
        # A 30-unit lot starting exactly when the 80-unit lot ends does NOT overlap
        # (half-open), so 30 alone <= 100 and the reservation succeeds.
        lot = validate_success(api_client.create_storage_lot(
            create_storage_lot_payload(contract_b["id"], bay["id"], unit_count=30,
                                       stored_from="2027-03-01T00:00:00Z",
                                       released_on="2027-05-01T00:00:00Z"), FS), 201)
        assert lot["status"] == "RESERVED"


# =====================================================================
# Rule 9 — compensating_invariant
# =====================================================================
class TestStorageBayCapacityConservedOnRelease:
    """Difficulty/compensating_invariant/storage_bay_capacity_conserved_on_lot_release."""

    def _bay_with_released_30(self, bay_code):
        # Check-in requires the owning contract to be SIGNED or ACTIVE (PRD §3.6),
        # so the lot is reserved against an ACTIVE contract before check-in/release.
        ctx = setup_active_contract(
            account_type="COMMERCIAL", contract_type="COMMERCIAL",
            sku=bay_code + "-SKU", line_quantity=4, unit_install_cents=5000)
        contract = {"id": ctx["contract_id"]}
        bay = create_storage_bay(bay_code=bay_code, capacity_units=100)
        lot_one = get_success_data(api_client.create_storage_lot(
            create_storage_lot_payload(contract["id"], bay["id"], unit_count=30,
                                       stored_from="2027-01-01T00:00:00Z",
                                       released_on="2027-03-01T00:00:00Z"), FS))
        get_success_data(api_client.check_in_storage_lot(lot_one["id"], FS))
        get_success_data(api_client.release_storage_lot(lot_one["id"], FS))
        return bay, contract, lot_one

    def test_released_lot_frees_full_capacity(self):
        """PRD §3.6: "A supervisor releases a lot, advancing `STORED` to `RELEASED`, which
        requires the lot to be `STORED` and frees the bay capacity that lot's interval occupied."

        Design: Difficulty/compensating_invariant/storage_bay_capacity_conserved_on_lot_release
        """
        bay, contract, _lot_one = self._bay_with_released_30("BAY-R-INV")
        # After releasing the 30-unit lot, a full 100-unit lot on the same interval fits.
        lot_two = validate_success(api_client.create_storage_lot(
            create_storage_lot_payload(contract["id"], bay["id"], unit_count=100,
                                       stored_from="2027-01-01T00:00:00Z",
                                       released_on="2027-03-01T00:00:00Z"), FS), 201)
        assert lot_two["unit_count"] == 100

    def test_released_lot_status_is_released(self):
        """PRD §3.6: "A supervisor releases a lot, advancing `STORED` to `RELEASED`, which
        requires the lot to be `STORED` and frees the bay capacity that lot's interval occupied."

        Design: Difficulty/compensating_invariant/storage_bay_capacity_conserved_on_lot_release
        """
        bay, _contract, lot_one = self._bay_with_released_30("BAY-R2-INV")
        released = validate_success(api_client.get_storage_lot(lot_one["id"], FS), 200)
        assert released["status"] == "RELEASED"


class TestInventoryConservedRestockThenFulfill:
    """Difficulty/compensating_invariant/inventory_on_hand_conserved_restock_then_fulfill."""

    def _settled_restock(self):
        ctx = setup_active_contract(
            account_type="COMMERCIAL", contract_type="COMMERCIAL",
            sku="STRAND-S-INV", sku_overrides={"category": "LIGHTING", "unit_replacement_cents": 4500, "on_hand_qty": 20},
            line_quantity=4, unit_install_cents=5000)
        crew = get_success_data(api_client.create_crew(create_crew_payload(crew_name="Sierra INV"), FS))
        completed_wo = create_completed_takedown(ctx, crew["id"], scheduled_date="2027-01-20T00:00:00Z")
        dr = get_success_data(api_client.create_damage_report(
            completed_wo["id"], create_damage_report_payload(ctx["sku_id"], damaged_qty=4), FS))
        get_success_data(api_client.assess_damage_report(dr["id"], {"resolution_path": "RESTOCK"}, FS))
        get_success_data(api_client.settle_damage_report(dr["id"], FS))
        return ctx, dr

    def test_settle_decrements_then_check(self):
        """PRD §3.7: "settling mints a new `RestockOrder` in `status` `REQUESTED` whose
        `damage_report_id` points back to this report and whose `quantity` equals the report's
        `damaged_qty`, and then decrements the referenced inventory item's `on_hand_qty` by
        `damaged_qty`, floored at 0 so stock never goes negative."

        Design: Difficulty/compensating_invariant/inventory_on_hand_conserved_restock_then_fulfill
        """
        ctx, _dr = self._settled_restock()
        item = validate_success(api_client.get_inventory_item(ctx["sku_id"], PA), 200)
        assert item["on_hand_qty"] == 16, (
            f"expected 20->16 immediately after RESTOCK settle, got {item['on_hand_qty']}")

    def test_fulfill_restores_original_on_hand(self):
        """PRD §3.7: "fulfillment increments the referenced inventory item's `on_hand_qty` by
        the restock order's `quantity` — compensating the settle-time decrement — and
        increments the restock order's `version`."

        Design: Difficulty/compensating_invariant/inventory_on_hand_conserved_restock_then_fulfill
        """
        ctx, dr = self._settled_restock()
        data, _meta = validate_paginated(api_client.list_restock_orders(
            FS, params={"damage_report_id": dr["id"]}))
        ro_id = data[0]["id"]
        fulfilled = validate_success(api_client.fulfill_restock_order(ro_id, PA), 200)
        assert fulfilled["status"] == "FULFILLED"
        item = validate_success(api_client.get_inventory_item(ctx["sku_id"], PA), 200)
        assert item["on_hand_qty"] == 20, (
            f"expected 16->20 after fulfill (restored to original), got {item['on_hand_qty']}")
