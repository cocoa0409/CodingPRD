"""Honey allocation: projected vs final variants, share formula, pinned
rounding/evaluation order, distribution, and mass conservation."""
import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    complete_course,
    create_and_verify_inspection,
    get_allocation,
    get_allocation_for,
    make_host_headers,
    propose_amendment_payload,
    record_harvest,
    rollover_season,
    setup_allocation_scenario,
    validate_error,
    validate_success,
)

MGR = TEST_USERS["manager_headers"]
OPS = TEST_USERS["ops_headers"]
BK1 = TEST_USERS["beekeeper_headers"]

ROLLOVER_AT = "2026-10-20T00:00:00Z"


def _dual_variant_scenario():
    """Season + PLUS (paid) + HOST-101 COMPLETED; agreement amended mid-season
    2500 -> 3000; h1 APPROVED net 9.800, h2 APPROVED net 8.000, h3 RECORDED
    net 5.000."""
    ctx = setup_allocation_scenario(
        plan="PLUS",
        with_education=True,
        base_bps=2500,
        harvests=((10.000, 19.6), (8.000, 18.6)),
        inspection_schedule=[
            {"inspected_at": "2026-07-01T00:00:00Z",
             "collected_on": "2026-07-05T00:00:00Z"},
            {"inspected_at": "2026-08-01T00:00:00Z",
             "collected_on": "2026-08-05T00:00:00Z"},
        ],
    )
    host, agreement = ctx["host"], ctx["agreement"]
    amended = validate_success(
        api_client.propose_amendment(
            agreement["id"],
            propose_amendment_payload(3000, agreement["version"]),
            OPS,
        ),
        200,
    )
    accepted = validate_success(
        api_client.accept_amendment(
            agreement["id"], make_host_headers(host["id"]),
        ),
        200,
    )
    assert accepted["host_share_base_bps"] == 3000, "Setup failed: amendment"
    ctx["agreement"] = accepted
    # A third harvest, verified-fresh but never approved.
    create_and_verify_inspection(
        ctx["hive"]["id"], inspected_at="2026-09-01T00:00:00Z",
        mites_counted=0, bees_sampled=300,
        brood_score=9, queen_seen=True, stores_kg=13.0,
    )
    h3 = record_harvest(
        ctx["hive"]["id"], collected_on="2026-09-05T00:00:00Z",
        gross_kg=5.000, moisture_pct=18.0,
    )
    ctx["recorded_harvest"] = h3
    ctx["allocation"] = get_allocation_for(
        ctx["hive"]["id"], ctx["season"]["id"],
    )
    return ctx


class TestProjectedVsFinalVariants:
    def test_projected_variant_includes_recorded_and_live_inputs(self, api):
        """PRD §3.6: "It reports `projected_pool_net_kg`, the sum of `net_kg`
        over the pair's harvests in `RECORDED` or `APPROVED` status, and
        `projected_host_kg`, computed from those same harvests with all share
        inputs read live — the agreement's current `host_share_base_bps`, the
        host's current subscription plan, and the host's current enrollment
        record."
        PRD §3.6: "for each included harvest, multiply its `net_kg` by the
        effective basis points, divide by ten thousand, and round half-up to
        three decimal places; then sum the rounded per-harvest amounts."

        Design: Difficulty/dual_variant_calc/honey_share_projected_vs_final_variant
        """
        ctx = _dual_variant_scenario()
        alloc = get_allocation(ctx["allocation"]["id"])
        # Live inputs at read time: 3000 (amended) + 250 (PLUS) + 200 (edu).
        # round3(9.800*0.345)=3.381, round3(8.000*0.345)=2.760,
        # round3(5.000*0.345)=1.725 -> 7.866
        assert alloc["projected_pool_net_kg"] == pytest.approx(22.800, abs=1e-9), (
            "RECORDED harvest included in the projected input set"
        )
        assert alloc["projected_host_kg"] == pytest.approx(7.866, abs=1e-9)
        assert alloc["status"] == "PROJECTED"

    def test_final_variant_counts_approved_only(self, api):
        """PRD §3.6: "the final variant recomputes everything with inputs
        pinned at the moment of close: only `APPROVED` harvests count."
        PRD §3.6: "The final variant writes `pool_net_kg` (the sum of `net_kg`
        over `APPROVED` harvests only), `effective_bps`, and `host_kg`."

        Design: Difficulty/dual_variant_calc/honey_share_projected_vs_final_variant
        """
        ctx = _dual_variant_scenario()
        projected = get_allocation(ctx["allocation"]["id"])
        rollover_season(ctx["season"]["id"], at=ROLLOVER_AT)
        alloc = get_allocation(ctx["allocation"]["id"])
        assert alloc["status"] == "FINALIZED"
        assert alloc["pool_net_kg"] == pytest.approx(17.800, abs=1e-9)
        # 3.381 + 2.760 — the RECORDED 5.000 kg is excluded at close.
        assert alloc["host_kg"] == pytest.approx(6.141, abs=1e-9)
        assert alloc["effective_bps"] == 3450
        # The two sanctioned variants diverge on identical harvest data.
        assert alloc["host_kg"] != pytest.approx(
            projected["projected_host_kg"],
        )


class TestShareFormulaCombination:
    def _cap_scenario(self):
        return setup_allocation_scenario(
            plan="PREMIUM",
            with_education=True,
            base_bps=5500,
            harvests=((20.000, 18.0),),
            inspection_schedule=[{"inspected_at": "2026-06-01T00:00:00Z"}],
        )

    def test_effective_bps_capped_at_6000(self, api):
        """PRD §3.6: "The host's effective rate adds three components: the
        agreement's base share, a tier bonus of 0 basis points on `BASIC`, 250
        on `PLUS`, and 500 on `PREMIUM`, and an education bonus of 200 basis
        points when the host holds a `COMPLETED` `HOST-101` enrollment; the sum
        is capped at 6000 basis points."

        Design: Difficulty/combinatorial_formula/share_formula_cap_tier_edu_combination
        """
        ctx = self._cap_scenario()
        rollover_season(ctx["season"]["id"], at=ROLLOVER_AT)
        alloc = get_allocation(ctx["allocation"]["id"])
        # min(5500 + 500 + 200, 6000): the cap engages, not 6200.
        assert alloc["effective_bps"] == 6000
        # round3(20.000 * 6000/10000) = 12.000; uncapped would be 12.400.
        assert alloc["host_kg"] == pytest.approx(12.000, abs=1e-9)

    def test_waterfall_with_cap_engaged(self, api):
        """PRD §3.6: "Third the education bonus mass `edu_bonus_kg` is fixed:
        when the education bonus applied, the pool multiplied by 200 and
        divided by ten thousand, rounded half-up to three decimals; otherwise
        zero."
        PRD §3.6: "Fifth `reserve_kg` is the pool multiplied by the chosen
        percentage, rounded half-up to three decimals, plus the `edu_bonus_kg`
        top-up."
        PRD §3.6: "Sixth `operator_kg` takes the remainder — pool minus host
        share minus reserve — which makes the conservation identity exact: for
        every finalized allocation, `host_kg` plus `reserve_kg` plus
        `operator_kg` equals `pool_net_kg`."
        PRD §3.6: "Fourth the reserve percentage is chosen by pool size: six
        percent of the pool when `pool_net_kg` reaches at least 100.000
        kilograms, three percent below that."

        Design: Difficulty/combinatorial_formula/share_formula_cap_tier_edu_combination
        """
        ctx = self._cap_scenario()
        rollover_season(ctx["season"]["id"], at=ROLLOVER_AT)
        alloc = get_allocation(ctx["allocation"]["id"])
        assert alloc["pool_net_kg"] == pytest.approx(20.000, abs=1e-9)
        assert alloc["edu_bonus_kg"] == pytest.approx(0.400, abs=1e-9), (
            "round3(20.000 * 200/10000)"
        )
        # Pool below 100.000 kg -> 3% tier: round3(0.600) + 0.400 top-up.
        assert alloc["reserve_kg"] == pytest.approx(1.000, abs=1e-9)
        assert alloc["operator_kg"] == pytest.approx(7.000, abs=1e-9), (
            "20.000 - 12.000 - 1.000"
        )


class TestPerHarvestRoundingOrder:
    def _rounding_scenario(self):
        return setup_allocation_scenario(
            plan=None,
            with_education=False,
            base_bps=1000,
            harvests=((1.005, 18.0), (1.005, 18.0)),
            inspection_schedule=[
                {"inspected_at": "2026-06-01T00:00:00Z"},
                {"inspected_at": "2026-06-02T00:00:00Z"},
            ],
        )

    def test_round_each_harvest_then_sum(self, api):
        """PRD §3.6: "Rounding each harvest first and summing second is
        mandatory."

        Design: Difficulty/combinatorial_formula/per_harvest_rounding_order_pinned
        """
        ctx = self._rounding_scenario()
        rollover_season(ctx["season"]["id"], at=ROLLOVER_AT)
        alloc = get_allocation(ctx["allocation"]["id"])
        assert alloc["pool_net_kg"] == pytest.approx(2.010, abs=1e-9)
        assert alloc["effective_bps"] == 1000
        # Pinned order: round3(1.005 * 0.10) = 0.101 per harvest, then sum
        # 0.101 + 0.101 = 0.202. The forbidden sum-then-round order would
        # give round3(2.010 * 0.10) = 0.201.
        assert alloc["host_kg"] == pytest.approx(0.202, abs=1e-9)

    def test_waterfall_on_small_pool(self, api):
        """PRD §3.6: "Fifth `reserve_kg` is the pool multiplied by the chosen
        percentage, rounded half-up to three decimals, plus the `edu_bonus_kg`
        top-up. Sixth `operator_kg` takes the remainder — pool minus host share
        minus reserve — which makes the conservation identity exact."
        PRD §3.6: "otherwise zero" (education bonus when not applied).

        Design: Difficulty/combinatorial_formula/per_harvest_rounding_order_pinned
        """
        ctx = self._rounding_scenario()
        rollover_season(ctx["season"]["id"], at=ROLLOVER_AT)
        alloc = get_allocation(ctx["allocation"]["id"])
        assert alloc["edu_bonus_kg"] == pytest.approx(0.0, abs=1e-9), (
            "no COMPLETED HOST-101 here"
        )
        assert alloc["reserve_kg"] == pytest.approx(0.060, abs=1e-9), (
            "round3(2.010 * 0.03)"
        )
        assert alloc["operator_kg"] == pytest.approx(1.748, abs=1e-9), (
            "2.010 - 0.202 - 0.060"
        )


class TestReservePinnedEvaluationOrder:
    def _reserve_scenario(self):
        return setup_allocation_scenario(
            plan="PLUS",
            with_education=True,
            base_bps=2500,
            harvests=((10.000, 19.6), (8.000, 18.6)),
            inspection_schedule=[
                {"inspected_at": "2026-07-01T00:00:00Z",
                 "collected_on": "2026-07-05T00:00:00Z"},
                {"inspected_at": "2026-08-01T00:00:00Z",
                 "collected_on": "2026-08-05T00:00:00Z"},
            ],
        )

    def test_host_share_includes_edu_bonus(self, api):
        """PRD §3.6: "Second the host share is computed per the final variant
        above. Third the education bonus mass `edu_bonus_kg` is fixed: when the
        education bonus applied, the pool multiplied by 200 and divided by ten
        thousand, rounded half-up to three decimals."

        Design: Difficulty/combinatorial_formula/reserve_pool_pinned_evaluation_order
        """
        ctx = self._reserve_scenario()
        rollover_season(ctx["season"]["id"], at=ROLLOVER_AT)
        alloc = get_allocation(ctx["allocation"]["id"])
        assert alloc["pool_net_kg"] == pytest.approx(17.800, abs=1e-9)
        assert alloc["effective_bps"] == 2950
        # round3(9.800 * 0.295) = 2.891; round3(8.000 * 0.295) = 2.360.
        assert alloc["host_kg"] == pytest.approx(5.251, abs=1e-9)
        assert alloc["edu_bonus_kg"] == pytest.approx(0.356, abs=1e-9), (
            "round3(17.800 * 200/10000)"
        )

    def test_reserve_topped_up_by_edu_portion(self, api):
        """PRD §3.6: "Fifth `reserve_kg` is the pool multiplied by the chosen
        percentage, rounded half-up to three decimals, plus the `edu_bonus_kg`
        top-up. Sixth `operator_kg` takes the remainder — pool minus host share
        minus reserve — which makes the conservation identity exact: for every
        finalized allocation, `host_kg` plus `reserve_kg` plus `operator_kg`
        equals `pool_net_kg`."

        Design: Difficulty/combinatorial_formula/reserve_pool_pinned_evaluation_order
        """
        ctx = self._reserve_scenario()
        rollover_season(ctx["season"]["id"], at=ROLLOVER_AT)
        alloc = get_allocation(ctx["allocation"]["id"])
        # round3(17.800 * 0.03) = 0.534, then + 0.356 edu top-up.
        assert alloc["reserve_kg"] == pytest.approx(0.890, abs=1e-9)
        assert alloc["operator_kg"] == pytest.approx(11.659, abs=1e-9)
        total = alloc["host_kg"] + alloc["reserve_kg"] + alloc["operator_kg"]
        assert total == pytest.approx(alloc["pool_net_kg"], abs=1e-9), (
            "conservation identity must hold exactly"
        )


class TestMassConservation:
    def _conservation_scenario(self):
        return setup_allocation_scenario(
            plan="PLUS",
            with_education=True,
            base_bps=2500,
            harvests=((4.000, 18.0), (6.000, 18.0)),
            inspection_schedule=[
                {"inspected_at": "2026-06-01T00:00:00Z"},
                {"inspected_at": "2026-06-01T12:00:00Z"},
            ],
        )

    def test_approve_then_void_restores_projection(self, api):
        """PRD §3.6: "The projected variant is recomputed on every harvest
        approval, every harvest void, and every quarantine cascade that voids
        recorded harvests."
        PRD §3.5: "A manager may also void a harvest in `RECORDED` or
        `APPROVED` status — again only while the allocation is not `FINALIZED`
        or `DISTRIBUTED` — which recomputes the allocation excluding the voided
        harvest."

        Design: Difficulty/compensating_invariant/honey_mass_conserved_across_approve_void
        """
        ctx = self._conservation_scenario()
        hive_id = ctx["hive"]["id"]
        alloc_id = ctx["allocation"]["id"]
        before = get_allocation(alloc_id)
        assert before["projected_pool_net_kg"] == pytest.approx(10.000, abs=1e-9)
        assert before["projected_host_kg"] == pytest.approx(2.950, abs=1e-9)

        # Forward action: approve a third harvest (net 2.000).
        create_and_verify_inspection(
            hive_id, inspected_at="2026-06-03T00:00:00Z",
            mites_counted=0, bees_sampled=300,
            brood_score=9, queen_seen=True, stores_kg=12.0,
        )
        h3 = record_harvest(
            hive_id, collected_on="2026-06-17T00:00:00Z",
            gross_kg=2.000, moisture_pct=18.0,
        )
        validate_success(api.approve_harvest(h3["id"], MGR), 200)
        forward = get_allocation(alloc_id)
        assert forward["projected_pool_net_kg"] == pytest.approx(12.000, abs=1e-9)
        assert forward["projected_host_kg"] == pytest.approx(3.540, abs=1e-9), (
            "2.950 + round3(2.000 * 0.295) = 2.950 + 0.590"
        )

        # Compensating action: void the same harvest — zero drift.
        validate_success(api.void_harvest(h3["id"], MGR), 200)
        restored = get_allocation(alloc_id)
        assert restored["projected_pool_net_kg"] == pytest.approx(10.000, abs=1e-9)
        assert restored["projected_host_kg"] == pytest.approx(2.950, abs=1e-9)

    def test_finalization_conservation_identity(self, api):
        """PRD §3.6: "for every finalized allocation, `host_kg` plus
        `reserve_kg` plus `operator_kg` equals `pool_net_kg`."

        Design: Difficulty/compensating_invariant/honey_mass_conserved_across_approve_void
        """
        ctx = self._conservation_scenario()
        rollover_season(ctx["season"]["id"], at=ROLLOVER_AT)
        alloc = get_allocation(ctx["allocation"]["id"])
        assert alloc["pool_net_kg"] == pytest.approx(10.000, abs=1e-9)
        # round3(4.000 * 0.295) + round3(6.000 * 0.295) = 1.180 + 1.770.
        assert alloc["host_kg"] == pytest.approx(2.950, abs=1e-9)
        assert alloc["edu_bonus_kg"] == pytest.approx(0.200, abs=1e-9), (
            "round3(10.000 * 200/10000)"
        )
        # round3(10.000 * 0.03) = 0.300, plus the 0.200 edu top-up.
        assert alloc["reserve_kg"] == pytest.approx(0.500, abs=1e-9)
        assert alloc["operator_kg"] == pytest.approx(6.550, abs=1e-9)
        assert (
            alloc["host_kg"] + alloc["reserve_kg"] + alloc["operator_kg"]
        ) == pytest.approx(alloc["pool_net_kg"], abs=1e-9)


class TestDistribution:
    def test_distribute_projected_rejected_then_finalized_succeeds(self, api):
        """PRD §3.6: "Distribution is a deliberate `PlatformOps` act on a
        `FINALIZED` allocation; attempting it earlier is rejected with
        `ERR_ALLOCATION_NOT_DISTRIBUTABLE`."
        PRD §3.6: "Distribution credits the host's `honey_credit_kg` with the
        allocation's `host_kg`, moves every `APPROVED` harvest of the
        season-and-hive pair to `SETTLED`, stamps `distributed_at`, and leaves
        the allocation `DISTRIBUTED`."

        Design: Corner/endpoints/distribute_projected_allocation_rejected
        """
        ctx = setup_allocation_scenario(
            plan=None, with_education=False, base_bps=2500,
            harvests=((4.000, 18.0),),
            inspection_schedule=[{"inspected_at": "2026-06-01T00:00:00Z"}],
        )
        alloc_id = ctx["allocation"]["id"]
        res = api.distribute_allocation(alloc_id, OPS)
        validate_error(res, "ERR_ALLOCATION_NOT_DISTRIBUTABLE")

        rollover_season(ctx["season"]["id"], at=ROLLOVER_AT)
        distributed = validate_success(
            api.distribute_allocation(alloc_id, OPS), 200,
        )
        assert distributed["status"] == "DISTRIBUTED"
        # Base-only inputs: round3(4.000 * 2500/10000) = 1.000.
        assert distributed["host_kg"] == pytest.approx(1.000, abs=1e-9)

        host = validate_success(api.get_host(ctx["host"]["id"], OPS))
        assert host["honey_credit_kg"] == pytest.approx(1.000, abs=1e-9), (
            "host credited exactly host_kg"
        )
        harvest = validate_success(api.get_harvest(ctx["harvest_ids"][0], OPS))
        assert harvest["status"] == "SETTLED", (
            "distribution settles the approved harvest"
        )
