"""Production-order scheduling: spec-state gate, overlap vs credit priority, changeover buffer semantics, credit limit, labeler fit, slot cancellation, order filters, and OCC on order version."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    create_customer, create_line, create_spec, submit_spec, begin_qualification,
    create_qualification_run, execute_run, submit_review, review_run,
    create_draft_order, schedule_order, schedule_order_payload,
    setup_qualified_plant, setup_scheduled_order, create_lot, install_mold,
    list_order_slots, get_order,
    api_client, ApiErrorId, TEST_USERS,
)

SCHEDULER = TEST_USERS["production_scheduler"]
ENGINEER = TEST_USERS["process_engineer"]


def _setup_spec_in_qualification(api):
    """Spec IN_QUALIFICATION (run in CUSTOMER_REVIEW) + line + DRAFT order."""
    customer = create_customer()
    line = create_line()
    spec = create_spec(customer["id"])
    submit_spec(spec["id"])
    begin = begin_qualification(spec["id"])
    qrun = create_qualification_run(spec["id"], begin["version"])
    execute_run(qrun["id"])
    submit_review(qrun["id"])
    order = create_draft_order(spec["id"])
    return customer, line, spec, qrun, order


class TestScheduleRequiresQualifiedSpec:
    def test_schedule_rejected_while_spec_in_qualification(self, api):
        """PRD §3.5: "In both cases the spec must be `QUALIFIED` or `PRODUCTION_ACTIVE`, else `ERR_SPEC_NOT_QUALIFIED`."

Design: Difficulty/cross_entity_state_dependency/schedule_requires_qualified_spec"""
        _, line, spec, _, order = _setup_spec_in_qualification(api)
        spec_now = get_success_data(api.get_bottle_spec(spec["id"], ENGINEER))
        assert spec_now["status"] == "IN_QUALIFICATION"
        res = api.schedule_production_order(
            order["id"],
            schedule_order_payload(line["id"], "2026-08-02T10:00:00Z",
                                   "2026-08-02T14:00:00Z", order["version"]),
            SCHEDULER)
        validate_error(res, ApiErrorId.ERR_SPEC_NOT_QUALIFIED)

    def test_schedule_after_approval_activates_spec(self, api):
        """PRD §3.2/§3.5: "The first successful schedule against a `QUALIFIED` spec quietly advances the spec to `PRODUCTION_ACTIVE`." "A successful schedule creates a ScheduleSlot in `CONFIRMED` for the order and line".

Design: Difficulty/cross_entity_state_dependency/schedule_requires_qualified_spec"""
        customer, line, spec, qrun, order = _setup_spec_in_qualification(api)
        review_run(qrun["id"], "APPROVE", customer["id"])
        scheduled = schedule_order(order, line["id"])
        assert scheduled["status"] == "SCHEDULED"
        slots = list_order_slots(order["id"])
        assert len(slots) == 1 and slots[0]["status"] == "CONFIRMED"
        spec_after = get_success_data(api.get_bottle_spec(spec["id"], ENGINEER))
        assert spec_after["status"] == "PRODUCTION_ACTIVE"


class TestOverlapVersusCredit:
    def _setup_credit_pair(self, api):
        """Customer with a 30000-cent limit; order1 SCHEDULED (27000 cents of exposure at 9 cents/unit x 3000 units); order2 DRAFT for the same."""
        ctx = setup_qualified_plant(customer_overrides={"credit_limit_cents": 30000})
        order1 = setup_scheduled_order(ctx, order_overrides={"quantity_ordered": 3000})
        assert order1["status"] == "SCHEDULED"
        order2 = create_draft_order(ctx["spec"]["id"])
        return ctx, order1, order2

    def test_overlap_error_masks_credit_error(self, api):
        """PRD §2.9: "a failure at an earlier stage masks every later stage" — "seventh temporal rules (schedule overlap, dock window conflicts, dock load timing, no-show timing)" — "and tenth fiscal rules (customer credit, material sufficiency, accepted stock)".

Design: Difficulty/priority_pair_validation_conflict/schedule_overlap_before_credit"""
        ctx, _, order2 = self._setup_credit_pair(api)
        # [12:00,16:00) overlaps order1's [10:00,14:00) AND pushes exposure to
        # 54000 > 30000; the temporal error must win.
        res = api.schedule_production_order(
            order2["id"],
            schedule_order_payload(ctx["line"]["id"], "2026-08-02T12:00:00Z",
                                   "2026-08-02T16:00:00Z", order2["version"]),
            SCHEDULER)
        validate_error(res, ApiErrorId.ERR_SCHEDULE_OVERLAP)

    def test_credit_error_surfaces_when_temporal_passes(self, api):
        """PRD §3.5: "the sum over the customer's orders in `SCHEDULED`, `RELEASED`, `RUNNING`, or `HELD` of each order's `quantity_ordered` multiplied by its spec's `unit_price_cents`, plus the value of the order being scheduled, must be less than or equal to the customer's `credit_limit_cents` — equality is allowed — else the schedule is refused with `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402)."

Design: Difficulty/priority_pair_validation_conflict/schedule_overlap_before_credit"""
        ctx, _, order2 = self._setup_credit_pair(api)
        # half-open adjacency with identical (absent) mold snapshots needs no
        # buffer, so only the fiscal rule can fail.
        res = api.schedule_production_order(
            order2["id"],
            schedule_order_payload(ctx["line"]["id"], "2026-08-02T14:00:00Z",
                                   "2026-08-02T16:00:00Z", order2["version"]),
            SCHEDULER)
        validate_error(res, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)


class TestChangeoverBuffer:
    def _setup_two_orders_with_mold_installed_late(self, api):
        """order1 scheduled while NO mold is installed (null mold snapshot); the mold is installed afterwards, so order2's snapshot differs."""
        ctx = setup_qualified_plant()
        order1 = setup_scheduled_order(ctx)  # slot snapshots mold_id = null
        ctx["mold"] = install_mold(ctx["mold"]["id"], ctx["line"]["id"])
        order2 = create_draft_order(ctx["spec"]["id"])
        return ctx, order1, order2

    def test_adjacent_slot_with_different_mold_snapshot_rejected(self, api):
        """PRD §3.5: "the gap to each adjacent slot must be at least the mold-change buffer: zero minutes when both slots carry the same `mold_id` snapshot, ninety minutes otherwise". "Violations surface as `ERR_SCHEDULE_OVERLAP`."

Design: Difficulty/resource_temporal_overlap/schedule_slot_changeover_buffer_half_open"""
        ctx, _, order2 = self._setup_two_orders_with_mold_installed_late(api)
        res = api.schedule_production_order(
            order2["id"],
            schedule_order_payload(ctx["line"]["id"], "2026-08-02T14:00:00Z",
                                   "2026-08-02T16:00:00Z", order2["version"]),
            SCHEDULER)
        # gap 0 < 90-minute buffer (null vs installed mold snapshots differ)
        validate_error(res, ApiErrorId.ERR_SCHEDULE_OVERLAP)

    def test_gap_exactly_ninety_minutes_allowed(self, api):
        """PRD §3.5: "the gap to each adjacent slot must be at least the mold-change buffer: zero minutes when both slots carry the same `mold_id` snapshot, ninety minutes otherwise".

Design: Difficulty/resource_temporal_overlap/schedule_slot_changeover_buffer_half_open"""
        ctx, _, order2 = self._setup_two_orders_with_mold_installed_late(api)
        scheduled = schedule_order(order2, ctx["line"]["id"],
                                   planned_start="2026-08-02T15:30:00Z",
                                   planned_end="2026-08-02T17:30:00Z")
        # gap exactly 90 minutes == the buffer; "at least" is inclusive
        assert scheduled["status"] == "SCHEDULED"


class TestCreditLimit:
    def test_credit_limit_exceeded_pure(self, api):
        """PRD §3.5: "the sum over the customer's orders in `SCHEDULED`, `RELEASED`, `RUNNING`, or `HELD` of each order's `quantity_ordered` multiplied by its spec's `unit_price_cents`, plus the value of the order being scheduled, must be less than or equal to the customer's `credit_limit_cents` — equality is allowed — else the schedule is refused with `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402)."

Design: Corner/validations/credit_limit_exceeded_pure"""
        ctx = setup_qualified_plant(customer_overrides={"credit_limit_cents": 30000})
        setup_scheduled_order(ctx, order_overrides={"quantity_ordered": 3000})
        order2 = create_draft_order(ctx["spec"]["id"])
        res = api.schedule_production_order(
            order2["id"],
            schedule_order_payload(ctx["line"]["id"], "2026-08-02T14:00:00Z",
                                   "2026-08-02T16:00:00Z", order2["version"]),
            SCHEDULER)
        validate_error(res, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)


class TestEquipmentFit:
    def test_labeler_required_blocks_schedule(self, api):
        """PRD §3.5: "a spec whose `requires_inline_labeler` is true demands a line whose `has_inline_labeler` is true, and the spec's `diameter_mm` must not exceed the line's `max_bottle_diameter_mm` — either failure is `ERR_LABELER_REQUIRED`."
PRD §3.2: "the server derives `requires_inline_labeler`, which is true exactly when `label_type` is anything other than `NONE`."

Design: Corner/validations/labeler_required_blocks_schedule"""
        ctx = setup_qualified_plant(
            line_overrides={"line_code": "L-NOLAB", "has_inline_labeler": False},
            spec_overrides={"label_type": "SHRINK_SLEEVE"})
        order = create_draft_order(ctx["spec"]["id"])
        res = api.schedule_production_order(
            order["id"],
            schedule_order_payload(ctx["line"]["id"], "2026-08-02T10:00:00Z",
                                   "2026-08-02T14:00:00Z", order["version"]),
            SCHEDULER)
        validate_error(res, ApiErrorId.ERR_LABELER_REQUIRED)


class TestPlannedWeightTolerance:
    def test_planned_weight_out_of_tolerance_rejected(self, api):
        """PRD §3.5: "The planned weight must sit inside the spec's tolerance band — the absolute difference between `planned_weight_g` and the spec's `target_weight_g` no greater than `target_weight_g` times `weight_tolerance_pct` over 100 — or the create is refused with `ERR_PLANNED_WEIGHT_OUT_OF_TOLERANCE`."

Design: Corner/validations/planned_weight_out_of_tolerance_rejected"""
        customer = create_customer()
        spec = create_spec(customer["id"], label_type="NONE")
        res = api.create_production_order(
            {"bottle_spec_id": spec["id"], "quantity_ordered": 3000,
             "planned_weight_g": 23.0},
            SCHEDULER)
        # |23.0 - 22| = 1.0 > 22 * 2.0 / 100 = 0.44
        validate_error(res, ApiErrorId.ERR_PLANNED_WEIGHT_OUT_OF_TOLERANCE)


class TestOrderFilters:
    def test_production_orders_filter_by_status(self, api):
        """PRD §3.5: "The order list supports filtering by `customer_id`, `bottle_spec_id`, or `status`."

Design: Corner/endpoints/production_orders_filter_by_status"""
        ctx = setup_qualified_plant()
        order1 = setup_scheduled_order(
            ctx, order_overrides={"quantity_ordered": 1000},
            planned_end="2026-08-02T12:00:00Z")
        order2 = create_draft_order(ctx["spec"]["id"], quantity_ordered=500)

        data, meta = validate_paginated(
            api.list_production_orders(SCHEDULER, params={"status": "SCHEDULED"}))
        assert meta["total_count"] == 1
        assert [o["id"] for o in data] == [order1["id"]]

        data, meta = validate_paginated(
            api.list_production_orders(SCHEDULER, params={"status": "DRAFT"}))
        assert meta["total_count"] == 1
        assert [o["id"] for o in data] == [order2["id"]]


class TestSlotCancelBlocksRelease:
    def test_release_without_confirmed_slot_fails(self, api):
        """PRD §3.5: "Releasing requires the order `SCHEDULED` with a `CONFIRMED` slot in place — without one the release fails with `ERR_NO_ACTIVE_SLOT`". A slot "can be cancelled from `CONFIRMED` by a `ProductionScheduler`".

Design: Corner/endpoints/slot_cancel_blocks_release"""
        ctx = setup_qualified_plant()
        order = setup_scheduled_order(ctx)
        create_lot(release=True)  # material gate satisfied; only slot missing
        slots = list_order_slots(order["id"])
        assert len(slots) == 1
        cancelled = validate_success(
            api.cancel_schedule_slot(slots[0]["id"], SCHEDULER), 200)
        assert cancelled["status"] == "CANCELLED"
        res = api.release_production_order(order["id"], SCHEDULER)
        validate_error(res, ApiErrorId.ERR_NO_ACTIVE_SLOT)
        order_after = get_order(order["id"])
        assert order_after["status"] == "SCHEDULED"


class TestOccOnOrderVersion:
    def test_stale_order_version_rejected_on_reslot(self, api):
        """PRD §2.7: "Scheduling a production order, including re-slotting an already `SCHEDULED` order onto a new window, requires `expected_production_order_version` matching the order's current `version`", and "a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412)".

Design: Corner/cross_cutting_layers/occ_schedule_stale_version_rejected"""
        ctx = setup_qualified_plant()
        order = create_draft_order(ctx["spec"]["id"])
        stale_version = order["version"]
        scheduled = schedule_order(order, ctx["line"]["id"])
        assert scheduled["status"] == "SCHEDULED"

        res = api.schedule_production_order(
            order["id"],
            schedule_order_payload(ctx["line"]["id"], "2026-08-03T10:00:00Z",
                                   "2026-08-03T14:00:00Z", stale_version),
            SCHEDULER)
        validate_error(res, ApiErrorId.ERR_STALE_VERSION)

    def test_reslot_with_current_version_supersedes_slot(self, api):
        """PRD §3.5: "the same action re-slots an order already `SCHEDULED`, legitimately superseding its prior window". "Re-slotting a `SCHEDULED` order first cancels its prior `CONFIRMED` slots, then writes the new one."

Design: Corner/cross_cutting_layers/occ_schedule_stale_version_rejected"""
        ctx = setup_qualified_plant()
        order = setup_scheduled_order(ctx)
        fresh = get_order(order["id"])
        reslot = schedule_order(fresh, ctx["line"]["id"],
                                planned_start="2026-08-03T10:00:00Z",
                                planned_end="2026-08-03T14:00:00Z")
        assert reslot["status"] == "SCHEDULED"
        slots = list_order_slots(order["id"])
        by_status = sorted((s["status"], s["planned_start"]) for s in slots)
        assert len(slots) == 2, f"expected old+new slots, got {by_status}"
        cancelled = [s for s in slots if s["status"] == "CANCELLED"]
        confirmed = [s for s in slots if s["status"] == "CONFIRMED"]
        assert len(cancelled) == 1 and len(confirmed) == 1
        assert confirmed[0]["planned_start"].startswith("2026-08-03")
