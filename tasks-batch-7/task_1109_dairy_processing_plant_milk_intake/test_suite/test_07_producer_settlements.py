"""Producer settlements: PROVISIONAL vs FINAL variants, the tiered hauling
formula and its 1000-cwt boundary, the pooling input set, and the approval
gate on pool finalization."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    announce_pool,
    create_pool_payload,
    create_producer_payload,
    create_settlement_payload,
    finalize_pool,
    get_pool,
    get_settlement,
    get_success_data,
    make_hauler,
    make_permit,
    make_pool,
    make_producer,
    make_settlement,
    release_receipt,
    set_clock,
    setup_intake_env,
    setup_releasable_receipt,
    setup_released_receipt,
    validate_error,
    validate_paginated,
    validate_success,
)

PC = TEST_USERS["plant_controller_headers"]
QA = TEST_USERS["qa_manager_headers"]

MAY_PERIOD = {
    "period_start_date": "2026-05-01T00:00:00Z",
    "period_end_date": "2026-05-31T23:59:59Z",
}


class TestProvisionalVsFinalDivergence:
    """2000 cwt delivered (net 200000 lbs), rate 200 cents/cwt, assay
    4.00/3.20/5.70 on a pool priced 300/250/40 (PRD §3.10, §3.11)."""

    def _setup(self, api):
        env = setup_intake_env(hauling_rate=200, pool=True)
        receipt = setup_released_receipt(
            env["producer"]["id"], env["hauler"]["id"],
            gross=230000, tare=30000,
            assay={"butterfat_pct": 4.00, "protein_pct": 3.20, "other_solids_pct": 5.70},
        )
        settlement = make_settlement(env["producer"]["id"])
        return env, receipt, settlement

    def test_finalize_flips_variant_and_recomputes(self, api):
        """PRD §3.10: "for each `ProducerSettlement` of the month,
        `pricing_variant` transitions from `PROVISIONAL` to `FINAL` and the
        settlement's credit is recomputed under the `FINAL` variant." PRD
        §3.11: "On approval, the four financial lines are recomputed under the
        `FINAL` variant: the `gross_pool_credit_cents` gains an additional term
        equal to the pool's `producer_price_differential_cents` multiplied by
        the producer's pooled hundredweight, and the hauling tier-2 discount
        percentage flips from 80 to 75".

        Design: Difficulty/dual_variant_calc/settlement_provisional_vs_final_divergence
        """
        env, _, settlement = self._setup(api)
        pid, pool_id = env["producer"]["id"], env["pool"]["id"]

        provisional = get_settlement(pid, settlement["id"])
        assert provisional["pricing_variant"] == "PROVISIONAL"
        assert provisional["gross_pool_credit_cents"] == 4456000  # 8000*300 + 6400*250 + 11400*40

        announce_pool(pool_id)
        finalize_pool(pool_id)

        final = get_settlement(pid, settlement["id"])
        assert final["pricing_variant"] == "FINAL"
        ppd = get_pool(pool_id)["producer_price_differential_cents"]
        assert final["gross_pool_credit_cents"] == 4456000 + ppd * 2000, (
            "FINAL gross must add producer_price_differential_cents x pooled cwt"
        )
        assert final["hauling_deduction_cents"] != provisional["hauling_deduction_cents"]
        assert final["net_payment_cents"] != provisional["net_payment_cents"]

    def test_final_variant_hauling_uses_75_percent(self, api):
        """PRD §3.11: "for any hundredweight above 1000, the first 1000
        hundredweight is charged at the full base rate and the excess is
        charged at 80 percent of the base rate" under the provisional variant;
        under FINAL "the hauling tier-2 discount percentage flips from 80 to
        75, so any hundredweight above 1000 is charged at 75 percent of the
        base rate."

        Design: Difficulty/dual_variant_calc/settlement_provisional_vs_final_divergence
        """
        env, _, settlement = self._setup(api)
        pid, pool_id = env["producer"]["id"], env["pool"]["id"]

        provisional = get_settlement(pid, settlement["id"])
        # 1000 cwt x 200 + 1000 cwt x 200 x 0.80 = 200000 + 160000
        assert provisional["hauling_deduction_cents"] == 360000

        announce_pool(pool_id)
        finalize_pool(pool_id)

        final = get_settlement(pid, settlement["id"])
        # 1000 cwt x 200 + 1000 cwt x 200 x 0.75 = 200000 + 150000
        assert final["hauling_deduction_cents"] == 350000


class TestHaulingTieredFormula:
    def test_hauling_tiered_above_1000_cwt(self, api):
        """PRD §3.11: "The `hauling_deduction_cents` applies the producer's
        `base_hauling_rate_cents_per_cwt` on a two-tier schedule: for total
        delivered hundredweight up to and including 1000, the deduction is the
        total hundredweight multiplied by the base rate; for any hundredweight
        above 1000, the first 1000 hundredweight is charged at the full base
        rate and the excess is charged at 80 percent of the base rate."
        1500 cwt @ 200 cents/cwt -> 1000x200 + 500x200x0.8 = 280000.

        Design: Difficulty/combinatorial_formula/hauling_deduction_tiered_formula_mode_a
        """
        env = setup_intake_env(hauling_rate=200, pool=True)
        setup_released_receipt(
            env["producer"]["id"], env["hauler"]["id"],
            gross=180000, tare=30000,  # net 150000 lbs = 1500 cwt
            assay={},
        )
        settlement = make_settlement(env["producer"]["id"])
        assert settlement["hauling_deduction_cents"] == 280000

    def test_hauling_flat_below_1000_cwt(self, api):
        """PRD §3.11: "for total delivered hundredweight up to and including
        1000, the deduction is the total hundredweight multiplied by the base
        rate". 500 cwt @ 200 cents/cwt -> 100000.

        Design: Difficulty/combinatorial_formula/hauling_deduction_tiered_formula_mode_a
        """
        env = setup_intake_env(hauling_rate=200, pool=True)
        setup_released_receipt(
            env["producer"]["id"], env["hauler"]["id"],
            gross=80000, tare=30000,  # net 50000 lbs = 500 cwt
            assay={},
        )
        settlement = make_settlement(env["producer"]["id"])
        assert settlement["hauling_deduction_cents"] == 100000


class TestHaulingTier1Boundary:
    def test_hauling_exactly_1000_cwt(self, api):
        """PRD §3.11: "for total delivered hundredweight up to and including
        1000, the deduction is the total hundredweight multiplied by the base
        rate". Exactly 1000 cwt stays entirely on tier 1: 1000 x 200 = 200000.

        Design: Difficulty/boundary_precision_check/hauling_tier1_cwt_boundary
        """
        env = setup_intake_env(hauling_rate=200, pool=True)
        setup_released_receipt(
            env["producer"]["id"], env["hauler"]["id"],
            gross=130000, tare=30000,  # net 100000 lbs = exactly 1000 cwt
            assay={},
        )
        settlement = make_settlement(env["producer"]["id"])
        assert settlement["hauling_deduction_cents"] == 200000

    def test_hauling_1001_cwt(self, api):
        """PRD §3.11: "for any hundredweight above 1000, the first 1000
        hundredweight is charged at the full base rate and the excess is
        charged at 80 percent of the base rate." 1001 cwt @ 200 ->
        200000 + 1x200x0.8 = 200160.

        Design: Difficulty/boundary_precision_check/hauling_tier1_cwt_boundary
        """
        env = setup_intake_env(hauling_rate=200, pool=True)
        setup_released_receipt(
            env["producer"]["id"], env["hauler"]["id"],
            gross=130100, tare=30000,  # net 100100 lbs = 1001 cwt
            assay={},
        )
        settlement = make_settlement(env["producer"]["id"])
        assert settlement["hauling_deduction_cents"] == 200160


def test_settlement_excludes_diverted_receipts(api):
    """PRD §3.11: "The provisional computation walks every `TankerReceipt` for
    this producer whose arrival falls within the settlement period and whose
    `disposition` is `RELEASED_FOR_PROCESSING`." PRD §3.4: "the draft
    `ProducerSettlement` records for the affected pool month are recomputed to
    reflect the reduced pool."

    Design: Corner/calculations/input_set_filters_diverted_receipts
    """
    env = setup_intake_env(hauling_rate=200, pool=True)
    pid, hid = env["producer"]["id"], env["hauler"]["id"]

    # Receipt 1: net 20000 lbs (200 cwt), stays released.
    setup_released_receipt(
        pid, hid, gross=50000, tare=30000,
        arrived_at="2026-05-05T08:00:00Z",
        assay={"butterfat_pct": 4.00, "protein_pct": 3.20, "other_solids_pct": 5.70},
    )
    # Receipt 2: net 30000 lbs, released then diverted — out of the input set.
    r2 = setup_released_receipt(
        pid, hid, gross=60000, tare=30000,
        arrived_at="2026-05-06T08:00:00Z",
        assay={},
    )
    get_success_data(api.divert_tanker_receipt(r2["id"], {}, QA))

    settlement = make_settlement(pid)
    # Only receipt 1 counts: 800*300 + 640*250 + 1140*40 = 240000+160000+45600
    assert settlement["gross_pool_credit_cents"] == 445600
    # 200 cwt x 200 cents/cwt, all within tier 1
    assert settlement["hauling_deduction_cents"] == 40000


def test_approve_blocked_until_pool_finalized(api):
    """PRD §3.11: "Approving a settlement, transitioning `DRAFT` to `APPROVED`,
    is a `PlantController` action with two preconditions: the
    `MarketingOrderPool` for the settlement's pool month must be in
    `FINALIZED`, otherwise `ERR_POOL_NOT_FINALIZED`".

    Design: Corner/state_machines/settlement_approve_blocked_until_pool_finalized
    """
    env = setup_intake_env(pool=True)
    settlement = make_settlement(env["producer"]["id"])
    announce_pool(env["pool"]["id"])  # ANNOUNCED, not yet FINALIZED

    res = api.approve_settlement(env["producer"]["id"], settlement["id"], {}, PC)
    validate_error(res, ApiErrorId.ERR_POOL_NOT_FINALIZED)


def test_list_settlements_scoped_to_producer(api):
    """PRD §3.11: "Settlements may be listed per producer (with an optional
    `producer_id` filter) and fetched by id by `PlantController` and
    `StateInspector`."

    Design: Corner/endpoints/get_settlements_filtered_by_producer
    """
    set_clock()
    producer_a = get_success_data(
        api.create_producer(create_producer_payload(producer_code="PE2", farm_name="FE2"), PC)
    )
    producer_b = get_success_data(
        api.create_producer(create_producer_payload(producer_code="PE3", farm_name="FE3"), PC)
    )
    make_pool()
    stl_a = make_settlement(producer_a["id"])
    make_settlement(producer_b["id"])

    data, meta = validate_paginated(api.list_settlements(producer_a["id"], PC))
    assert len(data) == 1
    assert meta["total_count"] == 1
    assert data[0]["id"] == stl_a["id"]
    assert data[0]["producer_id"] == producer_a["id"]
