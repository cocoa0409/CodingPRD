"""Cyclic and parallel state machines: the claim documentation loop (PRD §3.3),
the repair order's two independent dimensions (PRD §3.7) and the stockroom
band cycle on a part lot (PRD §2.10, §3.8).
"""

from test_helpers import (
    ERR_INFO_REQUEST_LIMIT,
    assert_estimate_breakdown,
    assert_part_lot_counts,
    factories,
    validate_error,
)


def _zipper_paid_order(catalogue):
    """A PAID_REPAIR order on the registered unit quoted for ZIPPER work only.

    Built through the PRD-declared endpoints: a `PAID_REPAIR_REQUEST` intake, a
    `USER_DAMAGE` bench finding on a single `ZIPPER` lane, the derived
    paid-repair adjudication, the order, and one `SENT` provisional quote of 35
    zipper minutes plus a single 1800-cent part line.
    """
    scenario = catalogue.scenario
    claim = scenario.claim(
        catalogue.center_id,
        catalogue.item_id,
        intake_kind="PAID_REPAIR_REQUEST",
        reported_defect_type="ZIPPER_FAILURE",
        customer_narrative="Snagged zipper.",
    )
    submitted = scenario.submit(claim["id"])
    scenario.assess(
        claim["id"],
        catalogue.technician_id,
        expected_claim_version=submitted["version"],
        determination="USER_DAMAGE",
        required_work_types=["ZIPPER"],
        estimated_labor_lines=[factories.labor_line("ZIPPER", 35)],
        estimated_parts_cents=1800,
        defect_notes="Snag damage to the zipper tape.",
    )
    scenario.decide(claim["id"], decision_note="User damage: quote as paid repair.")
    order = scenario.repair_order(claim["id"])
    estimate = scenario.estimate(
        order["id"],
        expected_repair_order_version=order["version"],
        labor_lines=[factories.labor_line("ZIPPER", 35)],
        parts_lines=[factories.parts_line(factories.ZIP_PART_CODE, 1, 1800)],
    )
    catalogue.update(
        claim=submitted,
        claim_id=claim["id"],
        order=order,
        order_id=order["id"],
        estimate=estimate,
        estimate_id=estimate["id"],
    )
    return catalogue


def _low_clip_lot(world):
    """Stock the pole-clip lot with one unit against a watermark of two.

    available_units 1 is at least one and at most `low_watermark_units`, so the
    lot is minted in the `LOW` band (PRD §2.10).
    """
    return world.scenario.part_lot(
        world.model_id,
        part_code=factories.CLIP_PART_CODE,
        part_kind="FRAME_SEGMENT",
        on_hand_units=1,
        unit_price_cents=900,
        low_watermark_units=2,
    )


class TestClaimDocumentationCycle:
    """PRD §3.3 — the bounded `SUBMITTED` → `INFO_REQUESTED` → `SUBMITTED` loop."""

    def test_documentation_loop_runs_twice_before_the_budget_is_spent(self, catalogue):
        """Each round moves the claim into INFO_REQUESTED and back, counting up.

        "A `ServiceAgent` may issue an information request with a `reason`, moving the claim from either `SUBMITTED` or `UNDER_ASSESSMENT` into `INFO_REQUESTED` and increasing `info_request_count` by one."
        "Resubmitting closes the loop, moving `INFO_REQUESTED` → `SUBMITTED`, and is available to the owner or to a `ServiceAgent`; a `Customer` caller must again own the unit."
        "The complete cycle is therefore `DRAFT` → `SUBMITTED` → `INFO_REQUESTED` → `SUBMITTED`, traversable at most twice before the information-request budget is exhausted."

        Design: Difficulty/non_linear_state_machine/claim_info_request_cycle_bounded_at_two
        """
        scenario = catalogue.scenario
        claim = scenario.claim(catalogue.center_id, catalogue.item_id)
        claim_id = claim["id"]
        scenario.submit(claim_id)
        assert scenario.read_claim(claim_id)["status"] == "SUBMITTED"
        assert scenario.read_claim(claim_id)["info_request_count"] == 0

        scenario.info_request(claim_id, "Photographs of the failed seam required.")
        after_first_request = scenario.read_claim(claim_id)
        assert after_first_request["status"] == "INFO_REQUESTED"
        assert after_first_request["info_request_count"] == 1

        scenario.resubmit(
            claim_id,
            catalogue.customer_id,
            customer_narrative="Photos attached of the split seam.",
        )
        after_first_resubmit = scenario.read_claim(claim_id)
        assert after_first_resubmit["status"] == "SUBMITTED"
        assert after_first_resubmit["info_request_count"] == 1

        scenario.info_request(claim_id, "Original retailer receipt number required.")
        after_second_request = scenario.read_claim(claim_id)
        assert after_second_request["status"] == "INFO_REQUESTED"
        assert after_second_request["info_request_count"] == 2

        scenario.resubmit(
            claim_id,
            catalogue.customer_id,
            customer_narrative="Retailer lookup reference added.",
        )
        after_second_resubmit = scenario.read_claim(claim_id)
        assert after_second_resubmit["status"] == "SUBMITTED"
        assert after_second_resubmit["info_request_count"] == 2

    def test_third_information_request_is_refused_at_count_two(
        self, api, claim_after_two_info_rounds, agent_headers
    ):
        """A third round is refused and leaves the claim exactly where it stood.

        "The cycle is bounded at two: an information request is only permitted while `info_request_count` is strictly below two, so a third attempt on the same claim is refused with `ERR_INFO_REQUEST_LIMIT`."

        Design: Difficulty/non_linear_state_machine/claim_info_request_cycle_bounded_at_two
        """
        world = claim_after_two_info_rounds
        before = world.scenario.read_claim(world.claim_id)
        assert before["info_request_count"] == 2
        assert before["status"] == "SUBMITTED"

        response = api.create_info_request(
            world.claim_id, {"reason": "One more photograph, please."}, agent_headers
        )
        validate_error(response, ERR_INFO_REQUEST_LIMIT)

        after = world.scenario.read_claim(world.claim_id)
        assert after["info_request_count"] == 2, after
        assert after["status"] == "SUBMITTED", after

    def test_resubmitted_proof_is_written_through_onto_the_unit(
        self, claim_after_two_info_rounds
    ):
        """The second resubmit's proof fields land on the unit and re-derive the flag.

        "Any proof fields supplied are written through onto the gear unit itself — which mutates the unit, refreshing its `updated_at` and incrementing its `version` — after which the claim's `proof_verified` is recomputed from the unit's stored proof fields."
        "At creation the claim's `status` is `DRAFT`, its `info_request_count` and `assessment_count` are both 0, its `submitted_at`, `latest_determination`, `latest_repair_cost_cents`, `decision`, `decision_threshold_pct`, `repair_ratio_pct`, `decision_by_role` and `decided_at` are all null, and its `proof_verified` flag is derived from the unit: it is true exactly when the unit's `proof_of_purchase_type` is not `NONE` and its `proof_of_purchase_ref` is not null, and it is recomputed whenever those fields change."

        Design: Difficulty/non_linear_state_machine/claim_info_request_cycle_bounded_at_two
        """
        world = claim_after_two_info_rounds
        unit = world.scenario.read_item(world.item_id)
        assert unit["proof_of_purchase_type"] == "RETAILER_LOOKUP", unit
        assert unit["proof_of_purchase_ref"] == "RTL-55921", unit

        claim = world.scenario.read_claim(world.claim_id)
        assert claim["proof_verified"] is True, claim


class TestRepairOrderParallelDimensions:
    """PRD §3.7 — `work_status` and `billing_status` advance independently."""

    def test_quote_approval_moves_only_the_money_dimension(self, catalogue):
        """Approving the quote lifts billing_status while work_status stays QUEUED.

        "A repair order carries **two independent state dimensions** that advance on different operations and gate one another."
        "On approval the estimate moves `SENT` → `APPROVED`, its `decided_at` is stamped, the order's `provisional_estimate_total_cents` is set from the estimate's `total_cents`, and the order's `billing_status` moves `ESTIMATE_SENT` → `ESTIMATE_APPROVED` — which is the moment the bench dimension is unlocked and `QUEUED` → `IN_WORK` becomes reachable."

        Design: Difficulty/non_linear_state_machine/repair_order_parallel_work_and_billing_dimensions
        """
        world = _zipper_paid_order(catalogue)
        scenario = world.scenario

        before = scenario.read_order(world.order_id)
        assert before["work_status"] == "QUEUED", before
        assert before["billing_status"] == "ESTIMATE_SENT", before

        scenario.approve_estimate(world.estimate_id, world.customer_id)

        after = scenario.read_order(world.order_id)
        assert after["billing_status"] == "ESTIMATE_APPROVED", after
        assert after["work_status"] == "QUEUED", after

    def test_first_work_block_moves_only_the_bench_dimension(self, catalogue):
        """The first block lifts work_status to IN_WORK, billing_status unchanged.

        "A repair order carries **two independent state dimensions** that advance on different operations and gate one another."
        "On success the block's `duration_minutes` is the whole number of minutes between `start_at` and `end_at`, its `status` is `SCHEDULED`, its `actual_minutes` is null, the assigned technician's `scheduled_minutes_open` increases by `duration_minutes`, and — if this is the first block on the order — the order's `work_status` moves `QUEUED` → `IN_WORK`."

        Design: Difficulty/non_linear_state_machine/repair_order_parallel_work_and_billing_dimensions
        """
        world = _zipper_paid_order(catalogue)
        scenario = world.scenario
        scenario.approve_estimate(world.estimate_id, world.customer_id)

        block = scenario.work_block(
            world.order_id,
            world.technician_id,
            work_type="ZIPPER",
            start_at="2026-06-16T09:00:00Z",
            end_at="2026-06-16T10:00:00Z",
        )

        after = scenario.read_order(world.order_id)
        assert after["work_status"] == "IN_WORK", after
        assert after["billing_status"] == "ESTIMATE_APPROVED", after

        assert block["duration_minutes"] == 60, block
        technician = scenario.read_technician(world.technician_id)
        assert technician["scheduled_minutes_open"] == 60, technician

    def test_approved_quote_total_is_frozen_onto_the_order(self, catalogue):
        """The PRO-discounted, taxed provisional total lands on the order at 7531.

        "`labor_subtotal_cents` is the sum of those already-rounded per-line charges; the sum itself is not rounded again, and it is emphatically not the rounding of one big rate-times-minutes total."
        "**Step three** applies a capped shop supply fee on labour alone: `shop_supply_fee_cents` is the lesser of 2500 cents and seven percent of `labor_subtotal_cents` rounded half up."
        "**Step eight** totals: `total_cents` is `subtotal_cents` minus `loyalty_discount_cents` plus `expedite_fee_cents` plus `tax_cents`."
        "On approval the estimate moves `SENT` → `APPROVED`, its `decided_at` is stamped, the order's `provisional_estimate_total_cents` is set from the estimate's `total_cents`, and the order's `billing_status` moves `ESTIMATE_SENT` → `ESTIMATE_APPROVED` — which is the moment the bench dimension is unlocked and `QUEUED` → `IN_WORK` becomes reachable."

        Design: Difficulty/non_linear_state_machine/repair_order_parallel_work_and_billing_dimensions
        """
        world = _zipper_paid_order(catalogue)
        scenario = world.scenario

        assert_estimate_breakdown(
            world.estimate,
            labor_subtotal_cents=5542,
            parts_subtotal_cents=1800,
            shop_supply_fee_cents=388,
            subtotal_cents=7730,
            loyalty_discount_cents=773,
            expedite_fee_cents=0,
            tax_cents=574,
            total_cents=7531,
        )

        scenario.approve_estimate(world.estimate_id, world.customer_id)
        order = scenario.read_order(world.order_id)
        assert order["provisional_estimate_total_cents"] == 7531, order


class TestPartLotBandCycle:
    """PRD §2.10, §3.8 — the stockroom band is a cycle, not a ladder."""

    def test_reservation_drains_a_low_lot_straight_to_depleted(self, open_order):
        """Reserving the last available unit takes the lot LOW → DEPLETED.

        "It is `DEPLETED` when `available_units` is zero; `LOW` when `available_units` is at least one and at most `low_watermark_units`; and `AVAILABLE` otherwise."
        "A successful reservation begins with `status` `RESERVED` and a null `settled_at`, increases the lot's `reserved_units` by `units`, recomputes the lot's `available_units`, re-derives the lot's `status`, and then re-derives `parts_support_status` on the lot's model."

        Design: Difficulty/non_linear_state_machine/part_lot_depleted_to_available_restock_cycle
        """
        scenario = open_order.scenario
        clip_lot = _low_clip_lot(open_order)
        assert_part_lot_counts(
            clip_lot, on_hand_units=1, reserved_units=0, available_units=1, status="LOW"
        )

        reservation = scenario.reserve_parts(
            open_order.order_id, clip_lot["id"], factories.CLIP_PART_CODE, 1
        )
        assert reservation["status"] == "RESERVED", reservation

        after_reserve = scenario.read_lot(clip_lot["id"])
        assert_part_lot_counts(
            after_reserve,
            on_hand_units=1,
            reserved_units=1,
            available_units=0,
            status="DEPLETED",
        )

    def test_release_returns_a_depleted_lot_to_low(self, open_order):
        """Releasing the reservation gives the unit back: DEPLETED → LOW.

        "This is a cycle, not a ladder — a lot moves `AVAILABLE` → `LOW` → `DEPLETED` as stock drains, and returns `DEPLETED` → `LOW` or `DEPLETED` → `AVAILABLE` when a restocking adjustment or a reservation release puts units back."
        "Alternatively a `PartsCoordinator` **releases** it with an optional `reason`, moving it `RESERVED` → `RELEASED`, stamping `settled_at`, and decreasing only the lot's `reserved_units` by `units`, so `available_units` rises by that many units while `on_hand_units` is untouched; again the lot's `status` and then the model's `parts_support_status` are re-derived."

        Design: Difficulty/non_linear_state_machine/part_lot_depleted_to_available_restock_cycle
        """
        scenario = open_order.scenario
        clip_lot = _low_clip_lot(open_order)
        reservation = scenario.reserve_parts(
            open_order.order_id, clip_lot["id"], factories.CLIP_PART_CODE, 1
        )
        assert scenario.read_lot(clip_lot["id"])["status"] == "DEPLETED"

        scenario.release_parts(
            reservation["id"], reason="Clip not needed after inspection."
        )

        after_release = scenario.read_lot(clip_lot["id"])
        assert_part_lot_counts(
            after_release,
            on_hand_units=1,
            reserved_units=0,
            available_units=1,
            status="LOW",
        )
        assert scenario.read_reservation(reservation["id"])["status"] == "RELEASED"

    def test_restock_adjustment_lifts_the_lot_back_to_available(self, open_order):
        """A five-unit restock closes the cycle at AVAILABLE with six units.

        "Otherwise `on_hand_units` changes by `delta_units`, `available_units` is recomputed, the lot's `status` is re-derived — which is how a `DEPLETED` lot climbs back to `LOW` or `AVAILABLE` and closes the inventory cycle — and the model's `parts_support_status` is re-derived."
        "That model-level field is `SUPPORTED` when some part lot for the model has a `status` of `AVAILABLE` or `LOW`."

        Design: Difficulty/non_linear_state_machine/part_lot_depleted_to_available_restock_cycle
        """
        scenario = open_order.scenario
        clip_lot = _low_clip_lot(open_order)
        reservation = scenario.reserve_parts(
            open_order.order_id, clip_lot["id"], factories.CLIP_PART_CODE, 1
        )
        scenario.release_parts(
            reservation["id"], reason="Clip not needed after inspection."
        )

        scenario.adjust_lot(clip_lot["id"], 5, reason="Quarterly restock")

        after_adjust = scenario.read_lot(clip_lot["id"])
        assert_part_lot_counts(
            after_adjust,
            on_hand_units=6,
            reserved_units=0,
            available_units=6,
            status="AVAILABLE",
        )

        model = scenario.read_model(open_order.model_id)
        assert model["parts_support_status"] == "SUPPORTED", model
