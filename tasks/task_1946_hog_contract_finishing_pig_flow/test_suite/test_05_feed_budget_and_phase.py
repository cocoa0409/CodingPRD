"""Feed ordering: the lifetime hard budget vs the phase-plan advisory flag,
phase advancement cascade, delivery variance branch, and read consistency.
"""
from test_helpers import (
    ApiErrorId,
    assert_feed_order,
    assert_head_reconciliation_pre_close,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import create_feed_order_payload
from test_helpers.fixtures import (
    FIELDTECH,
    confirm_group,
    create_and_deliver_feed,
    create_barn,
    create_feed_order,
    create_scheduled_group,
    deliver_feed,
    get_group,
    report_mortality,
    schedule_feed,
    setup_contract_with_barn,
    setup_placed_group,
)

GROUP_1000 = {"head_placed": 1000}  # lifetime feed budget = 1000 * 650 = 650000


def _setup_group_with_280000_delivered(api):
    """PLACED 1000-head group with 90000 STARTER + 190000 GROWER lbs delivered;
    feed phase now GROWER. Hard remaining 370000, phase-plan remaining 5000."""
    ctx = setup_placed_group(head_placed=1000)
    group_id = ctx["group"]["id"]
    create_and_deliver_feed(group_id, 90000)  # STARTER, default dates
    get_success_data(api.advance_phase(group_id, FIELDTECH))
    create_and_deliver_feed(
        group_id, 190000, phase="GROWER", diet_code="GR-1",
        req_date="2026-04-01", sched_date="2026-04-01",
    )
    ctx["group"] = get_group(group_id)
    return ctx


class TestDualVariantBudget:
    def test_hard_cap_allows_order_that_phase_plan_flags(self, api):
        """PRD §3.3: "The hard remainder is the budget minus both drawdowns, and
        a new order whose `quantity_lbs` exceeds the hard remainder is rejected
        with `ERR_FEED_BUDGET_EXCEEDED` — a whole-budget gate on chronological,
        actual grounds."
        PRD §3.3: "A phase remainder is that allotment minus the phase's own
        committed and delivered pounds, and when a new order's `quantity_lbs`
        exceeds its phase remainder, the created order is flagged with
        `over_phase_plan` set to true."
        PRD §3.3: "Each phase is allotted a fixed share of the whole lifetime
        budget — fifteen percent for `STARTER`, thirty percent for `GROWER`,
        thirty percent for `FINISHER_1`, and twenty-five percent for
        `FINISHER_2` — with each allotment rounded half-up to a whole pound."

        Hard remaining = 650000 - 280000 = 370000 permits 10000 lbs, while the
        GROWER phase plan (195000 - 190000 = 5000) is exceeded: the two budget
        algorithms disagree on one order.

        Design: Difficulty/dual_variant_calc/feed_hard_cap_vs_phase_plan_divergence
        """
        ctx = _setup_group_with_280000_delivered(api)
        group_id = ctx["group"]["id"]

        res = api.create_feed_order(
            create_feed_order_payload(
                group_id, phase="GROWER", diet_code="GR-1", quantity_lbs=10000,
                requested_delivery_date="2026-04-10",
            ),
            FIELDTECH,
        )
        order = validate_success(res, 201)
        assert_feed_order(order)
        assert order["order_status"] == "REQUESTED"
        assert order["over_phase_plan"] is True

        group = get_group(group_id)
        assert group["cumulative_feed_lbs"] == 280000

    def test_hard_cap_boundary_exact_fit_then_one_over(self, api):
        """PRD §3.3: "The hard remainder is the budget minus both drawdowns, and
        a new order whose `quantity_lbs` exceeds the hard remainder is rejected
        with `ERR_FEED_BUDGET_EXCEEDED` — a whole-budget gate on chronological,
        actual grounds."

        370000 lbs lands exactly on the hard remainder and is accepted; one
        more pound exceeds it and is rejected.

        Design: Difficulty/dual_variant_calc/feed_hard_cap_vs_phase_plan_divergence
        """
        ctx = _setup_group_with_280000_delivered(api)
        group_id = ctx["group"]["id"]

        exact = validate_success(
            api.create_feed_order(
                create_feed_order_payload(
                    group_id, phase="GROWER", diet_code="GR-1",
                    quantity_lbs=370000, requested_delivery_date="2026-04-10",
                ),
                FIELDTECH,
            ),
            201,
        )
        assert exact["order_status"] == "REQUESTED"
        assert exact["over_phase_plan"] is True

        res = api.create_feed_order(
            create_feed_order_payload(
                group_id, phase="GROWER", diet_code="GR-1", quantity_lbs=1,
                requested_delivery_date="2026-04-10",
            ),
            FIELDTECH,
        )
        validate_error(res, ApiErrorId.ERR_FEED_BUDGET_EXCEEDED, expected_status=409)


class TestPhaseCascade:
    def test_advance_phase_cancels_old_phase_orders(self, api):
        """PRD §3.3: "Advancing the phase has a deliberate casualty: every feed
        order of the group still `REQUESTED` or `SCHEDULED` for the phase being
        left behind is automatically cancelled, releasing its committed budget."

        Design: Corner/state_machines/advance_phase_cancels_old_phase_orders
        """
        ctx = setup_placed_group(head_placed=1000)
        group_id = ctx["group"]["id"]
        o1 = create_feed_order(group_id, quantity_lbs=30000,
                               requested_delivery_date="2026-03-05")
        o2 = create_feed_order(group_id, quantity_lbs=40000,
                               requested_delivery_date="2026-03-06")
        schedule_feed(o2["id"], "2026-03-06")
        assert o1["order_status"] == "REQUESTED"

        advanced = validate_success(api.advance_phase(group_id, FIELDTECH), 200)
        assert advanced["current_phase"] == "GROWER"

        o1_after = validate_success(api.get_feed_order(o1["id"], FIELDTECH), 200)
        o2_after = validate_success(api.get_feed_order(o2["id"], FIELDTECH), 200)
        assert o1_after["order_status"] == "CANCELLED"
        assert o2_after["order_status"] == "CANCELLED"

        # The released 70000 committed lbs no longer stand against the budget:
        # a GROWER order of 190000 fits the intact 650000-lb hard budget.
        o3 = create_feed_order(group_id, phase="GROWER", diet_code="GR-1",
                               quantity_lbs=190000,
                               requested_delivery_date="2026-03-10")
        assert o3["order_status"] == "REQUESTED"

    def test_phase_mismatch_rejected(self, api):
        """PRD §3.3: "The `phase` on the order must equal the group's
        `current_phase` — a mismatch is rejected with `ERR_PHASE_MISMATCH`."

        Design: Corner/errors/phase_mismatch_rejected
        """
        ctx = setup_placed_group(head_placed=1000)
        group_id = ctx["group"]["id"]
        res = api.create_feed_order(
            create_feed_order_payload(
                group_id, phase="GROWER", diet_code="GR-1", quantity_lbs=10000,
                requested_delivery_date="2026-03-05",
            ),
            FIELDTECH,
        )
        validate_error(res, ApiErrorId.ERR_PHASE_MISMATCH, expected_status=409)
        _data, meta = validate_paginated(
            api.list_feed_orders(FIELDTECH, params={"group_id": group_id})
        )
        assert meta["total_count"] == 0


class TestFeedDeliveryVariance:
    def test_feed_deliver_variance_branch_80pct(self, api):
        """PRD §3.3: "Delivering at least eighty percent of the ordered
        `quantity_lbs` closes the order as `DELIVERED`; delivering less than
        eighty percent closes it as `SHORTED`. Either way, the delivered pounds
        accumulate into the group's `cumulative_feed_lbs`."

        8000 of 10000 is exactly 80% and delivers; 7999 is shorted.

        Design: Corner/calculations/feed_deliver_variance_branch_80pct
        """
        ctx = setup_placed_group(head_placed=1000)
        group_id = ctx["group"]["id"]
        o1 = create_feed_order(group_id, quantity_lbs=10000,
                               requested_delivery_date="2026-03-05")
        schedule_feed(o1["id"], "2026-03-05")
        o2 = create_feed_order(group_id, quantity_lbs=10000,
                               requested_delivery_date="2026-03-06")
        schedule_feed(o2["id"], "2026-03-06")

        d1 = deliver_feed(o1["id"], 8000)
        assert d1["order_status"] == "DELIVERED"
        d2 = deliver_feed(o2["id"], 7999)
        assert d2["order_status"] == "SHORTED"

        group = get_group(group_id)
        assert group["cumulative_feed_lbs"] == 15999

    def test_terminal_transitions_rejected(self, api):
        """PRD §3.3: "Every group starts its feed dimension in `STARTER` and may
        advance one step at a time — `STARTER` → `GROWER`, `GROWER` →
        `FINISHER_1`, `FINISHER_1` → `FINISHER_2`" — no step exists beyond
        `FINISHER_2`.
        PRD §3.3: "A `FieldTech` may cancel an order while it is still
        `REQUESTED` or `SCHEDULED`, moving it to `CANCELLED`".
        PRD §2.6: "State validity. The target resource must sit in a legal
        from-state for the requested transition; failures surface as
        `ERR_INVALID_STATE_TRANSITION` or one of its domain variants".

        Design: Corner/errors/terminal_transitions_rejected
        """
        ctx = setup_placed_group(head_placed=1000)
        group_id = ctx["group"]["id"]
        for _ in range(3):
            get_success_data(api.advance_phase(group_id, FIELDTECH))
        assert get_group(group_id)["current_phase"] == "FINISHER_2"

        res = api.advance_phase(group_id, FIELDTECH)
        validate_error(
            res, ApiErrorId.ERR_INVALID_STATE_TRANSITION, expected_status=409
        )

        order = create_feed_order(
            group_id, phase="FINISHER_2", diet_code="F2-1", quantity_lbs=10000,
            requested_delivery_date="2026-03-05",
        )
        schedule_feed(order["id"], "2026-03-05")
        delivered = deliver_feed(order["id"], 10000)
        assert delivered["order_status"] == "DELIVERED"

        res = api.cancel_feed_order(order["id"], FIELDTECH)
        validate_error(
            res, ApiErrorId.ERR_INVALID_STATE_TRANSITION, expected_status=409
        )


class TestCancelReleasesBudget:
    def test_feed_cancel_releases_committed_budget(self, api):
        """PRD §3.3: "A `FieldTech` may cancel an order while it is still
        `REQUESTED` or `SCHEDULED`, moving it to `CANCELLED`; cancellation
        releases the order's committed pounds back into the budget, because the
        order leaves the committed set."

        Design: Corner/endpoints/feed_cancel_releases_committed_budget
        """
        ctx = setup_placed_group(head_placed=1000)
        group_id = ctx["group"]["id"]
        o1 = create_feed_order(group_id, quantity_lbs=50000,
                               requested_delivery_date="2026-03-05")

        # 50000 committed + 640000 new > 650000 budget: rejected.
        res = api.create_feed_order(
            create_feed_order_payload(
                group_id, quantity_lbs=640000,
                requested_delivery_date="2026-03-06",
            ),
            FIELDTECH,
        )
        validate_error(res, ApiErrorId.ERR_FEED_BUDGET_EXCEEDED, expected_status=409)

        cancelled = validate_success(api.cancel_feed_order(o1["id"], FIELDTECH), 200)
        assert cancelled["order_status"] == "CANCELLED"

        # With the commitment released, the same order now fits; the phase
        # plan (97500 lbs for STARTER) is still exceeded — advisory only.
        o2 = create_feed_order(group_id, quantity_lbs=640000,
                               requested_delivery_date="2026-03-06")
        assert o2["order_status"] == "REQUESTED"
        assert o2["over_phase_plan"] is True


class TestStateVsFiscalPriority:
    def test_state_beats_fiscal_on_cancelled_group(self, api):
        """PRD §2.6: "Every mutating request is validated against a fixed
        cascade of checks, and the first failing check determines the error
        returned — later checks are not evaluated for that request."
        PRD §2.6: "12. **Fiscal budgets, always last.** Feed budget
        (`ERR_FEED_BUDGET_EXCEEDED`), slot head capacity
        (`ERR_SLOT_CAPACITY_EXCEEDED`), ...".
        PRD §3.3: "Feed orders are placed by a `FieldTech` against a group that
        is `PLACED` or `MARKETING` (`ERR_GROUP_NOT_ACTIVE` otherwise)".

        One request violates both the state gate (group CANCELLED) and the
        fiscal gate (999999999 lbs): the state check reports first.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_feed_order_on_cancelled_group
        """
        ctx = setup_contract_with_barn()
        group = create_scheduled_group(
            ctx["barn"]["id"], ctx["contract"]["id"], head_placed=1000
        )
        get_success_data(api.cancel_pig_group(group["id"], FIELDTECH))

        res = api.create_feed_order(
            create_feed_order_payload(
                group["id"], quantity_lbs=999999999,
                requested_delivery_date="2026-03-05",
            ),
            FIELDTECH,
        )
        validate_error(res, ApiErrorId.ERR_GROUP_NOT_ACTIVE, expected_status=409)

    def test_state_and_fiscal_each_fire_in_isolation(self, api):
        """PRD §3.3: "Feed orders are placed by a `FieldTech` against a group
        that is `PLACED` or `MARKETING` (`ERR_GROUP_NOT_ACTIVE` otherwise)".
        PRD §3.3: "The hard remainder is the budget minus both drawdowns, and a
        new order whose `quantity_lbs` exceeds the hard remainder is rejected
        with `ERR_FEED_BUDGET_EXCEEDED` — a whole-budget gate on chronological,
        actual grounds."

        Complementary isolation: an in-budget order against the cancelled group
        still reports the state failure; an over-budget order against a placed
        group reports the fiscal failure.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_feed_order_on_cancelled_group
        """
        ctx = setup_contract_with_barn()
        barn2 = create_barn(ctx["site"]["id"], barn_code="B2")
        group1 = create_scheduled_group(
            ctx["barn"]["id"], ctx["contract"]["id"], head_placed=1000
        )
        get_success_data(api.cancel_pig_group(group1["id"], FIELDTECH))
        group2 = create_scheduled_group(
            barn2["id"], ctx["contract"]["id"], head_placed=1000
        )
        confirm_group(group2["id"])

        # State failure alone (in-budget quantity on a CANCELLED group).
        res = api.create_feed_order(
            create_feed_order_payload(
                group1["id"], quantity_lbs=1000,
                requested_delivery_date="2026-03-05",
            ),
            FIELDTECH,
        )
        validate_error(res, ApiErrorId.ERR_GROUP_NOT_ACTIVE, expected_status=409)

        # Fiscal failure alone (650001 > 650000 budget on a PLACED group).
        res = api.create_feed_order(
            create_feed_order_payload(
                group2["id"], quantity_lbs=650001,
                requested_delivery_date="2026-03-05",
            ),
            FIELDTECH,
        )
        validate_error(res, ApiErrorId.ERR_FEED_BUDGET_EXCEEDED, expected_status=409)


class TestImmediateConsistency:
    def test_immediate_read_after_write_consistency(self, api):
        """PRD §2.8: "Every mutation, together with all of its cascading side
        effects, commits atomically within its request — a client never
        observes a half-applied cascade."
        PRD §3.3: "Either way, the delivered pounds accumulate into the group's
        `cumulative_feed_lbs`."
        PRD §3.4: "Before close, the `head_placed` must always equal the sum of
        `head_current`, `mortality_total`, `cull_total`, and `head_marketed`".

        Design: Corner/consistency_model/immediate_read_after_write_consistency
        """
        ctx = setup_placed_group(head_placed=1000)
        group_id = ctx["group"]["id"]

        create_and_deliver_feed(group_id, 40000)
        report_mortality(
            group_id, ctx["grower"]["id"], "2026-03-06", 5, cull_count=2,
            reason_code="STRESS", clock="2026-03-06T00:00:00Z",
        )

        group = get_group(group_id)
        assert group["cumulative_feed_lbs"] == 40000
        assert group["mortality_total"] == 5
        assert group["cull_total"] == 2
        assert group["head_current"] == 993
        assert_head_reconciliation_pre_close(group)
