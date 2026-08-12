"""Settlement pipeline: provisional vs final variants, split ladder, fee order,
dispute cycle, phase cascades, payment gating, regeneration guards, and OCC."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_phase,
    assert_settlement,
    book_and_check_in,
    checkout_transaction,
    close_intake,
    complete_shift_signup,
    create_event,
    create_item_for,
    create_slot,
    drop_off_item,
    finalize_settlement,
    generate_settlements,
    generate_settlements_with_version,
    get_consignor,
    get_event,
    get_item,
    get_settlement,
    inspect_fail,
    inspect_pass,
    make_consignor_headers,
    open_intake,
    open_transaction,
    register_consignor,
    register_volunteer,
    scan_barcode,
    sell_item,
    set_clock,
    setup_item_on_floor,
    setup_settlement_for_sold_item,
    start_presale,
    start_sale,
    start_settlement,
    validate_error,
    validate_success,
)

ORGANIZER = TEST_USERS["organizer_headers"]


class TestProvisionalVsFinalVariants:

    def _setup_provisional_scenario(self):
        """Event in SALE_ACTIVE; Ann's 10000-cent item ON_FLOOR; a DRAFT
        settlement already generated (floor projection in force)."""
        ctx = setup_item_on_floor(price_cents=10000, consignor_name="Ann",
                                  item_overrides={"title": "Bike",
                                                  "category": "GEAR",
                                                  "discount_eligible": True,
                                                  "donate_flag": False})
        settlements = generate_settlements(ctx["event"]["id"])
        assert len(settlements) == 1
        ctx["settlement"] = settlements[0]
        return ctx

    def test_provisional_projection_during_sale(self, api):
        """PRD §3.9: "`provisional_gross_cents` is the consignor's actual sold gross plus a sell-through projection that assumes half of the consignor's remaining `ON_FLOOR` inventory sells at today's markdown — for each such item, the line price at the current markdown is halved and rounded half-up to whole cents, and the per-item values are summed — and `provisional_payout_cents` runs the full payout pipeline on that estimated gross with the adjustment treated as 0."

        Design: Difficulty/dual_variant_calc/settlement_provisional_projection_vs_final_actuals
        """
        ctx = self._setup_provisional_scenario()
        settlement = get_settlement(ctx["settlement"]["id"])
        assert_settlement(settlement)
        # 0 actual + round_half_up(10000 * 50 / 100) floor projection
        assert settlement["provisional_gross_cents"] == 5000
        # Pipeline on 5000: split 60 -> commission 2000 -> before fee 3000 ->
        # supply fee 1000 (3000 < 30000, no volunteer) -> payout 2000
        assert settlement["provisional_payout_cents"] == 2000

    def test_final_variant_counts_actuals_only(self, api):
        """PRD §3.9: "Finalization runs steps one through seven on actuals only, excluding any `ON_FLOOR` projection, and freezes the results onto the row: `gross_cents`, `split_pct`, `commission_cents`, `payout_before_fee_cents`, `supply_fee_cents`, `rejected_fee_cents`, and `payout_cents` transition from null to concrete values, and the settlement moves `DRAFT` → `FINALIZED`."
        PRD §3.9: "Step one computes `gross_cents`: the sum of `final_line_cents` over transaction lines whose item belongs to the consignor and whose transaction is `COMPLETED`."

        Design: Difficulty/dual_variant_calc/settlement_provisional_projection_vs_final_actuals
        """
        ctx = self._setup_provisional_scenario()
        provisional_before = get_settlement(ctx["settlement"]["id"])

        sell_item(ctx)  # item SOLD for 10000 actual
        start_settlement(ctx["event"]["id"])
        settlements = generate_settlements(ctx["event"]["id"])
        finalized = finalize_settlement(settlements[0]["id"])

        assert finalized["status"] == "FINALIZED"
        assert finalized["gross_cents"] == 10000, (
            "The final variant counts COMPLETED-transaction actuals only"
        )
        assert finalized["split_pct"] == 60
        assert finalized["commission_cents"] == 4000
        assert finalized["payout_before_fee_cents"] == 6000
        assert finalized["supply_fee_cents"] == 1000
        assert finalized["payout_cents"] == 5000
        assert provisional_before["provisional_gross_cents"] != finalized["gross_cents"], (
            "Identical item data yields projection 5000 vs final actuals 10000"
        )


class TestSplitTierBonusCap:

    def _setup_bea_finalized(self, api):
        """Consignor Bea with a linked volunteer at 4.0 completed hours; her
        60000-cent item SOLD; settlement generated in SETTLEMENT."""
        event = create_event()
        open_intake(event["id"])
        bea = register_consignor(event["id"], "Bea")
        bea_vol = register_volunteer(event["id"], "Bea Vol",
                                     linked_consignor_id=bea["id"])
        complete_shift_signup(event["id"], bea_vol["id"])  # 4.0 hours
        slot = create_slot(event["id"])
        book_and_check_in(slot["id"], bea["id"])
        item = create_item_for(bea["id"], price_cents=60000, title="Stroller",
                               category="GEAR")
        drop_off_item(item["id"], bea["id"])
        inspector = register_volunteer(event["id"], "Insp Ida")
        inspect_pass(item["id"], inspector["id"])
        close_intake(event["id"])
        start_presale(event["id"])
        start_sale(event["id"])
        tx = open_transaction(event["id"])
        scan_barcode(tx["id"], item["barcode"])
        checkout_transaction(tx["id"], 60000)
        start_settlement(event["id"])
        settlements = generate_settlements(event["id"])
        assert len(settlements) == 1
        return settlements[0]

    def test_split_tier_bonus_capped_at_75(self, api):
        """PRD §3.9: "at 50000 cents or more they keep 70 percent. A volunteer bonus adds 5 percentage points when there exists a volunteer whose `linked_consignor_id` points at this consignor and whose `completed_hours` is at least 4, and the result is capped — the split is the smaller of the tiered-plus-bonus value and 75 percent."

        Design: Difficulty/combinatorial_formula/split_tier_bonus_cap_interaction
        """
        settlement = self._setup_bea_finalized(api)
        finalized = finalize_settlement(settlement["id"])

        assert finalized["gross_cents"] == 60000
        # tier(60000) = 70, bonus = 5, nested min caps at 75
        assert finalized["split_pct"] == 75, (
            f"min(75, 70 + 5) must cap the split at 75, got {finalized['split_pct']}"
        )
        assert finalized["commission_cents"] == 15000    # 60000 * 25%
        assert finalized["payout_before_fee_cents"] == 45000

    def test_fee_waived_and_payout_reflects_cap(self, api):
        """PRD §3.9: "Step five applies the supply fee: 1000 cents ($10.00), waived to 0 when `payout_before_fee_cents` is at least 30000 cents ($300.00) or when the volunteer-bonus condition of step two holds."
        PRD §3.9: "Step seven yields `payout_cents`: the pre-fee payout minus the supply fee, minus the rejected-item fee, plus `adjustment_cents`, floored at 0 so a payout can never go negative."

        Design: Difficulty/combinatorial_formula/split_tier_bonus_cap_interaction
        """
        settlement = self._setup_bea_finalized(api)
        finalized = finalize_settlement(settlement["id"])

        assert finalized["supply_fee_cents"] == 0, (
            "Fee waived: payout_before_fee 45000 >= 30000 (and the bonus "
            "condition holds)"
        )
        assert finalized["rejected_fee_cents"] == 0
        assert finalized["payout_cents"] == 45000


class TestFeeWaiverEvaluationOrder:

    def _setup_dee_settlement(self, api):
        """Consignor Dee (no linked volunteer) with one 47000-cent item SOLD;
        DRAFT settlement exists in SETTLEMENT."""
        ctx = setup_settlement_for_sold_item(price_cents=47000,
                                             consignor_name="Dee",
                                             item_overrides={"title": "Crib",
                                                             "category": "GEAR"})
        return ctx

    def test_fee_waiver_reads_pre_fee_payout(self, api):
        """PRD §3.9: "Step five applies the supply fee: 1000 cents ($10.00), waived to 0 when `payout_before_fee_cents` is at least 30000 cents ($300.00) or when the volunteer-bonus condition of step two holds. The waiver test deliberately reads the pre-fee payout, never the post-fee payout; evaluating the fee first would produce different results."

        Design: Difficulty/combinatorial_formula/fee_waiver_evaluation_order
        """
        ctx = self._setup_dee_settlement(api)
        finalized = finalize_settlement(ctx["settlement"]["id"])

        assert finalized["gross_cents"] == 47000
        assert finalized["split_pct"] == 65              # 20000 <= 47000 < 50000
        assert finalized["commission_cents"] == 16450    # 47000 * 35%
        assert finalized["payout_before_fee_cents"] == 30550
        assert finalized["supply_fee_cents"] == 0, (
            "Waiver is keyed on the pre-fee payout 30550 >= 30000; fee-first "
            "evaluation (29550 < 30000) would wrongly charge 1000"
        )

    def test_payout_equals_pre_fee_when_waived(self, api):
        """PRD §3.9: "Step seven yields `payout_cents`: the pre-fee payout minus the supply fee, minus the rejected-item fee, plus `adjustment_cents`, floored at 0 so a payout can never go negative. The `adjustment_cents` field starts at 0 and accumulates dispute-resolution input."

        Design: Difficulty/combinatorial_formula/fee_waiver_evaluation_order
        """
        ctx = self._setup_dee_settlement(api)
        finalized = finalize_settlement(ctx["settlement"]["id"])

        assert finalized["rejected_fee_cents"] == 0
        assert finalized["adjustment_cents"] == 0
        assert finalized["payout_cents"] == 30550, (
            f"30550 - 0 - 0 + 0 = 30550; got {finalized['payout_cents']}"
        )


class TestCheckoutCascade:

    def _setup_gia(self):
        """Event in SALE_ACTIVE; Gia's 10000-cent item ON_FLOOR; DRAFT settlement
        exists with the 50% floor projection (provisional gross 5000)."""
        ctx = setup_item_on_floor(price_cents=10000, consignor_name="Gia",
                                  item_overrides={"title": "Bike",
                                                  "category": "GEAR"})
        settlements = generate_settlements(ctx["event"]["id"])
        assert len(settlements) == 1
        ctx["settlement"] = settlements[0]
        assert get_settlement(settlements[0]["id"])["provisional_gross_cents"] == 5000
        return ctx

    def test_checkout_cascades_item_and_consignor(self, api):
        """PRD §3.8: "Every line item then moves `IN_CART` → `SOLD` as the first cascade hop; each sale triggers recomputation of its consignor's `sold_count` and `sold_gross_cents` (the second hop, where `sold_gross_cents` sums `final_line_cents` over lines of the consignor's items in `COMPLETED` transactions) and recomputation of that consignor's `DRAFT` settlement provisional fields (the third hop); and the event's `sold_gross_cents` is recomputed to keep the money invariant of §2.10 exact."

        Design: Difficulty/transitive_cascade/checkout_cascades_item_consignor_settlement
        """
        ctx = self._setup_gia()
        sell_item(ctx)  # checkout at tag price 10000

        assert get_item(ctx["item"]["id"])["status"] == "SOLD"          # hop 1
        consignor = get_consignor(ctx["consignor"]["id"])
        assert consignor["sold_count"] == 1                              # hop 2
        assert consignor["sold_gross_cents"] == 10000

    def test_checkout_cascades_settlement_provisional_and_event(self, api):
        """PRD §3.8: "each sale triggers recomputation of its consignor's `sold_count` and `sold_gross_cents` (the second hop, where `sold_gross_cents` sums `final_line_cents` over lines of the consignor's items in `COMPLETED` transactions) and recomputation of that consignor's `DRAFT` settlement provisional fields (the third hop); and the event's `sold_gross_cents` is recomputed to keep the money invariant of §2.10 exact."

        Design: Difficulty/transitive_cascade/checkout_cascades_item_consignor_settlement
        """
        ctx = self._setup_gia()
        sell_item(ctx)

        settlement = get_settlement(ctx["settlement"]["id"])             # hop 3
        # Floor projection now 0 (item left ON_FLOOR); actual gross 10000.
        assert settlement["provisional_gross_cents"] == 10000
        # Pipeline: 10000 at 60% -> commission 4000 -> before fee 6000 ->
        # fee 1000 -> payout 5000
        assert settlement["provisional_payout_cents"] == 5000
        assert get_event(ctx["event"]["id"])["sold_gross_cents"] == 10000


class TestSettlementPhaseCascade:

    def _setup_hal(self):
        """Event in SALE_ACTIVE; Hal's 4000-cent item unsold ON_FLOOR; DRAFT
        settlement exists with provisional gross 2000 (50% projection)."""
        ctx = setup_item_on_floor(price_cents=4000, consignor_name="Hal",
                                  item_overrides={"title": "Puzzle"})
        settlements = generate_settlements(ctx["event"]["id"])
        assert len(settlements) == 1
        ctx["settlement"] = settlements[0]
        settlement = get_settlement(settlements[0]["id"])
        assert settlement["provisional_gross_cents"] == 2000
        # Pipeline on 2000: 60% -> commission 800 -> before 1200 -> fee 1000 -> 200
        assert settlement["provisional_payout_cents"] == 200
        return ctx

    def test_advance_marks_on_floor_items_unsold(self, api):
        """PRD §3.8: "On this advance, every item still `ON_FLOOR` moves to `UNSOLD` in item `created_at` ascending order (hop 1), each triggering recomputation of its consignor's `unsold_count` and provisional counters (hop 2) and of the consignor's `DRAFT` settlement provisional fields — with the floor projection now removed (hop 3)."

        Design: Difficulty/transitive_cascade/settlement_phase_cascades_unsold_counters
        """
        ctx = self._setup_hal()
        start_settlement(ctx["event"]["id"])

        assert get_item(ctx["item"]["id"])["status"] == "UNSOLD"         # hop 1
        assert get_consignor(ctx["consignor"]["id"])["unsold_count"] == 1  # hop 2

    def test_advance_removes_floor_projection(self, api):
        """PRD §3.8: "On this advance, every item still `ON_FLOOR` moves to `UNSOLD` in item `created_at` ascending order (hop 1), each triggering recomputation of its consignor's `unsold_count` and provisional counters (hop 2) and of the consignor's `DRAFT` settlement provisional fields — with the floor projection now removed (hop 3)."

        Design: Difficulty/transitive_cascade/settlement_phase_cascades_unsold_counters
        """
        ctx = self._setup_hal()
        start_settlement(ctx["event"]["id"])

        settlement = get_settlement(ctx["settlement"]["id"])             # hop 3
        assert settlement["provisional_gross_cents"] == 0, (
            "The floor projection must be removed by the cascade"
        )
        # Pipeline on 0: before fee 0 -> fee 1000 -> max(0, -1000) = 0
        assert settlement["provisional_payout_cents"] == 0


class TestDisputeRefinaleCycle:

    def _setup_fay_finalized(self, api):
        """Fay's 10000-cent item SOLD; event in SETTLEMENT; settlement generated
        and finalized (payout 5000)."""
        ctx = setup_settlement_for_sold_item(price_cents=10000,
                                             consignor_name="Fay",
                                             item_overrides={"title": "Bike",
                                                             "category": "GEAR"})
        finalized = finalize_settlement(ctx["settlement"]["id"])
        assert finalized["payout_cents"] == 5000
        ctx["settlement"] = finalized
        return ctx

    def test_dispute_and_resolve_cycle_states(self, api):
        """PRD §3.9: "The owning consignor may dispute a `FINALIZED` settlement by supplying a `reason`; the settlement moves `FINALIZED` → `DISPUTED` and the reason is recorded in `dispute_reason`, overwriting any earlier one so it always reflects the latest dispute. The organizer resolves a `DISPUTED` settlement by submitting an `adjustment_cents` value, which is added onto the settlement's accumulated `adjustment_cents`, and the settlement cycles back to `DRAFT` so it can be re-finalized with the adjustment included."

        Design: Difficulty/non_linear_state_machine/settlement_dispute_refinale_cycle
        """
        ctx = self._setup_fay_finalized(api)
        settlement_id = ctx["settlement"]["id"]

        disputed = validate_success(
            api.dispute_settlement(settlement_id, {"reason": "missing item credit"},
                                   make_consignor_headers(ctx["consignor"]["id"]))
        )
        assert disputed["status"] == "DISPUTED"
        assert disputed["dispute_reason"] == "missing item credit"

        resolved = validate_success(
            api.resolve_settlement(settlement_id, {"adjustment_cents": 500},
                                   ORGANIZER)
        )
        assert resolved["status"] == "DRAFT"
        assert resolved["adjustment_cents"] == 500, (
            "Resolve accumulates its input onto adjustment_cents"
        )

    def test_refinalize_includes_accumulated_adjustment(self, api):
        """PRD §3.9: "the settlement cycles back to `DRAFT` so it can be re-finalized with the adjustment included."
        PRD §3.9: "Step seven yields `payout_cents`: the pre-fee payout minus the supply fee, minus the rejected-item fee, plus `adjustment_cents`, floored at 0 so a payout can never go negative."

        Design: Difficulty/non_linear_state_machine/settlement_dispute_refinale_cycle
        """
        ctx = self._setup_fay_finalized(api)
        settlement_id = ctx["settlement"]["id"]
        first_payout = ctx["settlement"]["payout_cents"]

        validate_success(
            api.dispute_settlement(settlement_id, {"reason": "missing item credit"},
                                   make_consignor_headers(ctx["consignor"]["id"]))
        )
        validate_success(
            api.resolve_settlement(settlement_id, {"adjustment_cents": 500},
                                   ORGANIZER)
        )
        refinalized = finalize_settlement(settlement_id)

        assert refinalized["status"] == "FINALIZED"
        assert first_payout == 5000
        assert refinalized["payout_cents"] == 5500, (
            "The second finalization must include the accumulated 500-cent "
            f"adjustment (5000 + 500); got {refinalized['payout_cents']}"
        )


class TestPaymentRequiresTerminalItems:

    def _setup_rae_finalized(self, api):
        """Event in SETTLEMENT; Rae has one SOLD item (1000) and one UNSOLD item
        (800); settlement FINALIZED with gross 1000."""
        event = create_event()
        open_intake(event["id"])
        rae = register_consignor(event["id"], "Rae")
        slot = create_slot(event["id"])
        book_and_check_in(slot["id"], rae["id"])
        it1 = create_item_for(rae["id"], price_cents=1000, title="Sold toy")
        it2 = create_item_for(rae["id"], price_cents=800, title="Unsold toy")
        drop_off_item(it1["id"], rae["id"])
        drop_off_item(it2["id"], rae["id"])
        inspector = register_volunteer(event["id"], "Insp Ira")
        inspect_pass(it1["id"], inspector["id"])
        inspect_pass(it2["id"], inspector["id"])
        close_intake(event["id"])
        start_presale(event["id"])
        start_sale(event["id"])
        tx = open_transaction(event["id"])
        scan_barcode(tx["id"], it1["barcode"])
        checkout_transaction(tx["id"], 1000)
        start_settlement(event["id"])
        settlements = generate_settlements(event["id"])
        assert len(settlements) == 1
        finalized = finalize_settlement(settlements[0]["id"])
        assert finalized["gross_cents"] == 1000
        return event, rae, it1, it2, finalized

    def test_mark_paid_blocked_by_unsold_item(self, api):
        """PRD §3.9: "Payment closes the loop: the organizer marks a `FINALIZED` settlement paid, but only once every item of the consignor sits in a terminal status — `SOLD`, `PICKED_UP`, or `DONATED` — otherwise the request fails with `ERR_ITEMS_NOT_TERMINAL`."

        Design: Difficulty/cross_entity_state_dependency/settlement_payment_requires_items_terminal
        """
        _event, _rae, _it1, it2, settlement = self._setup_rae_finalized(api)
        assert get_item(it2["id"])["status"] == "UNSOLD"

        resp = api.mark_paid_settlement(settlement["id"], ORGANIZER)
        validate_error(resp, ApiErrorId.ERR_ITEMS_NOT_TERMINAL)
        assert get_settlement(settlement["id"])["status"] == "FINALIZED"

    def test_mark_paid_succeeds_after_pickup(self, api):
        """PRD §3.9: "During `SETTLEMENT`, a consignor may pick up their own `UNSOLD` items provided the logical clock is at or before the event's `pickup_deadline`; a later attempt is rejected with `ERR_PICKUP_WINDOW_CLOSED`, and success moves the item `UNSOLD` → `PICKED_UP` and recomputes the consignor's `unsold_count`."
        PRD §3.9: "Success moves `FINALIZED` → `PAID`."

        Design: Difficulty/cross_entity_state_dependency/settlement_payment_requires_items_terminal
        """
        _event, rae, _it1, it2, settlement = self._setup_rae_finalized(api)

        picked = validate_success(
            api.pickup_item(it2["id"], make_consignor_headers(rae["id"]))
        )
        assert picked["status"] == "PICKED_UP"

        paid = validate_success(api.mark_paid_settlement(settlement["id"], ORGANIZER))
        assert paid["status"] == "PAID"


class TestRejectedItemFeeAndFloor:

    def _setup_rejected_settlement(self, api):
        """Event in SETTLEMENT; Ann's single 500-cent item REJECTED at inspection;
        DRAFT settlement generated (gross 0)."""
        event = create_event()
        open_intake(event["id"])
        ann = register_consignor(event["id"], "Ann")
        slot = create_slot(event["id"])
        book_and_check_in(slot["id"], ann["id"])
        item = create_item_for(ann["id"], price_cents=500, title="Stained",
                               category="CLOTHING")
        drop_off_item(item["id"], ann["id"])
        inspector = register_volunteer(event["id"], "Insp Ira")
        inspect_fail(item["id"], inspector["id"], reasons="stain")
        close_intake(event["id"])
        start_presale(event["id"])
        start_sale(event["id"])
        start_settlement(event["id"])
        settlements = generate_settlements(event["id"])
        assert len(settlements) == 1
        return event, ann, settlements[0]

    def test_rejected_fee_and_zero_payout_floor(self, api):
        """PRD §3.9: "Step six computes `rejected_fee_cents` as 200 cents ($2.00) multiplied by the consignor's `rejected_count`."
        PRD §3.9: "Step seven yields `payout_cents`: the pre-fee payout minus the supply fee, minus the rejected-item fee, plus `adjustment_cents`, floored at 0 so a payout can never go negative."

        Design: Corner/calculations/rejected_item_fee_and_zero_payout_floor
        """
        _event, ann, settlement = self._setup_rejected_settlement(api)
        assert get_consignor(ann["id"])["rejected_count"] == 1

        finalized = finalize_settlement(settlement["id"])
        assert finalized["gross_cents"] == 0
        assert finalized["sold_item_count"] == 0
        assert finalized["rejected_fee_cents"] == 200      # 200 * rejected_count 1
        assert finalized["supply_fee_cents"] == 1000       # 0 < 30000, no volunteer
        assert finalized["payout_cents"] == 0, (
            "max(0, 0 - 1000 - 200) — a payout can never go negative"
        )


class TestSettlementStateGuards:

    def test_dispute_from_draft_rejected(self, api):
        """PRD §3.9: "The owning consignor may dispute a `FINALIZED` settlement by supplying a `reason`".
        PRD §2.8: "fifth, the target entity's lifecycle state (the `ERR_*_WRONG_STATE` family, plus `ERR_TRANSACTION_NOT_OPEN`, `ERR_PASS_NOT_ACTIVE`, and `ERR_SETTLEMENTS_LOCKED`)".

        Design: Corner/state_machines/settlement_dispute_from_draft_rejected
        """
        _event, ann, settlement = TestRejectedItemFeeAndFloor._setup_rejected_settlement(
            self, api
        )
        assert settlement["status"] == "DRAFT"

        resp = api.dispute_settlement(settlement["id"], {"reason": "too early"},
                                      make_consignor_headers(ann["id"]))
        validate_error(resp, ApiErrorId.ERR_SETTLEMENT_WRONG_STATE)
        assert get_settlement(settlement["id"])["status"] == "DRAFT"

    def test_generate_settlements_locked_when_finalized(self, api):
        """PRD §3.9: "If any settlement of the event has already reached `FINALIZED`, `DISPUTED`, or `PAID`, the regeneration is rejected with `ERR_SETTLEMENTS_LOCKED`."

        Design: Corner/errors/generate_settlements_locked_when_finalized
        """
        event, _ann, settlement = (
            TestRejectedItemFeeAndFloor._setup_rejected_settlement(self, api)
        )
        finalize_settlement(settlement["id"])

        fresh_version = get_event(event["id"])["version"]
        resp = generate_settlements_with_version(event["id"], fresh_version)
        validate_error(resp, ApiErrorId.ERR_SETTLEMENTS_LOCKED)


class TestSettlementRegenerationOCC:

    def test_stale_version_on_regenerate_rejected(self, api):
        """PRD §2.9: "If that value does not match the event's current `version` — because another mutation has advanced the event since the client last read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from superseding drafts built from newer sales data."
        PRD §3.9: "A successful regeneration increments the event's `version` by 1."

        Design: Corner/complexity_layers/occ_stale_version_on_regenerate_settlements
        """
        ctx = setup_item_on_floor(price_cents=1000, consignor_name="Ann")
        version_before = get_event(ctx["event"]["id"])["version"]

        first = generate_settlements_with_version(ctx["event"]["id"], version_before)
        validate_success(first)
        version_after = get_event(ctx["event"]["id"])["version"]
        assert version_after == version_before + 1, (
            "A successful regeneration increments the event's version by 1"
        )

        replay = generate_settlements_with_version(ctx["event"]["id"], version_before)
        validate_error(replay, ApiErrorId.ERR_STALE_VERSION)
        assert replay.status_code == 412
