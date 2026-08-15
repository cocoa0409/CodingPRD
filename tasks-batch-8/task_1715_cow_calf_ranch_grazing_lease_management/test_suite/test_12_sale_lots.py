"""Sale lots: settlement arithmetic with pinned rounding order, relist/dispute
branching, settle segregation, crop closure bubble-up, and creation gates."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_aum,
    assert_money,
    contract_lot,
    create_herd_group,
    create_sale_lot,
    create_sale_lot_payload,
    deliver_lot,
    get_calf_crop,
    get_herd_group,
    get_success_data,
    make_ranch_manager_headers,
    make_sales_agent_headers,
    offer_lot,
    setup_certified_crop,
    setup_delivered_lot,
    setup_weaned_crop,
    settle_lot,
    validate_error,
    validate_success,
)

SALES_AGENT = TEST_USERS["sales_agent_headers"]


def _settlement_terms(**overrides):
    base = dict(base_price_cents_per_cwt=25000, slide_cents_per_lb=15,
                base_weight_lbs=550, shrink_pct=0.04, precon_claim="CERTIFIED",
                freight_cents_per_head=3500, commission_pct=0.03)
    base.update(overrides)
    return base


class TestPerHeadRoundingThenMultiply:
    def _setup(self, api):
        ctx = setup_certified_crop(steer_head=100, heifer_head=60)
        lot = create_sale_lot(ctx["crop"]["id"], ctx["ranch"]["id"],
                              lot_class="STEER", head_count=96,
                              **_settlement_terms())
        offer_lot(lot["id"])
        contract_lot(lot["id"], buyer_name="Five Rivers")
        return ctx, lot

    def test_pay_weight_slide_and_premium_order(self, api):
        """PRD §3.7: "First, `pay_weight_lbs` is the delivered average weight
        reduced by the shrink fraction — the delivered weight multiplied by one
        minus `shrink_pct`, rounded half-up to 2 decimal places."
        PRD §3.7: "Third, the slid price is floored: if it has fallen below 100
        cents per hundredweight it is raised to exactly 100, and only then is
        the preconditioning premium added — nothing for a `NONE` claim, 250
        cents per hundredweight for `ENROLLED`, and 600 for `CERTIFIED` —
        yielding `final_price_cents_per_cwt`, rounded half-up to 2 decimal
        places."

        Design: Difficulty/combinatorial_formula/sale_settlement_per_head_rounding_then_multiply
        """
        _ctx, lot = self._setup(api)
        delivered = deliver_lot(lot["id"], 535)
        assert delivered["lot_status"] == "DELIVERED"
        assert_aum(delivered["pay_weight_lbs"], 513.6, "535 x (1 - 0.04)")
        # Slide up: 25000 + (550 - 513.6) x 15 = 25546; then +600 premium.
        assert_money(delivered["final_price_cents_per_cwt"], 26146.0,
                     "slide BEFORE premium")

    def test_per_head_rounding_then_multiply_and_net_waterfall(self, api):
        """PRD §3.7: "Fourth, `per_head_gross_cents` is the final price
        multiplied by the pay weight and divided by 100, rounded half-up to 2
        decimal places; `gross_cents` is then that rounded per-head figure
        multiplied by the `head_count` — the system rounds per head first and
        multiplies second, never the other way around."
        PRD §3.7: "Fifth, `commission_cents` is the gross multiplied by
        `commission_pct`, rounded half-up to 2 decimal places, while
        `freight_cents` is the whole-number product of `head_count` and
        `freight_cents_per_head`. Finally, `net_settlement_cents` is the gross
        minus the commission minus the freight."

        Design: Difficulty/combinatorial_formula/sale_settlement_per_head_rounding_then_multiply
        """
        _ctx, lot = self._setup(api)
        delivered = deliver_lot(lot["id"], 535)
        assert_money(delivered["per_head_gross_cents"], 134285.86,
                     "26146.0 x 513.6 / 100, rounded per head")
        assert_money(delivered["gross_cents"], 12891442.56,
                     "134285.86 x 96 — per-head rounding THEN multiply")
        assert_money(delivered["commission_cents"], 386743.28, "gross x 0.03")
        assert delivered["freight_cents"] == 336000, "96 x 3500"
        assert_money(delivered["net_settlement_cents"], 12168699.28)


class TestRelistAndDisputeBranching:
    def _setup(self, api):
        ctx = setup_certified_crop(steer_head=100, heifer_head=60)
        lot = create_sale_lot(ctx["crop"]["id"], ctx["ranch"]["id"],
                              lot_class="STEER", head_count=100,
                              **_settlement_terms(base_price_cents_per_cwt=24000))
        offer_lot(lot["id"])
        contract_lot(lot["id"], buyer_name="JBS")
        return ctx, lot

    def test_relist_cycle_and_slide_down_delivery(self, api):
        """PRD §3.7: "When a buyer defaults, relisting returns the lot from
        `CONTRACTED` to `OFFERED`, increments its `relist_count`, and clears the
        `buyer_name`; the offer–contract cycle is unrestricted in count."
        PRD §3.7: "Second, the slide: the `base_price_cents_per_cwt` is adjusted
        by the difference between `base_weight_lbs` and the pay weight,
        multiplied by `slide_cents_per_lb`, and the adjustment is signed in both
        directions — a pay weight lighter than base raises the price, a heavier
        one lowers it."

        Design: Difficulty/non_linear_state_machine/sale_lot_relist_and_dispute_branching
        """
        _ctx, lot = self._setup(api)
        relisted = validate_success(api.relist_lot(lot["id"], SALES_AGENT))
        assert relisted["lot_status"] == "OFFERED"
        assert relisted["relist_count"] == 1
        assert relisted["buyer_name"] in (None, ""), "buyer_name cleared"
        contract_lot(lot["id"], buyer_name="Tyson")
        delivered = deliver_lot(lot["id"], 570)
        assert_aum(delivered["pay_weight_lbs"], 547.2)
        # Slide DOWN for the heavier pay weight: 24000 + (550-547.2)x15 + 600.
        assert_money(delivered["final_price_cents_per_cwt"], 24642.0)
        assert_money(delivered["net_settlement_cents"], 12729578.94)

    def test_resolve_dispute_recomputes_settlement(self, api):
        """PRD §3.7: "Resolving the dispute returns the lot to `DELIVERED`, and
        when the resolution supplies an `adjusted_delivered_weight_lbs`, that
        figure replaces `delivered_avg_weight_lbs` and the entire settlement
        chain above is recomputed from it."
        PRD §3.7: "Settling stamps `settled_by_user_id`, moves the lot to
        `SETTLED`"

        Design: Difficulty/non_linear_state_machine/sale_lot_relist_and_dispute_branching
        """
        _ctx, lot = self._setup(api)
        validate_success(api.relist_lot(lot["id"], SALES_AGENT))
        contract_lot(lot["id"], buyer_name="Tyson")
        deliver_lot(lot["id"], 570)
        disputed = validate_success(api.dispute_lot(
            lot["id"], {"reason": "weight variance at scale"}, SALES_AGENT))
        assert disputed["lot_status"] == "DISPUTED"

        resolved = validate_success(api.resolve_dispute(
            lot["id"], {"adjusted_delivered_weight_lbs": 535}, SALES_AGENT))
        assert resolved["lot_status"] == "DELIVERED"
        # Settlement recomputed from the adjusted weight, not frozen.
        assert_aum(resolved["pay_weight_lbs"], 513.6)
        assert_money(resolved["final_price_cents_per_cwt"], 25146.0)
        assert_money(resolved["gross_cents"], 12914986.0)
        assert_money(resolved["net_settlement_cents"], 12177536.42)

        settled = settle_lot(lot["id"], settler_user_id="u-ranch-9")
        assert settled["lot_status"] == "SETTLED"
        assert settled["settled_by_user_id"] == "u-ranch-9"
        assert settled["sold_by_user_id"] == "u-sale-1"


class TestSettleBubbleUpCropClose:
    def _setup(self, api):
        ctx = setup_weaned_crop(steer_head=40, heifer_head=20,
                                avg_wean_weight_lbs=540, avg_wean_age_days=195)
        lot = create_sale_lot(ctx["crop"]["id"], ctx["ranch"]["id"],
                              lot_class="STEER", head_count=40,
                              **_settlement_terms(
                                  base_price_cents_per_cwt=23000,
                                  slide_cents_per_lb=10, base_weight_lbs=520,
                                  shrink_pct=0.03, precon_claim="NONE",
                                  freight_cents_per_head=3000,
                                  commission_pct=0.025))
        offer_lot(lot["id"])
        contract_lot(lot["id"], buyer_name="CattCo")
        deliver_lot(lot["id"], 500)
        repl = create_herd_group(ctx["ranch"]["id"],
                                 group_name="Replacement Heifers",
                                 animal_class="REPLACEMENT_HEIFER",
                                 head_count=0, avg_weight_lbs=650)
        return ctx, lot, repl

    def test_settle_moves_reserved_to_marketed_but_crop_stays_open(self, api):
        """PRD §3.7: "Settling stamps `settled_by_user_id`, moves the lot to
        `SETTLED`, and then cascades twice into the crop: first the crop's
        reserved counter for the lot's class decreases by the `head_count` while
        its marketed counter increases by the same amount, and second that
        marketed-head mutation re-evaluates the crop's closure predicate from
        §3.6, closing the crop when every head is accounted for."

        Design: Difficulty/transitive_cascade/sale_settle_bubble_up_crop_close
        """
        ctx, lot, _repl = self._setup(api)
        settled = settle_lot(lot["id"], settler_user_id="u-ranch-9")
        assert settled["lot_status"] == "SETTLED"
        assert_money(settled["net_settlement_cents"], 4296652.5)
        crop = get_calf_crop(ctx["crop"]["id"])
        assert crop["marketed_steer_head"] == 40
        assert crop["reserved_steer_head"] == 0
        # 20 heifers remain unaccounted — closure is NOT a direct settle effect.
        assert crop["lifecycle_status"] == "ACTIVE"

    def test_crop_closes_after_last_head_accounted_and_locks(self, api):
        """PRD §3.6: "After any event that moves these counters — a settle, a
        retain, an unretain, a death loss, or a lot cancellation — the crop
        re-evaluates its closure predicate: when both available counts have
        reached zero and no sale lot of the crop remains in `DRAFT`, `OFFERED`,
        `CONTRACTED`, `DELIVERED`, or `DISPUTED`, the crop's `lifecycle_status`
        bubbles up to `CLOSED` on its own. Closure is terminal, and any attempt
        to create a new sale lot against a closed crop is rejected with
        `ERR_ALREADY_TERMINAL` (HTTP 400)."

        Design: Difficulty/transitive_cascade/sale_settle_bubble_up_crop_close
        """
        ctx, lot, repl = self._setup(api)
        settle_lot(lot["id"], settler_user_id="u-ranch-9")
        # Retain the last 20 heifers — every head is now accounted for.
        ok = api.retain_heifers(
            ctx["crop"]["id"],
            {"head_count": 20, "target_herd_group_id": repl["id"]},
            TEST_USERS["herd_manager_headers"])
        assert ok.status_code == 200, ok.text
        group_after = get_herd_group(repl["id"])
        assert group_after["head_count"] == 20
        assert group_after["retained_from_crop_id"] == ctx["crop"]["id"]

        crop = get_calf_crop(ctx["crop"]["id"])
        assert crop["available_steer_head"] == 0
        assert crop["available_heifer_head"] == 0
        assert crop["lifecycle_status"] == "CLOSED"

        resp = api.create_sale_lot(
            create_sale_lot_payload(ctx["crop"]["id"], ctx["ranch"]["id"],
                                    lot_class="STEER", head_count=1,
                                    base_price_cents_per_cwt=23000),
            SALES_AGENT)
        validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL)


class TestSaleLotGates:
    def test_terminal_lockdown_settled_lot(self, api):
        """PRD §3.7: "`SETTLED` and `CANCELLED` are both terminal."
        PRD §2.8: "Terminal-state rejection: a resource that has reached a
        terminal state refuses all further transitions (`ERR_ALREADY_TERMINAL`)."

        Design: Corner/state_machines/terminal_lockdown_settled_lot
        """
        ctx = setup_delivered_lot(steer_head=10, heifer_head=0, certified=False,
                                  delivered_avg_weight_lbs=500)
        lot = ctx["lot"]
        settle_lot(lot["id"], settler_user_id="u-ranch-9")

        resp = api.settle_lot(lot["id"], make_ranch_manager_headers("u-ranch-9"))
        validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL)
        resp = api.cancel_lot(lot["id"], make_sales_agent_headers("u-sale-1"))
        validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL)
        resp = api.dispute_lot(lot["id"], {"reason": "late"},
                               make_sales_agent_headers("u-sale-1"))
        validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL)
        after = get_success_data(api.get_sale_lot(lot["id"], SALES_AGENT))
        assert after["lot_status"] == "SETTLED"

    def test_lot_head_exceeds_available_rejected(self, api):
        """PRD §3.7: "the crop's available head of the lot's class must cover
        the lot's `head_count` (`ERR_INSUFFICIENT_CROP_HEAD`, HTTP 422)"
        PRD §3.7: "Moving from `DRAFT` to `OFFERED` re-verifies that the crop's
        lifecycle is still `ACTIVE` and that the crop's available head of the
        lot's class still covers the lot's `head_count` — availability can have
        moved since drafting — and then reserves the head"

        Design: Corner/validations/lot_head_exceeds_available_rejected
        """
        ctx = setup_weaned_crop(steer_head=40, heifer_head=0)
        crop = ctx["crop"]
        resp = api.create_sale_lot(
            create_sale_lot_payload(crop["id"], ctx["ranch"]["id"],
                                    lot_class="STEER", head_count=41),
            SALES_AGENT)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_CROP_HEAD,
                       expected_status=422)
        # Exactly the available head drafts fine — the bound is inclusive.
        lot = create_sale_lot(crop["id"], ctx["ranch"]["id"], lot_class="STEER",
                              head_count=40)
        assert lot["lot_status"] == "DRAFT"
        # Drafting alone does not reserve; the reservation lands at offer time.
        assert get_calf_crop(crop["id"])["available_steer_head"] == 40

    def test_precon_claim_exceeds_crop_rejected(self, api):
        """PRD §3.7: "the lot's `precon_claim` may not rank above the crop's own
        `precon_status`, where `CERTIFIED` outranks `ENROLLED` and `ENROLLED`
        outranks `NONE` (`ERR_PRECON_CLAIM_EXCEEDS_CROP`, HTTP 422)"

        Design: Corner/validations/precon_claim_exceeds_crop_rejected
        """
        ctx = setup_weaned_crop(steer_head=40, heifer_head=60)
        crop = ctx["crop"]
        from test_helpers import enroll_preconditioning
        enroll_preconditioning(crop["id"])  # ENROLLED, not CERTIFIED
        resp = api.create_sale_lot(
            create_sale_lot_payload(crop["id"], ctx["ranch"]["id"],
                                    lot_class="STEER", head_count=10,
                                    precon_claim="CERTIFIED"),
            SALES_AGENT)
        validate_error(resp, ApiErrorId.ERR_PRECON_CLAIM_EXCEEDS_CROP,
                       expected_status=422)
        lot = create_sale_lot(crop["id"], ctx["ranch"]["id"], lot_class="STEER",
                              head_count=10, precon_claim="ENROLLED")
        assert lot["lot_status"] == "DRAFT"
