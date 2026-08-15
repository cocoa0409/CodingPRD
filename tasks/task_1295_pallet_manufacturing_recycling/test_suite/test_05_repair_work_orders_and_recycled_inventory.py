"""Repair work orders: cycles, abort compensation, and recycled lots."""
import pytest

from test_helpers import (
    ApiErrorId,
    SALES,
    YARD,
    api_client,
    complete_repair_order,
    create_active_spec,
    create_confirmed_order,
    create_customer,
    create_graded_core,
    create_new_build_lot,
    create_repair_order,
    find_lots,
    get_core,
    get_lot,
    list_order_lines,
    publish_lumber_index,
    set_clock,
    sort_core,
    start_repair_order,
    validate_error,
    validate_success,
)


def _setup_cycle_scenario():
    """ACTIVE spec + one B-graded core with a FAILED repair behind it."""
    spec = create_active_spec()
    _batch, core = create_graded_core(
        "B", supplier_name="CycleCo",
        estimated_grade_mix={"A": 0.0, "B": 1.0, "SCRAP": 0.0})
    wo = create_repair_order(core["id"], spec["id"], target_grade="A",
                             labor_minutes_estimate=30)
    start_repair_order(wo["id"])
    complete_repair_order(wo["id"], "FAILED", 25)
    return spec, core, wo


class TestRepairFailureCycle:

    def test_failed_repair_cycles_core_back_to_unsorted_yard(self):
        """PRD §3.4: "Every completion increments the core's
        `repair_cycle_count` by one."
        PRD §3.4: "When the outcome is `FAILED`, the core cycles: its `grade`
        reverts to `UNSORTED` and its `processing_status` returns to `YARD`,
        ready to be sorted again."

        Design: Difficulty/non_linear_state_machine/core_unit_repair_failure_cycle
        """
        spec, core, wo = _setup_cycle_scenario()
        after = get_core(core["id"])
        assert after["repair_cycle_count"] == 1, (
            f"one FAILED completion must set repair_cycle_count 1, "
            f"got {after['repair_cycle_count']}"
        )
        assert after["grade"] == "UNSORTED", (
            f"FAILED outcome must revert grade to UNSORTED, got {after['grade']}"
        )
        assert after["processing_status"] == "YARD"
        wo_after = validate_success(
            api_client.get_repair_order(wo["id"], YARD))
        assert wo_after["status"] == "COMPLETED"
        assert wo_after["outcome_grade"] == "FAILED"

    def test_cycled_core_can_be_resorted_and_repaired_again(self):
        """PRD §3.4: "The same core row cycles — no new core unit row is
        created and the row keeps its `id`; a self-referential `rework_of_id`
        is set only when a fresh sort creates a derived record, while in-place
        cycling keeps the same identifier."
        PRD §3.4: "Opening the order moves the core to `IN_REPAIR` and creates
        the work order in `OPEN` status."

        Design: Difficulty/non_linear_state_machine/core_unit_repair_failure_cycle
        """
        spec, core, wo = _setup_cycle_scenario()
        # The cycled core is UNSORTED/YARD again: re-sort it on the SAME id.
        resorted = sort_core(core["id"], "A")
        assert resorted["id"] == core["id"]
        assert resorted["grade"] == "A"
        assert resorted["repair_cycle_count"] == 1
        wo2_resp = api_client.create_repair_order(
            {
                "core_unit_id": core["id"],
                "target_grade": "A",
                "target_spec_id": spec["id"],
                "labor_minutes_estimate": 20,
            },
            YARD,
        )
        wo2 = validate_success(wo2_resp, expected_status=201)
        assert wo2["status"] == "OPEN"
        after = get_core(core["id"])
        assert after["processing_status"] == "IN_REPAIR", (
            "opening the second work order must move the cycled core back "
            f"to IN_REPAIR, got {after['processing_status']}"
        )


class TestRepairAbort:

    def test_abort_work_order_releases_core(self):
        """PRD §3.4: "Aborting likewise requires `OPEN` (else
        `ERR_WO_NOT_OPEN`) and releases the core back to `YARD` without
        touching its grade."

        Design: Corner/state_machines/wo_abort_releases_core_to_yard
        """
        spec = create_active_spec()
        _batch, core = create_graded_core(
            "B", supplier_name="AbortCo",
            estimated_grade_mix={"A": 0.0, "B": 1.0, "SCRAP": 0.0})
        wo = create_repair_order(core["id"], spec["id"], target_grade="A",
                                 labor_minutes_estimate=30)
        assert wo["status"] == "OPEN"
        resp = api_client.abort_repair_order(wo["id"], YARD)
        aborted = validate_success(resp)
        assert aborted["status"] == "ABORTED"
        after = get_core(core["id"])
        assert after["processing_status"] == "YARD", (
            f"abort must release the core to YARD, "
            f"got {after['processing_status']}"
        )
        assert after["grade"] == "B", "abort must not touch the core's grade"


class TestRepairEligibility:

    def test_repair_on_scrap_core_rejected(self):
        """PRD §3.4: "Three eligibility gates guard the opening, surfacing as
        `ERR_CORE_NOT_REPAIRABLE` when the core's grade is not `A` or `B`,
        `ERR_CORE_NOT_IN_YARD` when its `processing_status` is not `YARD`, and
        `ERR_REPAIR_ALREADY_OPEN` when another work order for the same core is
        still `OPEN` or `IN_PROGRESS`."

        Design: Corner/validations/repair_ineligible_core_rejected
        """
        spec = create_active_spec()
        _batch, core = create_graded_core(
            "SCRAP", supplier_name="ScrapCo", agreed_unit_price_cents=100,
            sort_note="destroyed",
            estimated_grade_mix={"A": 0.0, "B": 0.0, "SCRAP": 1.0})
        resp = api_client.create_repair_order(
            {
                "core_unit_id": core["id"],
                "target_grade": "A",
                "target_spec_id": spec["id"],
                "labor_minutes_estimate": 15,
            },
            YARD,
        )
        validate_error(resp, ApiErrorId.ERR_CORE_NOT_REPAIRABLE)
        assert resp.status_code == 422


def _setup_recycled_and_new_lots():
    """One RECYCLED_REPAIR A-lot (from repair) + one NEW_BUILD A-lot.

    Returns (spec, recycled_lot, new_lot, customer, core).
    """
    set_clock()
    publish_lumber_index()
    spec = create_active_spec(
        spec_code="GMA-42X42-11B", length_in=42, width_in=42,
        height_in=5.0, board_count=11, lumber_species="PINE")
    # Repair a B core into an A outcome against the spec.
    _batch, core = create_graded_core(
        "B", supplier_name="SelCo",
        estimated_grade_mix={"A": 0.0, "B": 1.0, "SCRAP": 0.0})
    wo = create_repair_order(core["id"], spec["id"], target_grade="A",
                             labor_minutes_estimate=30)
    start_repair_order(wo["id"])
    complete_repair_order(wo["id"], "A", 20)
    recycled_lots = find_lots(spec_id=spec["id"], status="AVAILABLE",
                              origin_type="RECYCLED_REPAIR")
    assert len(recycled_lots) == 1, (
        f"repair completion must create exactly one recycled lot, "
        f"got {len(recycled_lots)}"
    )
    new_lot = create_new_build_lot(spec["id"], 50, quality_grade="A")
    customer = create_customer("SelBuyer")
    return spec, recycled_lots[0], new_lot, customer, core


class TestRecycledLotAllocation:

    def test_allocation_prefers_recycled_lot(self):
        """PRD §3.6: "Candidates are ranked lexicographically — recycled lots
        before new-build lots under the recycle-first policy, then lowest
        `unit_cost_cents`, then earliest lot `created_at` — and the winner's
        identity lands in the line's `allocated_lot_id` as the line moves to
        `ALLOCATED` and the lot's `quantity_available` is debited by the
        reservation."

        Design: Corner/calculations/allocation_selector_prefers_recycled_then_cheapest
        """
        spec, recycled, new_lot, customer, _core = \
            _setup_recycled_and_new_lots()
        order = create_confirmed_order(customer["id"], spec["id"], 1, "A")
        resp = api_client.allocate_order(
            order["id"], {"expected_order_version": order["version"]}, SALES)
        allocated = validate_success(resp)
        assert allocated["fulfillment_status"] == "ALLOCATED"
        lines = list_order_lines(order["id"])
        assert len(lines) == 1
        assert lines[0]["allocated_lot_id"] == recycled["id"], (
            f"recycle-first policy must pick the RECYCLED_REPAIR lot "
            f"{recycled['id']} over the NEW_BUILD lot {new_lot['id']}, "
            f"got {lines[0]['allocated_lot_id']}"
        )
        chosen = get_lot(lines[0]["allocated_lot_id"])
        assert chosen["origin_type"] == "RECYCLED_REPAIR"


class TestRepairToDepletionCascade:

    def test_repair_completion_creates_recycled_lot_consumable_by_allocation(self):
        """PRD §3.4: "When the outcome is `A` or `B`, the core's
        `processing_status` becomes `REPAIRED` and the system creates a new
        recycled **InventoryLot**: `origin_type` `RECYCLED_REPAIR`,
        `quality_grade` equal to the certified outcome, `quantity_total` of
        one, and its spec resolved from the work order's `target_spec_id`."

        Design: Difficulty/transitive_cascade/repair_completion_to_lot_depletion_cascade
        """
        spec, recycled, _new_lot, customer, core = _setup_recycled_and_new_lots()
        core_after = get_core(core["id"])
        assert core_after["processing_status"] == "REPAIRED"
        assert recycled["origin_type"] == "RECYCLED_REPAIR"
        assert recycled["quality_grade"] == "A"
        assert recycled["quantity_total"] == 1
        assert recycled["spec_id"] == spec["id"]
        # Only the A-grade lot is consumable by an A-grade order line.
        order = create_confirmed_order(customer["id"], spec["id"], 1, "A")
        resp = api_client.allocate_order(
            order["id"], {"expected_order_version": order["version"]}, SALES)
        allocated = validate_success(resp)
        lines = list_order_lines(order["id"])
        assert lines[0]["allocated_lot_id"] == recycled["id"]

    def test_allocation_of_recycled_lot_auto_depletes_it(self):
        """PRD §3.5: "When an allocation drains `quantity_available` to zero,
        the lot automatically transitions to `DEPLETED` and drops out of the
        allocation selector."
        PRD §3.5: "Lots are born `AVAILABLE`, with `quantity_available` — a
        read-only figure equal to `quantity_total` minus the sum of active
        reservations against the lot — starting equal to `quantity_total`."

        Design: Difficulty/transitive_cascade/repair_completion_to_lot_depletion_cascade
        """
        spec, recycled, _new_lot, customer, _core = _setup_recycled_and_new_lots()
        assert recycled["quantity_available"] == 1
        order = create_confirmed_order(customer["id"], spec["id"], 1, "A")
        allocate_resp = api_client.allocate_order(
            order["id"], {"expected_order_version": order["version"]}, SALES)
        validate_success(allocate_resp)
        lot_after = get_lot(recycled["id"])
        assert lot_after["quantity_available"] == 0, (
            f"the single-unit lot must drain to 0, "
            f"got {lot_after['quantity_available']}"
        )
        assert lot_after["status"] == "DEPLETED", (
            f"lot must auto-transition to DEPLETED at zero availability, "
            f"got {lot_after['status']}"
        )
