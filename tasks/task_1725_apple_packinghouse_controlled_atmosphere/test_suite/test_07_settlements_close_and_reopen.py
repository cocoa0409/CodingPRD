"""Grower settlements: the provisional advance, pool-close reconciliation, the
depth-3 close cascade to lots, and the close/reopen revision loop."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    allocate_bins,
    assert_grower_settlement,
    close_pool_fresh,
    complete_run,
    create_active_spec,
    create_block,
    create_grower,
    create_grower_with_block,
    create_open_pool,
    create_room,
    get_pool_settlement,
    get_success_data,
    open_room,
    receive_lot,
    record_sale,
    refresh_lot,
    refresh_settlement,
    release_allocation,
    schedule_run,
    seal_room,
    setup_completed_run,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
POOL_MGR = TEST_USERS["pool_manager_headers"]


class TestAdvance:
    def test_advance_twice_rejected(self, api):
        """PRD §3.6: "While the pool is `OPEN`, a `PoolManager` may pay the
        provisional advance on an `ACCRUING` settlement — attempts in any other
        settlement state are rejected with `ERR_SETTLEMENT_INVALID_STATE`"
        PRD §3.6: "The advance is sixty percent of the provisional value:
        `attributed_cartons` times the pool's current `estimated_price_cents`
        times 0.60, rounded half-up to whole cents"
        PRD §3.5: "While the pool is `OPEN` or `REOPENED`, the provisional
        `estimated_price_cents` is that net divided by `total_packed_cartons`,
        rounded half-up to whole cents, but never allowed below the floor of 1,000
        cents per carton"

        With 40 cartons and no sales the net is negative, so the estimate floors
        at 1,000 and the advance is round_half_up(40 * 1000 * 0.60) = 24000.

        Design: Corner/state_machines/c_advance_twice_rejected
        """
        ctx = setup_completed_run(received_bin_count=5, received_weight_lbs=4000,
                                  input_weight_lbs=4000, cartons_produced=40,
                                  packed_weight_lbs=4000, cull_weight_lbs=0,
                                  juice_weight_lbs=0)
        pool = get_success_data(api.get_pool(ctx["pool"]["id"], ADMIN))
        assert pool["estimated_price_cents"] == 1000, "net is negative: floor applies"

        advanced = validate_success(
            api.pay_settlement_advance(ctx["settlement"]["id"], POOL_MGR))
        assert_grower_settlement(advanced)
        assert advanced["advance_amount_cents"] == 24000
        assert advanced["status"] == "ADVANCE_PAID"

        resp = api.pay_settlement_advance(ctx["settlement"]["id"], POOL_MGR)
        validate_error(resp, ApiErrorId.ERR_SETTLEMENT_INVALID_STATE)

    def test_advance_without_cartons_rejected(self, api):
        """PRD §3.6: "The settlement must have at least one attributed carton,
        else `ERR_NO_ATTRIBUTED_CARTONS`."
        PRD §3.6: "exactly one settlement exists for each pairing of grower and
        pool, auto-created the first time one of the grower's lots completes a run
        attributed to that pool."

        Design: Corner/validations/c_advance_without_cartons_rejected
        """
        ctx = setup_completed_run(received_bin_count=5, received_weight_lbs=4000,
                                  input_weight_lbs=1000, cartons_produced=0,
                                  packed_weight_lbs=0, cull_weight_lbs=500,
                                  juice_weight_lbs=500)
        settlement = refresh_settlement(ctx["settlement"]["id"])
        assert settlement["attributed_cartons"] == 0, (
            "settlement exists despite zero cartons"
        )
        resp = api.pay_settlement_advance(settlement["id"], POOL_MGR)
        validate_error(resp, ApiErrorId.ERR_NO_ATTRIBUTED_CARTONS)


class TestAdvancePoolGate:
    def test_advance_rejected_after_pool_close(self, api):
        """PRD §3.6: "advances are not paid while the pool is `REOPENED` or
        `CLOSED` (`ERR_POOL_INVALID_STATE`)."
        PRD §2.9: "When several state gates fail on one call, the error is
        reported in this fixed order: lot first, then spec, pool, room,
        allocation, run, and settlement last."

        After the close the settlement is SETTLED too, but pool outranks
        settlement in the state-gate order.

        Design: Difficulty/cross_entity_state_dependency/advance_requires_open_pool
        """
        ctx = setup_completed_run(received_bin_count=2, received_weight_lbs=1000,
                                  input_weight_lbs=1000, cartons_produced=3,
                                  packed_weight_lbs=1000, cull_weight_lbs=0,
                                  juice_weight_lbs=0)
        record_sale(ctx["pool"]["id"], cartons_sold=3, gross_revenue_cents=10000)
        close_pool_fresh(ctx["pool"]["id"])

        settlement = refresh_settlement(ctx["settlement"]["id"])
        assert settlement["status"] == "SETTLED", "close already settled it"

        resp = api.pay_settlement_advance(settlement["id"], POOL_MGR)
        validate_error(resp, ApiErrorId.ERR_POOL_INVALID_STATE)
        settlement = refresh_settlement(settlement["id"])
        assert settlement["advance_amount_cents"] == 0, "advance stays rejected"

    def test_advance_rejected_while_pool_reopened(self, api):
        """PRD §3.6: "advances are not paid while the pool is `REOPENED` or
        `CLOSED` (`ERR_POOL_INVALID_STATE`)."
        PRD §3.6: "The cascade runs in reverse: every `SETTLED` settlement of the
        pool reverts to `ADVANCE_PAID`, its final numbers now stale until the
        re-close"

        Design: Difficulty/cross_entity_state_dependency/advance_requires_open_pool
        """
        ctx = setup_completed_run(received_bin_count=2, received_weight_lbs=1000,
                                  input_weight_lbs=1000, cartons_produced=3,
                                  packed_weight_lbs=1000, cull_weight_lbs=0,
                                  juice_weight_lbs=0)
        record_sale(ctx["pool"]["id"], cartons_sold=3, gross_revenue_cents=10000)
        close_pool_fresh(ctx["pool"]["id"])
        reopened = validate_success(api.reopen_pool(ctx["pool"]["id"], POOL_MGR))
        assert reopened["status"] == "REOPENED"

        settlement = refresh_settlement(ctx["settlement"]["id"])
        assert settlement["status"] == "ADVANCE_PAID", "reopen reverts the settlement"

        resp = api.pay_settlement_advance(settlement["id"], POOL_MGR)
        validate_error(resp, ApiErrorId.ERR_POOL_INVALID_STATE)


class TestAdvanceVsFinalPayout:
    def _setup_pool_with_sales(self, api):
        """100 attributed cartons; sales 300000 (ded 8000) + 120000 (ded 4000).

        Net = 420000 - (100*650 + 12000) = 343000 over 100 cartons, so both the
        floored estimate and the final price are 3430 cents per carton.
        """
        ctx = setup_completed_run(received_bin_count=20, received_weight_lbs=19000,
                                  input_weight_lbs=19000, cartons_produced=100,
                                  packed_weight_lbs=16150, cull_weight_lbs=1900,
                                  juice_weight_lbs=950)
        record_sale(ctx["pool"]["id"], cartons_sold=60,
                    gross_revenue_cents=300000, deduction_cents=8000)
        record_sale(ctx["pool"]["id"], cartons_sold=40,
                    gross_revenue_cents=120000, deduction_cents=4000)
        return ctx

    def test_advance_pays_sixty_percent_of_floored_estimate(self, api):
        """PRD §3.6: "The advance is sixty percent of the provisional value:
        `attributed_cartons` times the pool's current `estimated_price_cents`
        times 0.60, rounded half-up to whole cents, recorded as
        `advance_amount_cents` as the settlement moves `ACCRUING → ADVANCE_PAID`."

        Design: Difficulty/dual_variant_calc/settlement_advance_vs_final_payout
        """
        ctx = self._setup_pool_with_sales(api)
        pool = get_success_data(api.get_pool(ctx["pool"]["id"], ADMIN))
        assert pool["estimated_price_cents"] == 3430

        advanced = validate_success(
            api.pay_settlement_advance(ctx["settlement"]["id"], POOL_MGR))
        assert advanced["advance_amount_cents"] == 205800, (
            "round_half_up(100 * 3430 * 0.60)"
        )
        assert advanced["status"] == "ADVANCE_PAID"

    def test_final_settlement_diverges_from_advance(self, api):
        """PRD §3.6: "the settlement value is `attributed_cartons` times
        `pool_price_per_carton_cents`; the delta is that value minus
        `advance_amount_cents` and minus `paid_final_cents`; `final_payment_cents`
        is the delta with a floor of zero"
        PRD §3.6: "Because it is priced off the floored estimate, the advance and
        the eventual final payment differ even on identical carton counts."

        Design: Difficulty/dual_variant_calc/settlement_advance_vs_final_payout
        """
        ctx = self._setup_pool_with_sales(api)
        validate_success(api.pay_settlement_advance(ctx["settlement"]["id"], POOL_MGR))
        closed = close_pool_fresh(ctx["pool"]["id"])
        assert closed["pool_price_per_carton_cents"] == 3430
        assert closed["rounding_drift_cents"] == 0

        settlement = refresh_settlement(ctx["settlement"]["id"])
        assert settlement["status"] == "SETTLED"
        assert settlement["final_payment_cents"] == 137200, (
            "100*3430 - 205800 advance - 0 already paid"
        )
        assert settlement["advance_amount_cents"] == 205800
        assert settlement["advance_amount_cents"] != settlement["final_payment_cents"], (
            "provisional and final variants diverge"
        )


class TestPoolPriceRoundingOrder:
    def _setup_three_carton_pool(self, api):
        """3 cartons, one sale gross 105001 ded 0: net = 105001 - 3*650 = 103051,
        so round_half_up(103051/3) = 34350 with drift 34350*3 - 103051 = -1."""
        ctx = setup_completed_run(received_bin_count=2, received_weight_lbs=1000,
                                  input_weight_lbs=1000, cartons_produced=3,
                                  packed_weight_lbs=1000, cull_weight_lbs=0,
                                  juice_weight_lbs=0)
        record_sale(ctx["pool"]["id"], cartons_sold=3, gross_revenue_cents=105001,
                    deduction_cents=0)
        return ctx

    def test_close_rounds_price_first_and_records_negative_drift(self, api):
        """PRD §3.6: "first the per-carton price — the pool's net value divided by
        `total_packed_cartons` — is rounded half-up to whole cents and stored as
        `pool_price_per_carton_cents`, and only then is it multiplied per grower."
        PRD §3.6: "`rounding_drift_cents` records the gap between the rounded
        per-carton price times `total_packed_cartons` and the true net, may be
        negative, and is recorded on the pool but never redistributed."

        Design: Difficulty/combinatorial_formula/pool_price_rounding_order_pinned
        """
        ctx = self._setup_three_carton_pool(api)
        closed = close_pool_fresh(ctx["pool"]["id"])
        assert closed["pool_price_per_carton_cents"] == 34350, (
            "round_half_up(103051/3) = 34350"
        )
        assert closed["rounding_drift_cents"] == -1, "34350*3 - 103051"

    def test_settlement_pays_rounded_price_times_cartons(self, api):
        """PRD §3.6: "the settlement value is `attributed_cartons` times
        `pool_price_per_carton_cents`"
        PRD §3.6: "first the per-carton price — the pool's net value divided by
        `total_packed_cartons` — is rounded half-up to whole cents and stored as
        `pool_price_per_carton_cents`, and only then is it multiplied per grower."

        Design: Difficulty/combinatorial_formula/pool_price_rounding_order_pinned
        """
        ctx = self._setup_three_carton_pool(api)
        close_pool_fresh(ctx["pool"]["id"])
        settlement = refresh_settlement(ctx["settlement"]["id"])
        assert settlement["status"] == "SETTLED"
        # Pinned order pays 3 x 34350 = 103050, NOT the 103051 exact share.
        assert settlement["final_payment_cents"] == 103050


class TestPoolCloseCascadeToLots:
    def _setup_two_grower_pool(self, api):
        """Two growers' lots fully packed into one pool: 100 + 60 cartons.

        Sales 300000 (ded 8000) + 120000 (ded 4000): net = 420000 - (160*650 +
        12000) = 304000 over 160 cartons -> price 1900 exactly.
        """
        grower1, block1 = create_grower_with_block(grower_name="Grower One",
                                                   grower_code="G1")
        grower2 = create_grower("Grower Two", "G2")
        block2 = create_block(grower2["id"], orchard_name="Hilltop",
                              block_code="B7")
        room = create_room()
        lot1 = receive_lot(grower1["id"], block1["id"], 20, 19000, 80)
        lot2 = receive_lot(grower2["id"], block2["id"], 12, 12000, 78)
        a1 = allocate_bins(room["id"], lot1["id"], 20)
        a2 = allocate_bins(room["id"], lot2["id"], 12)
        seal_room(room)
        open_room(room["id"])
        release_allocation(a1["id"])
        release_allocation(a2["id"])
        spec = create_active_spec()
        pool = create_open_pool()

        run1 = schedule_run({"lot": lot1, "spec": spec, "pool": pool},
                            input_weight_lbs=19000,
                            scheduled_start="2026-08-02T08:00:00Z",
                            scheduled_end="2026-08-02T12:00:00Z")
        complete_run(run1["id"], 100, 16150, 1900, 950)
        run2 = schedule_run({"lot": lot2, "spec": spec, "pool": pool},
                            input_weight_lbs=12000,
                            scheduled_start="2026-08-02T12:00:00Z",
                            scheduled_end="2026-08-02T16:00:00Z")
        complete_run(run2["id"], 60, 10200, 1200, 600)

        record_sale(pool["id"], cartons_sold=100, gross_revenue_cents=300000,
                    deduction_cents=8000)
        record_sale(pool["id"], cartons_sold=60, gross_revenue_cents=120000,
                    deduction_cents=4000)
        return {"g1": grower1, "g2": grower2, "lot1": lot1, "lot2": lot2,
                "pool": pool}

    def test_close_settles_every_settlement(self, api):
        """PRD §3.6: "Every settlement of the pool in `ACCRUING` or `ADVANCE_PAID`
        computes its final position and moves to `SETTLED`: the settlement value
        is `attributed_cartons` times `pool_price_per_carton_cents`"

        Design: Difficulty/transitive_cascade/pool_close_cascade_to_lot_closure
        """
        ctx = self._setup_two_grower_pool(api)
        closed = close_pool_fresh(ctx["pool"]["id"])
        assert closed["pool_price_per_carton_cents"] == 1900, "hop 1 output"

        s1 = get_pool_settlement(ctx["pool"]["id"], ctx["g1"]["id"])
        s2 = get_pool_settlement(ctx["pool"]["id"], ctx["g2"]["id"])
        assert s1["status"] == "SETTLED"
        assert s1["final_payment_cents"] == 190000, "100 cartons x 1900 (hop 2)"
        assert s2["status"] == "SETTLED"
        assert s2["final_payment_cents"] == 114000, "60 cartons x 1900 (hop 2)"

    def test_close_cascade_closes_packed_lots(self, api):
        """PRD §3.6: "for each lot whose runs fed a settlement that just became
        `SETTLED`, if every settlement touching that lot is `SETTLED` and the lot
        is `PACKED`, the lot transitions `PACKED → CLOSED`."

        Design: Difficulty/transitive_cascade/pool_close_cascade_to_lot_closure
        """
        ctx = self._setup_two_grower_pool(api)
        # Both lots consumed their full balance: PACKED before the close.
        assert refresh_lot(ctx["lot1"]["id"])["status"] == "PACKED"
        assert refresh_lot(ctx["lot2"]["id"])["status"] == "PACKED"

        close_pool_fresh(ctx["pool"]["id"])

        assert refresh_lot(ctx["lot1"]["id"])["status"] == "CLOSED", (
            "hop 3 — caused by the settlement becoming SETTLED"
        )
        assert refresh_lot(ctx["lot2"]["id"])["status"] == "CLOSED"


class TestPoolReopenRevisionLoop:
    def _setup_first_close(self, api):
        """10 cartons fully packed; sale 30000 (ded 0); first close at 2350."""
        ctx = setup_completed_run(received_bin_count=10, received_weight_lbs=9000,
                                  input_weight_lbs=9000, cartons_produced=10,
                                  packed_weight_lbs=7650, cull_weight_lbs=900,
                                  juice_weight_lbs=450)
        record_sale(ctx["pool"]["id"], cartons_sold=10, gross_revenue_cents=30000)
        closed = close_pool_fresh(ctx["pool"]["id"])
        assert closed["pool_price_per_carton_cents"] == 2350, (
            "net 30000 - 6500 = 23500 over 10 cartons"
        )
        return ctx

    def test_reopen_reverts_settlements_and_lots(self, api):
        """PRD §3.6: "The pool moves `CLOSED → REOPENED`; the previously computed
        `pool_price_per_carton_cents` is retained until the next close recomputes
        it. The cascade runs in reverse: every `SETTLED` settlement of the pool
        reverts to `ADVANCE_PAID`, its final numbers now stale until the re-close,
        and each lot that reached `CLOSED` through this pool's settlements reverts
        `CLOSED → PACKED`."

        Design: Difficulty/non_linear_state_machine/pool_reopen_revision_loop
        """
        ctx = self._setup_first_close(api)
        settlement = refresh_settlement(ctx["settlement"]["id"])
        assert settlement["status"] == "SETTLED"
        assert settlement["final_payment_cents"] == 23500
        assert refresh_lot(ctx["lot"]["id"])["status"] == "CLOSED"

        reopened = validate_success(api.reopen_pool(ctx["pool"]["id"], POOL_MGR))
        assert reopened["status"] == "REOPENED"
        assert reopened["pool_price_per_carton_cents"] == 2350, "retained"

        settlement = refresh_settlement(ctx["settlement"]["id"])
        assert settlement["status"] == "ADVANCE_PAID"
        assert refresh_lot(ctx["lot"]["id"])["status"] == "PACKED"

    def test_reclose_pays_only_the_delta(self, api):
        """PRD §3.6: "Re-closing a `REOPENED` pool follows the same preconditions
        and cascades as the first close, recomputing the price over all recorded
        sales; because the final-position formula subtracts `paid_final_cents`,
        settlements pay only the delta against what prior closes already
        computed."

        Design: Difficulty/non_linear_state_machine/pool_reopen_revision_loop
        """
        ctx = self._setup_first_close(api)
        validate_success(api.reopen_pool(ctx["pool"]["id"], POOL_MGR))
        record_sale(ctx["pool"]["id"], cartons_sold=10, gross_revenue_cents=5000,
                    deduction_cents=500)

        closed = close_pool_fresh(ctx["pool"]["id"])
        assert closed["status"] == "CLOSED", "loop REOPENED -> CLOSED"
        assert closed["pool_price_per_carton_cents"] == 2800, (
            "net 35000 - 500 - 6500 = 28000 over 10 cartons"
        )

        settlement = refresh_settlement(ctx["settlement"]["id"])
        assert settlement["status"] == "SETTLED"
        assert settlement["final_payment_cents"] == 4500, (
            "28000 - 0 advance - 23500 already paid"
        )
        assert settlement["paid_final_cents"] == 28000, "10 x 2800 across the loop"
        assert refresh_lot(ctx["lot"]["id"])["status"] == "CLOSED"
