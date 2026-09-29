"""
The workflow-side rungs of the rejection order: shrink-period geometry, the two
vendor-money preconditions, the tag-integrity quarantine outranking the approval
gate, the per-task line uniqueness, the two entry points of the open-investigation
guard, the physical-inventory recount gate and the investigation state guard.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_ADJUSTMENT_APPROVAL_REQUIRED,
    ERR_CREDIT_EXCEEDS_BALANCE,
    ERR_DUPLICATE_COUNT_LINE,
    ERR_INVALID_PERIOD_RANGE,
    ERR_INVESTIGATION_INVALID_STATE,
    ERR_NO_COVERING_SHRINK_PERIOD,
    ERR_NO_VENDOR_SHORTAGE,
    ERR_OPEN_INVESTIGATIONS,
    ERR_RECOUNT_REQUIRED,
    ERR_SHRINK_PERIOD_OVERLAP,
    ERR_TAG_INTEGRITY_HOLD,
)
from test_helpers.assertions import (
    assert_adjustment_dimensions,
    assert_units_conserved,
    assert_vendor_ledger_identity,
)
from test_helpers.test_users import (
    ADMIN,
    ANALYST,
    CONTROLLER,
    SUPERVISOR,
)


class TestShrinkPeriodGeometry:
    def test_a_single_shared_endpoint_day_is_an_overlap(self, api):
        """
        Inclusive ranges collide on one shared calendar date.

        "Periods for one store may not overlap: if any existing period for the same
        store has an inclusive date range that intersects the requested one, the
        creation is rejected with `ERR_SHRINK_PERIOD_OVERLAP`. Sharing a single
        endpoint date counts as an intersection."

        Design: Corner/errors/shrink_period_overlap_and_inverted_range_rejected
        """
        store = fx.create_store(api, f.store_payload())
        incumbent = fx.create_shrink_period(api, store["id"])
        assert incumbent["period_start"] == "2026-07-01"
        assert incumbent["period_end"] == "2026-09-30"

        validate_error(
            api.create_shrink_period(
                f.shrink_period_payload(
                    store["id"],
                    period_start="2026-09-30",
                    period_end="2026-12-31",
                    sales_at_cost_cents=4000000,
                ),
                CONTROLLER,
            ),
            ERR_SHRINK_PERIOD_OVERLAP,
            409,
        )

        rows, meta = validate_paginated(
            api.list_shrink_periods(CONTROLLER, {"store_id": store["id"]})
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == incumbent["id"]

    def test_the_constraint_is_per_store_and_adjacency_is_legal(self, api):
        """
        A second store, and the very next day, are both free.

        "Periods for one store may not overlap: if any existing period for the same
        store has an inclusive date range that intersects the requested one, the
        creation is rejected with `ERR_SHRINK_PERIOD_OVERLAP`. Sharing a single
        endpoint date counts as an intersection."

        Design: Corner/errors/shrink_period_overlap_and_inverted_range_rejected
        """
        store = fx.create_store(api, f.store_payload())
        other_store = fx.create_store(api, f.handheld_only_store_payload())
        fx.create_shrink_period(api, store["id"])

        elsewhere = validate_success(
            api.create_shrink_period(
                f.shrink_period_payload(
                    other_store["id"],
                    period_start="2026-09-30",
                    period_end="2026-12-31",
                    sales_at_cost_cents=4000000,
                ),
                CONTROLLER,
            ),
            201,
        )
        assert elsewhere["store_id"] == other_store["id"]
        assert elsewhere["status"] == "OPEN"

        adjacent = validate_success(
            api.create_shrink_period(
                f.shrink_period_payload(
                    store["id"],
                    period_start="2026-10-01",
                    period_end="2026-12-31",
                    sales_at_cost_cents=4000000,
                ),
                CONTROLLER,
            ),
            201,
        )
        assert adjacent["period_start"] == "2026-10-01"

        rows, meta = validate_paginated(
            api.list_shrink_periods(CONTROLLER, {"store_id": store["id"]})
        )
        assert meta["total_count"] == 2

    def test_an_inverted_shrink_period_range_is_rejected(self, api):
        """
        The end date may not precede the start date.

        "The two dates are calendar dates in `YYYY-MM-DD` form and the range is
        inclusive at both ends; `period_end` must be on or after `period_start`, and an
        inverted range is rejected with `ERR_INVALID_PERIOD_RANGE`."

        Design: Corner/errors/shrink_period_overlap_and_inverted_range_rejected
        """
        store = fx.create_store(api, f.store_payload())

        validate_error(
            api.create_shrink_period(
                f.shrink_period_payload(
                    store["id"],
                    period_start="2026-12-31",
                    period_end="2026-01-01",
                    sales_at_cost_cents=4000000,
                ),
                CONTROLLER,
            ),
            ERR_INVALID_PERIOD_RANGE,
            422,
        )

        rows, meta = validate_paginated(
            api.list_shrink_periods(CONTROLLER, {"store_id": store["id"]})
        )
        assert meta["total_count"] == 0

        same_day = validate_success(
            api.create_shrink_period(
                f.shrink_period_payload(
                    store["id"], period_start="2026-07-01", period_end="2026-07-01"
                ),
                CONTROLLER,
            ),
            201,
        )
        assert same_day["status"] == "OPEN"

    def test_an_inverted_physical_inventory_range_reports_the_same_identifier(self, api):
        """
        The scheduling window is guarded by the same range rule.

        "The two dates are calendar dates and `scheduled_end_date` must be on or after
        `scheduled_start_date`; an inverted range is rejected with
        `ERR_INVALID_PERIOD_RANGE`."

        Design: Corner/errors/shrink_period_overlap_and_inverted_range_rejected
        """
        store = fx.create_store(api, f.store_payload())
        firm = fx.create_counter_firm(api)

        validate_error(
            api.create_physical_inventory(
                f.physical_inventory_payload(
                    store["id"],
                    firm["id"],
                    scheduled_start_date="2026-09-12",
                    scheduled_end_date="2026-09-10",
                ),
                CONTROLLER,
            ),
            ERR_INVALID_PERIOD_RANGE,
            422,
        )

        rows, meta = validate_paginated(
            api.list_physical_inventories(CONTROLLER, {"store_id": store["id"]})
        )
        assert meta["total_count"] == 0

        accepted = validate_success(
            api.create_physical_inventory(
                f.physical_inventory_payload(store["id"], firm["id"]), CONTROLLER
            ),
            201,
        )
        assert accepted["status"] == "PLANNED"
        assert accepted["scheduled_start_date"] == "2026-09-10"


class TestVendorMoneyPreconditions:
    def test_a_period_with_no_vendor_shortage_cannot_be_charged(self, api):
        """
        A chargeback needs a closed vendor-shortage attribution behind it.

        "Step one aggregates the gross shortage attributable to this vendor: sum
        `variance_value_cents` over every investigation whose `shrink_period_id` is the
        named period, whose `status` is exactly `CLOSED`, whose `approved_root_cause` is
        exactly `VENDOR_SHORTAGE`, and whose originating count line references a SKU
        whose `primary_vendor_id` is the path vendor. Investigations in `CAUSE_APPROVED`
        are excluded — only a closed attribution supports a charge. Membership is by the
        `shrink_period_id` foreign key and includes every such row regardless of the
        period's own status, so a provisionally closed or finally closed period can still
        be charged against. If the sum is 0, the request is rejected with
        `ERR_NO_VENDOR_SHORTAGE`."

        Design: Corner/errors/chargeback_without_attributable_shortage_rejected
        """
        store = fx.create_store(api, f.store_payload())
        vendor = fx.create_vendor(api)
        period = fx.create_shrink_period(api, store["id"])
        assert period["status"] == "OPEN"
        assert period["vendor_shortage_cents"] == 0

        validate_error(
            api.create_chargeback(
                vendor["id"], f.chargeback_payload(period["id"]), CONTROLLER
            ),
            ERR_NO_VENDOR_SHORTAGE,
            409,
        )

        ledger = fx.read_vendor(api, vendor["id"])
        assert ledger["chargeback_balance_cents"] == 0
        assert ledger["lifetime_chargeback_gross_cents"] == 0
        assert ledger["credited_cents"] == 0
        assert_vendor_ledger_identity(ledger)

        unchanged = validate_success(api.get_shrink_period(period["id"], CONTROLLER))
        assert unchanged["chargeback_issued_vendor_ids"] == []

    def test_a_credit_against_a_zero_balance_is_rejected(self, api):
        """
        Neither leg of the money invariant may be opened out of thin air.

        "The credit may not exceed the vendor's current `chargeback_balance_cents`; an
        excess is rejected with `ERR_CREDIT_EXCEEDS_BALANCE`, and a credit exactly equal
        to the balance is allowed and drives it to 0."

        Design: Corner/errors/chargeback_without_attributable_shortage_rejected
        """
        vendor = fx.create_vendor(api)
        assert fx.read_vendor(api, vendor["id"])["chargeback_balance_cents"] == 0

        validate_error(
            api.create_chargeback_credit(
                vendor["id"], f.chargeback_credit_payload(1), CONTROLLER
            ),
            ERR_CREDIT_EXCEEDS_BALANCE,
            422,
        )

        ledger = fx.read_vendor(api, vendor["id"])
        assert ledger["credited_cents"] == 0
        assert ledger["chargeback_balance_cents"] == 0
        assert_vendor_ledger_identity(ledger)


class TestTagIntegrityHoldOutranksTheApprovalGate:
    @staticmethod
    def _held_position_with_a_pending_adjustment(api):
        """A quarantined position carrying one PENDING adjustment of -20 units."""
        world = fx.failed_verification_world(api, sampled=50, readable=48)
        assert world["failed_batch"]["read_rate_bps"] == 9600
        assert world["failed_batch"]["verification_outcome"] == "FAIL"
        assert world["failed_batch"]["status"] == "VERIFICATION_FAILED"
        assert fx.read_vendor(api, world["vendor_id"])["tag_compliance_score_bps"] == 8500

        held = fx.read_position(api, world["position_id"])
        assert held["tag_integrity_hold"] is True
        assert held["promising_state"] == "BLOCKED"

        adjustment = fx.create_adjustment(api, world["position_id"], -20)
        assert adjustment["value_impact_cents"] == 24680
        assert adjustment["authority_threshold_cents"] == 20000
        assert_adjustment_dimensions(
            adjustment, approval_state="PENDING", posting_state="UNPOSTED"
        )
        world["adjustment_id"] = adjustment["id"]
        return world

    def test_the_hold_is_reported_and_not_the_still_pending_approval(self, api):
        """
        A quarantined ledger may not be edited, whatever the approval says.

        "And the position's `tag_integrity_hold` must be false, otherwise
        `ERR_TAG_INTEGRITY_HOLD` — a position whose tag reads are untrustworthy is not a
        position whose ledger may be edited."

        Design: Corner/errors/adjustment_post_onto_a_tag_held_position_rejected
        """
        world = self._held_position_with_a_pending_adjustment(api)

        validate_error(
            api.post_adjustment(world["adjustment_id"], SUPERVISOR),
            ERR_TAG_INTEGRITY_HOLD,
            409,
        )

        position = fx.read_position(api, world["position_id"])
        assert position["tag_integrity_hold"] is True
        assert position["promising_state"] == "BLOCKED"
        assert position["on_hand_units"] == 100
        assert_units_conserved(position, [])
        assert_adjustment_dimensions(
            fx.read_adjustment(api, world["adjustment_id"]),
            approval_state="PENDING",
            posting_state="UNPOSTED",
        )

    def test_approval_does_not_clear_a_quarantine(self, api):
        """
        Only a passing verification clears the hold, and approval is not one.

        "Any stock position for the batch's destination store and SKU has its
        `tag_integrity_hold` cleared to false — this is the **only** way a hold is ever
        cleared — after which that position's `promising_state` is re-derived and then
        the store's `fulfillment_status` follows."

        Design: Corner/errors/adjustment_post_onto_a_tag_held_position_rejected
        """
        world = self._held_position_with_a_pending_adjustment(api)

        approved = validate_success(
            api.approve_adjustment(world["adjustment_id"], SUPERVISOR)
        )
        assert_adjustment_dimensions(
            approved, approval_state="APPROVED", posting_state="UNPOSTED"
        )

        validate_error(
            api.post_adjustment(world["adjustment_id"], SUPERVISOR),
            ERR_TAG_INTEGRITY_HOLD,
            409,
        )
        assert fx.read_position(api, world["position_id"])["on_hand_units"] == 100

    def test_a_passing_batch_clears_the_hold_and_lets_the_post_land(self, api):
        """
        The penalised band demands a larger sample, and a pass releases the ledger.

        "The sample band is a three-step ladder read off the vendor's score:
        `required_verification_sample_pct` is 5 when `tag_compliance_score_bps` is 9000
        or more, 10 when the score is 7500 or more but below 9000, and 20 when the score
        is below 7500. A vendor starting at a perfect 10000 who fails one verification
        drops to 8500 and therefore into the 10 percent band, so the next thousand-unit
        batch that vendor encodes will demand 100 sampled units rather than 50."

        Design: Corner/errors/adjustment_post_onto_a_tag_held_position_rejected
        """
        world = self._held_position_with_a_pending_adjustment(api)
        validate_success(api.approve_adjustment(world["adjustment_id"], SUPERVISOR))

        batch_b = validate_success(
            api.create_tag_batch(
                f.tag_batch_payload(
                    world["vendor_id"],
                    world["item_id"],
                    world["store_id"],
                    quantity_encoded=1000,
                ),
                world["vendor_headers"],
            ),
            201,
        )
        encoded_b = validate_success(
            api.encode_tag_batch(
                batch_b["id"], f.encode_payload(), world["vendor_headers"]
            )
        )
        assert encoded_b["required_sample_units"] == 100
        validate_success(api.receive_tag_batch(batch_b["id"], world["store_headers"]))

        passed = validate_success(
            api.verify_tag_batch(
                batch_b["id"],
                f.verify_payload(sampled_units=100, readable_units=100),
                world["store_headers"],
            )
        )
        assert passed["read_rate_bps"] == 10000
        assert passed["verification_outcome"] == "PASS"

        cleared = fx.read_position(api, world["position_id"])
        assert cleared["tag_integrity_hold"] is False

        posted = validate_success(
            api.post_adjustment(world["adjustment_id"], SUPERVISOR)
        )
        assert_adjustment_dimensions(
            posted, approval_state="APPROVED", posting_state="POSTED"
        )
        settled = fx.read_position(api, world["position_id"])
        assert settled["on_hand_units"] == 80
        assert_units_conserved(settled, [-20])

    def test_a_clean_position_reports_the_approval_gate(self, api):
        """
        Without a hold, the unsatisfied approval is what the caller hears.

        "`approval_state` must be either `NOT_REQUIRED` or `APPROVED`, otherwise
        `ERR_ADJUSTMENT_APPROVAL_REQUIRED` — this catches both the still-`PENDING` and
        the `REJECTED` row."

        Design: Corner/errors/adjustment_post_onto_a_tag_held_position_rejected
        """
        world = fx.apparel_reference_world(api, baseline=100)
        assert fx.read_position(api, world["position_id"])["tag_integrity_hold"] is False

        adjustment = fx.create_adjustment(api, world["position_id"], -20)
        assert_adjustment_dimensions(
            adjustment, approval_state="PENDING", posting_state="UNPOSTED"
        )

        validate_error(
            api.post_adjustment(adjustment["id"], SUPERVISOR),
            ERR_ADJUSTMENT_APPROVAL_REQUIRED,
            409,
        )

        rejected = validate_success(
            api.reject_adjustment(adjustment["id"], SUPERVISOR)
        )
        assert_adjustment_dimensions(
            rejected, approval_state="REJECTED", posting_state="UNPOSTED"
        )

        validate_error(
            api.post_adjustment(adjustment["id"], SUPERVISOR),
            ERR_ADJUSTMENT_APPROVAL_REQUIRED,
            409,
        )
        assert fx.read_position(api, world["position_id"])["on_hand_units"] == 100


class TestOneLinePerItemPerTask:
    def test_a_second_line_for_the_same_item_is_a_conflict(self, api):
        """
        A recount inside a live task is refused rather than absorbed.

        "Only one line per SKU may be attached to a task; a second is rejected with
        `ERR_DUPLICATE_COUNT_LINE`."

        Design: Corner/errors/second_count_line_for_the_same_item_returns_duplicate_conflict
        """
        world = fx.apparel_two_item_world(api, baseline_a=100, baseline_b=50)
        fx.with_started_task(api, world)
        first = fx.add_line(api, world["task_id"], world["item_id"], 100)
        assert first["counted_units"] == 100

        validate_error(
            api.create_count_line(
                world["task_id"],
                f.count_line_payload(world["item_id"], 98),
                ANALYST,
            ),
            ERR_DUPLICATE_COUNT_LINE,
            409,
        )

        rows, meta = validate_paginated(
            api.list_count_lines(ANALYST, {"count_task_id": world["task_id"]})
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == first["id"]
        assert rows[0]["counted_units"] == 100

    def test_a_different_item_on_the_same_task_is_accepted(self, api):
        """
        The constraint is per SKU, not per task.

        "Only one line per SKU may be attached to a task; a second is rejected with
        `ERR_DUPLICATE_COUNT_LINE`."

        Design: Corner/errors/second_count_line_for_the_same_item_returns_duplicate_conflict
        """
        world = fx.apparel_two_item_world(api, baseline_a=100, baseline_b=50)
        fx.with_started_task(api, world)
        fx.add_line(api, world["task_id"], world["item_id"], 100)

        second = validate_success(
            api.create_count_line(
                world["task_id"],
                f.count_line_payload(world["item_b_id"], 40),
                ANALYST,
            ),
            201,
        )
        assert second["counted_units"] == 40
        assert second["count_task_id"] == world["task_id"]

        rows, meta = validate_paginated(
            api.list_count_lines(ANALYST, {"count_task_id": world["task_id"]})
        )
        assert meta["total_count"] == 2

    def test_another_task_at_another_store_may_count_the_same_item(self, api):
        """
        The uniqueness is scoped to one task.

        "Only one line per SKU may be attached to a task; a second is rejected with
        `ERR_DUPLICATE_COUNT_LINE`."

        Design: Corner/errors/second_count_line_for_the_same_item_returns_duplicate_conflict
        """
        world = fx.apparel_reference_world(api, baseline=100)
        fx.with_started_task(api, world)
        fx.add_line(api, world["task_id"], world["item_id"], 100)

        other_store = fx.create_store(api, f.handheld_only_store_payload())
        fx.create_position(api, other_store["id"], world["item_id"], baseline=100)
        other_schedule = fx.create_schedule(
            api, other_store["id"], world["category_id"], first_due_date="2026-08-01"
        )
        other_task = fx.create_task(api, other_schedule["id"])
        fx.start_task(api, other_task["id"])

        accepted = validate_success(
            api.create_count_line(
                other_task["id"], f.count_line_payload(world["item_id"], 97), ANALYST
            ),
            201,
        )
        assert accepted["count_task_id"] == other_task["id"]
        assert accepted["counted_units"] == 97

        rows, meta = validate_paginated(
            api.list_count_lines(ANALYST, {"count_task_id": other_task["id"]})
        )
        assert meta["total_count"] == 1


class TestOpenInvestigationsBlockBothClosures:
    def test_reconcile_is_refused_while_the_investigation_it_opened_is_open(self, api):
        """
        A count may not outrun its own root-cause work.

        "Every investigation this task opened must already be in `CLOSED` or `WAIVED`;
        if even one remains in `OPEN`, `IN_REVIEW`, `CAUSE_PROPOSED` or
        `CAUSE_APPROVED`, the reconcile is rejected with `ERR_OPEN_INVESTIGATIONS`."

        Design: Corner/errors/count_reconcile_with_an_open_investigation_rejected
        """
        world = fx.counted_variance_world(api, counted_units=90, baseline=100)
        assert world["line"]["variance_units"] == -10
        assert world["line"]["variance_value_cents"] == 13266
        assert world["line"]["within_tolerance"] is False
        assert world["submitted_task"]["status"] == "COUNTED"
        assert world["investigation"]["status"] == "OPEN"

        validate_error(
            api.reconcile_count_task(world["task_id"], SUPERVISOR),
            ERR_OPEN_INVESTIGATIONS,
            409,
        )

        assert fx.read_task(api, world["task_id"])["status"] == "COUNTED"

        rows, meta = validate_paginated(
            api.list_investigations(SUPERVISOR, {"count_line_id": world["line_id"]})
        )
        assert meta["total_count"] == 1
        assert rows[0]["status"] == "OPEN"

        schedule = fx.read_schedule(api, world["schedule_id"])
        assert schedule["completed_cycle_count"] == 0
        assert schedule["next_due_date"] == "2026-08-01"

    def test_closing_the_investigation_releases_the_reconcile(self, api):
        """
        Once the attribution work is terminal the count closes out.

        "An `InventorySupervisor` or `ShrinkController` closes out a submitted count,
        moving it from `COUNTED` to the terminal `RECONCILED`. Every investigation this
        task opened must already be in `CLOSED` or `WAIVED`; if even one remains in
        `OPEN`, `IN_REVIEW`, `CAUSE_PROPOSED` or `CAUSE_APPROVED`, the reconcile is
        rejected with `ERR_OPEN_INVESTIGATIONS`. On success the backing schedule
        advances: `completed_cycle_count` is incremented by 1 and `next_due_date` is set
        to the calendar date of the task's `window_end` plus the schedule's
        `cadence_days` days."

        Design: Corner/errors/count_reconcile_with_an_open_investigation_rejected
        """
        world = fx.counted_variance_world(api, counted_units=90, baseline=100)
        closed = fx.drive_to_closed(api, world["investigation_id"], "THEFT")
        assert closed["status"] == "CLOSED"

        reconciled = validate_success(
            api.reconcile_count_task(world["task_id"], SUPERVISOR)
        )
        assert reconciled["status"] == "RECONCILED"

        schedule = fx.read_schedule(api, world["schedule_id"])
        assert schedule["completed_cycle_count"] == 1
        assert schedule["next_due_date"] == "2026-09-02"

    def test_a_final_close_reports_the_same_identifier(self, api):
        """
        The period's own closure ladder consults the same terminality rule.

        "A final close requires that every investigation whose `shrink_period_id` names
        this period be in `CLOSED` or `WAIVED`; if even one is still non-terminal, it is
        rejected with `ERR_OPEN_INVESTIGATIONS`."

        Design: Corner/errors/count_reconcile_with_an_open_investigation_rejected
        """
        world = fx.counted_variance_world(api, counted_units=90, baseline=100)

        provisional = validate_success(
            api.provisional_close_shrink_period(world["shrink_period_id"], CONTROLLER)
        )
        assert provisional["status"] == "PROVISIONAL_CLOSED"
        assert provisional["unresolved_cents"] == 13266

        validate_error(
            api.final_close_shrink_period(world["shrink_period_id"], CONTROLLER),
            ERR_OPEN_INVESTIGATIONS,
            409,
        )

        stalled = validate_success(
            api.get_shrink_period(world["shrink_period_id"], CONTROLLER)
        )
        assert stalled["status"] == "PROVISIONAL_CLOSED"
        assert stalled["unresolved_cents"] == 13266


def _submit_physical_line(api, world, counted_units):
    """Submit one physical-inventory line quoting the inventory's live version."""
    current = validate_success(
        api.get_physical_inventory(world["physical_inventory_id"], CONTROLLER)
    )
    return validate_success(
        api.create_physical_inventory_line(
            world["physical_inventory_id"],
            f.physical_line_payload(
                world["item_id"], counted_units, current["version"]
            ),
            world["counter_headers"],
        ),
        201,
    )


class TestThePhysicalRecountGate:
    @staticmethod
    def _first_pass_ten_percent_short(api, **kwargs):
        """A completed first pass whose net variance is exactly 1000 basis points."""
        world = fx.physical_inventory_world(api, baseline=100, **kwargs)
        validate_success(
            api.start_physical_inventory(
                world["physical_inventory_id"], world["counter_headers"]
            )
        )
        _submit_physical_line(api, world, 90)
        completed = validate_success(
            api.complete_pass(
                world["physical_inventory_id"], world["counter_headers"]
            )
        )
        assert completed["status"] == "FIRST_PASS_COMPLETE"
        assert completed["book_value_cents"] == 123400
        assert completed["counted_value_cents"] == 111060
        assert completed["net_variance_cents"] == -12340
        assert completed["net_variance_bps"] == 1000
        world["completed"] = completed
        return world

    def test_a_first_pass_above_the_default_threshold_demands_a_recount(self, api):
        """
        A wildly varying first pass may not be reconciled.

        "First, the variance must be either small enough or already re-counted: the
        reconcile proceeds when `net_variance_bps` is strictly below
        `recount_threshold_bps`, or when `recount_round` is at least 1. A first pass
        whose `net_variance_bps` is greater than **or equal to** `recount_threshold_bps`
        is rejected with `ERR_RECOUNT_REQUIRED` — the boundary demands a recount — and
        the way past that rejection is to order the recount, after which the reconcile is
        permitted regardless of the variance."

        Design: Corner/errors/physical_reconcile_above_recount_threshold_rejected
        """
        world = self._first_pass_ten_percent_short(api, recount_threshold_bps=None)

        validate_error(
            api.reconcile_physical_inventory(
                world["physical_inventory_id"], CONTROLLER
            ),
            ERR_RECOUNT_REQUIRED,
            409,
        )

        stalled = fx.read_physical_inventory(api, world["physical_inventory_id"])
        assert stalled["recount_threshold_bps"] == 150
        assert stalled["net_variance_bps"] == 1000
        assert stalled["status"] == "FIRST_PASS_COMPLETE"
        assert stalled["recount_round"] == 0

        rows, meta = validate_paginated(
            api.list_adjustments(ADMIN, {"posting_state": "POSTED"})
        )
        assert rows == []
        assert meta["total_count"] == 0
        assert fx.read_position(api, world["position_id"])["on_hand_units"] == 100

    def test_ordering_the_recount_opens_the_reconcile_whatever_the_variance(self, api):
        """
        The second branch of the guard ignores the variance entirely.

        "First, the variance must be either small enough or already re-counted: the
        reconcile proceeds when `net_variance_bps` is strictly below
        `recount_threshold_bps`, or when `recount_round` is at least 1. A first pass
        whose `net_variance_bps` is greater than **or equal to** `recount_threshold_bps`
        is rejected with `ERR_RECOUNT_REQUIRED` — the boundary demands a recount — and
        the way past that rejection is to order the recount, after which the reconcile is
        permitted regardless of the variance."

        Design: Corner/errors/physical_reconcile_above_recount_threshold_rejected
        """
        world = self._first_pass_ten_percent_short(api, recount_threshold_bps=None)
        validate_error(
            api.reconcile_physical_inventory(
                world["physical_inventory_id"], CONTROLLER
            ),
            ERR_RECOUNT_REQUIRED,
            409,
        )

        recounting = validate_success(
            api.order_recount(world["physical_inventory_id"], CONTROLLER)
        )
        assert recounting["status"] == "COUNTING"
        assert recounting["recount_round"] == 1

        _submit_physical_line(api, world, 80)
        _submit_physical_line(api, world, 90)
        second_pass = validate_success(
            api.complete_pass(
                world["physical_inventory_id"], world["counter_headers"]
            )
        )
        assert second_pass["line_count"] == 1
        assert second_pass["net_variance_bps"] == 1000

        reconciled = validate_success(
            api.reconcile_physical_inventory(
                world["physical_inventory_id"], CONTROLLER
            )
        )
        assert reconciled["status"] == "RECONCILING"

    def test_a_variance_exactly_at_the_threshold_is_still_rejected(self, api):
        """
        The comparison is not strict, so equality demands the recount.

        "A first pass whose `net_variance_bps` is greater than **or equal to**
        `recount_threshold_bps` is rejected with `ERR_RECOUNT_REQUIRED` — the boundary
        demands a recount — and the way past that rejection is to order the recount,
        after which the reconcile is permitted regardless of the variance."

        Design: Corner/errors/physical_reconcile_above_recount_threshold_rejected
        """
        world = self._first_pass_ten_percent_short(api, recount_threshold_bps=1000)
        assert (
            fx.read_physical_inventory(api, world["physical_inventory_id"])[
                "recount_threshold_bps"
            ]
            == 1000
        )

        validate_error(
            api.reconcile_physical_inventory(
                world["physical_inventory_id"], CONTROLLER
            ),
            ERR_RECOUNT_REQUIRED,
            409,
        )
        assert (
            fx.read_physical_inventory(api, world["physical_inventory_id"])["status"]
            == "FIRST_PASS_COMPLETE"
        )

    def test_one_basis_point_higher_is_the_first_threshold_that_passes(self, api):
        """
        A threshold strictly above the variance lets the reconcile through.

        "First, the variance must be either small enough or already re-counted: the
        reconcile proceeds when `net_variance_bps` is strictly below
        `recount_threshold_bps`, or when `recount_round` is at least 1."

        Design: Corner/errors/physical_reconcile_above_recount_threshold_rejected
        """
        world = self._first_pass_ten_percent_short(api, recount_threshold_bps=1001)

        reconciled = validate_success(
            api.reconcile_physical_inventory(
                world["physical_inventory_id"], CONTROLLER
            )
        )
        assert reconciled["status"] == "RECONCILING"
        assert reconciled["recount_round"] == 0

        settled = fx.read_position(api, world["position_id"])
        assert settled["on_hand_units"] == 90
        assert_units_conserved(settled, [-10])

    def test_clearing_the_recount_gate_exposes_the_second_guard(self, api):
        """
        A physical reconciliation needs a fully open period to write into.

        "Second, a shrink period for the inventory's store whose inclusive range from
        `period_start` through `period_end` contains `scheduled_end_date` must exist with
        `status` exactly `OPEN`; otherwise `ERR_NO_COVERING_SHRINK_PERIOD`."

        Design: Corner/errors/physical_reconcile_above_recount_threshold_rejected
        """
        world = self._first_pass_ten_percent_short(
            api, recount_threshold_bps=1001, with_period=False
        )

        validate_error(
            api.reconcile_physical_inventory(
                world["physical_inventory_id"], CONTROLLER
            ),
            ERR_NO_COVERING_SHRINK_PERIOD,
            409,
        )
        assert (
            fx.read_physical_inventory(api, world["physical_inventory_id"])["status"]
            == "FIRST_PASS_COMPLETE"
        )


class TestInvestigationStateGuards:
    def test_approving_a_cause_that_was_never_proposed_is_a_state_error(self, api):
        """
        The approval verb is defined only on a standing proposal.

        "An investigation's `status` runs through `OPEN`, `IN_REVIEW`,
        `CAUSE_PROPOSED`, `CAUSE_APPROVED` and terminates in either `CLOSED` or
        `WAIVED`. Any transition attempted from a state the requested step does not
        declare — including any transition out of `CLOSED` or `WAIVED` — is rejected with
        `ERR_INVESTIGATION_INVALID_STATE`."

        Design: Corner/errors/approving_a_cause_that_was_never_proposed_rejected
        """
        world = fx.counted_variance_world(api, counted_units=90, baseline=100)
        assert world["investigation"]["status"] == "OPEN"

        validate_error(
            api.approve_cause(world["investigation_id"], SUPERVISOR),
            ERR_INVESTIGATION_INVALID_STATE,
            409,
        )

        unchanged = fx.read_investigation(api, world["investigation_id"])
        assert unchanged["status"] == "OPEN"
        assert unchanged["approved_root_cause"] is None
        assert unchanged["approved_by_user_id"] is None
        assert unchanged["proposed_root_cause"] is None

    def test_return_and_close_are_equally_undefined_on_an_open_investigation(self, api):
        """
        Neither verb is declared on the state the investigation is in.

        "An investigation's `status` runs through `OPEN`, `IN_REVIEW`,
        `CAUSE_PROPOSED`, `CAUSE_APPROVED` and terminates in either `CLOSED` or
        `WAIVED`. Any transition attempted from a state the requested step does not
        declare — including any transition out of `CLOSED` or `WAIVED` — is rejected with
        `ERR_INVESTIGATION_INVALID_STATE`."

        Design: Corner/errors/approving_a_cause_that_was_never_proposed_rejected
        """
        world = fx.counted_variance_world(api, counted_units=90, baseline=100)

        validate_error(
            api.return_investigation(world["investigation_id"], SUPERVISOR),
            ERR_INVESTIGATION_INVALID_STATE,
            409,
        )
        validate_error(
            api.close_investigation(world["investigation_id"], SUPERVISOR),
            ERR_INVESTIGATION_INVALID_STATE,
            409,
        )

        unchanged = fx.read_investigation(api, world["investigation_id"])
        assert unchanged["status"] == "OPEN"
        assert unchanged["proposal_round"] == 0

    def test_a_second_approval_is_not_idempotent(self, api):
        """
        `CAUSE_APPROVED` no longer declares the approval verb.

        "An investigation's `status` runs through `OPEN`, `IN_REVIEW`,
        `CAUSE_PROPOSED`, `CAUSE_APPROVED` and terminates in either `CLOSED` or
        `WAIVED`. Any transition attempted from a state the requested step does not
        declare — including any transition out of `CLOSED` or `WAIVED` — is rejected with
        `ERR_INVESTIGATION_INVALID_STATE`."

        Design: Corner/errors/approving_a_cause_that_was_never_proposed_rejected
        """
        world = fx.counted_variance_world(api, counted_units=90, baseline=100)
        approved = fx.drive_to_cause_approved(
            api, world["investigation_id"], "PROCESS_ERROR"
        )
        assert approved["status"] == "CAUSE_APPROVED"
        assert approved["approved_root_cause"] == "PROCESS_ERROR"

        validate_error(
            api.approve_cause(world["investigation_id"], SUPERVISOR),
            ERR_INVESTIGATION_INVALID_STATE,
            409,
        )

        unchanged = fx.read_investigation(api, world["investigation_id"])
        assert unchanged["status"] == "CAUSE_APPROVED"
        assert unchanged["version"] == approved["version"]
